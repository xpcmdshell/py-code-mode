"""Namespace setup code generation for SubprocessExecutor.

Generates Python code that sets up tools, skills, artifacts, and deps namespaces
in the kernel subprocess using full py-code-mode functionality.
"""

from __future__ import annotations

from py_code_mode.execution.protocol import FileStorageAccess, StorageAccess


def build_namespace_setup_code(
    storage_access: StorageAccess | None,
    allow_runtime_deps: bool = True,
) -> str:
    """Generate Python code that sets up namespaces in the kernel.

    The generated code imports from py-code-mode (which must be installed
    in the kernel's venv) and creates real namespace objects with full
    functionality including tool invocation, skill creation, and semantic search.

    Args:
        storage_access: Storage access descriptor with paths or connection info.
                       If None, returns empty string.
        allow_runtime_deps: Whether to allow deps.add() and deps.sync() calls.
                           If False, these methods raise RuntimeError.

    Returns:
        Python code string to execute in the kernel to set up namespaces.
    """
    if storage_access is None:
        return ""

    if isinstance(storage_access, FileStorageAccess):
        return _build_file_storage_setup_code(storage_access, allow_runtime_deps)

    # Other storage types not yet supported for subprocess
    return ""


def _build_file_storage_setup_code(
    storage_access: FileStorageAccess,
    allow_runtime_deps: bool,
) -> str:
    """Generate namespace setup code for FileStorageAccess."""
    tools_path_str = repr(str(storage_access.tools_path)) if storage_access.tools_path else "None"
    skills_path_str = (
        repr(str(storage_access.skills_path)) if storage_access.skills_path else "None"
    )
    artifacts_path_str = repr(str(storage_access.artifacts_path))
    # Base path is parent of artifacts for deps store
    base_path_str = repr(str(storage_access.artifacts_path.parent))
    allow_deps_str = "True" if allow_runtime_deps else "False"

    return f'''# Auto-generated namespace setup for SubprocessExecutor
# This code sets up full py-code-mode namespaces in the kernel

from pathlib import Path
import asyncio
import nest_asyncio

# Enable nested event loops (required for sync tool calls in Jupyter kernel)
nest_asyncio.apply()

# =============================================================================
# Tools Namespace (with sync wrapper for subprocess context)
# =============================================================================

from py_code_mode.tools import ToolRegistry, ToolsNamespace
from py_code_mode.tools.adapters import CLIAdapter

_tools_path = Path({tools_path_str}) if {tools_path_str} else None
_registry = ToolRegistry()

if _tools_path is not None and _tools_path.exists():
    _adapter = CLIAdapter(tools_path=_tools_path)
    _registry.add_adapter(_adapter)

# Create the base namespace
_base_tools = ToolsNamespace(_registry)

# Wrapper that forces sync execution in Jupyter kernel context
class _SyncToolsWrapper:
    """Wrapper that ensures tools execute synchronously in subprocess."""

    def __init__(self, namespace):
        self._namespace = namespace

    def __getattr__(self, name):
        attr = getattr(self._namespace, name)
        if hasattr(attr, '_tool'):
            # It's a ToolProxy - wrap it
            return _SyncToolProxy(attr)
        return attr

    def list(self):
        return self._namespace.list()

    def search(self, query, limit=5):
        return self._namespace.search(query, limit)


class _SyncToolProxy:
    """Wrapper that forces sync execution for tool proxies."""

    def __init__(self, proxy):
        self._proxy = proxy

    def __call__(self, **kwargs):
        result = self._proxy(**kwargs)
        if asyncio.iscoroutine(result):
            return asyncio.get_event_loop().run_until_complete(result)
        return result

    def __getattr__(self, name):
        attr = getattr(self._proxy, name)
        if callable(attr):
            return _SyncCallableWrapper(attr)
        return attr

    def list(self):
        return self._proxy.list()


class _SyncCallableWrapper:
    """Wrapper that forces sync execution for callable proxies."""

    def __init__(self, callable_proxy):
        self._callable = callable_proxy

    def __call__(self, **kwargs):
        result = self._callable(**kwargs)
        if asyncio.iscoroutine(result):
            return asyncio.get_event_loop().run_until_complete(result)
        return result


tools = _SyncToolsWrapper(_base_tools)

# =============================================================================
# Skills Namespace
# =============================================================================

from py_code_mode.skills import FileSkillStore, create_skill_library
from py_code_mode.execution.in_process.skills_namespace import SkillsNamespace

_skills_path = Path({skills_path_str}) if {skills_path_str} else None

if _skills_path is not None:
    _skills_path.mkdir(parents=True, exist_ok=True)
    _store = FileSkillStore(_skills_path)
    _library = create_skill_library(store=_store)
else:
    from py_code_mode.skills import MemorySkillStore, MockEmbedder, SkillLibrary
    _store = MemorySkillStore()
    _library = SkillLibrary(embedder=MockEmbedder(), store=_store)

# SkillsNamespace now takes a namespace dict directly (no executor needed).
# Create the namespace dict first, then wire up circular references.
_skills_ns_dict = {{}}
skills = SkillsNamespace(_library, _skills_ns_dict)

# Wire up the namespace so skills can access tools/skills/artifacts
_skills_ns_dict["tools"] = tools
_skills_ns_dict["skills"] = skills

# =============================================================================
# Artifacts Namespace (with simplified API for agent usage)
# =============================================================================

from py_code_mode.artifacts import FileArtifactStore

_artifacts_path = Path({artifacts_path_str})
_artifacts_path.mkdir(parents=True, exist_ok=True)
_base_artifacts = FileArtifactStore(_artifacts_path)


class _SimpleArtifactStore:
    """Wrapper providing simplified artifacts API for agents.

    Wraps FileArtifactStore to provide:
    - save(name, data) with optional description (defaults to empty string)
    - All other methods pass through unchanged
    """

    def __init__(self, store):
        self._store = store

    def save(self, name, data, description=""):
        """Save artifact with optional description."""
        return self._store.save(name, data, description)

    def load(self, name):
        """Load artifact by name."""
        return self._store.load(name)

    def list(self):
        """List all artifacts."""
        return self._store.list()

    def exists(self, name):
        """Check if artifact exists."""
        return self._store.exists(name)

    def delete(self, name):
        """Delete artifact."""
        return self._store.delete(name)

    def get(self, name):
        """Get artifact metadata."""
        return self._store.get(name)

    @property
    def path(self):
        """Base path for raw file access."""
        return self._store.path


artifacts = _SimpleArtifactStore(_base_artifacts)

# Complete the namespace wiring for skills
_skills_ns_dict["artifacts"] = artifacts

# =============================================================================
# Deps Namespace (with optional runtime deps control)
# =============================================================================

from py_code_mode.deps import DepsNamespace, FileDepsStore, PackageInstaller

_base_path = Path({base_path_str})
_deps_store = FileDepsStore(_base_path)
_installer = PackageInstaller()
_base_deps = DepsNamespace(_deps_store, _installer)

_allow_runtime_deps = {allow_deps_str}


class _ControlledDepsNamespace:
    """Wrapper that optionally blocks add() and sync() calls.

    When allow_runtime_deps=False, add() and sync() raise RuntimeError
    to prevent runtime package installation. list() and remove() always work.
    """

    def __init__(self, namespace, allow_runtime):
        self._namespace = namespace
        self._allow_runtime = allow_runtime

    def add(self, package):
        """Add a package (blocked if runtime deps disabled)."""
        if not self._allow_runtime:
            raise RuntimeError(
                "Runtime dependency installation is disabled. "
                "Set allow_runtime_deps=True in SubprocessConfig to enable."
            )
        return self._namespace.add(package)

    def sync(self):
        """Sync packages (blocked if runtime deps disabled)."""
        if not self._allow_runtime:
            raise RuntimeError(
                "Runtime dependency installation is disabled. "
                "Set allow_runtime_deps=True in SubprocessConfig to enable."
            )
        return self._namespace.sync()

    def list(self):
        """List packages (always allowed)."""
        return self._namespace.list()

    def remove(self, package):
        """Remove a package from config (always allowed)."""
        return self._namespace.remove(package)

    @property
    def _store(self):
        """Access underlying store for testing."""
        return self._namespace._store

    def __repr__(self):
        return self._namespace.__repr__()


deps = _ControlledDepsNamespace(_base_deps, _allow_runtime_deps)

# Complete the namespace wiring for skills to include deps
_skills_ns_dict["deps"] = deps

# =============================================================================
# Cleanup temporary variables (keep wrapper classes for runtime use)
# =============================================================================

del _tools_path, _registry, _base_tools
try:
    del _adapter
except NameError:
    pass
del _skills_path, _store, _library, _skills_ns_dict
del _artifacts_path, _base_artifacts
del _base_path, _deps_store, _installer, _base_deps, _allow_runtime_deps
del Path
del ToolRegistry, ToolsNamespace, CLIAdapter
del FileSkillStore, create_skill_library, SkillsNamespace
try:
    del MemorySkillStore, MockEmbedder, SkillLibrary
except NameError:
    pass
del FileArtifactStore
del DepsNamespace, FileDepsStore, PackageInstaller
# Note: Wrapper classes (_SyncToolsWrapper, _SyncToolProxy, _SyncCallableWrapper,
# _SimpleArtifactStore, _ControlledDepsNamespace) and asyncio/nest_asyncio are kept for runtime use
'''
