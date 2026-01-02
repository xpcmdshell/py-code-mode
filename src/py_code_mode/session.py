"""Session - unified interface for code execution with storage.

Session wraps a StorageBackend and Executor, providing the primary API
for py-code-mode. It injects tools, skills, and artifacts namespaces
into the executor's runtime environment.
"""

from __future__ import annotations

from pathlib import Path
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
        storage: StorageBackend,
        executor: Executor | None = None,
        sync_deps_on_start: bool = False,
    ) -> None:
        """Initialize session.

        Args:
            storage: Storage backend (FileStorage or RedisStorage). Required.
            executor: Executor instance (InProcessExecutor, SubprocessExecutor,
                     ContainerExecutor). Default: InProcessExecutor()
            sync_deps_on_start: If True, install all configured dependencies
                               when session starts. Default: False.

        Raises:
            TypeError: If executor is a string (unsupported) or wrong type.

        For convenience, use class methods instead of __init__ directly:
            - Session.from_base(path) - auto-discover tools/skills/artifacts
            - Session.subprocess(...) - subprocess isolation (recommended)
            - Session.in_process(...) - same process (fastest, no isolation)
            - Session.container(...) - Docker isolation (most secure)
        """
        if storage is None:
            raise TypeError("storage is required (use FileStorage or RedisStorage)")

        # Reject string-based executor selection
        if isinstance(executor, str):
            raise TypeError(
                f"String-based executor selection is no longer supported. "
                f"Use typed executor instances instead:\n"
                f"  Session(storage=storage, executor=InProcessExecutor())\n"
                f"  Session(storage=storage, executor=SubprocessExecutor(config))\n"
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

    @classmethod
    def from_base(
        cls,
        base_path: str | Path,
        *,
        timeout: float | None = 30.0,
        extra_deps: tuple[str, ...] | None = None,
        allow_runtime_deps: bool = True,
        sync_deps_on_start: bool = False,
    ) -> Session:
        """Convenience constructor for local development.

        Auto-discovers from workspace directory:
        - tools/ for tool definitions
        - skills/ for skill files
        - artifacts/ for persistent data
        - requirements.txt for pre-configured dependencies

        Uses InProcessExecutor for simplicity. For process isolation use
        Session.subprocess().

        Args:
            base_path: Workspace directory (e.g., "~/.code-mode").
            timeout: Execution timeout in seconds (None = unlimited).
            extra_deps: Additional packages beyond requirements.txt.
            allow_runtime_deps: Allow deps.add()/remove() at runtime.
            sync_deps_on_start: Install configured deps on start.

        Example:
            async with Session.from_base("~/.code-mode") as session:
                await session.run("tools.list()")
        """
        from py_code_mode.storage import FileStorage

        base = Path(base_path).expanduser().resolve()
        base.mkdir(parents=True, exist_ok=True)

        tools_dir = base / "tools"
        tools_dir.mkdir(exist_ok=True)

        storage = FileStorage(base_path=base)

        deps_file = base / "requirements.txt"
        deps_file_resolved = deps_file if deps_file.is_file() else None

        executor = cls._create_in_process_executor(
            tools_path=tools_dir,
            timeout=timeout,
            deps=extra_deps,
            deps_file=deps_file_resolved,
            allow_runtime_deps=allow_runtime_deps,
        )

        return cls(storage=storage, executor=executor, sync_deps_on_start=sync_deps_on_start)

    @classmethod
    def subprocess(
        cls,
        base_path: str | Path,
        *,
        timeout: float | None = 60.0,
        extra_deps: tuple[str, ...] | None = None,
        allow_runtime_deps: bool = True,
        sync_deps_on_start: bool = False,
        python_version: str | None = None,
        cache_venv: bool = True,
    ) -> Session:
        """Create session with SubprocessExecutor (process isolation).

        Auto-discovers from base_path like from_base(), but uses subprocess
        for process isolation via a dedicated virtualenv.

        Args:
            base_path: Workspace directory (e.g., "~/.code-mode").
            timeout: Execution timeout in seconds (None = unlimited).
            extra_deps: Additional packages beyond requirements.txt.
            allow_runtime_deps: Allow deps.add()/remove() at runtime.
            sync_deps_on_start: Install configured deps on start.
            python_version: Python version for venv (e.g., "3.11").
            cache_venv: Reuse cached venv across runs.

        Raises:
            ImportError: If jupyter_client/ipykernel not installed.
        """
        from py_code_mode.execution import SUBPROCESS_AVAILABLE

        if not SUBPROCESS_AVAILABLE:
            raise ImportError(
                "SubprocessExecutor requires jupyter_client and ipykernel. "
                "Install with: pip install jupyter_client ipykernel"
            )

        from py_code_mode.execution import SubprocessConfig, SubprocessExecutor
        from py_code_mode.storage import FileStorage

        base = Path(base_path).expanduser().resolve()
        base.mkdir(parents=True, exist_ok=True)

        tools_dir = base / "tools"
        tools_dir.mkdir(exist_ok=True)

        storage = FileStorage(base_path=base)

        deps_file = base / "requirements.txt"
        deps_file_resolved = deps_file if deps_file.is_file() else None

        config = SubprocessConfig(
            tools_path=tools_dir,
            default_timeout=timeout,
            deps=extra_deps,
            deps_file=deps_file_resolved,
            allow_runtime_deps=allow_runtime_deps,
            python_version=python_version,
            cache_venv=cache_venv,
        )
        executor = SubprocessExecutor(config=config)

        return cls(storage=storage, executor=executor, sync_deps_on_start=sync_deps_on_start)

    @classmethod
    def inprocess(
        cls,
        base_path: str | Path,
        *,
        timeout: float | None = 30.0,
        extra_deps: tuple[str, ...] | None = None,
        allow_runtime_deps: bool = True,
        sync_deps_on_start: bool = False,
    ) -> Session:
        """Create session with InProcessExecutor (fastest, no isolation).

        Auto-discovers from base_path like from_base(). Runs code directly
        in the same process - fast but no isolation.

        Args:
            base_path: Workspace directory (e.g., "~/.code-mode").
            timeout: Execution timeout in seconds (None = unlimited).
            extra_deps: Additional packages beyond requirements.txt.
            allow_runtime_deps: Allow deps.add()/remove() at runtime.
            sync_deps_on_start: Install configured deps on start.
        """
        from py_code_mode.execution import InProcessConfig, InProcessExecutor
        from py_code_mode.storage import FileStorage

        base = Path(base_path).expanduser().resolve()
        base.mkdir(parents=True, exist_ok=True)

        tools_dir = base / "tools"
        tools_dir.mkdir(exist_ok=True)

        storage = FileStorage(base_path=base)

        deps_file = base / "requirements.txt"
        deps_file_resolved = deps_file if deps_file.is_file() else None

        config = InProcessConfig(
            tools_path=tools_dir,
            default_timeout=timeout,
            deps=extra_deps,
            deps_file=deps_file_resolved,
            allow_runtime_deps=allow_runtime_deps,
        )
        executor = InProcessExecutor(config=config)

        return cls(storage=storage, executor=executor, sync_deps_on_start=sync_deps_on_start)

    @staticmethod
    def _create_in_process_executor(
        tools_path: Path | None = None,
        timeout: float | None = 30.0,
        deps: tuple[str, ...] | None = None,
        deps_file: Path | None = None,
        allow_runtime_deps: bool = True,
    ) -> Executor:
        from py_code_mode.execution import InProcessConfig, InProcessExecutor

        config = InProcessConfig(
            tools_path=tools_path,
            default_timeout=timeout,
            deps=deps,
            deps_file=deps_file,
            allow_runtime_deps=allow_runtime_deps,
        )
        return InProcessExecutor(config=config)

    @property
    def storage(self) -> StorageBackend:
        """Access the storage backend."""
        return self._storage

    async def _sync_deps(self) -> None:
        """Sync configured dependencies by installing them via the executor.

        This method installs pre-configured dependencies to the correct executor
        environment (in-process, subprocess venv, or container). Deps are now
        managed by the executor (via config.deps and config.deps_file), not storage.
        """
        if self._executor is None:
            return

        # Get pre-configured deps from executor config and install them
        deps = self._executor.get_configured_deps()
        if deps:
            await self._executor.install_deps(deps)

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

        Tools are owned by the executor (loaded from config.tools_path).

        Returns:
            List of tool info dicts with 'name', 'description', 'tags' keys.
        """
        if not self._started:
            await self.start()
        if self._executor is None:
            raise RuntimeError("Session not started")
        return await self._executor.list_tools()

    async def search_tools(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search tools by name/description/semantic similarity.

        Tools are owned by the executor (loaded from config.tools_path).

        Args:
            query: Search query string.
            limit: Maximum number of results.

        Returns:
            List of matching tool info dicts.
        """
        if not self._started:
            await self.start()
        if self._executor is None:
            raise RuntimeError("Session not started")
        return await self._executor.search_tools(query, limit)

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

        Deps are owned by the executor (loaded from config.deps and config.deps_file).

        Returns:
            List of package specifications.
        """
        if not self._started:
            await self.start()
        if self._executor is None:
            raise RuntimeError("Session not started")
        return await self._executor.list_deps()

    async def add_dep(self, package: str) -> dict[str, Any]:
        """Add and install a dependency.

        Persists the package to executor's deps store (survives restarts) and
        installs it to the executor's environment (targets correct Python:
        in-process, subprocess venv, or container).

        Args:
            package: Package specification (e.g., "pandas>=2.0").

        Returns:
            Install result dict with keys: installed, already_present, failed.

        Raises:
            RuntimeError: If session not started.
        """
        if not self._started:
            await self.start()
        if self._executor is None:
            raise RuntimeError("Session not started")
        return await self._executor.add_dep(package)

    async def remove_dep(self, package: str) -> dict[str, Any]:
        """Remove a dependency.

        Removes the package from executor's deps store and uninstalls it from
        the executor's environment.

        Args:
            package: Package specification to remove.

        Returns:
            Result dict with keys: removed, not_found, failed, removed_from_config.

        Raises:
            RuntimeError: If session not started.
        """
        if not self._started:
            await self.start()
        if self._executor is None:
            raise RuntimeError("Session not started")
        return await self._executor.remove_dep(package)

    async def sync_deps(self) -> dict[str, Any]:
        """Sync all configured dependencies.

        Installs all pre-configured packages to the executor's environment.

        Returns:
            Sync result dict with keys: installed, already_present, failed.

        Raises:
            RuntimeError: If session not started.
        """
        if not self._started:
            await self.start()
        if self._executor is None:
            raise RuntimeError("Session not started")
        return await self._executor.sync_deps()

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
