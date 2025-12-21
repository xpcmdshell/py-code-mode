"""Subprocess-based code execution using IPython kernel."""

from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from py_code_mode.storage.backends import StorageBackend

from jupyter_client import AsyncKernelManager

from py_code_mode.execution.protocol import (
    Capability,
    StorageAccess,
    validate_storage_not_access,
)
from py_code_mode.execution.registry import register_backend
from py_code_mode.execution.subprocess.config import SubprocessConfig
from py_code_mode.execution.subprocess.namespace import build_namespace_setup_code
from py_code_mode.execution.subprocess.venv import KernelVenv, VenvManager
from py_code_mode.types import ExecutionResult


def _get_current_python_version() -> str:
    """Get current Python version in major.minor format."""
    return f"{sys.version_info.major}.{sys.version_info.minor}"


class SubprocessExecutor:
    """Execute code in an isolated subprocess with its own venv and IPython kernel.

    Capabilities:
    - TIMEOUT: Yes (via message wait timeout)
    - PROCESS_ISOLATION: Yes (code runs in subprocess)
    - NETWORK_ISOLATION: No
    - FILESYSTEM_ISOLATION: No
    - RESET: Yes (kernel restart)

    Usage:
        config = SubprocessConfig(python_version="3.11", venv_path=Path("./venv"))
        async with SubprocessExecutor(config=config) as executor:
            result = await executor.run("1 + 1")
    """

    _CAPABILITIES = frozenset(
        {
            Capability.TIMEOUT,
            Capability.PROCESS_ISOLATION,
            Capability.RESET,
        }
    )

    def __init__(self, config: SubprocessConfig | None = None) -> None:
        """Initialize SubprocessExecutor.

        Args:
            config: Configuration for venv and kernel. Uses defaults if None.
        """
        self._config = config or SubprocessConfig(python_version=_get_current_python_version())
        self._venv_manager: VenvManager | None = None
        self._venv: KernelVenv | None = None
        self._km: AsyncKernelManager | None = None
        self._kc: Any = None  # AsyncKernelClient
        self._closed = False
        self._storage_access: StorageAccess | None = None

    def supports(self, capability: str) -> bool:
        """Check if this backend supports a capability."""
        return capability in self._CAPABILITIES

    def supported_capabilities(self) -> set[str]:
        """Return set of all capabilities this backend supports."""
        return set(self._CAPABILITIES)

    async def start(self, storage: StorageBackend | None = None) -> None:
        """Start kernel: create venv, start kernel, inject namespaces.

        Args:
            storage: Optional StorageBackend for namespace injection.
                    Calls storage.get_serializable_access() to get paths/URLs.

        Raises:
            RuntimeError: If already started or storage access fails.
            TypeError: If passed old StorageAccess types instead of StorageBackend.
        """
        # Reject old StorageAccess types - no backward compatibility
        validate_storage_not_access(storage, "SubprocessExecutor")

        if self._km is not None:
            raise RuntimeError("Executor already started")

        # Convert storage to storage_access for namespace injection
        storage_access: StorageAccess | None = None
        if storage is not None:
            try:
                storage_access = storage.get_serializable_access()
            except Exception as e:
                raise RuntimeError(
                    f"Failed to get serializable access from storage: {e}"
                ) from e
        self._storage_access = storage_access

        # 1. Create venv with VenvManager
        self._venv_manager = VenvManager(self._config)
        self._venv = await self._venv_manager.create()

        # 2. Start kernel
        self._km = AsyncKernelManager(kernel_name=self._venv.kernel_spec_name)
        await self._km.start_kernel()

        # 3. Connect client
        self._kc = self._km.client()
        self._kc.start_channels()
        await self._kc.wait_for_ready(timeout=self._config.startup_timeout)

        # 4. Inject namespaces if storage_access provided
        await self._setup_namespaces()

    async def run(self, code: str, timeout: float | None = None) -> ExecutionResult:
        """Execute code in kernel, return result.

        Args:
            code: Python code to execute.
            timeout: Optional timeout in seconds. Uses config default if None.

        Returns:
            ExecutionResult with value, stdout, and error fields.
        """
        if self._closed or self._kc is None:
            return ExecutionResult(value=None, stdout="", error="Executor is closed")

        timeout = timeout if timeout is not None else self._config.default_timeout

        # Send execute request
        msg_id = self._kc.execute(code, store_history=True)

        # Collect output from IOPub channel
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        value: Any = None
        error: str | None = None

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout

        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return ExecutionResult(
                    value=None,
                    stdout="".join(stdout_parts),
                    error=f"Timeout after {timeout}s",
                )

            try:
                msg = await asyncio.wait_for(
                    self._kc.get_iopub_msg(),
                    timeout=remaining,
                )
            except TimeoutError:
                return ExecutionResult(
                    value=None,
                    stdout="".join(stdout_parts),
                    error=f"Timeout after {timeout}s",
                )

            parent_msg_id = msg.get("parent_header", {}).get("msg_id")
            if parent_msg_id != msg_id:
                continue

            msg_type = msg["header"]["msg_type"]
            content = msg["content"]

            if msg_type == "stream":
                stream_name = content.get("name")
                if stream_name == "stdout":
                    stdout_parts.append(content["text"])
                elif stream_name == "stderr":
                    stderr_parts.append(content["text"])
            elif msg_type == "execute_result":
                value = content["data"].get("text/plain")
            elif msg_type == "error":
                error = "\n".join(content["traceback"])
            elif msg_type == "status" and content.get("execution_state") == "idle":
                break

        # Combine stdout and stderr (stderr appended after stdout)
        combined_output = "".join(stdout_parts)
        if stderr_parts:
            stderr_output = "".join(stderr_parts)
            if combined_output:
                combined_output = combined_output + stderr_output
            else:
                combined_output = stderr_output

        return ExecutionResult(value=value, stdout=combined_output, error=error)

    async def reset(self) -> None:
        """Clear kernel state by restarting.

        This clears all user-defined variables but re-injects namespaces.
        """
        if self._km is not None:
            await self._km.restart_kernel()
            if self._kc is not None:
                await self._kc.wait_for_ready(timeout=self._config.startup_timeout)
            await self._setup_namespaces()

    async def close(self) -> None:
        """Shutdown kernel and cleanup venv."""
        self._closed = True

        if self._kc is not None:
            self._kc.stop_channels()
            self._kc = None

        if self._km is not None:
            await self._km.shutdown_kernel()
            self._km = None

        if (
            self._config.cleanup_venv_on_close
            and self._venv is not None
            and self._venv_manager is not None
        ):
            await self._venv_manager.cleanup(self._venv)
            self._venv = None

    async def _setup_namespaces(self) -> None:
        """Inject tools/skills/artifacts namespaces into kernel.

        Uses build_namespace_setup_code() to generate Python code that sets up
        full py-code-mode namespaces in the kernel subprocess.
        """
        if self._storage_access is None:
            return

        setup_code = build_namespace_setup_code(self._storage_access)
        if setup_code:
            await self._run_setup_code(setup_code)

    async def _run_setup_code(self, code: str) -> None:
        """Run setup code in the kernel.

        Raises:
            RuntimeError: If namespace setup fails or times out.
        """
        if self._kc is None:
            return

        msg_id = self._kc.execute(code, store_history=False, silent=True)

        # Wait for completion
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._config.startup_timeout
        error: str | None = None

        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise RuntimeError(
                    f"Namespace setup timed out after {self._config.startup_timeout}s"
                )

            try:
                msg = await asyncio.wait_for(
                    self._kc.get_iopub_msg(),
                    timeout=remaining,
                )
            except TimeoutError:
                raise RuntimeError(
                    f"Namespace setup timed out after {self._config.startup_timeout}s"
                ) from None

            parent_msg_id = msg.get("parent_header", {}).get("msg_id")
            if parent_msg_id != msg_id:
                continue

            msg_type = msg["header"]["msg_type"]
            content = msg["content"]

            if msg_type == "error":
                traceback = content.get("traceback", [content.get("evalue", "Unknown error")])
                error = "\n".join(traceback)
            elif msg_type == "status" and content.get("execution_state") == "idle":
                break

        if error is not None:
            raise RuntimeError(f"Namespace setup failed: {error}")

    async def __aenter__(self) -> SubprocessExecutor:
        """Support async context manager."""
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Close on context exit."""
        await self.close()


# Register this backend
register_backend("subprocess", SubprocessExecutor)
