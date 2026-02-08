// NDJSON protocol runner: host (Python) <-> Deno main <-> Pyodide worker.
//
// This is dependency-light. The only external dependency should come from
// worker.ts (npm:pyodide). We rely on `deno cache` being run outside the
// sandbox so the sandboxed runner can use `--cached-only` and `--deny-net`.

type Req =
  | { id: string; type: "init" }
  | { id: string; type: "exec"; code: string }
  | { id: string; type: "deps_install"; packages: string[] }
  | { id: string; type: "reset" }
  | { id: string; type: "close" }
  | { id: string; type: "rpc_response"; ok: boolean; result?: unknown; error?: unknown };

type Resp =
  | { id: string; type: "ready" }
  | { id: string; type: "exec_result"; stdout: string; value: unknown; error: string | null }
  | { id: string; type: "deps_install_result"; installed: string[]; already_present: string[]; failed: string[] }
  | { id: string; type: "rpc_request"; namespace: string; op: string; args: Record<string, unknown> }
  | { id: string; type: "error"; message: string };

function writeMsg(msg: Resp) {
  Deno.stdout.writeSync(new TextEncoder().encode(JSON.stringify(msg) + "\n"));
}

async function* readNdjsonLines(): AsyncGenerator<string> {
  const decoder = new TextDecoder();
  let buf = "";
  for await (const chunk of Deno.stdin.readable) {
    buf += decoder.decode(chunk, { stream: true });
    while (true) {
      const idx = buf.indexOf("\n");
      if (idx < 0) break;
      const line = buf.slice(0, idx);
      buf = buf.slice(idx + 1);
      yield line;
    }
  }
  if (buf) yield buf;
}

// Shared buffers for synchronous RPC from the Pyodide worker.
// Single-flight: one outstanding RPC at a time.
const rpcState = new Int32Array(new SharedArrayBuffer(8)); // [status, length]
const rpcBuf = new Uint8Array(new SharedArrayBuffer(1024 * 1024)); // 1MB payload
// status: 0 = idle, 1 = response ready
let currentRpcId: string | null = null;

function rpcWriteResponse(rpcId: string, payload: unknown) {
  if (currentRpcId !== rpcId) {
    writeMsg({ id: rpcId, type: "error", message: `rpc id mismatch: expected ${currentRpcId}, got ${rpcId}` });
    return;
  }
  const data = new TextEncoder().encode(JSON.stringify(payload ?? null));
  const out = data.length > rpcBuf.byteLength
    ? new TextEncoder().encode(JSON.stringify({ ok: false, error: { type: "RPCTransportError", message: "rpc payload too large" } }))
    : data;

  rpcBuf.set(out.subarray(0, rpcBuf.byteLength));
  rpcState[1] = out.length;
  rpcState[0] = 1;
  Atomics.notify(rpcState, 0, 1);
  currentRpcId = null;
}

function newWorker(): Worker {
  const worker = new Worker(new URL("./worker.ts", import.meta.url), {
    type: "module",
    deno: { namespace: true },
  });
  worker.postMessage({
    type: "boot",
    rpcState,
    rpcBuf,
  });
  return worker;
}

let worker: Worker | null = null;
let workerBootError: string | null = null;
let workerReady = false;
let bootWait: Promise<void> | null = null;
let bootResolve: (() => void) | null = null;
let bootReject: ((e: unknown) => void) | null = null;

const execPending = new Map<string, { resolve: (v: any) => void; reject: (e: any) => void }>();

function ensureWorker() {
  if (!worker) worker = newWorker();
}

function resetWorker() {
  if (worker) worker.terminate();
  worker = newWorker();
  workerBootError = null;
  workerReady = false;
  bootWait = new Promise<void>((resolve, reject) => {
    bootResolve = resolve;
    bootReject = reject;
  });
}

function callExec(id: string, code: string): Promise<any> {
  ensureWorker();
  return new Promise((resolve, reject) => {
    if (workerBootError) return reject(new Error(workerBootError));
    execPending.set(id, { resolve, reject });
    worker!.postMessage({ type: "exec", id, code });
  });
}

function callDepsInstall(id: string, packages: string[]): Promise<any> {
  ensureWorker();
  return new Promise((resolve, reject) => {
    if (workerBootError) return reject(new Error(workerBootError));
    execPending.set(id, { resolve, reject });
    worker!.postMessage({ type: "deps_install", id, packages });
  });
}

function attachWorkerHandler() {
  if (!worker) return;
  worker.onmessage = (ev: MessageEvent<any>) => {
    const msg = ev.data;
    if (!msg || typeof msg !== "object") return;

    if (msg.type === "boot_ok") {
      workerReady = true;
      bootResolve?.();
      bootResolve = null;
      bootReject = null;
      return;
    }

    if (msg.type === "boot_error") {
      workerBootError = String(msg.error ?? "boot failed");
      workerReady = false;
      bootReject?.(new Error(workerBootError));
      bootResolve = null;
      bootReject = null;
      for (const [id, pending] of execPending) {
        pending.reject(new Error(workerBootError));
        execPending.delete(id);
      }
      writeMsg({ id: "worker", type: "error", message: workerBootError });
      return;
    }

    if (msg.type === "exec_result") {
      const pending = execPending.get(msg.id);
      if (pending) {
        execPending.delete(msg.id);
        pending.resolve(msg);
      }
      return;
    }

    if (msg.type === "deps_install_result") {
      const pending = execPending.get(msg.id);
      if (pending) {
        execPending.delete(msg.id);
        pending.resolve(msg);
      }
      return;
    }

    if (msg.type === "rpc_request") {
      currentRpcId = msg.id;
      writeMsg({ id: msg.id, type: "rpc_request", namespace: msg.namespace, op: msg.op, args: msg.args });
      return;
    }
  };

  worker.onerror = (e) => {
    const m = String((e as any).message ?? e);
    workerBootError = m;
    workerReady = false;
    bootReject?.(new Error(m));
    bootResolve = null;
    bootReject = null;
    for (const [id, pending] of execPending) {
      pending.reject(new Error(m));
      execPending.delete(id);
    }
    writeMsg({ id: "worker", type: "error", message: m });
  };
}

// Ensure exec/deps_install are single-flight, but don't block stdin processing:
// the worker needs rpc_response messages to arrive while code is running.
let runChain: Promise<unknown> = Promise.resolve();
function enqueueRun(fn: () => Promise<void>) {
  const p = runChain.then(fn, fn);
  runChain = p.catch(() => {});
}

async function handleReq(req: Req) {
  try {
    if (req.type === "rpc_response") {
      rpcWriteResponse(req.id, req.ok ? { ok: true, result: req.result } : { ok: false, error: req.error });
      return;
    }

    if (req.type === "init") {
      resetWorker();
      attachWorkerHandler();
      if (bootWait) await bootWait;
      writeMsg({ id: req.id, type: "ready" });
      return;
    }

    if (req.type === "reset") {
      resetWorker();
      attachWorkerHandler();
      if (bootWait) await bootWait;
      writeMsg({ id: req.id, type: "ready" });
      return;
    }

    if (req.type === "exec") {
      enqueueRun(async () => {
        if (bootWait) await bootWait;
        const res = await callExec(req.id, req.code);
        writeMsg({
          id: req.id,
          type: "exec_result",
          stdout: res.stdout ?? "",
          value: res.value ?? null,
          error: res.error ?? null,
        });
      });
      return;
    }

    if (req.type === "deps_install") {
      enqueueRun(async () => {
        if (bootWait) await bootWait;
        const res = await callDepsInstall(req.id, req.packages ?? []);
        writeMsg({
          id: req.id,
          type: "deps_install_result",
          installed: res.installed ?? [],
          already_present: res.already_present ?? [],
          failed: res.failed ?? [],
        });
      });
      return;
    }
  } catch (e) {
    writeMsg({ id: req.id, type: "error", message: String((e as any)?.stack ?? e) });
  }
}

for await (const line of readNdjsonLines()) {
  if (!line.trim()) continue;
  let req: Req;
  try {
    req = JSON.parse(line);
  } catch (e) {
    writeMsg({ id: "parse", type: "error", message: `invalid json: ${String(e)}` });
    continue;
  }

  if (req.type === "close") {
    try {
      if (worker) worker.terminate();
      worker = null;
      writeMsg({ id: req.id, type: "ready" });
    } finally {
      break;
    }
  }

  void handleReq(req);
}
