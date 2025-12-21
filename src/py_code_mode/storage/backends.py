"""Unified storage backend protocol for tools, skills, and artifacts.

This module provides a protocol that unifies storage of all three resource types
under a single interface, enabling swapping between FileStorage and RedisStorage.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from py_code_mode.artifacts import ArtifactStoreProtocol, FileArtifactStore, RedisArtifactStore
from py_code_mode.errors import StorageReadError, StorageWriteError
from py_code_mode.skills import (
    FileSkillStore,
    PythonSkill,
    RedisSkillStore,
    SkillLibrary,
    SkillStore,
    create_skill_library,
)
from py_code_mode.storage.redis_tools import RedisToolStore
from py_code_mode.tools.adapters.base import ToolAdapter

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from redis import Redis


def _tool_to_dict(tool: Any) -> dict[str, Any]:
    """Convert Tool object to dict."""
    from py_code_mode.tools import Tool

    if not isinstance(tool, Tool):
        return {}
    params = {}
    for callable_obj in tool.callables:
        for param in callable_obj.parameters:
            params[param.name] = param.description or param.type
    return {
        "name": tool.name,
        "description": tool.description,
        "params": params,
    }


def _skill_to_dict(skill: PythonSkill) -> dict[str, Any]:
    """Convert PythonSkill to dict."""
    params = {}
    for p in skill.parameters:
        params[p.name] = p.description or p.type
    return {
        "name": skill.name,
        "description": skill.description,
        "params": params,
    }


@runtime_checkable
class ToolStore(Protocol):
    """Protocol for tool storage sub-component."""

    def list(self) -> list[dict[str, Any]]:
        """List all tools."""
        ...

    def get(self, name: str) -> dict[str, Any] | None:
        """Get tool by name."""
        ...

    def save(self, tool: dict[str, Any]) -> None:
        """Save tool configuration."""
        ...

    def delete(self, name: str) -> bool:
        """Delete tool. Returns True if deleted."""
        ...

    def exists(self, name: str) -> bool:
        """Check if tool exists."""
        ...

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search tools by query."""
        ...


@runtime_checkable
class SkillStoreWrapperProtocol(Protocol):
    """Protocol for skill storage sub-component."""

    def list(self) -> list[dict[str, Any]]:
        """List all skills."""
        ...

    def get(self, name: str) -> dict[str, Any] | None:
        """Get skill by name."""
        ...

    def save(self, skill: dict[str, Any] | PythonSkill) -> None:
        """Save skill."""
        ...

    def delete(self, name: str) -> bool:
        """Delete skill. Returns True if deleted."""
        ...

    def exists(self, name: str) -> bool:
        """Check if skill exists."""
        ...

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search skills by query."""
        ...

    def create(self, name: str, description: str, source: str) -> dict[str, Any]:
        """Create a new skill."""
        ...


@runtime_checkable
class ArtifactStoreWrapperProtocol(Protocol):
    """Protocol for artifact storage sub-component."""

    def list(self) -> list[Any]:
        """List all artifacts."""
        ...

    def load(self, name: str) -> Any:
        """Load artifact by name."""
        ...

    def save(
        self,
        name: str,
        data: Any,
        description: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Save artifact."""
        ...

    def delete(self, name: str) -> bool:
        """Delete artifact. Returns True if deleted."""
        ...

    def exists(self, name: str) -> bool:
        """Check if artifact exists."""
        ...


@runtime_checkable
class StorageBackend(Protocol):
    """Protocol for unified storage backend.

    Provides tools, skills, and artifacts storage under a single interface.
    """

    @property
    def tools(self) -> ToolStore:
        """Tool storage interface."""
        ...

    @property
    def skills(self) -> SkillStoreWrapperProtocol:
        """Skill storage interface."""
        ...

    @property
    def artifacts(self) -> ArtifactStoreWrapperProtocol:
        """Artifact storage interface."""
        ...


class SkillStoreWrapper:
    """Wraps any SkillStore with search, lazy loading, and dict conversion."""

    def __init__(self, store: SkillStore) -> None:
        self._store = store
        self._library: SkillLibrary | None = None

    def _get_library(self) -> SkillLibrary:
        """Lazy-load skill library with embeddings."""
        if self._library is None:
            try:
                self._library = create_skill_library(store=self._store)
            except ImportError:
                logger.warning(
                    "Semantic search dependencies not available, falling back to MockEmbedder. "
                    "Install with: pip install sentence-transformers scikit-learn"
                )
                from py_code_mode.skills import MockEmbedder, SkillLibrary

                self._library = SkillLibrary(embedder=MockEmbedder(), store=self._store)
        return self._library

    def list(self) -> list[dict[str, Any]]:
        """List all skills."""
        library = self._get_library()
        skills = library.list()
        return [_skill_to_dict(s) for s in skills]

    def get(self, name: str) -> dict[str, Any] | None:
        """Get skill by name."""
        library = self._get_library()
        skill = library.get(name)
        if skill is None:
            return None
        return _skill_to_dict(skill)

    def save(self, skill: dict[str, Any] | PythonSkill) -> None:
        """Save skill."""
        if isinstance(skill, dict):
            skill = PythonSkill.from_source(
                name=skill["name"],
                source=skill["source"],
                description=skill.get("description", ""),
            )
        library = self._get_library()
        library.add(skill)

    def delete(self, name: str) -> bool:
        """Delete skill."""
        library = self._get_library()
        return library.remove(name)

    def exists(self, name: str) -> bool:
        """Check if skill exists."""
        return self._store.exists(name)

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search skills by query."""
        library = self._get_library()
        skills = library.search(query, limit=limit)
        return [_skill_to_dict(s) for s in skills]

    def create(self, name: str, description: str, source: str) -> dict[str, Any]:
        """Create a new skill."""
        skill = PythonSkill.from_source(name=name, source=source, description=description)
        library = self._get_library()
        library.add(skill)
        return _skill_to_dict(skill)


class ArtifactStoreWrapper:
    """Wraps any ArtifactStoreProtocol with dict conversion and error handling."""

    def __init__(self, store: ArtifactStoreProtocol) -> None:
        self._store = store

    def list(self) -> list[dict[str, Any]]:
        """List all artifacts."""
        artifacts = self._store.list()
        return [
            {
                "name": a.name,
                "path": a.path,
                "description": a.description,
                "metadata": a.metadata,
                "created_at": a.created_at.isoformat(),
            }
            for a in artifacts
        ]

    def load(self, name: str) -> Any:
        """Load artifact by name."""
        from py_code_mode.errors import ArtifactNotFoundError

        try:
            return self._store.load(name)
        except ArtifactNotFoundError:
            return None
        except OSError as e:
            logger.error(f"Failed to load artifact '{name}': {e}")
            raise StorageReadError(f"Failed to load artifact '{name}': {e}") from e

    def save(
        self,
        name: str,
        data: Any,
        description: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Save artifact."""
        self._store.save(name, data, description, metadata)

    def delete(self, name: str) -> bool:
        """Delete artifact."""
        if not self._store.exists(name):
            return False
        try:
            self._store.delete(name)
            return True
        except OSError as e:
            logger.error(f"Failed to delete artifact '{name}': {e}")
            raise StorageWriteError(f"Failed to delete artifact '{name}': {e}") from e

    def exists(self, name: str) -> bool:
        """Check if artifact exists."""
        return self._store.exists(name)


class FileToolStore:
    """File-based tool store wrapper."""

    def __init__(self, base_path: Path) -> None:
        self._base_path = base_path
        self._tools_path = base_path / "tools"
        self._tools_path.mkdir(parents=True, exist_ok=True)
        self._adapter: Any = None  # CLIAdapter

    def _get_adapter(self) -> Any:
        """Lazy-load CLIAdapter from files."""
        if self._adapter is None:
            from py_code_mode.tools.adapters.cli import CLIAdapter

            self._adapter = CLIAdapter(tools_path=self._tools_path)
        return self._adapter

    def _get_tools(self) -> list[Any]:
        """Get list of Tool objects from adapter."""
        adapter = self._get_adapter()
        if isinstance(adapter, ToolAdapter):
            return adapter.list_tools()
        return []

    def list(self) -> list[dict[str, Any]]:
        """List all tools."""
        tools = self._get_tools()
        return [_tool_to_dict(t) for t in tools]

    def get(self, name: str) -> dict[str, Any] | None:
        """Get tool by name."""
        tools = self._get_tools()
        for tool in tools:
            if tool.name == name:
                return _tool_to_dict(tool)
        return None

    def save(self, tool: dict[str, Any]) -> None:
        """Save tool configuration."""
        import yaml

        tool_file = self._tools_path / f"{tool['name']}.yaml"
        tool_file.write_text(yaml.dump(tool))
        # Invalidate adapter cache
        self._adapter = None

    def delete(self, name: str) -> bool:
        """Delete tool."""
        tool_file = self._tools_path / f"{name}.yaml"
        if tool_file.exists():
            tool_file.unlink()
            # Invalidate adapter cache
            self._adapter = None
            return True
        return False

    def exists(self, name: str) -> bool:
        """Check if tool exists."""
        tool_file = self._tools_path / f"{name}.yaml"
        return tool_file.exists()

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search tools by query."""
        from py_code_mode.tools.registry import substring_search

        tools = self._get_tools()
        matches = substring_search(
            query=query,
            items=tools,
            get_name=lambda t: t.name,
            get_description=lambda t: t.description,
            limit=limit,
        )
        return [_tool_to_dict(t) for t in matches]


class FileStorage:
    """File-based storage using directories for tools, skills, and artifacts."""

    def __init__(self, base_path: Path | str) -> None:
        """Initialize file storage.

        Args:
            base_path: Base directory for storage. Will create tools/, skills/, artifacts/ subdirs.
        """
        self._base_path = Path(base_path) if isinstance(base_path, str) else base_path
        self._base_path.mkdir(parents=True, exist_ok=True)

        # Lazy-initialized stores
        self._tools_store: FileToolStore | None = None
        self._skills_wrapper: SkillStoreWrapper | None = None
        self._artifacts_wrapper: ArtifactStoreWrapper | None = None

    @property
    def root(self) -> Path:
        """Get the root storage path."""
        return self._base_path

    @property
    def tools(self) -> ToolStore:
        """Tool storage interface."""
        if self._tools_store is None:
            self._tools_store = FileToolStore(self._base_path)
        return self._tools_store

    @property
    def skills(self) -> SkillStoreWrapper:
        """Skill storage interface."""
        if self._skills_wrapper is None:
            skills_path = self._base_path / "skills"
            skills_path.mkdir(parents=True, exist_ok=True)
            raw_store = FileSkillStore(skills_path)
            self._skills_wrapper = SkillStoreWrapper(raw_store)
        return self._skills_wrapper

    @property
    def artifacts(self) -> ArtifactStoreWrapper:
        """Artifact storage interface."""
        if self._artifacts_wrapper is None:
            artifacts_path = self._base_path / "artifacts"
            artifacts_path.mkdir(parents=True, exist_ok=True)
            raw_store = FileArtifactStore(artifacts_path)
            self._artifacts_wrapper = ArtifactStoreWrapper(raw_store)
        return self._artifacts_wrapper


class RedisToolStoreWrapper:
    """Redis-based tool store wrapper."""

    def __init__(self, redis: Redis, prefix: str) -> None:
        self._store = RedisToolStore(redis, prefix=f"{prefix}:tools")
        self._adapter: Any = None  # CLIAdapter

    def _get_adapter(self) -> Any:
        """Lazy-load CLIAdapter from Redis configs."""
        if self._adapter is None:
            from py_code_mode.tools.adapters.cli import CLIAdapter

            configs = list(self._store.list().values())
            if configs:
                self._adapter = CLIAdapter.from_configs(configs)
            else:
                self._adapter = CLIAdapter()  # Empty adapter
        return self._adapter

    def _get_tools(self) -> list[Any]:
        """Get list of Tool objects from adapter."""
        adapter = self._get_adapter()
        if isinstance(adapter, ToolAdapter):
            return adapter.list_tools()
        return []

    def list(self) -> list[dict[str, Any]]:
        """List all tools."""
        tools = self._get_tools()
        return [_tool_to_dict(t) for t in tools]

    def get(self, name: str) -> dict[str, Any] | None:
        """Get tool by name."""
        config = self._store.get(name)
        if config is None:
            return None
        return config

    def save(self, tool: dict[str, Any]) -> None:
        """Save tool configuration."""
        self._store.add(tool["name"], tool)
        # Invalidate adapter cache
        self._adapter = None

    def delete(self, name: str) -> bool:
        """Delete tool."""
        result = self._store.remove(name)
        if result:
            # Invalidate adapter cache
            self._adapter = None
        return result

    def exists(self, name: str) -> bool:
        """Check if tool exists."""
        return self._store.get(name) is not None

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search tools by query."""
        from py_code_mode.tools.registry import substring_search

        tools = self._get_tools()
        matches = substring_search(
            query=query,
            items=tools,
            get_name=lambda t: t.name,
            get_description=lambda t: t.description,
            limit=limit,
        )
        return [_tool_to_dict(t) for t in matches]


class RedisStorage:
    """Redis-based storage for tools, skills, and artifacts."""

    def __init__(self, redis: Redis, prefix: str = "py_code_mode") -> None:
        """Initialize Redis storage.

        Args:
            redis: Redis client instance.
            prefix: Key prefix for all storage. Default: "py_code_mode"
        """
        self._redis = redis
        self._prefix = prefix

        # Lazy-initialized stores
        self._tools_store: RedisToolStoreWrapper | None = None
        self._skills_wrapper: SkillStoreWrapper | None = None
        self._artifacts_wrapper: ArtifactStoreWrapper | None = None

    @property
    def prefix(self) -> str:
        """Get the configured prefix."""
        return self._prefix

    @property
    def client(self) -> Redis:
        """Get the Redis client."""
        return self._redis

    @property
    def tools(self) -> ToolStore:
        """Tool storage interface."""
        if self._tools_store is None:
            self._tools_store = RedisToolStoreWrapper(self._redis, self._prefix)
        return self._tools_store

    @property
    def skills(self) -> SkillStoreWrapper:
        """Skill storage interface."""
        if self._skills_wrapper is None:
            raw_store = RedisSkillStore(self._redis, prefix=f"{self._prefix}:skills")
            self._skills_wrapper = SkillStoreWrapper(raw_store)
        return self._skills_wrapper

    @property
    def artifacts(self) -> ArtifactStoreWrapper:
        """Artifact storage interface."""
        if self._artifacts_wrapper is None:
            raw_store = RedisArtifactStore(self._redis, prefix=f"{self._prefix}:artifacts")
            self._artifacts_wrapper = ArtifactStoreWrapper(raw_store)
        return self._artifacts_wrapper
