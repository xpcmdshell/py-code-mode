// Pyodide worker. Executes Python code and provides synchronous RPC calls
// back to the Deno main thread (which forwards to the Python host).
//
// Single-flight RPC: one outstanding call at a time.

import { loadPyodide } from "npm:pyodide@0.29.3";

// Keep stdout/stderr reserved for the NDJSON protocol in main.ts.
// Pyodide and micropip can be chatty, and interleaved output would corrupt NDJSON.
const _noop = () => {};
console.log = _noop;
console.info = _noop;
console.warn = _noop;
console.debug = _noop;
console.error = _noop;

type BootMsg = {
  type: "boot";
  rpcState: Int32Array;
  rpcBuf: Uint8Array;
};

type ExecMsg = { type: "exec"; id: string; code: string };
type DepsInstallMsg = { type: "deps_install"; id: string; packages: string[] };

let rpcState: Int32Array | null = null;
let rpcBuf: Uint8Array | null = null;

function rpcCallSync(namespace: string, op: string, args: Record<string, unknown>): string {
  if (!rpcState || !rpcBuf) throw new Error("rpc not initialized");
  const id = crypto.randomUUID();
  (self as any).postMessage({ type: "rpc_request", id, namespace, op, args });

  while (Atomics.load(rpcState, 0) === 0) {
    Atomics.wait(rpcState, 0, 0, 60_000);
  }

  const len = Atomics.load(rpcState, 1);
  const bytes = rpcBuf.subarray(0, len);
  const txt = new TextDecoder().decode(bytes);
  Atomics.store(rpcState, 0, 0);
  Atomics.store(rpcState, 1, 0);
  return txt;
}

function rpcCallSyncJsonArgs(namespace: string, op: string, argsJson: string): string {
  let args: Record<string, unknown> = {};
  try {
    const parsed = JSON.parse(String(argsJson ?? "{}"));
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      args = parsed as Record<string, unknown>;
    }
  } catch {
    // fall back to empty args
  }
  return rpcCallSync(namespace, op, args);
}

function rpcCallSyncResult(namespace: string, op: string, args: Record<string, unknown>): any {
  const txt = rpcCallSync(namespace, op, args);
  const obj = JSON.parse(txt);
  if (!obj || typeof obj !== "object") {
    throw new Error(`RPCTransportError: invalid rpc payload: ${txt.slice(0, 200)}`);
  }
  if (!obj.ok) {
    const err = obj.error ?? {};
    throw new Error(`RPCError: ${String(err.message ?? err.type ?? "unknown")}`);
  }
  return obj.result;
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

  // Use a filesystem path for indexURL to avoid "file:/..." pseudo-path issues.
  const indexURL = pyodidePackageDir();
  // Silence Pyodide's own package-loader chatter; stdout for user code is captured
  // explicitly in runWithLastExpr() by redirecting sys.stdout.
  pyodide = await loadPyodide({ indexURL, stdout: _noop, stderr: _noop });

  // Expose a JSON-args RPC to Python; Pyodide dicts become non-cloneable proxies
  // if we try to postMessage them directly.
  (self as any).rpc_call_sync = rpcCallSyncJsonArgs;

  const bootstrap = `
import ast, io, json, sys

class _RPC:
    @staticmethod
    def call(namespace: str, op: str, args: dict):
        import js
        payload = js.rpc_call_sync(namespace, op, json.dumps(args))
        obj = json.loads(str(payload))
        if not obj.get("ok", False):
            err = obj.get("error") or {}
            raise RuntimeError(f"RPCError: {err.get('message','unknown')}")
        return obj.get("result")

class _ToolCallable:
    def __init__(self, name: str, recipe: str | None = None):
        self._name = name
        self._recipe = recipe
    def __call__(self, **kwargs):
        tool = self._name if self._recipe is None else f"{self._name}.{self._recipe}"
        return _RPC.call("tools", "call_tool", {"name": tool, "args": kwargs})

class _Tool:
    def __init__(self, name: str):
        self._name = name
    def __call__(self, **kwargs):
        return _RPC.call("tools", "call_tool", {"name": self._name, "args": kwargs})
    def __getattr__(self, recipe: str):
        if recipe.startswith("_"):
            raise AttributeError(recipe)
        return _ToolCallable(self._name, recipe)
    def list(self):
        return _RPC.call("tools", "list_tool_recipes", {"name": self._name})

class _Tools:
    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        return _Tool(name)
    def list(self):
        return _RPC.call("tools", "list_tools", {})
    def search(self, query: str, limit: int = 5):
        return _RPC.call("tools", "search_tools", {"query": query, "limit": limit})

tools = _Tools()

class workflows:
    @staticmethod
    def list():
        return _RPC.call("workflows", "list_workflows", {})
    @staticmethod
    def search(query: str, limit: int = 5):
        return _RPC.call("workflows", "search_workflows", {"query": query, "limit": limit})
    @staticmethod
    def get(name: str):
        return _RPC.call("workflows", "get_workflow", {"name": name})
    @staticmethod
    def create(name: str, source: str, description: str):
        return _RPC.call("workflows", "create_workflow", {"name": name, "source": source, "description": description})
    @staticmethod
    def delete(name: str):
        return _RPC.call("workflows", "delete_workflow", {"name": name})

class artifacts:
    @staticmethod
    def list():
        return _RPC.call("artifacts", "list_artifacts", {})
    @staticmethod
    def get(name: str):
        return _RPC.call("artifacts", "get_artifact", {"name": name})
    @staticmethod
    def exists(name: str):
        return _RPC.call("artifacts", "artifact_exists", {"name": name})
    @staticmethod
    def load(name: str):
        return _RPC.call("artifacts", "load_artifact", {"name": name})
    @staticmethod
    def save(name: str, data, description: str = ""):
        return _RPC.call("artifacts", "save_artifact", {"name": name, "data": data, "description": description})
    @staticmethod
    def delete(name: str):
        return _RPC.call("artifacts", "delete_artifact", {"name": name})

class deps:
    @staticmethod
    def list():
        return _RPC.call("deps", "list_deps", {})
    @staticmethod
    def add(spec: str):
        _RPC.call("deps", "persist_add", {"spec": spec})
        return {"installed": [spec], "already_present": [], "failed": []}
    @staticmethod
    def remove(spec_or_name: str):
        removed = _RPC.call("deps", "persist_remove", {"spec_or_name": spec_or_name})
        return {
            "removed": [spec_or_name] if removed else [],
            "not_found": [] if removed else [spec_or_name],
            "failed": [],
            "removed_from_config": bool(removed),
        }
    @staticmethod
    def sync():
        specs = _RPC.call("deps", "list_deps", {}) or []
        return {"installed": list(specs), "already_present": [], "failed": []}
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

async function micropipInstallOne(spec: string): Promise<void> {
  if (!pyodide) throw new Error("pyodide not initialized");
  pyodide.globals.set("_PYCM_DEP_SPEC", spec);
  // runPythonAsync supports top-level await.
  await pyodide.runPythonAsync(`
import micropip
await micropip.install(_PYCM_DEP_SPEC)
`);
}

async function installPackages(packages: string[]): Promise<{
  installed: string[];
  already_present: string[];
  failed: string[];
}> {
  const installed: string[] = [];
  const already_present: string[] = [];
  const failed: string[] = [];

  const unique: string[] = [];
  for (const p of packages) {
    const spec = String(p ?? "").trim();
    if (!spec) continue;
    if (attemptedInstalls.has(spec)) {
      already_present.push(spec);
      continue;
    }
    unique.push(spec);
  }

  if (!unique.length) return { installed, already_present, failed };

  await ensureMicropipLoaded();

  for (const spec of unique) {
    try {
      await micropipInstallOne(spec);
      attemptedInstalls.add(spec);
      installed.push(spec);
    } catch (e) {
      failed.push(spec);
      // Keep going; this is best-effort.
      // We intentionally do not mark attemptedInstalls on failure so a later retry
      // (e.g., after network policy changes) can re-attempt.
    }
  }

  return { installed, already_present, failed };
}

function extractDepsRequests(code: string): { specs: string[]; wants_sync: boolean } {
  if (!pyodide) throw new Error("pyodide not initialized");
  pyodide.globals.set("_PYCM_SCAN_CODE", code);
  const txt = pyodide.runPython(`
import ast, json
try:
    _tree = ast.parse(_PYCM_SCAN_CODE)
except Exception:
    _out = json.dumps({"specs": [], "wants_sync": False})
else:
    class _V(ast.NodeVisitor):
        def __init__(self):
            self.specs = set()
            self.wants_sync = False
        # Skip descending into defs/classes entirely; those bodies aren't executed
        # just by being present in a cell.
        def visit_FunctionDef(self, node): return
        def visit_AsyncFunctionDef(self, node): return
        def visit_ClassDef(self, node): return
        def visit_Lambda(self, node): return

        def visit_Call(self, node):
            try:
                f = node.func
                if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "deps":
                    if f.attr == "add" and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                        self.specs.add(node.args[0].value)
                    elif f.attr == "sync" and not node.args and not node.keywords:
                        self.wants_sync = True
            except Exception:
                pass
            self.generic_visit(node)

    _v = _V()
    # Only scan top-level statements (and their non-def bodies).
    for _stmt in getattr(_tree, "body", []):
        _v.visit(_stmt)
    _out = json.dumps({"specs": sorted(_v.specs), "wants_sync": bool(_v.wants_sync)})

_out
`);
  const obj = JSON.parse(String(txt));
  return { specs: (obj.specs ?? []) as string[], wants_sync: Boolean(obj.wants_sync) };
}

async function maybeInstallDepsForCode(code: string): Promise<void> {
  const info = extractDepsRequests(code);
  const specsToAdd = info.specs ?? [];

  for (const spec of specsToAdd) {
    rpcCallSyncResult("deps", "persist_add", { spec });
  }

  let specsToInstall = specsToAdd;
  if (info.wants_sync) {
    const all = rpcCallSyncResult("deps", "list_deps", {}) ?? [];
    specsToInstall = Array.isArray(all) ? all.map((s) => String(s)) : [];
  }

  if (!specsToInstall.length) return;

  let res;
  try {
    res = await installPackages(specsToInstall);
  } catch (e) {
    throw new Error(`Failed to load micropip (network permission?): ${String((e as any)?.stack ?? e)}`);
  }
  if (res.failed.length) {
    throw new Error(`Dependency install failed: ${res.failed.join(", ")}`);
  }
}

function runWithLastExpr(code: string): { stdout: string; value: any; error: string | null } {
  const wrapper = `
import ast, io, sys, traceback
_stdout = io.StringIO()
_value = None
_error = None
try:
    _tree = ast.parse(_CODE)
    if _tree.body and isinstance(_tree.body[-1], ast.Expr):
        _stmts = _tree.body[:-1]
        _expr = _tree.body[-1]
        if _stmts:
            _m = ast.Module(body=_stmts, type_ignores=[])
            _c = compile(_m, "<code>", "exec")
            _old = sys.stdout
            sys.stdout = _stdout
            try:
                exec(_c, globals())
            finally:
                sys.stdout = _old
        _ec = compile(ast.Expression(body=_expr.value), "<expr>", "eval")
        _old = sys.stdout
        sys.stdout = _stdout
        try:
            _value = eval(_ec, globals())
        finally:
            sys.stdout = _old
    else:
        _old = sys.stdout
        sys.stdout = _stdout
        try:
            exec(_CODE, globals())
        finally:
            sys.stdout = _old
        _value = None
except Exception:
    _error = traceback.format_exc()
`;

  if (!pyodide) throw new Error("pyodide not initialized");
  pyodide.globals.set("_CODE", code);
  pyodide.runPython(wrapper);
  const stdout = pyodide.globals.get("_stdout").getvalue();
  const error = pyodide.globals.get("_error");

  let outValue: any;
  try {
    const jsonTxt = pyodide.runPython("import json; json.dumps(_value)") as string;
    outValue = JSON.parse(String(jsonTxt));
  } catch {
    const repr = pyodide.runPython("repr(_value)") as string;
    outValue = { __py_repr__: String(repr) };
  }

  return { stdout: String(stdout ?? ""), value: outValue ?? null, error: error ? String(error) : null };
}

self.onmessage = async (ev: MessageEvent<BootMsg | ExecMsg | DepsInstallMsg>) => {
  const msg = ev.data;
  if (msg.type === "boot") {
    rpcState = msg.rpcState;
    rpcBuf = msg.rpcBuf;
    try {
      await ensureBooted();
      (self as any).postMessage({ type: "boot_ok" });
    } catch (e) {
      (self as any).postMessage({ type: "boot_error", error: String((e as any)?.stack ?? e) });
    }
    return;
  }

  if (msg.type === "exec") {
    try {
      await maybeInstallDepsForCode(msg.code);
      const res = runWithLastExpr(msg.code);
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
  }

  if (msg.type === "deps_install") {
    try {
      const res = await installPackages(msg.packages ?? []);
      (self as any).postMessage({ type: "deps_install_result", id: msg.id, ...res });
    } catch (e) {
      (self as any).postMessage({
        type: "deps_install_result",
        id: msg.id,
        installed: [],
        already_present: [],
        failed: (msg.packages ?? []).map((p) => String(p)),
        error: String((e as any)?.stack ?? e),
      });
    }
  }
};
