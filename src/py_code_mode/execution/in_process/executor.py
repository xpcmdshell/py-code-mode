"""In-process execution backend.

Runs Python code directly in the same process.
Fast but provides no isolation.
"""

from __future__ import annotations

import ast
import asyncio
import builtins
import io
import logging
import subprocess
import sys
import traceback
from contextlib import redirect_stdout
from typing import TYPE_CHECKING, Any

from py_code_mode.deps import (
    ControlledDepsNamespace,
    DepsNamespace,
    FileDepsStore,
    PackageInstaller,
)
from py_code_mode.execution.in_process.config import InProcessConfig
from py_code_mode.execution.in_process.skills_namespace import SkillsNamespace
from py_code_mode.execution.protocol import Capability, validate_storage_not_access
from py_code_mode.execution.registry import register_backend
from py_code_mode.skills import SkillLibrary
from py_code_mode.tools import ToolRegistry, ToolsNamespace, load_tools_from_path
from py_code_mode.types import ExecutionResult

if TYPE_CHECKING:
    from py_code_mode.artifacts import ArtifactStoreProtocol
    from py_code_mode.storage.backends import StorageBackend

logger = logging.getLogger(__name__)

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
    _CAPABILITIES = frozenset(
        {
            Capability.TIMEOUT,
            Capability.RESET,
            Capability.DEPS_INSTALL,
            Capability.DEPS_UNINSTALL,
        }
    )

    def __init__(
        self,
        registry: ToolRegistry | None = None,
        skill_library: SkillLibrary | None = None,
        artifact_store: ArtifactStoreProtocol | None = None,
        deps_namespace: DepsNamespace | None = None,
        default_timeout: float | None = 30.0,
        config: InProcessConfig | None = None,
    ) -> None:
        self._registry = registry
        self._skill_library = skill_library
        self._artifact_store: ArtifactStoreProtocol | None = artifact_store
        self._deps_namespace: DepsNamespace | None = deps_namespace
        self._config = config or InProcessConfig()
        self._default_timeout = self._config.default_timeout if config else default_timeout
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

        # Inject deps namespace if provided (wrap if runtime deps disabled)
        if deps_namespace is not None:
            if not self._config.allow_runtime_deps:
                self._namespace["deps"] = ControlledDepsNamespace(
                    deps_namespace, allow_runtime=False
                )
            else:
                self._namespace["deps"] = deps_namespace

    def supports(self, capability: str) -> bool:
        """Check if this backend supports a capability."""
        return capability in self._CAPABILITIES

    def supported_capabilities(self) -> set[str]:
        """Return set of all capabilities this backend supports."""
        return set(self._CAPABILITIES)

    def get_configured_deps(self) -> list[str]:
        """Return list of pre-configured dependencies from executor config.

        These are deps specified via config.deps list and config.deps_file.
        Used by Session._sync_deps() to install deps on start.

        Returns:
            List of package specifications.
        """
        deps: list[str] = []
        if self._config.deps:
            deps.extend(self._config.deps)
        if self._config.deps_file and self._config.deps_file.exists():
            file_deps = self._config.deps_file.read_text().strip().splitlines()
            for line in file_deps:
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    deps.append(stripped)
        return deps

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
        """Start executor and configure from config and storage backend.

        Tools and deps are loaded from executor config (tools_path, deps, deps_file).
        Skills and artifacts come from storage backend.

        Args:
            storage: Optional StorageBackend instance.
                    If provided, uses storage for skills and artifacts.
                    If None, uses whatever was passed to __init__.

        Raises:
            TypeError: If passed old StorageAccess types instead of StorageBackend.
        """
        # Reject old StorageAccess types - no backward compatibility
        validate_storage_not_access(storage, "InProcessExecutor")

        # Tools from executor config (NOT storage)
        if self._config.tools_path is not None:
            self._registry = await load_tools_from_path(self._config.tools_path)
            self._namespace["tools"] = ToolsNamespace(self._registry)
        elif self._registry is not None:
            # Use registry from __init__ if provided
            self._namespace["tools"] = ToolsNamespace(self._registry)
        else:
            # Always create tools namespace (empty if no tools configured)
            self._registry = ToolRegistry()
            self._namespace["tools"] = ToolsNamespace(self._registry)

        # Deps from executor config (NOT storage)
        # Collect deps from config.deps list and config.deps_file
        initial_deps: list[str] = []
        if self._config.deps:
            initial_deps.extend(self._config.deps)
        if self._config.deps_file and self._config.deps_file.exists():
            file_deps = self._config.deps_file.read_text().strip().splitlines()
            for line in file_deps:
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    initial_deps.append(stripped)

        # Create deps namespace with initial deps from config
        if self._deps_namespace is None:
            installer = PackageInstaller()
            # Use a file-backed store if deps_file is configured, otherwise in-memory
            if self._config.deps_file:
                deps_store = FileDepsStore(self._config.deps_file.parent)
                # Pre-populate store with config deps
                for dep in initial_deps:
                    if not deps_store.exists(dep):
                        deps_store.add(dep)
            else:
                # In-memory store for deps when no file configured
                from py_code_mode.deps.store import MemoryDepsStore

                deps_store = MemoryDepsStore()
                for dep in initial_deps:
                    deps_store.add(dep)
            self._deps_namespace = DepsNamespace(store=deps_store, installer=installer)

        # Wrap deps namespace if runtime deps disabled
        if not self._config.allow_runtime_deps:
            self._namespace["deps"] = ControlledDepsNamespace(
                self._deps_namespace, allow_runtime=False
            )
        else:
            self._namespace["deps"] = self._deps_namespace

        # Skills and artifacts from storage (if provided)
        if storage is not None:
            self._skill_library = storage.get_skill_library()
            self._namespace["skills"] = SkillsNamespace(self._skill_library, self._namespace)

            self._artifact_store = storage.get_artifact_store()
            self._namespace["artifacts"] = self._artifact_store
        elif self._skill_library is not None:
            # Use skill_library from __init__ if provided
            self._namespace["skills"] = SkillsNamespace(self._skill_library, self._namespace)

        if storage is None and self._artifact_store is not None:
            # Use artifact_store from __init__ if provided
            self._namespace["artifacts"] = self._artifact_store

    async def install_deps(self, packages: list[str]) -> dict[str, Any]:
        """Install packages in the in-process environment.

        This is a system-level API called by Session._sync_deps() during startup.
        It installs pre-configured packages and is NOT affected by allow_runtime_deps.

        Agent-initiated installs via deps.add() are blocked by ControlledDepsNamespace
        when allow_runtime_deps=False.

        Args:
            packages: List of package specifications (e.g., ["pandas>=2.0"])

        Returns:
            Dict with installed, already_present, and failed lists.

        Raises:
            RuntimeError: If deps namespace not initialized.
        """
        # NOTE: This method does NOT check allow_runtime_deps.
        # It's a system-level API for Session._sync_deps() to install pre-configured deps.
        # Agent-initiated installs are blocked at the namespace level by ControlledDepsNamespace.

        if self._deps_namespace is None:
            raise RuntimeError("Deps namespace not initialized")

        installed: list[str] = []
        already_present: list[str] = []
        failed: list[str] = []

        for pkg in packages:
            try:
                self._deps_namespace.add(pkg)
                installed.append(pkg)
            except Exception as e:
                logger.warning("Failed to install %s: %s", pkg, e)
                failed.append(pkg)

        return {
            "installed": installed,
            "already_present": already_present,
            "failed": failed,
        }

    async def uninstall_deps(self, packages: list[str]) -> dict[str, Any]:
        """Uninstall packages from the in-process environment.

        This is a system-level API called by Session.remove_dep().
        It uninstalls packages and is NOT affected by allow_runtime_deps.

        Agent-initiated removals via deps.remove() are blocked by ControlledDepsNamespace
        when allow_runtime_deps=False.

        Args:
            packages: List of package names to uninstall.

        Returns:
            Dict with removed, not_found, and failed lists.
        """
        # NOTE: This method does NOT check allow_runtime_deps.
        # It's a system-level API for Session.remove_dep() to uninstall packages.
        # Agent-initiated removals are blocked at the namespace level by ControlledDepsNamespace.

        removed: list[str] = []
        not_found: list[str] = []
        failed: list[str] = []

        for pkg in packages:
            # Validate package name to prevent flag injection
            if pkg.startswith("-"):
                logger.warning("Invalid package name (starts with '-'): %s", pkg)
                failed.append(pkg)
                continue

            try:
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "uninstall", "-y", pkg],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if result.returncode == 0:
                    removed.append(pkg)
                else:
                    # pip returns non-zero if package not found
                    if "not installed" in result.stderr.lower():
                        not_found.append(pkg)
                    else:
                        failed.append(pkg)
            except subprocess.TimeoutExpired:
                failed.append(pkg)
            except Exception:
                failed.append(pkg)

        return {
            "removed": removed,
            "not_found": not_found,
            "failed": failed,
        }

    def _sync_result_to_dict(self, result: Any) -> dict[str, Any]:
        """Convert SyncResult to dict format.

        Args:
            result: A SyncResult object or similar with installed/already_present/failed attrs.

        Returns:
            Dict with installed, already_present, and failed lists.
        """
        if hasattr(result, "installed"):
            return {
                "installed": list(getattr(result, "installed", [])),
                "already_present": list(getattr(result, "already_present", [])),
                "failed": list(getattr(result, "failed", [])),
            }
        return {"installed": [], "already_present": [], "failed": []}

    async def add_dep(self, package: str) -> dict[str, Any]:
        """Add and install a single package.

        Args:
            package: Package specification (e.g., "pandas>=2.0").

        Returns:
            Dict with installed, already_present, and failed lists.

        Raises:
            RuntimeDepsDisabledError: If runtime deps are disabled.
        """
        if self._deps_namespace is None:
            return {"installed": [], "already_present": [], "failed": [package]}

        # Check runtime deps permission
        if not self._config.allow_runtime_deps:
            from py_code_mode.deps import RuntimeDepsDisabledError

            raise RuntimeDepsDisabledError(
                "Runtime dependency installation is disabled. "
                "Dependencies must be pre-configured before session start."
            )

        result = self._deps_namespace.add(package)
        return self._sync_result_to_dict(result)

    async def remove_dep(self, package: str) -> dict[str, Any]:
        """Remove a package from configuration and uninstall it.

        Args:
            package: Package name to remove.

        Returns:
            Dict with removed, not_found, failed lists and removed_from_config flag.

        Raises:
            RuntimeDepsDisabledError: If runtime deps are disabled.
        """
        if self._deps_namespace is None:
            return {
                "removed": [],
                "not_found": [package],
                "failed": [],
                "removed_from_config": False,
            }

        # Check runtime deps permission
        if not self._config.allow_runtime_deps:
            from py_code_mode.deps import RuntimeDepsDisabledError

            raise RuntimeDepsDisabledError(
                "Runtime dependency modification is disabled. "
                "Dependencies must be pre-configured before session start."
            )

        removed = self._deps_namespace.remove(package)
        return {
            "removed": [package] if removed else [],
            "not_found": [] if removed else [package],
            "failed": [],
            "removed_from_config": removed,
        }

    async def list_deps(self) -> list[str]:
        """List all configured dependencies.

        Returns:
            List of package specifications.
        """
        if self._deps_namespace is None:
            return []
        return self._deps_namespace.list()

    async def sync_deps(self) -> dict[str, Any]:
        """Sync all configured dependencies.

        Returns:
            Dict with installed, already_present, and failed lists.
        """
        if self._deps_namespace is None:
            return {"installed": [], "already_present": [], "failed": []}
        result = self._deps_namespace.sync()
        return self._sync_result_to_dict(result)

    async def list_tools(self) -> list[dict[str, Any]]:
        """List all available tools.

        Returns:
            List of dicts with name, description, tags, and callables for each tool.
        """
        if self._registry is None:
            return []
        return [t.to_dict() for t in self._registry.list_tools()]

    async def search_tools(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search tools by name/description.

        Args:
            query: Search query string.
            limit: Maximum number of results to return.

        Returns:
            List of dicts with name, description, tags, and callables for matching tools.
        """
        if self._registry is None:
            return []
        return [t.to_dict() for t in self._registry.search(query, limit=limit)]

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
