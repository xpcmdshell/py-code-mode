"""Subprocess-based code execution using IPython kernel with RPC.

This executor runs Python code in an isolated subprocess (Jupyter kernel) with
bidirectional RPC for namespace operations. The kernel contains lightweight
proxy objects that forward all tools/skills/artifacts/deps calls to the host.

Key advantages over code injection (old namespace.py approach):
- No py-code-mode install needed in subprocess venv (just ipykernel + zmq)
- Single code path for all namespace operations
- Host maintains full control over storage access
"""

from __future__ import annotations

import ast
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from py_code_mode.storage.backends import StorageBackend

from py_code_mode.deps import DepsStore, FileDepsStore, MemoryDepsStore
from py_code_mode.execution.protocol import (
    Capability,
    StorageAccess,
    validate_storage_not_access,
)
from py_code_mode.execution.registry import register_backend
from py_code_mode.execution.subprocess.config import SubprocessConfig
from py_code_mode.execution.subprocess.host import KernelHost
from py_code_mode.execution.subprocess.venv import KernelVenv, VenvManager
from py_code_mode.tools import ToolRegistry, load_tools_from_path
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


class StorageResourceProvider:
    """ResourceProvider that bridges RPC to storage backend.

    This class implements the ResourceProvider protocol by delegating
    to the storage backend for skills and artifacts, and using
    executor-provided tool registry and deps store.
    """

    def __init__(
        self,
        storage: StorageBackend,
        tool_registry: ToolRegistry | None = None,
        deps_store: DepsStore | None = None,
        allow_runtime_deps: bool = True,
        venv_manager: VenvManager | None = None,
        venv: KernelVenv | None = None,
    ) -> None:
        """Initialize provider.

        Args:
            storage: Storage backend for skills and artifacts.
            tool_registry: Tool registry loaded from executor config.
            deps_store: Deps store for dependency management.
            allow_runtime_deps: Whether to allow deps.add() and deps.remove().
            venv_manager: VenvManager for package installation.
            venv: KernelVenv for the current subprocess.
        """
        self._storage = storage
        self._tool_registry = tool_registry
        self._deps_store = deps_store
        self._allow_runtime_deps = allow_runtime_deps
        self._venv_manager = venv_manager
        self._venv = venv
        # Cached skill library (lazy initialized)
        self._skill_library = None

    def _get_tool_registry(self) -> ToolRegistry | None:
        """Get tool registry. Already loaded at construction time."""
        return self._tool_registry

    def _get_skill_library(self):
        """Get skill library, caching the result."""
        if self._skill_library is None:
            self._skill_library = self._storage.get_skill_library()
        return self._skill_library

    # -------------------------------------------------------------------------
    # Tool methods
    # -------------------------------------------------------------------------

    async def call_tool(self, name: str, args: dict[str, Any]) -> Any:
        """Call a tool by name with given arguments.

        Supports both:
        - Direct tool invocation: name="curl", args={...}
        - Recipe invocation: name="curl.get", args={...}
        """
        registry = self._get_tool_registry()
        if registry is None:
            raise ValueError("No tools configured")

        # Parse name for recipe syntax (e.g., "curl.get")
        if "." in name:
            tool_name, recipe_name = name.split(".", 1)
        else:
            tool_name = name
            recipe_name = None

        # Find the tool's adapter
        adapter = registry.find_adapter_for_tool(tool_name)
        if adapter is None:
            raise ValueError(f"Unknown tool: {tool_name}")

        # Call the tool
        return await adapter.call_tool(tool_name, recipe_name, args)

    async def list_tools(self) -> list[dict[str, Any]]:
        """List all available tools."""
        registry = self._get_tool_registry()
        if registry is None:
            return []
        tools = registry.list_tools()
        return [
            {
                "name": tool.name,
                "description": tool.description or "",
                "tags": list(tool.tags),
            }
            for tool in tools
        ]

    async def search_tools(self, query: str, limit: int) -> list[dict[str, Any]]:
        """Search tools by query."""
        registry = self._get_tool_registry()
        if registry is None:
            return []
        tools = registry.search(query, limit=limit)
        return [
            {
                "name": tool.name,
                "description": tool.description or "",
                "tags": list(tool.tags),
            }
            for tool in tools
        ]

    async def list_tool_recipes(self, name: str) -> list[dict[str, Any]]:
        """List recipes for a specific tool."""
        registry = self._get_tool_registry()
        if registry is None:
            raise ValueError("No tools configured")
        all_tools = registry.get_all_tools()
        tool = next((t for t in all_tools if t.name == name), None)
        if tool is None:
            raise ValueError(f"Unknown tool: {name}")

        return [
            {
                "name": c.name,
                "description": c.description or "",
            }
            for c in tool.callables
        ]

    # -------------------------------------------------------------------------
    # Skill methods
    # -------------------------------------------------------------------------

    async def search_skills(self, query: str, limit: int) -> list[dict[str, Any]]:
        """Search for skills matching query."""
        library = self._get_skill_library()
        library.refresh()
        skills = library.search(query, limit=limit)
        return [
            {
                "name": s.name,
                "description": s.description,
                "params": {p.name: p.description or p.type for p in s.parameters},
            }
            for s in skills
        ]

    async def list_skills(self) -> list[dict[str, Any]]:
        """List all available skills."""
        library = self._get_skill_library()
        library.refresh()
        skills = library.list()
        return [
            {
                "name": s.name,
                "description": s.description,
                "params": {p.name: p.description or p.type for p in s.parameters},
            }
            for s in skills
        ]

    async def get_skill(self, name: str) -> dict[str, Any] | None:
        """Get a skill by name."""
        library = self._get_skill_library()
        library.refresh()
        skill = library.get(name)
        if skill is None:
            return None
        return {
            "name": skill.name,
            "description": skill.description,
            "source": skill.source,
            "params": {p.name: p.description or p.type for p in skill.parameters},
        }

    async def create_skill(self, name: str, source: str, description: str) -> dict[str, Any]:
        """Create and save a new skill."""
        from py_code_mode.skills import PythonSkill

        skill = PythonSkill.from_source(
            name=name,
            source=source,
            description=description,
        )

        library = self._get_skill_library()
        library.add(skill)

        return {
            "name": skill.name,
            "description": skill.description,
            "params": {p.name: p.description or p.type for p in skill.parameters},
        }

    async def delete_skill(self, name: str) -> bool:
        """Delete a skill."""
        library = self._get_skill_library()
        return library.remove(name)

    # -------------------------------------------------------------------------
    # Artifact methods
    # -------------------------------------------------------------------------

    async def load_artifact(self, name: str) -> Any:
        """Load an artifact by name."""
        store = self._storage.get_artifact_store()
        return store.load(name)

    async def save_artifact(self, name: str, data: Any, description: str) -> dict[str, Any]:
        """Save an artifact."""
        store = self._storage.get_artifact_store()
        artifact = store.save(name, data, description=description)
        return {
            "name": artifact.name,
            "path": artifact.path,
            "description": artifact.description,
            "created_at": artifact.created_at.isoformat(),
        }

    async def list_artifacts(self) -> list[dict[str, Any]]:
        """List all artifacts."""
        store = self._storage.get_artifact_store()
        artifacts = store.list()
        return [
            {
                "name": a.name,
                "path": a.path,
                "description": a.description,
                "created_at": a.created_at.isoformat(),
            }
            for a in artifacts
        ]

    async def delete_artifact(self, name: str) -> None:
        """Delete an artifact."""
        store = self._storage.get_artifact_store()
        store.delete(name)

    async def artifact_exists(self, name: str) -> bool:
        """Check if an artifact exists."""
        store = self._storage.get_artifact_store()
        return store.exists(name)

    async def get_artifact(self, name: str) -> dict[str, Any] | None:
        """Get artifact metadata."""
        store = self._storage.get_artifact_store()
        artifact = store.get(name)
        if artifact is None:
            return None
        return {
            "name": artifact.name,
            "path": artifact.path,
            "description": artifact.description,
            "created_at": artifact.created_at.isoformat(),
        }

    # -------------------------------------------------------------------------
    # Deps methods
    # -------------------------------------------------------------------------

    async def add_dep(self, package: str) -> dict[str, Any]:
        """Add and install a package.

        When allow_runtime_deps=False, raises RuntimeError.
        """
        if not self._allow_runtime_deps:
            raise RuntimeError(
                "RuntimeDepsDisabledError: Runtime dependency installation is disabled. "
                "Dependencies must be pre-configured before session start."
            )

        # Add to deps store if configured
        if self._deps_store is not None:
            self._deps_store.add(package)

        # Install via venv manager if available
        if self._venv_manager is not None and self._venv is not None:
            try:
                await self._venv_manager.add_package(self._venv, package)
                return {"installed": [package], "already_present": [], "failed": []}
            except Exception as e:
                logger.warning("Failed to install %s: %s", package, e)
                return {"installed": [], "already_present": [], "failed": [package]}
        else:
            # No venv manager - just report what we would install
            return {"installed": [package], "already_present": [], "failed": []}

    async def remove_dep(self, package: str) -> bool:
        """Remove a package from configuration.

        When allow_runtime_deps=False, raises RuntimeError.
        """
        if not self._allow_runtime_deps:
            raise RuntimeError(
                "RuntimeDepsDisabledError: Runtime dependency modification is disabled. "
                "Dependencies must be pre-configured before session start."
            )

        if self._deps_store is None:
            return False
        return self._deps_store.remove(package)

    async def list_deps(self) -> list[str]:
        """List configured packages."""
        if self._deps_store is None:
            return []
        return self._deps_store.list()

    async def sync_deps(self) -> dict[str, Any]:
        """Install all configured packages.

        This is always allowed, even when allow_runtime_deps=False,
        because it only installs pre-configured packages.
        """
        if self._deps_store is None:
            return {"installed": [], "already_present": [], "failed": []}

        packages = self._deps_store.list()

        if not packages:
            return {"installed": [], "already_present": [], "failed": []}

        if self._venv_manager is None or self._venv is None:
            return {"installed": packages, "already_present": [], "failed": []}

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


class SubprocessExecutor:
    """Execute code in an isolated subprocess with its own venv and IPython kernel.

    This executor uses bidirectional RPC via the stdin channel for namespace
    operations. The kernel contains lightweight proxy objects that forward
    all tools/skills/artifacts/deps calls to the host.

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
        self._host: KernelHost | None = None
        self._provider: StorageResourceProvider | None = None
        self._closed = False
        self._storage: StorageBackend | None = None
        self._storage_access: StorageAccess | None = None
        self._tool_registry: ToolRegistry | None = None
        self._deps_store: DepsStore | None = None

    def supports(self, capability: str) -> bool:
        """Check if this backend supports a capability."""
        return capability in self._CAPABILITIES

    def supported_capabilities(self) -> set[str]:
        """Return set of all capabilities this backend supports."""
        return set(self._CAPABILITIES)

    def get_configured_deps(self) -> list[str]:
        """Return list of pre-configured dependencies from executor config.

        These are deps specified via config.deps tuple and config.deps_file.
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

    async def start(self, storage: StorageBackend | None = None) -> None:
        """Start kernel: create venv, start kernel, initialize RPC.

        Tools and deps are loaded from executor config (tools_path, deps, deps_file).
        Skills and artifacts come from storage backend.

        Args:
            storage: Optional StorageBackend for skills and artifacts.

        Raises:
            RuntimeError: If already started or storage access fails.
            TypeError: If passed old StorageAccess types instead of StorageBackend.
        """
        # Reject old StorageAccess types - no backward compatibility
        validate_storage_not_access(storage, "SubprocessExecutor")

        if self._host is not None:
            raise RuntimeError("Executor already started")

        self._storage = storage

        # Store access info for serialization if needed
        if storage is not None:
            try:
                self._storage_access = storage.get_serializable_access()
            except Exception as e:
                raise RuntimeError(f"Failed to get serializable access from storage: {e}") from e

        # 1. Load tools from executor config (NOT storage)
        if self._config.tools_path is not None:
            self._tool_registry = await load_tools_from_path(self._config.tools_path)

        # 2. Create deps store from executor config (NOT storage)
        initial_deps: list[str] = []
        if self._config.deps:
            initial_deps.extend(self._config.deps)
        if self._config.deps_file and self._config.deps_file.exists():
            file_deps = self._config.deps_file.read_text().strip().splitlines()
            for line in file_deps:
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    initial_deps.append(stripped)

        # Create deps store with initial deps from config
        if self._config.deps_file:
            self._deps_store = FileDepsStore(self._config.deps_file.parent)
            for dep in initial_deps:
                if not self._deps_store.exists(dep):
                    self._deps_store.add(dep)
        else:
            self._deps_store = MemoryDepsStore()
            for dep in initial_deps:
                self._deps_store.add(dep)

        # 3. Create venv with VenvManager
        # Use minimal base_deps since we don't need py-code-mode in venv
        # The RPC approach only needs ipykernel and pyzmq
        self._venv_manager = VenvManager(self._config)
        self._venv = await self._venv_manager.create()

        # 4. Create KernelHost and ResourceProvider
        self._host = KernelHost()

        if storage is not None:
            self._provider = StorageResourceProvider(
                storage=storage,
                tool_registry=self._tool_registry,
                deps_store=self._deps_store,
                allow_runtime_deps=self._config.allow_runtime_deps,
                venv_manager=self._venv_manager,
                venv=self._venv,
            )
        else:
            # Create a minimal provider for basic execution
            self._provider = None

        # 5. Start kernel with RPC
        await self._host.start(
            provider=self._provider,  # type: ignore[arg-type]
            kernel_name=self._venv.kernel_spec_name,
            startup_timeout=self._config.startup_timeout,
            ipc_timeout=self._config.ipc_timeout,
        )

    async def run(self, code: str, timeout: float | None = None) -> ExecutionResult:
        """Execute code in kernel, return result.

        Args:
            code: Python code to execute.
            timeout: Optional timeout in seconds. Uses config default if None.
                    None means no timeout (unlimited).

        Returns:
            ExecutionResult with value, stdout, and error fields.
        """
        if self._closed or self._host is None:
            return ExecutionResult(value=None, stdout="", error="Executor is closed")

        # Use config default if not specified (could still be None for unlimited)
        effective_timeout = timeout if timeout is not None else self._config.default_timeout

        # Execute via KernelHost
        result = await self._host.execute(
            code,
            allow_stdin=True,
            timeout=effective_timeout,
        )

        # Convert KernelHost ExecutionResult to py-code-mode ExecutionResult
        # Deserialize the value from IPython's text/plain representation
        value = _deserialize_value(result.value)

        # Combine stdout and stderr
        combined_output = result.stdout
        if result.stderr:
            if combined_output:
                combined_output = combined_output + result.stderr
            else:
                combined_output = result.stderr

        # Format error with traceback if present
        error = result.error
        if error and result.traceback:
            error = "\n".join(result.traceback)

        return ExecutionResult(value=value, stdout=combined_output, error=error)

    async def reset(self) -> None:
        """Clear kernel state by restarting.

        This clears all user-defined variables but re-injects RPC namespaces.
        """
        if self._host is not None:
            await self._host.restart(startup_timeout=self._config.startup_timeout)

    async def install_deps(self, packages: list[str]) -> dict[str, Any]:
        """Install packages in the subprocess venv.

        This is a system-level API called by Session._sync_deps() during startup.
        It installs pre-configured packages and is NOT affected by allow_runtime_deps.

        Agent-initiated installs via deps.add() are blocked by the provider
        when allow_runtime_deps=False.

        Args:
            packages: List of package specifications to install.

        Returns:
            Dict with "installed", "already_present", and "failed" lists.

        Raises:
            RuntimeError: If venv is not initialized.
        """
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

        Agent-initiated removals via deps.remove() are blocked by the provider
        when allow_runtime_deps=False.

        Args:
            packages: List of package names to uninstall.

        Returns:
            Dict with "removed", "not_found", and "failed" lists.

        Raises:
            RuntimeError: If venv is not initialized.
        """
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

    async def add_dep(self, package: str) -> dict[str, Any]:
        """Add and install a single package.

        Delegates to the provider which handles deps store and venv installation.
        After installation, invalidates the kernel's import cache so the new
        package is immediately importable.
        """
        if self._provider is None:
            return {"installed": [], "already_present": [], "failed": [package]}

        result = await self._provider.add_dep(package)

        # Invalidate import caches in the kernel so newly installed packages
        # are immediately importable without restarting the kernel
        if result.get("installed") and self._host is not None:
            await self._host.execute(
                "import importlib; importlib.invalidate_caches()",
                allow_stdin=False,
                timeout=5.0,
            )

        return result

    async def remove_dep(self, package: str) -> dict[str, Any]:
        """Remove a package from configuration.

        Delegates to the provider which handles deps store removal.
        """
        if self._provider is None:
            return {
                "removed": [],
                "not_found": [package],
                "failed": [],
                "removed_from_config": False,
            }
        removed = await self._provider.remove_dep(package)
        return {
            "removed": [package] if removed else [],
            "not_found": [] if removed else [package],
            "failed": [],
            "removed_from_config": removed,
        }

    async def list_deps(self) -> list[str]:
        """List all configured dependencies."""
        if self._provider is None:
            return []
        return await self._provider.list_deps()

    async def sync_deps(self) -> dict[str, Any]:
        """Sync all configured dependencies.

        After installation, invalidates the kernel's import cache so newly
        installed packages are immediately importable.
        """
        if self._provider is None:
            return {"installed": [], "already_present": [], "failed": []}

        result = await self._provider.sync_deps()

        # Invalidate import caches in the kernel so newly installed packages
        # are immediately importable without restarting the kernel
        if result.get("installed") and self._host is not None:
            await self._host.execute(
                "import importlib; importlib.invalidate_caches()",
                allow_stdin=False,
                timeout=5.0,
            )

        return result

    async def list_tools(self) -> list[dict[str, Any]]:
        """List all available tools."""
        if self._provider is None:
            return []
        return await self._provider.list_tools()

    async def search_tools(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search tools by name/description."""
        if self._provider is None:
            return []
        return await self._provider.search_tools(query, limit)

    async def close(self) -> None:
        """Shutdown kernel and cleanup venv."""
        self._closed = True

        # Close tool registry first (MCP adapters need cleanup in same task)
        if self._tool_registry is not None:
            await self._tool_registry.close()
            self._tool_registry = None

        if self._host is not None:
            await self._host.shutdown()
            self._host = None

        if (
            self._config.get_resolved_cleanup()
            and self._venv is not None
            and self._venv_manager is not None
        ):
            await self._venv_manager.cleanup(self._venv)
            self._venv = None

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
