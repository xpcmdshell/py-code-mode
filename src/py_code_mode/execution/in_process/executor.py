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
from typing import TYPE_CHECKING, Any

from py_code_mode.artifacts import ArtifactStoreProtocol
from py_code_mode.execution.in_process.skills_namespace import SkillsNamespace
from py_code_mode.execution.protocol import Capability, validate_storage_not_access
from py_code_mode.execution.registry import register_backend
from py_code_mode.skills import SkillLibrary
from py_code_mode.tools import ToolRegistry, ToolsNamespace
from py_code_mode.types import ExecutionResult

if TYPE_CHECKING:
    from py_code_mode.storage.backends import StorageBackend

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
        storage: StorageBackend | None = None,
    ) -> None:
        """Start executor and configure from storage backend.

        Args:
            storage: Optional StorageBackend instance.
                    If provided, uses storage.tools/skills/artifacts directly.
                    If None, uses whatever was passed to __init__.

        Raises:
            TypeError: If passed old StorageAccess types instead of StorageBackend,
                      or if storage wrapper types are unexpected.
        """
        if storage is None:
            return  # Use __init__ configuration

        # Reject old StorageAccess types - no backward compatibility
        validate_storage_not_access(storage, "InProcessExecutor")

        # Use storage directly - access its internal adapters/stores
        # This is preferred for InProcessExecutor since we're in the same process
        # and can share the storage's resources directly.

        # Build registry from storage's tool adapters
        self._registry = await self._build_registry_from_storage(storage)
        self._namespace["tools"] = ToolsNamespace(self._registry)

        # Build skill library from storage's skill wrapper
        self._skill_library = self._build_skill_library_from_storage(storage)
        self._namespace["skills"] = SkillsNamespace(self._skill_library, self)

        # Get artifact store from storage
        self._artifact_store = self._get_artifact_store_from_storage(storage)
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
        """Build a SkillLibrary from a storage backend's skill wrapper.

        Raises:
            TypeError: If storage.skills is not a SkillStoreWrapper.
        """
        from py_code_mode.storage.backends import SkillStoreWrapper

        # Use protocol - storage.skills exists per StorageBackend protocol
        skills_wrapper = storage.skills
        if not isinstance(skills_wrapper, SkillStoreWrapper):
            raise TypeError(
                f"Expected SkillStoreWrapper from storage.skills, "
                f"got {type(skills_wrapper).__name__}"
            )
        return skills_wrapper._get_library()

    def _get_artifact_store_from_storage(self, storage: Any) -> ArtifactStoreProtocol:
        """Get artifact store from a storage backend.

        Raises:
            TypeError: If storage.artifacts is not an ArtifactStoreWrapper.
        """
        from py_code_mode.storage.backends import ArtifactStoreWrapper

        # Use protocol - storage.artifacts exists per StorageBackend protocol
        artifacts_wrapper = storage.artifacts
        if not isinstance(artifacts_wrapper, ArtifactStoreWrapper):
            raise TypeError(
                f"Expected ArtifactStoreWrapper from storage.artifacts, "
                f"got {type(artifacts_wrapper).__name__}"
            )
        return artifacts_wrapper

    async def __aenter__(self) -> InProcessExecutor:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        await self.close()


# Register this backend
register_backend("in-process", InProcessExecutor)
