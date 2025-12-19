"""Unified storage backend protocol for tools, skills, and artifacts.

This module provides a protocol that unifies storage of all three resource types
under a single interface, enabling swapping between FileStorage and RedisStorage.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from py_code_mode.artifacts import FileArtifactStore
from py_code_mode.redis_artifacts import RedisArtifactStore
from py_code_mode.redis_tools import RedisToolStore, registry_from_redis
from py_code_mode.registry import ToolRegistry
from py_code_mode.semantic import SkillLibrary, create_skill_library
from py_code_mode.skill_store import FileSkillStore, RedisSkillStore, SkillStore
from py_code_mode.skills import PythonSkill

if TYPE_CHECKING:
    from redis import Redis


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
class SkillStoreProtocol(Protocol):
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
class ArtifactStoreWrapper(Protocol):
    """Protocol for artifact storage sub-component."""

    def list(self) -> list[Any]:
        """List all artifacts."""
        ...

    def load(self, name: str) -> Any:
        """Load artifact by name."""
        ...

    def save(
        self, name: str, data: Any, description: str, metadata: dict[str, Any] | None = None
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
    def skills(self) -> SkillStoreProtocol:
        """Skill storage interface."""
        ...

    @property
    def artifacts(self) -> ArtifactStoreWrapper:
        """Artifact storage interface."""
        ...


class FileToolStore:
    """File-based tool store wrapper."""

    def __init__(self, base_path: Path) -> None:
        self._base_path = base_path
        self._tools_path = base_path / "tools"
        self._tools_path.mkdir(parents=True, exist_ok=True)
        self._registry: ToolRegistry | None = None

    async def _get_registry(self) -> ToolRegistry:
        """Lazy-load registry from files."""
        if self._registry is None:
            self._registry = await ToolRegistry.from_dir(str(self._tools_path))
        return self._registry

    def list(self) -> list[dict[str, Any]]:
        """List all tools."""
        import asyncio

        registry = asyncio.run(self._get_registry())
        tools = registry.list_tools()
        return [self._tool_to_dict(t) for t in tools]

    def get(self, name: str) -> dict[str, Any] | None:
        """Get tool by name."""
        import asyncio

        registry = asyncio.run(self._get_registry())
        try:
            tool = registry.get_tool(name)
            return self._tool_to_dict(tool)
        except Exception:
            return None

    def save(self, tool: dict[str, Any]) -> None:
        """Save tool configuration."""
        import yaml

        tool_file = self._tools_path / f"{tool['name']}.yaml"
        tool_file.write_text(yaml.dump(tool))
        # Invalidate registry cache
        self._registry = None

    def delete(self, name: str) -> bool:
        """Delete tool."""
        tool_file = self._tools_path / f"{name}.yaml"
        if tool_file.exists():
            tool_file.unlink()
            # Invalidate registry cache
            self._registry = None
            return True
        return False

    def exists(self, name: str) -> bool:
        """Check if tool exists."""
        tool_file = self._tools_path / f"{name}.yaml"
        return tool_file.exists()

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search tools by query."""
        import asyncio

        registry = asyncio.run(self._get_registry())
        tools = registry.search(query, limit=limit)
        return [self._tool_to_dict(t) for t in tools]

    @staticmethod
    def _tool_to_dict(tool: Any) -> dict[str, Any]:
        """Convert tool definition to dict."""
        params = {}
        if tool.input_schema and tool.input_schema.properties:
            for name, schema in tool.input_schema.properties.items():
                params[name] = schema.description or schema.type
        return {
            "name": tool.name,
            "description": tool.description,
            "params": params,
        }


class FileSkillStoreWrapper:
    """File-based skill store wrapper with search."""

    def __init__(self, base_path: Path) -> None:
        self._base_path = base_path
        self._skills_path = base_path / "skills"
        self._skills_path.mkdir(parents=True, exist_ok=True)
        self._store: SkillStore = FileSkillStore(self._skills_path)
        self._library: SkillLibrary | None = None

    def _get_library(self) -> SkillLibrary:
        """Lazy-load skill library."""
        if self._library is None:
            try:
                self._library = create_skill_library(store=self._store)
            except ImportError:
                # Semantic search not available, use basic store
                from py_code_mode.semantic import MockEmbedder, SkillLibrary

                self._library = SkillLibrary(embedder=MockEmbedder(), store=self._store)
        return self._library

    def list(self) -> list[dict[str, Any]]:
        """List all skills."""
        library = self._get_library()
        skills = library.list()
        return [self._skill_to_dict(s) for s in skills]

    def get(self, name: str) -> dict[str, Any] | None:
        """Get skill by name."""
        library = self._get_library()
        skill = library.get(name)
        if skill is None:
            return None
        return self._skill_to_dict(skill)

    def save(self, skill: dict[str, Any] | PythonSkill) -> None:
        """Save skill."""
        if isinstance(skill, dict):
            # Convert dict to PythonSkill
            skill = PythonSkill.from_source(
                name=skill["name"], source=skill["source"], description=skill.get("description", "")
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
        return [self._skill_to_dict(s) for s in skills]

    def create(self, name: str, description: str, source: str) -> dict[str, Any]:
        """Create a new skill."""
        skill = PythonSkill.from_source(name=name, source=source, description=description)
        library = self._get_library()
        library.add(skill)
        return self._skill_to_dict(skill)

    @staticmethod
    def _skill_to_dict(skill: PythonSkill) -> dict[str, Any]:
        """Convert skill to dict."""
        params = {}
        for p in skill.parameters:
            params[p.name] = p.description or p.type
        return {
            "name": skill.name,
            "description": skill.description,
            "params": params,
        }


class FileArtifactStoreWrapper:
    """File-based artifact store wrapper."""

    def __init__(self, store: FileArtifactStore) -> None:
        self._store = store

    def list(self) -> list[Any]:
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
        try:
            return self._store.load(name)
        except Exception:
            return None

    def save(
        self, name: str, data: Any, description: str, metadata: dict[str, Any] | None = None
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
        except Exception:
            return False

    def exists(self, name: str) -> bool:
        """Check if artifact exists."""
        return self._store.exists(name)


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
        self._skills_store: FileSkillStoreWrapper | None = None
        self._artifacts_store: FileArtifactStoreWrapper | None = None

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
    def skills(self) -> SkillStoreProtocol:
        """Skill storage interface."""
        if self._skills_store is None:
            self._skills_store = FileSkillStoreWrapper(self._base_path)
        return self._skills_store

    @property
    def artifacts(self) -> ArtifactStoreWrapper:
        """Artifact storage interface."""
        if self._artifacts_store is None:
            artifacts_path = self._base_path / "artifacts"
            artifacts_path.mkdir(parents=True, exist_ok=True)
            artifact_store = FileArtifactStore(artifacts_path)
            self._artifacts_store = FileArtifactStoreWrapper(artifact_store)
        return self._artifacts_store


class RedisToolStoreWrapper:
    """Redis-based tool store wrapper."""

    def __init__(self, redis: Redis, prefix: str) -> None:
        self._store = RedisToolStore(redis, prefix=f"{prefix}:tools")
        self._registry: ToolRegistry | None = None

    async def _get_registry(self) -> ToolRegistry:
        """Lazy-load registry from Redis."""
        if self._registry is None:
            self._registry = await registry_from_redis(self._store)
        return self._registry

    def list(self) -> list[dict[str, Any]]:
        """List all tools."""
        import asyncio

        registry = asyncio.run(self._get_registry())
        tools = registry.list_tools()
        return [self._tool_to_dict(t) for t in tools]

    def get(self, name: str) -> dict[str, Any] | None:
        """Get tool by name."""
        config = self._store.get(name)
        if config is None:
            return None
        return config

    def save(self, tool: dict[str, Any]) -> None:
        """Save tool configuration."""
        self._store.add(tool["name"], tool)
        # Invalidate registry cache
        self._registry = None

    def delete(self, name: str) -> bool:
        """Delete tool."""
        result = self._store.remove(name)
        if result:
            # Invalidate registry cache
            self._registry = None
        return result

    def exists(self, name: str) -> bool:
        """Check if tool exists."""
        return self._store.get(name) is not None

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search tools by query."""
        import asyncio

        registry = asyncio.run(self._get_registry())
        tools = registry.search(query, limit=limit)
        return [self._tool_to_dict(t) for t in tools]

    @staticmethod
    def _tool_to_dict(tool: Any) -> dict[str, Any]:
        """Convert tool definition to dict."""
        params = {}
        if tool.input_schema and tool.input_schema.properties:
            for name, schema in tool.input_schema.properties.items():
                params[name] = schema.description or schema.type
        return {
            "name": tool.name,
            "description": tool.description,
            "params": params,
        }


class RedisSkillStoreWrapper:
    """Redis-based skill store wrapper with search."""

    def __init__(self, redis: Redis, prefix: str) -> None:
        self._store: SkillStore = RedisSkillStore(redis, prefix=f"{prefix}:skills")
        self._library: SkillLibrary | None = None

    def _get_library(self) -> SkillLibrary:
        """Lazy-load skill library."""
        if self._library is None:
            try:
                self._library = create_skill_library(store=self._store)
            except ImportError:
                # Semantic search not available, use basic store
                from py_code_mode.semantic import MockEmbedder, SkillLibrary

                self._library = SkillLibrary(embedder=MockEmbedder(), store=self._store)
        return self._library

    def list(self) -> list[dict[str, Any]]:
        """List all skills."""
        library = self._get_library()
        skills = library.list()
        return [self._skill_to_dict(s) for s in skills]

    def get(self, name: str) -> dict[str, Any] | None:
        """Get skill by name."""
        library = self._get_library()
        skill = library.get(name)
        if skill is None:
            return None
        return self._skill_to_dict(skill)

    def save(self, skill: dict[str, Any] | PythonSkill) -> None:
        """Save skill."""
        if isinstance(skill, dict):
            # Convert dict to PythonSkill
            skill = PythonSkill.from_source(
                name=skill["name"], source=skill["source"], description=skill.get("description", "")
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
        return [self._skill_to_dict(s) for s in skills]

    def create(self, name: str, description: str, source: str) -> dict[str, Any]:
        """Create a new skill."""
        skill = PythonSkill.from_source(name=name, source=source, description=description)
        library = self._get_library()
        library.add(skill)
        return self._skill_to_dict(skill)

    @staticmethod
    def _skill_to_dict(skill: PythonSkill) -> dict[str, Any]:
        """Convert skill to dict."""
        params = {}
        for p in skill.parameters:
            params[p.name] = p.description or p.type
        return {
            "name": skill.name,
            "description": skill.description,
            "params": params,
        }


class RedisArtifactStoreWrapper:
    """Redis-based artifact store wrapper."""

    def __init__(self, store: RedisArtifactStore) -> None:
        self._store = store

    def list(self) -> list[Any]:
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
        try:
            return self._store.load(name)
        except Exception:
            return None

    def save(
        self, name: str, data: Any, description: str, metadata: dict[str, Any] | None = None
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
        except Exception:
            return False

    def exists(self, name: str) -> bool:
        """Check if artifact exists."""
        return self._store.exists(name)


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
        self._skills_store: RedisSkillStoreWrapper | None = None
        self._artifacts_store: RedisArtifactStoreWrapper | None = None

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
    def skills(self) -> SkillStoreProtocol:
        """Skill storage interface."""
        if self._skills_store is None:
            self._skills_store = RedisSkillStoreWrapper(self._redis, self._prefix)
        return self._skills_store

    @property
    def artifacts(self) -> ArtifactStoreWrapper:
        """Artifact storage interface."""
        if self._artifacts_store is None:
            artifact_store = RedisArtifactStore(self._redis, prefix=f"{self._prefix}:artifacts")
            self._artifacts_store = RedisArtifactStoreWrapper(artifact_store)
        return self._artifacts_store
