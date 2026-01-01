"""Bootstrap module for reconstructing storage and namespaces in subprocesses.

This module provides the core primitives for SubprocessExecutor to reconstruct
storage backends and their associated namespaces without knowing about specific
storage implementations. The pattern is:

1. Storage classes implement `to_bootstrap_config()` returning a JSON-serializable dict
2. This dict is passed to the subprocess along with executor config (tools_path, etc.)
3. `bootstrap_namespaces(config)` reconstructs the storage and creates namespaces

This keeps the executor decoupled from storage implementations.

Architecture note: Tools are owned by executors (via config.tools_path), not storage.
The bootstrap config can optionally include tools_path for the subprocess to load tools.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from py_code_mode.artifacts import ArtifactStoreProtocol
    from py_code_mode.deps import DepsNamespace
    from py_code_mode.execution.in_process.skills_namespace import SkillsNamespace
    from py_code_mode.tools import ToolsNamespace


@dataclass
class NamespaceBundle:
    """Container for reconstructed namespaces.

    Provides the four namespaces needed for code execution:
    - tools: ToolsNamespace for tool access
    - skills: SkillsNamespace for skill access
    - artifacts: ArtifactStoreProtocol for artifact storage
    - deps: DepsNamespace for dependency management
    """

    tools: ToolsNamespace
    skills: SkillsNamespace
    artifacts: ArtifactStoreProtocol
    deps: DepsNamespace


async def bootstrap_namespaces(config: dict[str, Any]) -> NamespaceBundle:
    """Reconstruct storage and namespaces from serialized config.

    This function is async because tool registry initialization may require
    async operations (e.g., MCP server connections).

    Args:
        config: Dict with "type" key ("file" or "redis") and type-specific fields.
                - For "file": {"type": "file", "base_path": str, "tools_path": str|None}
                - For "redis": {"type": "redis", "url": str, "prefix": str,
                  "tools_path": str|None}
                - tools_path is optional; if provided, tools load from that directory

    Returns:
        NamespaceBundle with tools, skills, artifacts namespaces.

    Raises:
        ValueError: If config["type"] is unknown or missing.
        KeyError: If required fields are missing for the storage type.
    """
    storage_type = config.get("type")

    if storage_type == "file":
        return await _bootstrap_file_storage(config)
    elif storage_type == "redis":
        return await _bootstrap_redis_storage(config)
    else:
        raise ValueError(f"Unknown storage type: {storage_type!r}. Expected 'file' or 'redis'.")


async def _bootstrap_file_storage(config: dict[str, Any]) -> NamespaceBundle:
    """Bootstrap namespaces from FileStorage config.

    Args:
        config: Dict with base_path key and optional tools_path.

    Returns:
        NamespaceBundle with file-based storage.

    Raises:
        KeyError: If base_path is missing.
    """
    # Import lazily to avoid circular imports
    from py_code_mode.deps import DepsNamespace, FileDepsStore, PackageInstaller
    from py_code_mode.execution.in_process.skills_namespace import SkillsNamespace
    from py_code_mode.storage import FileStorage
    from py_code_mode.tools import ToolRegistry, ToolsNamespace

    base_path = Path(config["base_path"])
    storage = FileStorage(base_path)

    # Tools are owned by executor, loaded from config if provided
    tools_path_str = config.get("tools_path")
    if tools_path_str:
        tools_path = Path(tools_path_str)
        registry = ToolRegistry()
        await registry.load_from_directory(tools_path)
        tools_ns = ToolsNamespace(registry)
    else:
        # Empty registry when no tools_path provided
        tools_ns = ToolsNamespace(ToolRegistry())

    artifact_store = storage.get_artifact_store()

    # Create deps namespace
    deps_store = FileDepsStore(base_path)
    installer = PackageInstaller()
    deps_ns = DepsNamespace(deps_store, installer)

    # SkillsNamespace needs a namespace dict for skill execution
    # Create the dict first, wire up after creation
    namespace_dict: dict[str, Any] = {}
    skills_ns = SkillsNamespace(storage.get_skill_library(), namespace_dict)

    # Wire up circular references
    namespace_dict["tools"] = tools_ns
    namespace_dict["skills"] = skills_ns
    namespace_dict["artifacts"] = artifact_store
    namespace_dict["deps"] = deps_ns

    return NamespaceBundle(
        tools=tools_ns,
        skills=skills_ns,
        artifacts=artifact_store,
        deps=deps_ns,
    )


async def _bootstrap_redis_storage(config: dict[str, Any]) -> NamespaceBundle:
    """Bootstrap namespaces from RedisStorage config.

    Args:
        config: Dict with url, prefix, and optional tools_path keys.

    Returns:
        NamespaceBundle with Redis-based storage.

    Raises:
        KeyError: If url or prefix is missing.
    """
    # Import lazily to avoid circular imports
    from py_code_mode.deps import DepsNamespace, PackageInstaller, RedisDepsStore
    from py_code_mode.execution.in_process.skills_namespace import SkillsNamespace
    from py_code_mode.storage import RedisStorage
    from py_code_mode.tools import ToolRegistry, ToolsNamespace

    url = config["url"]
    prefix = config["prefix"]

    # Connect to Redis
    storage = RedisStorage(url=url, prefix=prefix)

    # Tools are owned by executor, loaded from config if provided
    tools_path_str = config.get("tools_path")
    if tools_path_str:
        tools_path = Path(tools_path_str)
        registry = ToolRegistry()
        await registry.load_from_directory(tools_path)
        tools_ns = ToolsNamespace(registry)
    else:
        # Empty registry when no tools_path provided
        tools_ns = ToolsNamespace(ToolRegistry())

    artifact_store = storage.get_artifact_store()

    # Create deps namespace
    deps_store = RedisDepsStore(storage.client, prefix=f"{prefix}:deps")
    installer = PackageInstaller()
    deps_ns = DepsNamespace(deps_store, installer)

    # SkillsNamespace needs a namespace dict for skill execution
    namespace_dict: dict[str, Any] = {}
    skills_ns = SkillsNamespace(storage.get_skill_library(), namespace_dict)

    # Wire up circular references
    namespace_dict["tools"] = tools_ns
    namespace_dict["skills"] = skills_ns
    namespace_dict["artifacts"] = artifact_store
    namespace_dict["deps"] = deps_ns

    return NamespaceBundle(
        tools=tools_ns,
        skills=skills_ns,
        artifacts=artifact_store,
        deps=deps_ns,
    )
