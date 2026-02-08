// Pyodide worker. Executes Python code and provides synchronous RPC calls
// back to the Deno main thread (which forwards to the Python host).
//
// Single-flight RPC: one outstanding call at a time.

import { loadPyodide } from "npm:pyodide@0.29.3";

type BootMsg = {
  type: "boot";
  rpcState: Int32Array;
  rpcBuf: Uint8Array;
};

type ExecMsg = { type: "exec"; id: string; code: string };

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

async function ensureBooted() {
  if (booted) return;

  // Use a filesystem path for indexURL to avoid "file:/..." pseudo-path issues.
  const indexURL = pyodidePackageDir();
  pyodide = await loadPyodide({ indexURL });

  (self as any).rpc_call_sync = rpcCallSync;

  const bootstrap = `
import ast, io, json, sys

class _RPC:
    @staticmethod
    def call(namespace: str, op: str, args: dict):
        import js
        payload = js.rpc_call_sync(namespace, op, args)
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
    def recipes(self):
        return _RPC.call("tools", "list_tool_recipes", {"name": self._name})

class tools:
    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        return _Tool(name)
    @staticmethod
    def list():
        return _RPC.call("tools", "list_tools", {})
    @staticmethod
    def search(query: str, limit: int = 5):
        return _RPC.call("tools", "search_tools", {"query": query, "limit": limit})

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
        return {"installed": [], "already_present": [], "failed": ["deps.add not implemented (micropip TBD)"]}
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
        return {"installed": [], "already_present": [], "failed": [f"deps.sync not implemented (configured: {len(specs)})"]}
`;

  pyodide.runPython(bootstrap);
  booted = true;
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

self.onmessage = async (ev: MessageEvent<BootMsg | ExecMsg>) => {
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
};
