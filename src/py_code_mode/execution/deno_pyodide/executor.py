"""Deno + Pyodide execution backend.

This executor runs Python inside Pyodide (WASM) in a Deno subprocess.

It uses an NDJSON IPC protocol and a host-side provider to service sandbox
namespace proxy operations (tools/workflows/artifacts/deps persistence).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from py_code_mode.deps import (
    FileDepsStore,
    MemoryDepsStore,
    RuntimeDepsDisabledError,
    collect_configured_deps,
)
from py_code_mode.deps.store import DepsStore
from py_code_mode.execution.deno_pyodide.config import DenoPyodideConfig
from py_code_mode.execution.protocol import Capability, validate_storage_not_access
from py_code_mode.execution.registry import register_backend
from py_code_mode.execution.resource_provider import StorageResourceProvider
from py_code_mode.tools import ToolRegistry, load_tools_from_path
from py_code_mode.types import ExecutionResult

if TYPE_CHECKING:
    from asyncio.subprocess import Process

    from py_code_mode.storage.backends import StorageBackend

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Pending:
    fut: asyncio.Future[dict[str, Any]]


class DenoPyodideExecutor:
    """Execute code in Pyodide hosted by Deno.

    Capabilities:
    - TIMEOUT: Yes (soft timeout in host wait; does not interrupt sandbox run)
    - PROCESS_ISOLATION: Yes (Deno subprocess)
    - NETWORK_ISOLATION: Yes (Deno permissions; default deny)
    - FILESYSTEM_ISOLATION: Partial (Deno permissions; allow-read to Pyodide assets)
    - RESET: Yes (restart Deno subprocess)
    - DEPS_INSTALL / DEPS_UNINSTALL: Best-effort (Pyodide/micropip)
    """

    _CAPABILITIES = frozenset(
        {
            Capability.TIMEOUT,
            Capability.PROCESS_ISOLATION,
            Capability.NETWORK_ISOLATION,
            Capability.NETWORK_FILTERING,
            Capability.FILESYSTEM_ISOLATION,
            Capability.RESET,
            Capability.DEPS_INSTALL,
            Capability.DEPS_UNINSTALL,
        }
    )

    def __init__(self, config: DenoPyodideConfig | None = None) -> None:
        self._config = config or DenoPyodideConfig()
        self._proc: Process | None = None
        self._stdout_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._pending: dict[str, _Pending] = {}
        self._closed = False
        self._wedged = False  # indicates a soft-timeout run may still be executing
        self._deno_dir: Path | None = None

        self._storage: StorageBackend | None = None
        self._provider: StorageResourceProvider | None = None
        self._tool_registry: ToolRegistry | None = None
        self._deps_store: DepsStore | None = None

    def supports(self, capability: str) -> bool:
        return capability in self._CAPABILITIES

    def supported_capabilities(self) -> set[str]:
        return set(self._CAPABILITIES)

    def get_configured_deps(self) -> list[str]:
        return collect_configured_deps(self._config.deps, self._config.deps_file)

    async def __aenter__(self) -> DenoPyodideExecutor:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    async def start(self, storage: StorageBackend | None = None) -> None:
        validate_storage_not_access(storage, "DenoPyodideExecutor")
        if self._proc is not None:
            return

        if shutil.which(self._config.deno_executable) is None:
            raise RuntimeError(f"deno not found: {self._config.deno_executable!r}")

        self._storage = storage
        self._deno_dir = (self._config.deno_dir or self._default_deno_dir()).expanduser().resolve()
        self._deno_dir.mkdir(parents=True, exist_ok=True)

        # Tools from executor config
        if self._config.tools_path is not None:
            self._tool_registry = await load_tools_from_path(self._config.tools_path)
        else:
            self._tool_registry = ToolRegistry()

        # Deps store from executor config (persistence only; installs happen in sandbox)
        initial_deps = collect_configured_deps(self._config.deps, self._config.deps_file)
        if self._config.deps_file:
            self._deps_store = FileDepsStore(self._config.deps_file.parent)
            for dep in initial_deps:
                if not self._deps_store.exists(dep):
                    self._deps_store.add(dep)
        else:
            self._deps_store = MemoryDepsStore()
            for dep in initial_deps:
                self._deps_store.add(dep)

        if storage is not None:
            self._provider = StorageResourceProvider(
                storage=storage,
                tool_registry=self._tool_registry,
                deps_store=self._deps_store,
                allow_runtime_deps=self._config.allow_runtime_deps,
            )

        await self._ensure_deno_cache()
        await self._spawn_runner()

    def _default_deno_dir(self) -> Path:
        return Path.home() / ".cache" / "py-code-mode" / "deno-pyodide"

    async def _ensure_deno_cache(self) -> None:
        """Cache runner modules + npm:pyodide outside the sandbox."""
        runner_path = self._config.runner_path or (
            Path(__file__).resolve().parent / "runner" / "main.ts"
        )
        worker_path = runner_path.parent / "worker.ts"
        deno_dir = self._deno_dir
        assert deno_dir is not None

        cmd = [
            self._config.deno_executable,
            "cache",
            "--quiet",
            "--no-check",
            str(runner_path),
            str(worker_path),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            env={**os.environ, "DENO_DIR": str(deno_dir)},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _out, err = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"deno cache failed: {err.decode('utf-8', errors='replace')}")

    async def _spawn_runner(self) -> None:
        runner_path = self._config.runner_path or (
            Path(__file__).resolve().parent / "runner" / "main.ts"
        )
        runner_dir = runner_path.parent.resolve()
        deno_dir = self._deno_dir
        assert deno_dir is not None

        # Sandbox defaults: cached-only + deny-net.
        allow_reads = [runner_dir, deno_dir]

        deno_args: list[str] = [
            self._config.deno_executable,
            "run",
            "--quiet",
            "--no-check",
            "--no-prompt",
            "--cached-only",
            "--location=https://pyodide.invalid/",
            "--deny-env",
            "--deny-run",
        ]
        # Pyodide caches wheels into the Deno npm cache under DENO_DIR.
        # Allow writes only to that cache directory.
        deno_args.append(f"--allow-write={deno_dir}")
        profile = self._config.network_profile
        if profile == "full":
            deno_args.append("--allow-net")
        elif profile == "deps-only":
            allow = ",".join(self._config.deps_net_allowlist)
            deno_args.append(f"--allow-net={allow}")
        elif profile == "none":
            deno_args.append("--deny-net")
        else:
            raise ValueError(f"unknown network_profile: {profile!r}")

        deno_args.append(f"--allow-read={','.join(str(p) for p in allow_reads)}")
        deno_args.append(str(runner_path))

        self._proc = await asyncio.create_subprocess_exec(
            *deno_args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "DENO_DIR": str(deno_dir)},
        )

        assert self._proc.stdin is not None
        assert self._proc.stdout is not None

        self._stdout_task = asyncio.create_task(self._stdout_loop())
        self._stderr_task = asyncio.create_task(self._stderr_loop())

        # Initialize runner with runtime directory and wait for ready.
        init_id = uuid.uuid4().hex
        ready = await self._request(
            {
                "id": init_id,
                "type": "init",
            },
            timeout=self._config.ipc_timeout,
        )
        if ready.get("type") != "ready":
            raise RuntimeError(f"Runner init failed: {ready!r}")

        self._wedged = False

    async def _stdout_loop(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        reader = self._proc.stdout
        while True:
            line = await reader.readline()
            if not line:
                return
            try:
                msg = json.loads(line.decode("utf-8", errors="replace"))
            except Exception:
                continue
            if not isinstance(msg, dict):
                continue

            msg_type = msg.get("type")
            msg_id = msg.get("id")

            if msg_type == "rpc_request":
                await self._handle_rpc_request(msg)
                continue

            if isinstance(msg_id, str) and msg_id in self._pending:
                pending = self._pending.pop(msg_id)
                if not pending.fut.done():
                    pending.fut.set_result(msg)

    async def _stderr_loop(self) -> None:
        assert self._proc is not None and self._proc.stderr is not None
        reader = self._proc.stderr
        while True:
            line = await reader.readline()
            if not line:
                return
            # Keep stderr drained to avoid deadlocks; log at debug to aid diagnosis.
            logger.debug("deno stderr: %s", line.decode("utf-8", errors="replace").rstrip())

    async def _deps_install(self, packages: list[str]) -> dict[str, Any]:
        if not packages:
            return {"installed": [], "already_present": [], "failed": []}
        if self._proc is None:
            await self.start(storage=self._storage)

        req_id = uuid.uuid4().hex
        timeout = self._config.deps_timeout
        res = await self._request(
            {"id": req_id, "type": "deps_install", "packages": list(packages)},
            timeout=timeout,
        )
        if res.get("type") != "deps_install_result":
            return {
                "installed": [],
                "already_present": [],
                "failed": [f"Unexpected runner response: {res!r}"],
            }
        return {
            "installed": list(res.get("installed") or []),
            "already_present": list(res.get("already_present") or []),
            "failed": list(res.get("failed") or []),
        }

    async def _handle_rpc_request(self, msg: dict[str, Any]) -> None:
        if self._proc is None or self._proc.stdin is None:
            return

        req_id = msg.get("id")
        namespace = msg.get("namespace")
        op = msg.get("op")
        # Runner forwards rpc_request from the Pyodide worker. New protocol uses
        # args_json (string) to avoid structured clone issues with Python proxy
        # objects. Keep backwards-compat with args (dict) for older runners.
        args: dict[str, Any]
        if "args_json" in msg:
            raw = msg.get("args_json")
            if not isinstance(raw, str):
                raw = "{}"
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = {}
            if parsed is None:
                args = {}
            elif isinstance(parsed, dict):
                args = parsed
            else:
                args = {}
        else:
            raw_args = msg.get("args") or {}
            args = raw_args if isinstance(raw_args, dict) else {}

        if not isinstance(req_id, str) or not isinstance(namespace, str) or not isinstance(op, str):
            await self._send(
                {
                    "id": str(req_id),
                    "type": "rpc_response",
                    "ok": False,
                    "error": "bad rpc request",
                }
            )
            return

        try:
            result = await self._dispatch_rpc(namespace, op, args)
            await self._send({"id": req_id, "type": "rpc_response", "ok": True, "result": result})
        except Exception as e:
            await self._send(
                {
                    "id": req_id,
                    "type": "rpc_response",
                    "ok": False,
                    "error": {"type": type(e).__name__, "message": str(e)},
                }
            )

    async def _dispatch_rpc(self, namespace: str, op: str, args: dict[str, Any]) -> Any:
        if namespace in ("tools", "workflows", "artifacts"):
            if self._provider is None:
                raise RuntimeError("No storage/provider configured")

        if namespace == "tools":
            if op == "list_tools":
                return await self._provider.list_tools()
            if op == "search_tools":
                return await self._provider.search_tools(args["query"], int(args.get("limit", 10)))
            if op == "list_tool_recipes":
                return await self._provider.list_tool_recipes(args["name"])
            if op == "call_tool":
                return await self._provider.call_tool(args["name"], args.get("args") or {})
            raise ValueError(f"unknown tools op: {op}")

        if namespace == "workflows":
            if op == "list_workflows":
                return await self._provider.list_workflows()
            if op == "search_workflows":
                return await self._provider.search_workflows(
                    args["query"], int(args.get("limit", 5))
                )
            if op == "get_workflow":
                return await self._provider.get_workflow(args["name"])
            if op == "create_workflow":
                return await self._provider.create_workflow(
                    args["name"], args["source"], args.get("description", "")
                )
            if op == "delete_workflow":
                return await self._provider.delete_workflow(args["name"])
            raise ValueError(f"unknown workflows op: {op}")

        if namespace == "artifacts":
            if op == "list_artifacts":
                return await self._provider.list_artifacts()
            if op == "get_artifact":
                return await self._provider.get_artifact(args["name"])
            if op == "artifact_exists":
                return await self._provider.artifact_exists(args["name"])
            if op == "load_artifact":
                return await self._provider.load_artifact(args["name"])
            if op == "save_artifact":
                return await self._provider.save_artifact(
                    args["name"], args.get("data"), args.get("description", "")
                )
            if op == "delete_artifact":
                await self._provider.delete_artifact(args["name"])
                return None
            raise ValueError(f"unknown artifacts op: {op}")

        if namespace == "deps":
            # Persistence only; sandbox performs actual installs best-effort.
            if self._deps_store is None:
                return [] if op == "list_deps" else False

            if op == "list_deps":
                return self._deps_store.list()

            if op == "persist_add":
                if not self._config.allow_runtime_deps:
                    raise RuntimeDepsDisabledError(
                        "Runtime dependency installation is disabled. "
                        "Dependencies must be pre-configured before session start."
                    )
                spec = args["spec"]
                self._deps_store.add(spec)
                return True

            if op == "persist_remove":
                if not self._config.allow_runtime_deps:
                    raise RuntimeDepsDisabledError(
                        "Runtime dependency modification is disabled. "
                        "Dependencies must be pre-configured before session start."
                    )
                name = args["spec_or_name"]
                return self._deps_store.remove(name)

            raise ValueError(f"unknown deps op: {op}")

        raise ValueError(f"unknown rpc namespace: {namespace}")

    async def _send(self, msg: dict[str, Any]) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise RuntimeError("Runner not started")
        data = (json.dumps(msg, ensure_ascii=True) + "\n").encode("utf-8")
        self._proc.stdin.write(data)
        await self._proc.stdin.drain()

    async def _request(self, msg: dict[str, Any], timeout: float | None) -> dict[str, Any]:
        req_id = msg.get("id")
        if not isinstance(req_id, str):
            raise TypeError("request message must include string id")
        fut: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[req_id] = _Pending(fut=fut)
        await self._send(msg)

        if timeout is None:
            return await fut
        return await asyncio.wait_for(fut, timeout=timeout)

    async def run(self, code: str, timeout: float | None = None) -> ExecutionResult:
        if self._closed:
            return ExecutionResult(value=None, stdout="", error="Executor is closed")
        if self._proc is None:
            await self.start(storage=self._storage)

        if self._wedged:
            return ExecutionResult(
                value=None,
                stdout="",
                error=(
                    "Previous execution timed out; sandbox may still be running. "
                    "Call session.reset()."
                ),
            )

        effective_timeout = timeout if timeout is not None else self._config.default_timeout
        req_id = uuid.uuid4().hex

        try:
            res = await self._request(
                {"id": req_id, "type": "exec", "code": code},
                timeout=effective_timeout,
            )
        except TimeoutError:
            self._wedged = True
            return ExecutionResult(
                value=None,
                stdout="",
                error=(
                    f"Execution timeout after {effective_timeout} seconds "
                    "(soft timeout; state preserved if it finishes)."
                ),
            )

        if res.get("type") != "exec_result":
            return ExecutionResult(
                value=None, stdout="", error=f"Unexpected runner response: {res!r}"
            )

        return ExecutionResult(
            value=res.get("value"),
            stdout=res.get("stdout") or "",
            error=res.get("error"),
        )

    async def reset(self) -> None:
        # Hard reset: restart the Deno subprocess to guarantee recovery.
        await self._restart()

    async def _restart(self) -> None:
        await self.close()
        self._closed = False
        self._proc = None
        self._stdout_task = None
        self._pending.clear()
        self._wedged = False
        await self.start(storage=self._storage)

    async def close(self) -> None:
        if self._proc is not None:
            try:
                await self._send({"id": uuid.uuid4().hex, "type": "close"})
            except Exception:
                pass
            try:
                self._proc.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=2.0)
            except Exception:
                pass
        if self._stdout_task is not None:
            self._stdout_task.cancel()
        if self._stderr_task is not None:
            self._stderr_task.cancel()
        if self._tool_registry is not None:
            await self._tool_registry.close()
        self._proc = None
        self._stdout_task = None
        self._stderr_task = None
        self._closed = True
        self._pending.clear()
        self._wedged = False

    # -------------------------------------------------------------------------
    # Tools facade (host-side)
    # -------------------------------------------------------------------------

    async def list_tools(self) -> list[dict[str, Any]]:
        if self._tool_registry is None:
            return []
        return [tool.to_dict() for tool in self._tool_registry.list_tools()]

    async def search_tools(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        if self._tool_registry is None:
            return []
        return [tool.to_dict() for tool in self._tool_registry.search(query, limit=limit)]

    # -------------------------------------------------------------------------
    # Deps facade (host persistence + sandbox best-effort install via exec)
    # -------------------------------------------------------------------------

    async def install_deps(self, packages: list[str]) -> dict[str, Any]:
        # System-level API (used by Session._sync_deps()).
        return await self._deps_install(packages)

    async def uninstall_deps(self, packages: list[str]) -> dict[str, Any]:
        # Pyodide does not reliably support uninstall. We treat this as config removal only.
        removed: list[str] = []
        failed: list[str] = []
        for pkg in packages:
            try:
                await self.remove_dep(pkg)
                removed.append(pkg)
            except Exception:
                failed.append(pkg)
        return {"removed": removed, "not_found": [], "failed": failed}

    async def add_dep(self, package: str) -> dict[str, Any]:
        if not self._config.allow_runtime_deps:
            raise RuntimeDepsDisabledError(
                "Runtime dependency installation is disabled. "
                "Dependencies must be pre-configured before session start."
            )
        if self._deps_store is not None:
            self._deps_store.add(package)
        return await self._deps_install([package])

    async def remove_dep(self, package: str) -> dict[str, Any]:
        if not self._config.allow_runtime_deps:
            raise RuntimeDepsDisabledError(
                "Runtime dependency modification is disabled. "
                "Dependencies must be pre-configured before session start."
            )
        removed_from_config = False
        if self._deps_store is not None:
            removed_from_config = self._deps_store.remove(package)
        return {
            "removed": [package] if removed_from_config else [],
            "not_found": [] if removed_from_config else [package],
            "failed": [],
            "removed_from_config": removed_from_config,
        }

    async def list_deps(self) -> list[str]:
        if self._deps_store is None:
            return []
        return self._deps_store.list()

    async def sync_deps(self) -> dict[str, Any]:
        if self._deps_store is None:
            return {"installed": [], "already_present": [], "failed": []}
        return await self._deps_install(self._deps_store.list())


register_backend("deno-pyodide", DenoPyodideExecutor)
