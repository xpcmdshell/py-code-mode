"""Subprocess-based code execution using IPython kernel."""

from __future__ import annotations

import ast
import asyncio
import logging
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

logger = logging.getLogger(__name__)


def _deserialize_value(text_repr: str | None) -> Any:
    """Deserialize IPython text/plain representation to Python value.

    IPython returns repr() of results as text/plain. This safely evaluates
    Python literals (numbers, strings, bools, None, containers) using
    ast.literal_eval. For complex objects that can't be literal-evaluated,
    returns the string representation as-is.

    Args:
        text_repr: The text/plain representation from IPython.

    Returns:
        The Python value if it can be safely parsed, otherwise the string.
    """
    if text_repr is None:
        return None

    try:
        return ast.literal_eval(text_repr)
    except (ValueError, SyntaxError):
        # Complex objects (custom classes, etc.) - return as string
        return text_repr


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
            Capability.DEPS_INSTALL,
            Capability.DEPS_UNINSTALL,
        }
    )

    def __init__(self, config: SubprocessConfig | None = None) -> None:
        """Initialize SubprocessExecutor.

        Args:
            config: Configuration for venv and kernel. Uses defaults if None.
        """
        self._config = config or SubprocessConfig()
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
                raise RuntimeError(f"Failed to get serializable access from storage: {e}") from e
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
                    None means no timeout (unlimited).

        Returns:
            ExecutionResult with value, stdout, and error fields.
        """
        if self._closed or self._kc is None:
            return ExecutionResult(value=None, stdout="", error="Executor is closed")

        # Use config default if not specified (could still be None for unlimited)
        effective_timeout = timeout if timeout is not None else self._config.default_timeout

        # Send execute request
        msg_id = self._kc.execute(code, store_history=True)

        # Collect output from IOPub channel
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        value: Any = None
        error: str | None = None

        # Set up deadline only if timeout is specified
        loop = asyncio.get_running_loop()
        deadline: float | None = None
        if effective_timeout is not None:
            deadline = loop.time() + effective_timeout

        while True:
            # Check deadline if set
            if deadline is not None:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    return ExecutionResult(
                        value=None,
                        stdout="".join(stdout_parts),
                        error=f"Timeout after {effective_timeout}s",
                    )
            else:
                remaining = None  # No timeout

            try:
                if remaining is not None:
                    msg = await asyncio.wait_for(
                        self._kc.get_iopub_msg(),
                        timeout=remaining,
                    )
                else:
                    # Unlimited - wait without timeout
                    msg = await self._kc.get_iopub_msg()
            except TimeoutError:
                return ExecutionResult(
                    value=None,
                    stdout="".join(stdout_parts),
                    error=f"Timeout after {effective_timeout}s",
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
                text_repr = content["data"].get("text/plain")
                value = _deserialize_value(text_repr)
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

    async def install_deps(self, packages: list[str]) -> dict[str, Any]:
        """Install packages in the subprocess venv.

        This is a system-level API called by Session._sync_deps() during startup.
        It installs pre-configured packages and is NOT affected by allow_runtime_deps.

        Agent-initiated installs via deps.add() are blocked by ControlledDepsNamespace
        when allow_runtime_deps=False.

        Args:
            packages: List of package specifications to install.

        Returns:
            Dict with "installed", "already_present", and "failed" lists.

        Raises:
            RuntimeError: If venv is not initialized.
        """
        # NOTE: This method does NOT check allow_runtime_deps.
        # It's a system-level API for Session._sync_deps() to install pre-configured deps.
        # Agent-initiated installs are blocked at the namespace level by ControlledDepsNamespace.

        if self._venv_manager is None or self._venv is None:
            raise RuntimeError("Venv not initialized")

        installed: list[str] = []
        failed: list[str] = []

        for pkg in packages:
            try:
                await self._venv_manager.add_package(self._venv, pkg)
                installed.append(pkg)
            except Exception as e:
                logger.warning("Failed to install %s: %s", pkg, e)
                failed.append(pkg)

        return {"installed": installed, "already_present": [], "failed": failed}

    async def uninstall_deps(self, packages: list[str]) -> dict[str, Any]:
        """Uninstall packages from the subprocess venv.

        This is a system-level API called by Session.remove_dep().
        It uninstalls packages and is NOT affected by allow_runtime_deps.

        Agent-initiated removals via deps.remove() are blocked by ControlledDepsNamespace
        when allow_runtime_deps=False.

        Args:
            packages: List of package names to uninstall.

        Returns:
            Dict with "removed", "not_found", and "failed" lists.

        Raises:
            RuntimeError: If venv is not initialized.
        """
        # NOTE: This method does NOT check allow_runtime_deps.
        # It's a system-level API for Session.remove_dep() to uninstall packages.
        # Agent-initiated removals are blocked at the namespace level by ControlledDepsNamespace.

        if self._venv_manager is None or self._venv is None:
            raise RuntimeError("Venv not initialized")

        removed: list[str] = []
        failed: list[str] = []

        for pkg in packages:
            try:
                await self._venv_manager.remove_package(self._venv, pkg)
                removed.append(pkg)
            except Exception as e:
                logger.warning("Failed to uninstall %s: %s", pkg, e)
                failed.append(pkg)

        return {"removed": removed, "not_found": [], "failed": failed}

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
            self._config.get_resolved_cleanup()
            and self._venv is not None
            and self._venv_manager is not None
        ):
            await self._venv_manager.cleanup(self._venv)
            self._venv = None

    async def _setup_namespaces(self) -> None:
        """Inject tools/skills/artifacts/deps namespaces into kernel.

        Uses build_namespace_setup_code() to generate Python code that sets up
        full py-code-mode namespaces in the kernel subprocess.
        """
        if self._storage_access is None:
            return

        setup_code = build_namespace_setup_code(
            self._storage_access,
            allow_runtime_deps=self._config.allow_runtime_deps,
        )
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
