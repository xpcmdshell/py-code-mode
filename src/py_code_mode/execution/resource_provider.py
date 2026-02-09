"""Host-side ResourceProvider for sandboxed executors.

This module contains the provider used by isolated runtimes to access
tools/workflows/artifacts/deps via RPC.

Today SubprocessExecutor uses this to service kernel-side proxy namespaces.
The Deno/Pyodide executor will reuse the same provider to avoid duplicating
behavior across backends.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from py_code_mode.deps import DepsStore
from py_code_mode.tools import ToolRegistry

if TYPE_CHECKING:
    from py_code_mode.execution.subprocess.venv import KernelVenv, VenvManager
    from py_code_mode.storage.backends import StorageBackend

logger = logging.getLogger(__name__)


class StorageResourceProvider:
    """ResourceProvider that bridges RPC to storage backend.

    Delegates to:
    - tool_registry (executor-owned, from config.tools_path)
    - storage backend (workflows + artifacts)
    - deps_store (executor-owned, from config.deps/deps_file)

    Notes:
    - For SubprocessExecutor, deps installation uses VenvManager.
    - For other executors (e.g., Deno/Pyodide), deps ops may be mediated
      differently; those executors can ignore the venv fields or provide their own.
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
        self._storage = storage
        self._tool_registry = tool_registry
        self._deps_store = deps_store
        self._allow_runtime_deps = allow_runtime_deps
        self._venv_manager = venv_manager
        self._venv = venv
        self._workflow_library = None  # lazy

    def _get_tool_registry(self) -> ToolRegistry | None:
        return self._tool_registry

    def _get_workflow_library(self):
        if self._workflow_library is None:
            self._workflow_library = self._storage.get_workflow_library()
        return self._workflow_library

    # -------------------------------------------------------------------------
    # Tool methods
    # -------------------------------------------------------------------------

    async def call_tool(self, name: str, args: dict[str, Any]) -> Any:
        registry = self._get_tool_registry()
        if registry is None:
            raise ValueError("No tools configured")

        if "." in name:
            tool_name, recipe_name = name.split(".", 1)
        else:
            tool_name = name
            recipe_name = None

        return await registry.call_tool(tool_name, recipe_name, args)

    async def list_tools(self) -> list[dict[str, Any]]:
        registry = self._get_tool_registry()
        if registry is None:
            return []
        return [tool.to_dict() for tool in registry.list_tools()]

    async def search_tools(self, query: str, limit: int) -> list[dict[str, Any]]:
        registry = self._get_tool_registry()
        if registry is None:
            return []
        return [tool.to_dict() for tool in registry.search(query, limit=limit)]

    async def list_tool_recipes(self, name: str) -> list[dict[str, Any]]:
        registry = self._get_tool_registry()
        if registry is None:
            raise ValueError("No tools configured")

        all_tools = registry.get_all_tools()
        tool = next((t for t in all_tools if t.name == name), None)
        if tool is None:
            raise ValueError(f"Unknown tool: {name}")

        return [{"name": c.name, "description": c.description or ""} for c in tool.callables]

    # -------------------------------------------------------------------------
    # Workflow methods
    # -------------------------------------------------------------------------

    async def search_workflows(self, query: str, limit: int) -> list[dict[str, Any]]:
        library = self._get_workflow_library()
        library.refresh()
        workflows = library.search(query, limit=limit)
        return [
            {
                "name": w.name,
                "description": w.description,
                "params": {p.name: p.description or p.type for p in w.parameters},
            }
            for w in workflows
        ]

    async def list_workflows(self) -> list[dict[str, Any]]:
        library = self._get_workflow_library()
        library.refresh()
        workflows = library.list()
        return [
            {
                "name": w.name,
                "description": w.description,
                "params": {p.name: p.description or p.type for p in w.parameters},
            }
            for w in workflows
        ]

    async def get_workflow(self, name: str) -> dict[str, Any] | None:
        library = self._get_workflow_library()
        library.refresh()
        workflow = library.get(name)
        if workflow is None:
            return None
        return {
            "name": workflow.name,
            "description": workflow.description,
            "source": workflow.source,
            "params": {p.name: p.description or p.type for p in workflow.parameters},
        }

    async def create_workflow(self, name: str, source: str, description: str) -> dict[str, Any]:
        from py_code_mode.workflows import PythonWorkflow

        workflow = PythonWorkflow.from_source(
            name=name,
            source=source,
            description=description,
        )

        library = self._get_workflow_library()
        library.add(workflow)

        return {
            "name": workflow.name,
            "description": workflow.description,
            "params": {p.name: p.description or p.type for p in workflow.parameters},
        }

    async def delete_workflow(self, name: str) -> bool:
        library = self._get_workflow_library()
        return library.remove(name)

    # -------------------------------------------------------------------------
    # Artifact methods
    # -------------------------------------------------------------------------

    async def load_artifact(self, name: str) -> Any:
        store = self._storage.get_artifact_store()
        return store.load(name)

    async def save_artifact(self, name: str, data: Any, description: str) -> dict[str, Any]:
        store = self._storage.get_artifact_store()
        artifact = store.save(name, data, description=description)
        return {
            "name": artifact.name,
            "path": artifact.path,
            "description": artifact.description,
            "created_at": artifact.created_at.isoformat(),
        }

    async def list_artifacts(self) -> list[dict[str, Any]]:
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
        store = self._storage.get_artifact_store()
        store.delete(name)

    async def artifact_exists(self, name: str) -> bool:
        store = self._storage.get_artifact_store()
        return store.exists(name)

    async def get_artifact(self, name: str) -> dict[str, Any] | None:
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
    # Deps methods (host-side persistence + optional venv install hook)
    # -------------------------------------------------------------------------

    async def add_dep(self, package: str) -> dict[str, Any]:
        if not self._allow_runtime_deps:
            raise RuntimeError(
                "RuntimeDepsDisabledError: Runtime dependency installation is disabled. "
                "Dependencies must be pre-configured before session start."
            )

        if self._deps_store is not None:
            self._deps_store.add(package)

        # SubprocessExecutor path: also install into venv if available.
        if self._venv_manager is not None and self._venv is not None:
            try:
                await self._venv_manager.add_package(self._venv, package)
                return {"installed": [package], "already_present": [], "failed": []}
            except Exception as e:
                logger.warning("Failed to install %s: %s", package, e)
                return {"installed": [], "already_present": [], "failed": [package]}

        return {"installed": [package], "already_present": [], "failed": []}

    async def remove_dep(self, package: str) -> bool:
        if not self._allow_runtime_deps:
            raise RuntimeError(
                "RuntimeDepsDisabledError: Runtime dependency modification is disabled. "
                "Dependencies must be pre-configured before session start."
            )

        if self._deps_store is None:
            return False
        return self._deps_store.remove(package)

    async def list_deps(self) -> list[str]:
        if self._deps_store is None:
            return []
        return self._deps_store.list()

    async def sync_deps(self) -> dict[str, Any]:
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
