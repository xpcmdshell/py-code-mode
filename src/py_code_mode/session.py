"""Session - unified interface for code execution with storage.

Session wraps a StorageBackend and Executor, providing the primary API
for py-code-mode. It injects tools, skills, and artifacts namespaces
into the executor's runtime environment.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from py_code_mode.execution import Executor
from py_code_mode.types import ExecutionResult

if TYPE_CHECKING:
    from py_code_mode.storage import StorageBackend


class Session:
    """Unified session for code execution with storage.

    Session lifecycle:
        1. Create with storage backend (and optional executor type)
        2. Call start() to initialize executor and namespaces
        3. Run code via run()
        4. Close to release resources

    Or use as async context manager:
        async with Session(storage=storage) as session:
            result = await session.run("tools.list()")
    """

    def __init__(
        self,
        storage: StorageBackend | None = None,
        executor: Executor | None = None,
        sync_deps_on_start: bool = False,
    ) -> None:
        """Initialize session.

        Args:
            storage: Storage backend (FileStorage or RedisStorage).
                    Required (cannot be None).
            executor: Executor instance (InProcessExecutor, ContainerExecutor).
                     Default: InProcessExecutor()
            sync_deps_on_start: If True, install all configured dependencies
                               when session starts. Default: False.

        Raises:
            TypeError: If executor is a string (unsupported).
            ValueError: If storage is None.
        """
        # Validate storage
        if storage is None:
            raise ValueError("storage parameter is required and cannot be None")

        # Reject string-based executor selection
        if isinstance(executor, str):
            raise TypeError(
                f"String-based executor selection is no longer supported. "
                f"Use typed executor instances instead:\n"
                f"  Session(storage=storage, executor=InProcessExecutor())\n"
                f"  Session(storage=storage, executor=ContainerExecutor(config))\n"
                f"Got: executor={executor!r}"
            )

        # Validate executor type if provided
        if executor is not None and not isinstance(executor, Executor):
            raise TypeError(
                f"executor must be an Executor instance or None, got {type(executor).__name__}"
            )

        self._storage = storage
        self._executor_spec = executor  # Store the instance directly
        self._executor: Executor | None = None
        self._started = False
        self._closed = False
        self._sync_deps_on_start = sync_deps_on_start

    @property
    def storage(self) -> StorageBackend:
        """Access the storage backend."""
        return self._storage

    async def _sync_deps(self) -> None:
        """Sync configured dependencies by running deps.sync() via executor.

        This method syncs pre-configured dependencies even when runtime deps are
        disabled. It accesses the underlying DepsNamespace directly, bypassing
        any ControlledDepsNamespace wrapper.
        """
        if self._executor is None:
            return

        # Get the underlying deps namespace, bypassing any wrapper
        deps_ns = getattr(self._executor, "_deps_namespace", None)
        if deps_ns is not None:
            deps_ns.sync()

    async def start(self) -> None:
        """Initialize the executor and inject namespaces.

        This must be called before run() if not using as context manager.
        """
        if self._started:
            return

        # Use provided executor or default to InProcessExecutor
        if self._executor_spec is None:
            from py_code_mode.execution.in_process import InProcessExecutor

            self._executor = InProcessExecutor()
        else:
            self._executor = self._executor_spec

        # Start executor with storage backend directly
        # Each executor handles storage access appropriately:
        # - InProcessExecutor: uses storage.tools/skills/artifacts directly
        # - ContainerExecutor: calls storage.get_serializable_access() internally
        # - SubprocessExecutor: calls storage.get_serializable_access() internally
        await self._executor.start(storage=self._storage)
        self._started = True

        # Sync dependencies if requested
        if self._sync_deps_on_start:
            await self._sync_deps()

    async def run(self, code: str, timeout: float | None = None) -> ExecutionResult:
        """Run Python code and return result.

        Args:
            code: Python code to execute.
            timeout: Optional timeout in seconds.

        Returns:
            ExecutionResult with value, stdout, and optional error.
        """
        if self._closed:
            return ExecutionResult(
                value=None,
                stdout="",
                error="Session is closed",
            )

        if not self._started:
            await self.start()

        if self._executor is None:
            return ExecutionResult(
                value=None,
                stdout="",
                error="Executor not initialized",
            )

        return await self._executor.run(code, timeout=timeout)

    async def reset(self) -> None:
        """Reset the execution environment.

        Clears all user-defined variables but preserves tools, skills, artifacts namespaces.
        """
        if self._executor is None:
            return

        from py_code_mode.execution import Capability

        # Use executor's reset if supported
        if self._executor.supports(Capability.RESET):
            await self._executor.reset()
        else:
            # Fallback: close and restart
            await self._executor.close()
            self._started = False
            await self.start()

    async def close(self) -> None:
        """Release session resources."""
        if self._executor is not None:
            await self._executor.close()
            self._executor = None
        self._started = False
        self._closed = True

    def supports(self, capability: str) -> bool:
        """Check if session supports a capability.

        Args:
            capability: Capability name (e.g., "timeout", "network_isolation")

        Returns:
            True if capability is supported.
        """
        if self._executor is None:
            return False
        return self._executor.supports(capability)

    def supported_capabilities(self) -> set[str]:
        """Get all supported capabilities.

        Returns:
            Set of capability names.
        """
        if self._executor is None:
            return set()
        return self._executor.supported_capabilities()

    async def __aenter__(self) -> Session:
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Async context manager exit."""
        await self.close()
