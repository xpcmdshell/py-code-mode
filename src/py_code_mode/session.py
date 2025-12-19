"""Session - unified interface for code execution with storage.

Session wraps a StorageBackend and Executor, providing the primary API
for py-code-mode. It injects tools, skills, and artifacts namespaces
into the executor's runtime environment.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from py_code_mode.backend import Executor, StorageAccess
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
        **executor_kwargs: Any,
    ) -> None:
        """Initialize session.

        Args:
            storage: Storage backend (FileStorage or RedisStorage).
                    Required (cannot be None).
            executor: Executor instance (InProcessExecutor, ContainerExecutor).
                     Default: InProcessExecutor()
            **executor_kwargs: Deprecated. Reserved for future use.

        Raises:
            TypeError: If executor is a string (deprecated API).
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
        self._executor_kwargs = executor_kwargs
        self._executor: Executor | None = None
        self._started = False
        self._closed = False

    def _derive_storage_access(self) -> StorageAccess:
        """Derive StorageAccess descriptor from storage backend.

        Maps FileStorage to FileStorageAccess (paths).
        Maps RedisStorage to RedisStorageAccess (url + prefixes).

        Returns:
            FileStorageAccess or RedisStorageAccess.

        Raises:
            ValueError: If storage type is unsupported.
        """
        from py_code_mode.backend import (
            FileStorageAccess,
            RedisStorageAccess,
        )
        from py_code_mode.storage import FileStorage, RedisStorage

        if isinstance(self._storage, FileStorage):
            base_path = self._storage.root
            return FileStorageAccess(
                # Tools are read-only, only provide path if directory exists
                tools_path=base_path / "tools" if (base_path / "tools").exists() else None,
                # Skills path always provided - executor creates if needed
                skills_path=base_path / "skills",
                # Artifacts path always provided - executor creates if needed
                artifacts_path=base_path / "artifacts",
            )
        elif isinstance(self._storage, RedisStorage):
            # Reconstruct Redis URL from client connection parameters
            pool = self._storage._redis.connection_pool
            kwargs = pool.connection_kwargs

            # Build URL from connection kwargs
            host = kwargs.get("host", "localhost")
            port = kwargs.get("port", 6379)
            db = kwargs.get("db", 0)
            password = kwargs.get("password")

            if password:
                redis_url = f"redis://:{password}@{host}:{port}/{db}"
            else:
                redis_url = f"redis://{host}:{port}/{db}"

            # Build prefixes from base prefix
            prefix = self._storage._prefix
            return RedisStorageAccess(
                redis_url=redis_url,
                tools_prefix=f"{prefix}:tools",
                skills_prefix=f"{prefix}:skills",
                artifacts_prefix=f"{prefix}:artifacts",
            )
        else:
            raise ValueError(f"Unsupported storage type: {type(self._storage).__name__}")

    @property
    def storage(self) -> StorageBackend:
        """Access the storage backend."""
        return self._storage

    async def start(self) -> None:
        """Initialize the executor and inject namespaces.

        This must be called before run() if not using as context manager.
        """
        if self._started:
            return

        # Derive storage access descriptor
        storage_access = self._derive_storage_access()

        # Use provided executor or default to InProcessExecutor
        if self._executor_spec is None:
            from py_code_mode.backends.in_process import InProcessExecutor

            self._executor = InProcessExecutor()
        else:
            self._executor = self._executor_spec

        # Start executor with storage access
        # Executor.start() handles namespace injection based on storage_access
        await self._executor.start(storage_access=storage_access)
        self._started = True

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

        from py_code_mode.backend import Capability

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
