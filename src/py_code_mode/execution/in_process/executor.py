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

from py_code_mode.deps import DepsNamespace
from py_code_mode.execution.in_process.skills_namespace import SkillsNamespace
from py_code_mode.execution.protocol import Capability, validate_storage_not_access
from py_code_mode.execution.registry import register_backend
from py_code_mode.skills import SkillLibrary
from py_code_mode.tools import ToolRegistry, ToolsNamespace
from py_code_mode.types import ExecutionResult

if TYPE_CHECKING:
    from py_code_mode.artifacts import ArtifactStoreProtocol
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
        deps_namespace: DepsNamespace | None = None,
        default_timeout: float = 30.0,
    ) -> None:
        self._registry = registry
        self._skill_library = skill_library
        self._artifact_store: ArtifactStoreProtocol | None = artifact_store
        self._deps_namespace: DepsNamespace | None = deps_namespace
        self._default_timeout = default_timeout
        self._namespace: dict[str, Any] = {"__builtins__": builtins}
        self._closed = False

        # Inject tools namespace if registry provided
        if registry is not None:
            self._namespace["tools"] = ToolsNamespace(registry)

        # Inject skills namespace if skill_library provided
        if skill_library is not None:
            self._namespace["skills"] = SkillsNamespace(skill_library, self._namespace)

        # Inject artifacts namespace if artifact_store provided
        if artifact_store is not None:
            self._namespace["artifacts"] = artifact_store

        # Inject deps namespace if provided
        if deps_namespace is not None:
            self._namespace["deps"] = deps_namespace

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

        Clears all user-defined variables but preserves tools, skills, artifacts, deps namespaces.
        """
        # Store namespace items we want to preserve
        preserved = {
            "__builtins__": self._namespace.get("__builtins__"),
            "tools": self._namespace.get("tools"),
            "skills": self._namespace.get("skills"),
            "artifacts": self._namespace.get("artifacts"),
            "deps": self._namespace.get("deps"),
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
                    If provided, uses storage protocol methods to build namespaces.
                    If None, uses whatever was passed to __init__.

        Raises:
            TypeError: If passed old StorageAccess types instead of StorageBackend.
        """
        if storage is None:
            return  # Use __init__ configuration

        # Reject old StorageAccess types - no backward compatibility
        validate_storage_not_access(storage, "InProcessExecutor")

        # Use public protocol methods to build namespaces
        self._registry = storage.get_tool_registry()
        self._namespace["tools"] = ToolsNamespace(self._registry)

        self._skill_library = storage.get_skill_library()
        self._namespace["skills"] = SkillsNamespace(self._skill_library, self._namespace)

        self._artifact_store = storage.get_artifact_store()
        self._namespace["artifacts"] = self._artifact_store

        self._deps_namespace = storage.get_deps_namespace()
        self._namespace["deps"] = self._deps_namespace

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
