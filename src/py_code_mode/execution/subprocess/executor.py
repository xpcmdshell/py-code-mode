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

from py_code_mode.execution.protocol import (
    Capability,
    StorageAccess,
    validate_storage_not_access,
)
from py_code_mode.execution.registry import register_backend
from py_code_mode.execution.subprocess.config import SubprocessConfig
from py_code_mode.execution.subprocess.host import KernelHost
from py_code_mode.execution.subprocess.venv import KernelVenv, VenvManager
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
    to the storage backend's tools, skills, artifacts, and deps.
    """

    def __init__(
        self,
        storage: StorageBackend,
        allow_runtime_deps: bool = True,
        venv_manager: VenvManager | None = None,
        venv: KernelVenv | None = None,
    ) -> None:
        """Initialize provider.

        Args:
            storage: Storage backend for all resources.
            allow_runtime_deps: Whether to allow deps.add() and deps.remove().
            venv_manager: VenvManager for package installation.
            venv: KernelVenv for the current subprocess.
        """
        self._storage = storage
        self._allow_runtime_deps = allow_runtime_deps
        self._venv_manager = venv_manager
        self._venv = venv
        # Cached resources (lazy initialized)
        self._tool_registry = None
        self._skill_library = None

    async def _get_tool_registry(self):
        """Get tool registry, caching the result."""
        if self._tool_registry is None:
            self._tool_registry = await self._storage.get_tool_registry()
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
        registry = await self._get_tool_registry()

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
        registry = await self._get_tool_registry()
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
        registry = await self._get_tool_registry()
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
        registry = await self._get_tool_registry()
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

    async def invoke_skill(self, name: str, args: dict[str, Any]) -> Any:
        """Invoke a skill by name with given arguments.

        The skill is executed in the host process with access to tools,
        skills, and artifacts namespaces. Execution runs in a thread pool
        to avoid blocking the event loop while allowing sync tool calls.
        """
        import asyncio
        import builtins
        import concurrent.futures

        library = self._get_skill_library()
        skill = library.get(name)
        if skill is None:
            raise ValueError(f"Skill not found: {name}")

        # Execute skill in host with access to namespaces
        from py_code_mode.tools import ToolsNamespace

        registry = await self._get_tool_registry()
        tools_ns = ToolsNamespace(registry)
        artifact_store = self._storage.get_artifact_store()

        # Get the current event loop for thread-safe tool calls
        loop = asyncio.get_running_loop()
        tools_ns.set_loop(loop)

        # Create execution namespace
        skill_namespace: dict[str, Any] = {
            "tools": tools_ns,
            "skills": library,
            "artifacts": artifact_store,
        }

        def run_skill_sync() -> Any:
            """Run skill synchronously in a thread."""
            # Compile and execute skill
            _run_code = getattr(builtins, "exec")
            code = compile(skill.source, f"<skill:{name}>", "exec")
            _run_code(code, skill_namespace)
            # Call the run function
            return skill_namespace["run"](**args)

        # Run skill in thread pool to avoid blocking the event loop
        # This allows the skill to make sync tool calls that use
        # run_coroutine_threadsafe to call back into the event loop
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run_skill_sync)
            # Wait for completion while allowing async cooperation
            while not future.done():
                await asyncio.sleep(0.01)
            return future.result()

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

        # Add to storage
        deps_store = self._storage.get_deps_store()
        deps_store.add(package)

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

        deps_store = self._storage.get_deps_store()
        return deps_store.remove(package)

    async def list_deps(self) -> list[str]:
        """List configured packages."""
        deps_store = self._storage.get_deps_store()
        return deps_store.list()

    async def sync_deps(self) -> dict[str, Any]:
        """Install all configured packages.

        This is always allowed, even when allow_runtime_deps=False,
        because it only installs pre-configured packages.
        """
        deps_store = self._storage.get_deps_store()
        packages = deps_store.list()

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

    def supports(self, capability: str) -> bool:
        """Check if this backend supports a capability."""
        return capability in self._CAPABILITIES

    def supported_capabilities(self) -> set[str]:
        """Return set of all capabilities this backend supports."""
        return set(self._CAPABILITIES)

    async def start(self, storage: StorageBackend | None = None) -> None:
        """Start kernel: create venv, start kernel, initialize RPC.

        Args:
            storage: Optional StorageBackend for namespace injection.

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

        # 1. Create venv with VenvManager
        # Use minimal base_deps since we don't need py-code-mode in venv
        # The RPC approach only needs ipykernel and pyzmq
        self._venv_manager = VenvManager(self._config)
        self._venv = await self._venv_manager.create()

        # 2. Create KernelHost and ResourceProvider
        self._host = KernelHost()

        if storage is not None:
            self._provider = StorageResourceProvider(
                storage=storage,
                allow_runtime_deps=self._config.allow_runtime_deps,
                venv_manager=self._venv_manager,
                venv=self._venv,
            )
        else:
            # Create a minimal provider for basic execution
            self._provider = None

        # 3. Start kernel with RPC
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

    async def close(self) -> None:
        """Shutdown kernel and cleanup venv."""
        self._closed = True

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
