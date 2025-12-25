"""Session - unified interface for code execution with storage.

Session wraps a StorageBackend and Executor, providing the primary API
for py-code-mode. It injects tools, skills, and artifacts namespaces
into the executor's runtime environment.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from py_code_mode.execution import Executor
from py_code_mode.skills import PythonSkill
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

    # -------------------------------------------------------------------------
    # Tools facade methods
    # -------------------------------------------------------------------------

    async def list_tools(self) -> list[dict[str, Any]]:
        """List all available tools with their descriptions.

        Returns:
            List of tool info dicts with 'name', 'description', 'tags' keys.
        """
        registry = await self._storage.get_tool_registry()
        tools = registry.list_tools()
        return [
            {
                "name": tool.name,
                "description": tool.description or "",
                "tags": list(tool.tags),
            }
            for tool in tools
        ]

    async def search_tools(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search tools by name/description/semantic similarity.

        Args:
            query: Search query string.
            limit: Maximum number of results.

        Returns:
            List of matching tool info dicts.
        """
        registry = await self._storage.get_tool_registry()
        tools = registry.search(query, limit=limit)
        return [
            {
                "name": tool.name,
                "description": tool.description or "",
                "tags": list(tool.tags),
            }
            for tool in tools
        ]

    # -------------------------------------------------------------------------
    # Skills facade methods
    # -------------------------------------------------------------------------

    async def list_skills(self) -> list[dict[str, Any]]:
        """List all skills (refreshes from storage first).

        Returns:
            List of skill summaries (name, description, parameters - no source).
            Use get_skill() to retrieve full source for a specific skill.
        """
        library = self._storage.get_skill_library()
        library.refresh()
        skills = library.list()
        return [self._skill_to_dict(skill, include_source=False) for skill in skills]

    async def search_skills(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Search skills (refreshes from storage first).

        Args:
            query: Natural language search query.
            limit: Maximum number of results.

        Returns:
            List of matching skill summaries (name, description, parameters - no source).
            Use get_skill() to retrieve full source for a specific skill.
        """
        library = self._storage.get_skill_library()
        library.refresh()
        skills = library.search(query, limit=limit)
        return [self._skill_to_dict(skill, include_source=False) for skill in skills]

    async def add_skill(self, name: str, source: str, description: str) -> dict[str, Any]:
        """Create and persist a skill.

        Args:
            name: Unique skill name (must be valid Python identifier).
            source: Python source code with def run(...) function.
            description: What the skill does.

        Returns:
            Skill metadata dict.

        Raises:
            ValueError: If name is invalid or source doesn't define run().
            SyntaxError: If source has syntax errors.
        """
        skill = PythonSkill.from_source(name=name, source=source, description=description)
        library = self._storage.get_skill_library()
        library.add(skill)
        return self._skill_to_dict(skill)

    async def remove_skill(self, name: str) -> bool:
        """Remove a skill.

        Args:
            name: Name of the skill to remove.

        Returns:
            True if removed, False if not found.
        """
        library = self._storage.get_skill_library()
        return library.remove(name)

    async def get_skill(self, name: str) -> dict[str, Any] | None:
        """Get skill by name.

        Args:
            name: Skill name.

        Returns:
            Skill info dict, or None if not found.
        """
        library = self._storage.get_skill_library()
        library.refresh()
        skill = library.get(name)
        if skill is None:
            return None
        return self._skill_to_dict(skill)

    def _skill_to_dict(self, skill: PythonSkill, include_source: bool = True) -> dict[str, Any]:
        """Convert a PythonSkill to a JSON-serializable dict.

        Args:
            skill: The skill to convert.
            include_source: Whether to include full source code. False for listings,
                True for get_skill where the caller needs the implementation.
        """
        result: dict[str, Any] = {
            "name": skill.name,
            "description": skill.description,
            "parameters": [
                {
                    "name": p.name,
                    "type": p.type,
                    "description": p.description,
                    "required": p.required,
                    "default": p.default,
                }
                for p in skill.parameters
            ],
        }
        if include_source:
            result["source"] = skill.source
        return result

    # -------------------------------------------------------------------------
    # Artifacts facade methods
    # -------------------------------------------------------------------------

    async def list_artifacts(self) -> list[dict[str, Any]]:
        """List all artifacts with metadata.

        Returns:
            List of artifact info dicts.
        """
        store = self._storage.get_artifact_store()
        artifacts = store.list()
        return [
            {
                "name": a.name,
                "path": a.path,
                "description": a.description,
                "metadata": a.metadata,
                "created_at": a.created_at.isoformat(),
            }
            for a in artifacts
        ]

    async def save_artifact(
        self,
        name: str,
        data: Any,
        description: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Save an artifact.

        Args:
            name: Artifact name.
            data: Data to save (str, bytes, dict, or list).
            description: Optional description.
            metadata: Optional additional metadata.

        Returns:
            Artifact metadata dict.
        """
        store = self._storage.get_artifact_store()
        artifact = store.save(name, data, description=description, metadata=metadata)
        return {
            "name": artifact.name,
            "path": artifact.path,
            "description": artifact.description,
            "metadata": artifact.metadata,
            "created_at": artifact.created_at.isoformat(),
        }

    async def load_artifact(self, name: str) -> Any:
        """Load artifact content.

        Args:
            name: Artifact name.

        Returns:
            The artifact data.
        """
        store = self._storage.get_artifact_store()
        return store.load(name)

    async def delete_artifact(self, name: str) -> None:
        """Delete an artifact.

        Args:
            name: Artifact name.
        """
        store = self._storage.get_artifact_store()
        store.delete(name)

    # -------------------------------------------------------------------------
    # Deps facade methods
    # -------------------------------------------------------------------------

    async def list_deps(self) -> list[str]:
        """List configured dependencies.

        Returns:
            List of package specifications.
        """
        deps_ns = self._storage.get_deps_namespace()
        return deps_ns.list()

    async def add_dep(self, package: str) -> dict[str, Any]:
        """Add and install a dependency.

        Args:
            package: Package specification (e.g., "pandas>=2.0").

        Returns:
            Install result dict with success status and details.
        """
        deps_ns = self._storage.get_deps_namespace()
        result = deps_ns.add(package)
        return {
            "installed": list(result.installed),
            "already_present": list(result.already_present),
            "failed": list(result.failed),
        }

    async def remove_dep(self, package: str) -> bool:
        """Remove a dependency.

        Args:
            package: Package specification to remove.

        Returns:
            True if removed, False if not found.
        """
        deps_ns = self._storage.get_deps_namespace()
        return deps_ns.remove(package)

    async def sync_deps(self) -> dict[str, Any]:
        """Sync all configured dependencies.

        Returns:
            Sync result dict with success status and details.
        """
        deps_ns = self._storage.get_deps_namespace()
        result = deps_ns.sync()
        return {
            "installed": list(result.installed),
            "already_present": list(result.already_present),
            "failed": list(result.failed),
        }

    # -------------------------------------------------------------------------
    # Context manager
    # -------------------------------------------------------------------------

    async def __aenter__(self) -> Session:
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Async context manager exit."""
        await self.close()
