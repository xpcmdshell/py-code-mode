"""Unified storage backend protocol for tools, skills, and artifacts.

This module provides a protocol that unifies storage of all three resource types
under a single interface, enabling swapping between FileStorage and RedisStorage.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable
from urllib.parse import quote

from py_code_mode.artifacts import ArtifactStoreProtocol, FileArtifactStore, RedisArtifactStore
from py_code_mode.deps import DepsNamespace, FileDepsStore, PackageInstaller, RedisDepsStore
from py_code_mode.execution.protocol import FileStorageAccess, RedisStorageAccess
from py_code_mode.skills import (
    FileSkillStore,
    RedisSkillStore,
    SkillLibrary,
    SkillStore,
    create_skill_library,
)
from py_code_mode.storage.redis_tools import RedisToolStore

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from redis import Redis

    from py_code_mode.tools import ToolRegistry


@runtime_checkable
class StorageBackend(Protocol):
    """Protocol for unified storage backend.

    Provides tools, skills, and artifacts storage under a single interface.
    """

    def get_serializable_access(self) -> FileStorageAccess | RedisStorageAccess:
        """Return serializable access descriptor for cross-process communication.

        Used by executors that run in separate processes and need
        connection info rather than direct object references.
        """
        ...

    async def get_tool_registry(self) -> ToolRegistry:
        """Return ToolRegistry for in-process execution.

        This method is async because MCP tools require async initialization
        (connecting to MCP servers). CLI tools are loaded synchronously within
        the async method.

        This method provides a registry of tools loaded from storage for executors.
        """
        ...

    def get_skill_library(self) -> SkillLibrary:
        """Return SkillLibrary for in-process execution.

        This method provides a library of skills loaded from storage for executors.
        """
        ...

    def get_artifact_store(self) -> ArtifactStoreProtocol:
        """Return artifact store for in-process execution.

        This method provides access to the artifact store for executors.
        """
        ...

    def get_deps_namespace(self) -> DepsNamespace:
        """Return DepsNamespace for in-process execution.

        This method provides access to the deps namespace for executors.
        """
        ...


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
        self._skill_library: SkillLibrary | None = None
        self._artifact_store: FileArtifactStore | None = None
        self._deps_namespace: DepsNamespace | None = None

    @property
    def root(self) -> Path:
        """Get the root storage path."""
        return self._base_path

    def _get_tools_path(self) -> Path:
        """Get the tools directory path."""
        return self._base_path / "tools"

    def _get_skills_path(self) -> Path:
        """Get the skills directory path."""
        skills_path = self._base_path / "skills"
        skills_path.mkdir(parents=True, exist_ok=True)
        return skills_path

    def _get_artifacts_path(self) -> Path:
        """Get the artifacts directory path."""
        artifacts_path = self._base_path / "artifacts"
        artifacts_path.mkdir(parents=True, exist_ok=True)
        return artifacts_path

    def get_serializable_access(self) -> FileStorageAccess:
        """Return FileStorageAccess for cross-process communication."""
        base_path = self._base_path
        tools_path = base_path / "tools"
        deps_path = base_path / "deps"
        # Ensure deps directory exists for volume mount
        deps_path.mkdir(parents=True, exist_ok=True)

        return FileStorageAccess(
            tools_path=tools_path if tools_path.exists() else None,
            skills_path=base_path / "skills",
            artifacts_path=base_path / "artifacts",
            deps_path=deps_path,
        )

    async def get_tool_registry(self) -> ToolRegistry:
        """Return ToolRegistry for in-process execution.

        Uses ToolRegistry.from_dir() to load both CLI and MCP tools from
        the tools directory. This is async because MCP tools require
        async initialization.
        """
        from py_code_mode.tools import ToolRegistry

        tools_path = self._get_tools_path()
        if tools_path.exists():
            return await ToolRegistry.from_dir(str(tools_path))
        return ToolRegistry()

    def get_skill_library(self) -> SkillLibrary:
        """Return SkillLibrary for in-process execution."""
        if self._skill_library is None:
            skills_path = self._get_skills_path()
            raw_store = FileSkillStore(skills_path)
            try:
                self._skill_library = create_skill_library(store=raw_store)
            except ImportError:
                logger.warning(
                    "Semantic search dependencies not available, falling back to MockEmbedder. "
                    "Install with: pip install sentence-transformers scikit-learn"
                )
                from py_code_mode.skills import MockEmbedder

                self._skill_library = SkillLibrary(embedder=MockEmbedder(), store=raw_store)
        return self._skill_library

    def get_artifact_store(self) -> ArtifactStoreProtocol:
        """Return artifact store for in-process execution."""
        if self._artifact_store is None:
            self._artifact_store = FileArtifactStore(self._get_artifacts_path())
        return self._artifact_store

    def get_skill_store(self) -> SkillStore:
        """Return the underlying SkillStore for direct access."""
        skills_path = self._get_skills_path()
        return FileSkillStore(skills_path)

    def get_deps_store(self) -> FileDepsStore:
        """Return FileDepsStore for pre-configuring dependencies.

        This allows adding dependencies before session start:
            storage.get_deps_store().add("pandas")
            storage.get_deps_store().add("numpy")
            Session(storage=storage, sync_deps_on_start=True)

        Returns:
            FileDepsStore instance backed by this storage's base path.
        """
        return FileDepsStore(self._base_path)

    def get_deps_namespace(self) -> DepsNamespace:
        """Return DepsNamespace for in-process execution."""
        if self._deps_namespace is None:
            deps_store = FileDepsStore(self._base_path)
            installer = PackageInstaller()
            self._deps_namespace = DepsNamespace(store=deps_store, installer=installer)
        return self._deps_namespace

    def to_bootstrap_config(self) -> dict[str, str]:
        """Serialize storage configuration for subprocess bootstrap.

        Returns:
            Dict with type="file" and base_path as string.
            This config can be passed to bootstrap_namespaces() to reconstruct
            the storage in a subprocess.
        """
        return {
            "type": "file",
            "base_path": str(self._base_path),
        }


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
        self._tool_store: RedisToolStore | None = None
        self._skill_library: SkillLibrary | None = None
        self._artifact_store: RedisArtifactStore | None = None
        self._deps_namespace: DepsNamespace | None = None

    @property
    def prefix(self) -> str:
        """Get the configured prefix."""
        return self._prefix

    @property
    def client(self) -> Redis:
        """Get the Redis client."""
        return self._redis

    def _get_tool_store(self) -> RedisToolStore:
        """Get the Redis tool store."""
        if self._tool_store is None:
            self._tool_store = RedisToolStore(self._redis, prefix=f"{self._prefix}:tools")
        return self._tool_store

    def get_serializable_access(self) -> RedisStorageAccess:
        """Return RedisStorageAccess for cross-process communication."""
        # Reconstruct Redis URL from client connection
        pool = self._redis.connection_pool
        kwargs = pool.connection_kwargs
        host = kwargs.get("host", "localhost")
        port = kwargs.get("port", 6379)
        db = kwargs.get("db", 0)
        username = kwargs.get("username")
        password = kwargs.get("password")

        if username and password:
            encoded_user = quote(username, safe="")
            encoded_pass = quote(password, safe="")
            redis_url = f"redis://{encoded_user}:{encoded_pass}@{host}:{port}/{db}"
        elif password:
            redis_url = f"redis://:{quote(password, safe='')}@{host}:{port}/{db}"
        else:
            redis_url = f"redis://{host}:{port}/{db}"

        prefix = self._prefix
        return RedisStorageAccess(
            redis_url=redis_url,
            tools_prefix=f"{prefix}:tools",
            skills_prefix=f"{prefix}:skills",
            artifacts_prefix=f"{prefix}:artifacts",
            deps_prefix=f"{prefix}:deps",
        )

    async def get_tool_registry(self) -> ToolRegistry:
        """Return ToolRegistry for in-process execution.

        Uses registry_from_redis() to load both CLI and MCP tools from
        Redis. This is async because MCP tools require async initialization.
        """
        from py_code_mode.storage.redis_tools import registry_from_redis

        tool_store = self._get_tool_store()
        return await registry_from_redis(tool_store)

    def get_skill_library(self) -> SkillLibrary:
        """Return SkillLibrary for in-process execution."""
        if self._skill_library is None:
            raw_store = RedisSkillStore(self._redis, prefix=f"{self._prefix}:skills")
            try:
                self._skill_library = create_skill_library(store=raw_store)
            except ImportError:
                logger.warning(
                    "Semantic search dependencies not available, falling back to MockEmbedder. "
                    "Install with: pip install sentence-transformers scikit-learn"
                )
                from py_code_mode.skills import MockEmbedder

                self._skill_library = SkillLibrary(embedder=MockEmbedder(), store=raw_store)
        return self._skill_library

    def get_artifact_store(self) -> ArtifactStoreProtocol:
        """Return artifact store for in-process execution."""
        if self._artifact_store is None:
            self._artifact_store = RedisArtifactStore(
                self._redis, prefix=f"{self._prefix}:artifacts"
            )
        return self._artifact_store

    def get_skill_store(self) -> SkillStore:
        """Return the underlying SkillStore for direct access."""
        return RedisSkillStore(self._redis, prefix=f"{self._prefix}:skills")

    def get_deps_store(self) -> RedisDepsStore:
        """Return RedisDepsStore for pre-configuring dependencies.

        This allows adding dependencies before session start:
            storage.get_deps_store().add("pandas")
            storage.get_deps_store().add("numpy")
            Session(storage=storage, sync_deps_on_start=True)

        Returns:
            RedisDepsStore instance for this storage.
        """
        return RedisDepsStore(self._redis, prefix=f"{self._prefix}:deps")

    def get_deps_namespace(self) -> DepsNamespace:
        """Return DepsNamespace for in-process execution."""
        if self._deps_namespace is None:
            deps_store = RedisDepsStore(self._redis, prefix=f"{self._prefix}:deps")
            installer = PackageInstaller()
            self._deps_namespace = DepsNamespace(store=deps_store, installer=installer)
        return self._deps_namespace

    def to_bootstrap_config(self) -> dict[str, str]:
        """Serialize storage configuration for subprocess bootstrap.

        Returns:
            Dict with type="redis", url, and prefix.
            This config can be passed to bootstrap_namespaces() to reconstruct
            the storage in a subprocess.
        """
        # Reconstruct Redis URL from client connection pool
        pool = self._redis.connection_pool
        kwargs = pool.connection_kwargs
        host = kwargs.get("host", "localhost")
        port = kwargs.get("port", 6379)
        db = kwargs.get("db", 0)
        username = kwargs.get("username")
        password = kwargs.get("password")

        if username and password:
            encoded_user = quote(username, safe="")
            encoded_pass = quote(password, safe="")
            redis_url = f"redis://{encoded_user}:{encoded_pass}@{host}:{port}/{db}"
        elif password:
            redis_url = f"redis://:{quote(password, safe='')}@{host}:{port}/{db}"
        else:
            redis_url = f"redis://{host}:{port}/{db}"

        return {
            "type": "redis",
            "url": redis_url,
            "prefix": self._prefix,
        }
