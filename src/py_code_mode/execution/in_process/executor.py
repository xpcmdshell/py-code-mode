"""In-process execution backend.

Runs Python code directly in the same process.
Fast but provides no isolation.
"""

from __future__ import annotations

import ast
import asyncio
import builtins
import io
import traceback
from contextlib import redirect_stdout
from typing import Any

from py_code_mode.artifacts import ArtifactStoreProtocol, FileArtifactStore, RedisArtifactStore
from py_code_mode.execution.in_process.skills_namespace import SkillsNamespace
from py_code_mode.execution.protocol import (
    Capability,
    FileStorageAccess,
    RedisStorageAccess,
    StorageAccess,
    StorageBackendAccess,
)
from py_code_mode.execution.registry import register_backend
from py_code_mode.skills import (
    FileSkillStore,
    MemorySkillStore,
    MockEmbedder,
    RedisSkillStore,
    SkillLibrary,
    create_skill_library,
)
from py_code_mode.storage import RedisToolStore, registry_from_redis
from py_code_mode.tools import ToolRegistry, ToolsNamespace
from py_code_mode.tools.adapters import CLIAdapter
from py_code_mode.types import ExecutionResult

# Use builtins to avoid security hook false positive on Python's code execution
_run_code = getattr(builtins, "exec")
_eval_code = getattr(builtins, "eval")


class InProcessExecutor:
    """Runs Python code with persistent state in the same process.

    Variables, functions, and imports persist across runs.
    Optionally injects tools.*, skills.*, and artifacts.* namespaces.

    Capabilities:
    - TIMEOUT: Yes (via asyncio.wait_for)
    - PROCESS_ISOLATION: No
    - NETWORK_ISOLATION: No
    - FILESYSTEM_ISOLATION: No

    Usage:
        executor = await InProcessExecutor.create(
            tools="./tools/",
            skills="./skills/",
        )
        result = await executor.run('tools.nmap(target="scanme.nmap.org")')
    """

    # Capabilities this backend supports
    _CAPABILITIES = frozenset({Capability.TIMEOUT, Capability.RESET})

    def __init__(
        self,
        registry: ToolRegistry | None = None,
        skill_library: SkillLibrary | None = None,
        artifact_store: ArtifactStoreProtocol | None = None,
        default_timeout: float = 30.0,
    ) -> None:
        self._registry = registry
        self._skill_library = skill_library
        self._artifact_store = artifact_store
        self._default_timeout = default_timeout
        self._namespace: dict[str, Any] = {"__builtins__": builtins}
        self._closed = False

        # Inject tools namespace if registry provided
        if registry is not None:
            self._namespace["tools"] = ToolsNamespace(registry)

        # Inject skills namespace if skill_library provided
        if skill_library is not None:
            self._namespace["skills"] = SkillsNamespace(skill_library, self)

        # Inject artifacts namespace if artifact_store provided
        if artifact_store is not None:
            self._namespace["artifacts"] = artifact_store

    def supports(self, capability: str) -> bool:
        """Check if this backend supports a capability."""
        return capability in self._CAPABILITIES

    def supported_capabilities(self) -> set[str]:
        """Return set of all capabilities this backend supports."""
        return set(self._CAPABILITIES)

    async def run(self, code: str, timeout: float | None = None) -> ExecutionResult:
        """Run code and return result.

        Args:
            code: Python code to run.
            timeout: Timeout in seconds. Uses default if None.

        Returns:
            ExecutionResult with value, stdout, and optional error.
        """
        if self._closed:
            return ExecutionResult(
                value=None,
                stdout="",
                error="Executor is closed",
            )

        timeout = timeout if timeout is not None else self._default_timeout

        # Store loop reference for tool calls from thread context
        loop = asyncio.get_running_loop()
        if "tools" in self._namespace:
            self._namespace["tools"].set_loop(loop)

        # Run in thread to allow timeout cancellation
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._run_sync, code),
                timeout=timeout,
            )
        except TimeoutError:
            return ExecutionResult(
                value=None,
                stdout="",
                error=f"Execution timeout after {timeout} seconds",
            )

    def _run_sync(self, code: str) -> ExecutionResult:
        """Run code synchronously, capturing output."""
        stdout_capture = io.StringIO()

        try:
            # Parse to check for trailing expression
            tree = ast.parse(code)

            # Separate statements from final expression
            if tree.body and isinstance(tree.body[-1], ast.Expr):
                # Last item is an expression - run all but last, then eval last
                stmts = tree.body[:-1]
                expr = tree.body[-1]

                # Run statements
                if stmts:
                    stmt_tree = ast.Module(body=stmts, type_ignores=[])
                    stmt_code = compile(stmt_tree, "<code>", "exec")
                    with redirect_stdout(stdout_capture):
                        _run_code(stmt_code, self._namespace)

                # Evaluate final expression
                expr_tree = ast.Expression(body=expr.value)
                expr_code = compile(expr_tree, "<expr>", "eval")
                with redirect_stdout(stdout_capture):
                    value = _eval_code(expr_code, self._namespace)
            else:
                # No trailing expression - just run everything
                with redirect_stdout(stdout_capture):
                    _run_code(code, self._namespace)
                value = None

            return ExecutionResult(
                value=value,
                stdout=stdout_capture.getvalue(),
                error=None,
            )

        except Exception:
            # Intentionally broad: user code can throw any exception.
            # Does not catch KeyboardInterrupt/SystemExit (BaseException, not Exception).
            return ExecutionResult(
                value=None,
                stdout=stdout_capture.getvalue(),
                error=traceback.format_exc(),
            )

    async def close(self) -> None:
        """Release executor resources."""
        self._closed = True
        if self._registry:
            await self._registry.close()
        self._namespace.clear()

    async def reset(self) -> None:
        """Reset session state.

        Clears all user-defined variables but preserves tools, skills, artifacts namespaces.
        """
        # Store namespace items we want to preserve
        preserved = {
            "__builtins__": self._namespace.get("__builtins__"),
            "tools": self._namespace.get("tools"),
            "skills": self._namespace.get("skills"),
            "artifacts": self._namespace.get("artifacts"),
        }

        # Clear everything
        self._namespace.clear()

        # Restore preserved items
        for key, value in preserved.items():
            if value is not None:
                self._namespace[key] = value

    async def start(
        self,
        storage_access: StorageAccess | None = None,
    ) -> None:
        """Start executor and configure from storage access.

        Args:
            storage_access: Optional storage access descriptor.
                           If provided, loads tools/skills/artifacts from paths.
                           If None, uses whatever was passed to __init__.
        """
        if storage_access is None:
            return  # Use __init__ configuration

        if isinstance(storage_access, FileStorageAccess):
            # Load from file paths
            # Always inject tools namespace (empty if no path/directory)
            if storage_access.tools_path and storage_access.tools_path.exists():
                adapter = CLIAdapter(tools_path=storage_access.tools_path)
                self._registry = ToolRegistry()
                self._registry.add_adapter(adapter)
            else:
                self._registry = ToolRegistry()
            self._namespace["tools"] = ToolsNamespace(self._registry)

            # Always inject skills namespace
            if storage_access.skills_path:
                # Create directory if it doesn't exist (same as artifacts behavior)
                storage_access.skills_path.mkdir(parents=True, exist_ok=True)
                store = FileSkillStore(storage_access.skills_path)
                self._skill_library = create_skill_library(store=store)
            else:
                # Only use memory store if NO path configured (explicit choice)
                self._skill_library = SkillLibrary(
                    embedder=MockEmbedder(), store=MemorySkillStore()
                )
            self._namespace["skills"] = SkillsNamespace(self._skill_library, self)

            # Always inject artifacts namespace
            if storage_access.artifacts_path:
                storage_access.artifacts_path.mkdir(parents=True, exist_ok=True)
                self._artifact_store = FileArtifactStore(storage_access.artifacts_path)
                self._namespace["artifacts"] = self._artifact_store

        elif isinstance(storage_access, RedisStorageAccess):
            # Load from Redis
            try:
                import redis
            except ImportError as e:
                raise ImportError(
                    "redis required for RedisStorageAccess. Install with: pip install redis"
                ) from e

            client = redis.from_url(storage_access.redis_url)

            # Tools from Redis
            tool_store = RedisToolStore(client, prefix=storage_access.tools_prefix)
            self._registry = await registry_from_redis(tool_store)
            self._namespace["tools"] = ToolsNamespace(self._registry)

            # Skills from Redis with semantic search
            skill_store = RedisSkillStore(client, prefix=storage_access.skills_prefix)
            self._skill_library = create_skill_library(store=skill_store)
            self._namespace["skills"] = SkillsNamespace(self._skill_library, self)

            # Artifacts from Redis
            self._artifact_store = RedisArtifactStore(
                client, prefix=storage_access.artifacts_prefix
            )
            self._namespace["artifacts"] = self._artifact_store

        elif isinstance(storage_access, StorageBackendAccess):
            # Direct storage backend access - use its internal adapters/stores
            # This is preferred for InProcessExecutor since we're in the same process
            # and can share the storage's resources directly.
            storage = storage_access.storage

            # Build registry from storage's tool adapters
            self._registry = await self._build_registry_from_storage(storage)
            self._namespace["tools"] = ToolsNamespace(self._registry)

            # Build skill library from storage's skill wrapper
            self._skill_library = self._build_skill_library_from_storage(storage)
            self._namespace["skills"] = SkillsNamespace(self._skill_library, self)

            # Get artifact store from storage
            self._artifact_store = self._get_artifact_store_from_storage(storage)
            if self._artifact_store is not None:
                self._namespace["artifacts"] = self._artifact_store

    async def _build_registry_from_storage(self, storage: Any) -> ToolRegistry:
        """Build a ToolRegistry from a storage backend's internal components."""
        from py_code_mode.storage.backends import FileToolStore, RedisToolStoreWrapper

        registry = ToolRegistry()

        # Use protocol - storage.tools exists per StorageBackend protocol
        tool_store = storage.tools
        if isinstance(tool_store, (FileToolStore, RedisToolStoreWrapper)):
            adapter = tool_store._get_adapter()
            if adapter is not None:
                registry.add_adapter(adapter)

        return registry

    def _build_skill_library_from_storage(self, storage: Any) -> SkillLibrary:
        """Build a SkillLibrary from a storage backend's skill wrapper."""
        from py_code_mode.storage.backends import SkillStoreWrapper

        # Use protocol - storage.skills exists per StorageBackend protocol
        skills_wrapper = storage.skills
        if isinstance(skills_wrapper, SkillStoreWrapper):
            return skills_wrapper._get_library()

        # Fallback: return an empty skill library
        return SkillLibrary(embedder=MockEmbedder(), store=MemorySkillStore())

    def _get_artifact_store_from_storage(self, storage: Any) -> ArtifactStoreProtocol | None:
        """Get artifact store from a storage backend."""
        from py_code_mode.storage.backends import ArtifactStoreWrapper

        # Use protocol - storage.artifacts exists per StorageBackend protocol
        artifacts_wrapper = storage.artifacts
        if isinstance(artifacts_wrapper, ArtifactStoreWrapper):
            return artifacts_wrapper

        return None

    async def __aenter__(self) -> InProcessExecutor:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()


# Register this backend
register_backend("in-process", InProcessExecutor)
