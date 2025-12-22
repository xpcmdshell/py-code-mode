"""Bootstrap module for reconstructing storage and namespaces in subprocesses.

This module provides the core primitives for SubprocessExecutor to reconstruct
storage backends and their associated namespaces without knowing about specific
storage implementations. The pattern is:

1. Storage classes implement `to_bootstrap_config()` returning a JSON-serializable dict
2. This dict is passed to the subprocess
3. `bootstrap_namespaces(config)` reconstructs the storage and creates namespaces

This keeps the executor decoupled from storage implementations.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from py_code_mode.artifacts import ArtifactStoreProtocol
    from py_code_mode.execution.in_process.skills_namespace import SkillsNamespace
    from py_code_mode.tools import ToolsNamespace


@dataclass
class NamespaceBundle:
    """Container for reconstructed namespaces.

    Provides the three namespaces needed for code execution:
    - tools: ToolsNamespace for tool access
    - skills: SkillsNamespace for skill access
    - artifacts: ArtifactStoreProtocol for artifact storage
    """

    tools: ToolsNamespace
    skills: SkillsNamespace
    artifacts: ArtifactStoreProtocol


def bootstrap_namespaces(config: dict[str, Any]) -> NamespaceBundle:
    """Reconstruct storage and namespaces from serialized config.

    Args:
        config: Dict with "type" key ("file" or "redis") and type-specific fields.
                - For "file": {"type": "file", "base_path": str}
                - For "redis": {"type": "redis", "url": str, "prefix": str}

    Returns:
        NamespaceBundle with tools, skills, artifacts namespaces.

    Raises:
        ValueError: If config["type"] is unknown or missing.
        KeyError: If required fields are missing for the storage type.
    """
    storage_type = config.get("type")

    if storage_type == "file":
        return _bootstrap_file_storage(config)
    elif storage_type == "redis":
        return _bootstrap_redis_storage(config)
    else:
        raise ValueError(f"Unknown storage type: {storage_type!r}. Expected 'file' or 'redis'.")


def _bootstrap_file_storage(config: dict[str, Any]) -> NamespaceBundle:
    """Bootstrap namespaces from FileStorage config.

    Args:
        config: Dict with base_path key.

    Returns:
        NamespaceBundle with file-based storage.

    Raises:
        KeyError: If base_path is missing.
    """
    # Import lazily to avoid circular imports
    from py_code_mode.execution.in_process.skills_namespace import SkillsNamespace
    from py_code_mode.storage import FileStorage
    from py_code_mode.tools import ToolsNamespace

    base_path = Path(config["base_path"])
    storage = FileStorage(base_path)

    # Create namespaces
    tools_ns = ToolsNamespace(storage.get_tool_registry())
    artifact_store = storage.get_artifact_store()

    # SkillsNamespace needs a namespace dict for skill execution
    # Create the dict first, wire up after creation
    namespace_dict: dict[str, Any] = {}
    skills_ns = SkillsNamespace(storage.get_skill_library(), namespace_dict)

    # Wire up circular references
    namespace_dict["tools"] = tools_ns
    namespace_dict["skills"] = skills_ns
    namespace_dict["artifacts"] = artifact_store

    return NamespaceBundle(
        tools=tools_ns,
        skills=skills_ns,
        artifacts=artifact_store,
    )


def _bootstrap_redis_storage(config: dict[str, Any]) -> NamespaceBundle:
    """Bootstrap namespaces from RedisStorage config.

    Args:
        config: Dict with url and prefix keys.

    Returns:
        NamespaceBundle with Redis-based storage.

    Raises:
        KeyError: If url or prefix is missing.
    """
    # Import lazily to avoid circular imports
    import redis

    from py_code_mode.execution.in_process.skills_namespace import SkillsNamespace
    from py_code_mode.storage import RedisStorage
    from py_code_mode.tools import ToolsNamespace

    url = config["url"]
    prefix = config["prefix"]

    # Connect to Redis
    redis_client = redis.from_url(url)
    storage = RedisStorage(redis_client, prefix=prefix)

    # Create namespaces
    tools_ns = ToolsNamespace(storage.get_tool_registry())
    artifact_store = storage.get_artifact_store()

    # SkillsNamespace needs a namespace dict for skill execution
    namespace_dict: dict[str, Any] = {}
    skills_ns = SkillsNamespace(storage.get_skill_library(), namespace_dict)

    # Wire up circular references
    namespace_dict["tools"] = tools_ns
    namespace_dict["skills"] = skills_ns
    namespace_dict["artifacts"] = artifact_store

    return NamespaceBundle(
        tools=tools_ns,
        skills=skills_ns,
        artifacts=artifact_store,
    )
