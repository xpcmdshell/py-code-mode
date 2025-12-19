"""Session - unified interface for code execution with storage.

Session wraps a StorageBackend and Executor, providing the primary API
for py-code-mode. It injects tools, skills, and artifacts namespaces
into the executor's runtime environment.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from py_code_mode.backend import Executor
from py_code_mode.backends.in_process import SkillsNamespace, ToolsNamespace
from py_code_mode.types import ExecutionResult

if TYPE_CHECKING:
    from py_code_mode.backends.container import ContainerConfig
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
        storage: StorageBackend,
        executor: str | Executor | None = None,
        **executor_kwargs: Any,
    ) -> None:
        """Initialize session.

        Args:
            storage: Storage backend (FileStorage or RedisStorage).
            executor: Executor type string ("in-process", "container") or Executor instance.
                     Default: "in-process"
            **executor_kwargs: Additional arguments passed to executor creation.
                              For "container" executor: network_policy, etc.
        """
        self._storage = storage
        self._executor_spec = executor or "in-process"
        self._executor_kwargs = executor_kwargs
        self._executor: Executor | None = None
        self._started = False
        self._closed = False

        # Validate executor type early
        if isinstance(self._executor_spec, str):
            valid_backends = ["in-process", "container"]
            if self._executor_spec not in valid_backends:
                raise ValueError(
                    f"Unknown executor type: '{self._executor_spec}'. "
                    f"Valid types: {', '.join(valid_backends)}"
                )

    def _build_container_config(self) -> ContainerConfig:
        """Build ContainerConfig from storage backend.

        Maps FileStorage paths to container volume mounts.
        Maps RedisStorage to container Redis environment.
        """
        from py_code_mode.backends.container import ContainerConfig
        from py_code_mode.storage import FileStorage, RedisStorage

        # Extract common kwargs
        image = self._executor_kwargs.get("image", "py-code-mode-tools:latest")
        timeout = self._executor_kwargs.get("default_timeout", 30.0)
        startup_timeout = self._executor_kwargs.get("startup_timeout", 60.0)

        if isinstance(self._storage, FileStorage):
            # Map FileStorage directories to container volume mounts
            base_path = self._storage.root
            return ContainerConfig(
                image=image,
                host_tools_path=base_path / "tools"
                if (base_path / "tools").exists()
                else None,
                host_skills_path=base_path / "skills"
                if (base_path / "skills").exists()
                else None,
                host_artifacts_path=base_path / "artifacts",
                artifact_backend="file",
                timeout=timeout,
                startup_timeout=startup_timeout,
            )
        elif isinstance(self._storage, RedisStorage):
            # For Redis, container loads everything from Redis
            # User must provide redis_url since we can't extract it from the client
            redis_url = self._executor_kwargs.get("redis_url")
            if redis_url is None:
                # Try to get from storage if it has the url stored
                redis_url = getattr(self._storage, "_url", None)
            if redis_url is None:
                raise ValueError(
                    "Container executor with RedisStorage requires 'redis_url' in executor kwargs. "
                    "Example: Session(storage=redis_storage, executor='container', redis_url='redis://...')"
                )
            return ContainerConfig(
                image=image,
                artifact_backend="redis",
                redis_url=redis_url,
                timeout=timeout,
                startup_timeout=startup_timeout,
            )
        else:
            raise ValueError(
                f"Unsupported storage type for container executor: {type(self._storage).__name__}"
            )

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

        # Create or use provided executor
        if isinstance(self._executor_spec, str):
            # Check for unsupported capabilities
            backend_type = self._executor_spec
            if "network_policy" in self._executor_kwargs:
                if backend_type == "in-process":
                    raise ValueError(
                        "in-process executor does not support network_policy capability"
                    )

            # Create executor (for now, we'll build it manually since we need to inject namespaces)
            if backend_type == "in-process":
                from py_code_mode.backends.in_process import InProcessExecutor

                self._executor = InProcessExecutor(
                    default_timeout=self._executor_kwargs.get("default_timeout", 30.0)
                )
            elif backend_type == "container":
                from py_code_mode.backends.container import (
                    ContainerExecutor,
                )

                # Build ContainerConfig from storage backend
                container_config = self._build_container_config()

                self._executor = ContainerExecutor(container_config)
                # ContainerExecutor requires explicit start (starts Docker container)
                await self._executor.start()
            else:
                raise ValueError(f"Unknown executor type: {backend_type}")
        else:
            self._executor = self._executor_spec

        # Inject namespaces into executor
        await self._inject_namespaces()
        self._started = True

    async def _inject_namespaces(self) -> None:
        """Inject tools, skills, and artifacts namespaces into executor."""
        if self._executor is None:
            return

        # Get the executor's namespace (only works with InProcessExecutor for now)
        if hasattr(self._executor, "_namespace"):
            namespace = self._executor._namespace

            # Inject tools namespace by loading from storage

            from py_code_mode.registry import ToolRegistry
            from py_code_mode.semantic import create_skill_library
            from py_code_mode.skill_store import FileSkillStore
            from py_code_mode.storage import FileStorage

            # Load tools registry from storage
            # Check if this is FileStorage (has a base path)
            if isinstance(self._storage, FileStorage):
                # FileStorage has a _base_path attribute
                base_path = self._storage._base_path
                tools_path = base_path / "tools"
                if tools_path.exists():
                    registry = await ToolRegistry.from_dir(str(tools_path))
                else:
                    registry = ToolRegistry()
            else:
                # For other storage types, create empty registry
                # TODO: Implement loading from RedisStorage
                registry = ToolRegistry()

            namespace["tools"] = ToolsNamespace(registry)

            # Inject skills namespace
            # Load skill library from storage
            if isinstance(self._storage, FileStorage):
                base_path = self._storage._base_path
                skills_path = base_path / "skills"
                if skills_path.exists():
                    store = FileSkillStore(skills_path)
                    skill_library = create_skill_library(store=store)
                else:
                    # Create empty library
                    from py_code_mode.semantic import MockEmbedder, SkillLibrary
                    from py_code_mode.skill_store import MemorySkillStore

                    skill_library = SkillLibrary(
                        embedder=MockEmbedder(), store=MemorySkillStore()
                    )
            else:
                # For other storage types, create empty library
                from py_code_mode.semantic import MockEmbedder, SkillLibrary
                from py_code_mode.skill_store import MemorySkillStore

                skill_library = SkillLibrary(
                    embedder=MockEmbedder(), store=MemorySkillStore()
                )

            namespace["skills"] = SkillsNamespace(skill_library, self._executor)  # type: ignore

            # Inject artifacts namespace
            namespace["artifacts"] = self._storage.artifacts

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

        # Close current executor
        await self._executor.close()

        # Create fresh executor and re-inject namespaces
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
