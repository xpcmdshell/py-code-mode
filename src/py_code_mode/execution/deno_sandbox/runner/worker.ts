// Pyodide worker. Executes Python code and provides async RPC calls
// back to the Deno main thread (which forwards to the Python host).
//
// RPC is promise-based and supports arbitrarily large payloads by streaming
// chunks over postMessage (runner -> worker).

import { loadPyodide } from "npm:pyodide@0.29.3";

// Keep stdout/stderr reserved for the NDJSON protocol in main.ts.
// Pyodide and micropip can be chatty, and interleaved output would corrupt NDJSON.
const _noop = () => {};
console.log = _noop;
console.info = _noop;
console.warn = _noop;
console.debug = _noop;
console.error = _noop;

type BootMsg = { type: "boot" };
type ExecMsg = { type: "exec"; id: string; code: string };
type DepsInstallMsg = { type: "deps_install"; id: string; packages: string[] };

type RpcResponseChunkMsg = {
  type: "rpc_response_chunk";
  id: string;
  seq: number;
  chunk: string;
};
type RpcResponseEndMsg = { type: "rpc_response_end"; id: string; seq: number };

type RpcReq = {
  type: "rpc_request";
  id: string;
  namespace: string;
  op: string;
  args_json: string;
};

type Msg =
  | BootMsg
  | ExecMsg
  | DepsInstallMsg
  | RpcResponseChunkMsg
  | RpcResponseEndMsg;

const rpcPending = new Map<
  string,
  { chunks: string[]; resolve: (v: string) => void; reject: (e: Error) => void }
>();

function rpcCallAsync(
  namespace: string,
  op: string,
  argsJson: string,
): Promise<string> {
  const id = crypto.randomUUID();
  const msg: RpcReq = {
    type: "rpc_request",
    id,
    namespace,
    op,
    args_json: String(argsJson ?? "{}"),
  };

  return new Promise((resolve, reject) => {
    rpcPending.set(id, { chunks: [], resolve, reject });
    (self as any).postMessage(msg);
  });
}

function pyodidePackageDir(): string {
  // Resolve a file inside the npm package, then derive its directory path.
  const resolved = import.meta.resolve("npm:pyodide@0.29.3/pyodide.asm.js");
  if (resolved.startsWith("file:")) {
    const u = new URL(resolved);
    // Deno uses POSIX paths on macOS/Linux.
    const path = decodeURIComponent(u.pathname);
    return path.slice(0, path.lastIndexOf("/") + 1);
  }
  // Fallback: treat as path-like.
  const s = String(resolved);
  return s.slice(0, s.lastIndexOf("/") + 1);
}

let pyodide: any = null;
let booted = false;
let micropipLoaded = false;
const attemptedInstalls = new Set<string>();

async function ensureBooted() {
  if (booted) return;

  const indexURL = pyodidePackageDir();
  pyodide = await loadPyodide({ indexURL, stdout: _noop, stderr: _noop });

  // Expose async RPC to Python.
  (self as any).rpc_call_async = rpcCallAsync;

  // Expose deps installers to Python (so deps.add/sync can just await these).
  (self as any).pycm_install_package = installPackage;
  (self as any).pycm_install_packages = installPackages;

  const bootstrap = `
import ast, json

class _RPC:
    @staticmethod
    async def call(namespace: str, op: str, args: dict):
        import js
        payload = await js.rpc_call_async(namespace, op, json.dumps(args))
        obj = json.loads(str(payload))
        if not obj.get("ok", False):
            err = obj.get("error") or {}
            raise RuntimeError(f"RPCError: {err.get('message','unknown')}")
        return obj.get("result")

class _ToolCallable:
    def __init__(self, name: str, recipe: str | None = None):
        self._name = name
        self._recipe = recipe
    async def __call__(self, **kwargs):
        tool = self._name if self._recipe is None else f"{self._name}.{self._recipe}"
        return await _RPC.call("tools", "call_tool", {"name": tool, "args": kwargs})

class _Tool:
    def __init__(self, name: str):
        self._name = name
    async def __call__(self, **kwargs):
        return await _RPC.call("tools", "call_tool", {"name": self._name, "args": kwargs})
    def __getattr__(self, recipe: str):
        if recipe.startswith("_"):
            raise AttributeError(recipe)
        return _ToolCallable(self._name, recipe)
    async def list(self):
        return await _RPC.call("tools", "list_tool_recipes", {"name": self._name})

class _Tools:
    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        return _Tool(name)
    async def list(self):
        return await _RPC.call("tools", "list_tools", {})
    async def search(self, query: str, limit: int = 5):
        return await _RPC.call("tools", "search_tools", {"query": query, "limit": limit})

tools = _Tools()

class workflows:
    @staticmethod
    async def list():
        return await _RPC.call("workflows", "list_workflows", {})
    @staticmethod
    async def search(query: str, limit: int = 5):
        return await _RPC.call("workflows", "search_workflows", {"query": query, "limit": limit})
    @staticmethod
    async def get(name: str):
        return await _RPC.call("workflows", "get_workflow", {"name": name})
    @staticmethod
    async def create(name: str, source: str, description: str = ""):
        return await _RPC.call("workflows", "create_workflow", {"name": name, "source": source, "description": description})
    @staticmethod
    async def delete(name: str):
        return await _RPC.call("workflows", "delete_workflow", {"name": name})
    @staticmethod
    async def invoke(workflow_name: str, **kwargs):
        import asyncio
        wf = await workflows.get(workflow_name)
        if wf is None or not isinstance(wf, dict):
            raise ValueError(f"Workflow not found: {workflow_name}")
        source = wf.get("source")
        if not source:
            raise ValueError(f"Workflow has no source: {workflow_name}")
        ns = {"tools": tools, "workflows": workflows, "artifacts": artifacts, "deps": deps}
        exec(source, ns, ns)
        run_func = ns.get("run")
        if not callable(run_func):
            raise ValueError(f"Workflow {workflow_name} has no run() function")
        result = run_func(**kwargs)
        if asyncio.iscoroutine(result):
            result = await result
        return result

class artifacts:
    @staticmethod
    async def list():
        return await _RPC.call("artifacts", "list_artifacts", {})
    @staticmethod
    async def get(name: str):
        return await _RPC.call("artifacts", "get_artifact", {"name": name})
    @staticmethod
    async def exists(name: str):
        return await _RPC.call("artifacts", "artifact_exists", {"name": name})
    @staticmethod
    async def load(name: str):
        return await _RPC.call("artifacts", "load_artifact", {"name": name})
    @staticmethod
    async def save(name: str, data, description: str = ""):
        return await _RPC.call("artifacts", "save_artifact", {"name": name, "data": data, "description": description})
    @staticmethod
    async def delete(name: str):
        return await _RPC.call("artifacts", "delete_artifact", {"name": name})

class deps:
    @staticmethod
    async def list():
        return await _RPC.call("deps", "list_deps", {})
    @staticmethod
    async def add(spec: str):
        await _RPC.call("deps", "persist_add", {"spec": spec})
        import js
        ok = await js.pycm_install_package(spec)
        if ok:
            return {"installed": [spec], "already_present": [], "failed": []}
        return {"installed": [], "already_present": [], "failed": [spec]}
    @staticmethod
    async def remove(spec_or_name: str):
        removed = await _RPC.call("deps", "persist_remove", {"spec_or_name": spec_or_name})
        return {
            "removed": [spec_or_name] if removed else [],
            "not_found": [] if removed else [spec_or_name],
            "failed": [],
            "removed_from_config": bool(removed),
        }
    @staticmethod
    async def sync():
        specs = await _RPC.call("deps", "list_deps", {}) or []
        import js
        res = await js.pycm_install_packages(list(specs))
        return res
`;

  pyodide.runPython(bootstrap);
  booted = true;
}

async function ensureMicropipLoaded(): Promise<void> {
  if (micropipLoaded) return;
  if (!pyodide) throw new Error("pyodide not initialized");
  await pyodide.loadPackage("micropip");
  micropipLoaded = true;
}

async function installPackage(spec: string): Promise<boolean> {
  const s = String(spec ?? "").trim();
  if (!s) return false;
  if (attemptedInstalls.has(s)) return true;

  await ensureMicropipLoaded();
  try {
    pyodide.globals.set("_PYCM_DEP_SPEC", s);
    await pyodide.runPythonAsync(`
import micropip
await micropip.install(_PYCM_DEP_SPEC)
`);
    attemptedInstalls.add(s);
    return true;
  } catch {
    return false;
  }
}

async function installPackages(
  packages: string[],
): Promise<
  { installed: string[]; already_present: string[]; failed: string[] }
> {
  const installed: string[] = [];
  const already_present: string[] = [];
  const failed: string[] = [];

  for (const p of packages ?? []) {
    const spec = String(p ?? "").trim();
    if (!spec) continue;
    if (attemptedInstalls.has(spec)) {
      already_present.push(spec);
      continue;
    }
    const ok = await installPackage(spec);
    if (ok) installed.push(spec);
    else failed.push(spec);
  }

  return { installed, already_present, failed };
}

async function runWithLastExprAsync(
  code: string,
): Promise<{ stdout: string; value: any; error: string | null }> {
  const wrapper = `
import ast, asyncio, io, sys, traceback
_stdout = io.StringIO()
_value = None
_error = None

async def _pycm_exec(_CODE: str):
    global _value, _error
    try:
        _tree = ast.parse(_CODE)
        if _tree.body and isinstance(_tree.body[-1], ast.Expr):
            _stmts = _tree.body[:-1]
            _expr = _tree.body[-1].value
            if _stmts:
                _m = ast.Module(body=_stmts, type_ignores=[])
                _c = compile(_m, "<code>", "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
                _old = sys.stdout
                sys.stdout = _stdout
                try:
                    _r = eval(_c, globals(), globals())
                    if asyncio.iscoroutine(_r):
                        await _r
                finally:
                    sys.stdout = _old
            _ec = compile(ast.Expression(body=_expr), "<expr>", "eval", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
            _old = sys.stdout
            sys.stdout = _stdout
            try:
                _r2 = eval(_ec, globals(), globals())
                if asyncio.iscoroutine(_r2):
                    _r2 = await _r2
                _value = _r2
            finally:
                sys.stdout = _old
        else:
            _c = compile(_tree, "<code>", "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
            _old = sys.stdout
            sys.stdout = _stdout
            try:
                _r = eval(_c, globals(), globals())
                if asyncio.iscoroutine(_r):
                    await _r
            finally:
                sys.stdout = _old
            _value = None
    except Exception:
        _error = traceback.format_exc()

await _pycm_exec(_CODE)
`;

  if (!pyodide) throw new Error("pyodide not initialized");
  pyodide.globals.set("_CODE", code);
  await pyodide.runPythonAsync(wrapper);

  const stdout = pyodide.globals.get("_stdout").getvalue();
  const error = pyodide.globals.get("_error");

  let outValue: any;
  try {
    const jsonTxt = pyodide.runPython(
      "import json; json.dumps(_value)",
    ) as string;
    outValue = JSON.parse(String(jsonTxt));
  } catch {
    const repr = pyodide.runPython("repr(_value)") as string;
    outValue = { __py_repr__: String(repr) };
  }

  return {
    stdout: String(stdout ?? ""),
    value: outValue ?? null,
    error: error ? String(error) : null,
  };
}

self.onmessage = async (ev: MessageEvent<Msg>) => {
  const msg = ev.data as any;

  if (msg.type === "rpc_response_chunk") {
    const p = rpcPending.get(msg.id);
    if (!p) return;
    p.chunks.push(String(msg.chunk ?? ""));
    return;
  }

  if (msg.type === "rpc_response_end") {
    const p = rpcPending.get(msg.id);
    if (!p) return;
    rpcPending.delete(msg.id);
    p.resolve(p.chunks.join(""));
    return;
  }

  if (msg.type === "boot") {
    try {
      await ensureBooted();
      (self as any).postMessage({ type: "boot_ok" });
    } catch (e) {
      (self as any).postMessage({
        type: "boot_error",
        error: String((e as any)?.stack ?? e),
      });
    }
    return;
  }

  if (msg.type === "exec") {
    try {
      const res = await runWithLastExprAsync(msg.code);
      (self as any).postMessage({ type: "exec_result", id: msg.id, ...res });
    } catch (e) {
      (self as any).postMessage({
        type: "exec_result",
        id: msg.id,
        stdout: "",
        value: null,
        error: String((e as any)?.stack ?? e),
      });
    }
    return;
  }

  if (msg.type === "deps_install") {
    try {
      const res = await installPackages(msg.packages ?? []);
      (self as any).postMessage({
        type: "deps_install_result",
        id: msg.id,
        ...res,
      });
    } catch (e) {
      (self as any).postMessage({
        type: "deps_install_result",
        id: msg.id,
        installed: [],
        already_present: [],
        failed: (msg.packages ?? []).map((p: any) => String(p)),
        error: String((e as any)?.stack ?? e),
      });
    }
  }
};
