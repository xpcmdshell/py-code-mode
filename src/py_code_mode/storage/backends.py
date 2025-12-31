"""Unified storage backend protocol for tools, skills, and artifacts.

This module provides a protocol that unifies storage of all three resource types
under a single interface, enabling swapping between FileStorage and RedisStorage.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Protocol, runtime_checkable
from urllib.parse import quote

from py_code_mode.artifacts import ArtifactStoreProtocol, FileArtifactStore, RedisArtifactStore
from py_code_mode.deps import DepsNamespace, FileDepsStore, PackageInstaller, RedisDepsStore
from py_code_mode.execution.protocol import FileStorageAccess, RedisStorageAccess
from py_code_mode.skills import (
    FileSkillStore,
    RedisSkillStore,
    SkillLibrary,
    SkillStore,
    VectorStore,
    create_skill_library,
)
from py_code_mode.storage.redis_tools import RedisToolStore

# Import ChromaVectorStore at module level for test mocking support
# The actual import in get_vector_store() handles the ImportError gracefully
try:
    from py_code_mode.skills.vector_stores.chroma import ChromaVectorStore
except ImportError:
    ChromaVectorStore = None  # type: ignore[misc, assignment]

# Import RedisVectorStore at module level for test mocking support
try:
    from py_code_mode.skills.vector_stores.redis_store import (
        REDIS_AVAILABLE as REDIS_VECTOR_AVAILABLE,
    )
    from py_code_mode.skills.vector_stores.redis_store import (
        RedisVectorStore,
    )
except ImportError:
    RedisVectorStore = None  # type: ignore[misc, assignment]
    REDIS_VECTOR_AVAILABLE = False

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

    _UNINITIALIZED: ClassVar[object] = object()

    def __init__(self, base_path: Path | str) -> None:
        """Initialize file storage.

        Args:
            base_path: Base directory for storage. Will create tools/, skills/, artifacts/ subdirs.
        """
        self._base_path = Path(base_path) if isinstance(base_path, str) else base_path
        self._base_path.mkdir(parents=True, exist_ok=True)

        # Lazy-initialized stores
        self._tool_registry: ToolRegistry | None = None
        self._skill_library: SkillLibrary | None = None
        self._artifact_store: FileArtifactStore | None = None
        self._deps_namespace: DepsNamespace | None = None
        self._vector_store: VectorStore | None | object = FileStorage._UNINITIALIZED

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

    def _get_vectors_path(self) -> Path:
        """Get the vectors directory path."""
        vectors_path = self._base_path / "vectors"
        vectors_path.mkdir(parents=True, exist_ok=True)
        return vectors_path

    def get_vector_store(self) -> VectorStore | None:
        """Return ChromaVectorStore if chromadb available, else None.

        The vector store is cached after first creation.

        Returns:
            ChromaVectorStore instance if chromadb is installed, None otherwise.
        """
        if self._vector_store is not FileStorage._UNINITIALIZED:
            return self._vector_store  # type: ignore[return-value]

        # ChromaVectorStore is imported at module level (None if chromadb unavailable)
        if ChromaVectorStore is None:
            self._vector_store = None
        else:
            try:
                from py_code_mode.skills import BackgroundEmbedder

                vectors_path = self._get_vectors_path()
                embedder = BackgroundEmbedder()
                self._vector_store = ChromaVectorStore(path=vectors_path, embedder=embedder)
            except ImportError:
                self._vector_store = None

        return self._vector_store  # type: ignore[return-value]

    def get_serializable_access(self) -> FileStorageAccess:
        """Return FileStorageAccess for cross-process communication."""
        base_path = self._base_path
        tools_path = base_path / "tools"
        deps_path = base_path / "deps"
        vectors_path = base_path / "vectors"
        # Ensure deps directory exists for volume mount
        deps_path.mkdir(parents=True, exist_ok=True)

        return FileStorageAccess(
            tools_path=tools_path if tools_path.exists() else None,
            skills_path=base_path / "skills",
            artifacts_path=base_path / "artifacts",
            deps_path=deps_path,
            vectors_path=vectors_path if vectors_path.exists() else None,
        )

    async def get_tool_registry(self) -> ToolRegistry:
        """Return ToolRegistry for in-process execution.

        Uses ToolRegistry.from_dir() to load both CLI and MCP tools from
        the tools directory. This is async because MCP tools require
        async initialization.

        The registry is cached after first load. MCP connections are bound to
        the task that first calls this method, so call from main task context
        before spawning handler tasks. New tool files require server restart.
        """
        if self._tool_registry is not None:
            return self._tool_registry

        from py_code_mode.tools import ToolRegistry

        tools_path = self._get_tools_path()
        if tools_path.exists():
            self._tool_registry = await ToolRegistry.from_dir(str(tools_path))
        else:
            self._tool_registry = ToolRegistry()
        return self._tool_registry

    def get_skill_library(self) -> SkillLibrary:
        """Return SkillLibrary for in-process execution."""
        if self._skill_library is None:
            skills_path = self._get_skills_path()
            raw_store = FileSkillStore(skills_path)
            vector_store = self.get_vector_store()
            try:
                self._skill_library = create_skill_library(
                    store=raw_store,
                    vector_store=vector_store,
                )
            except ImportError:
                logger.warning(
                    "Semantic search dependencies not available, falling back to MockEmbedder. "
                    "Install with: pip install sentence-transformers scikit-learn"
                )
                from py_code_mode.skills import MockEmbedder

                self._skill_library = SkillLibrary(
                    embedder=MockEmbedder(),
                    store=raw_store,
                    vector_store=vector_store,
                )
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

    _UNINITIALIZED: ClassVar[object] = object()

    def __init__(
        self,
        url: str | None = None,
        redis: Redis | None = None,
        prefix: str = "py_code_mode",
    ) -> None:
        """Initialize Redis storage.

        Args:
            url: Redis URL (e.g., "redis://localhost:6379" or
                "rediss://:password@host:6380"). Preferred parameter.
            redis: Redis client instance. Use for advanced configurations
                (custom connection pools, etc.). Mutually exclusive with url.
            prefix: Key prefix for all storage. Default: "py_code_mode"

        Raises:
            ValueError: If neither url nor redis is provided, or if both are.
        """
        if url is not None and redis is not None:
            raise ValueError("Provide either 'url' or 'redis', not both")
        if url is None and redis is None:
            raise ValueError("Either 'url' or 'redis' must be provided")

        if url is not None:
            from redis import Redis as RedisClient

            self._redis = RedisClient.from_url(url)
            self._url = url
        else:
            self._redis = redis
            self._url = None  # Will be reconstructed if needed

        self._prefix = prefix

        # Lazy-initialized stores
        self._tool_registry: ToolRegistry | None = None
        self._tool_store: RedisToolStore | None = None
        self._skill_library: SkillLibrary | None = None
        self._artifact_store: RedisArtifactStore | None = None
        self._deps_namespace: DepsNamespace | None = None
        self._vector_store: VectorStore | None | object = RedisStorage._UNINITIALIZED

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

    def get_vector_store(self) -> VectorStore | None:
        """Return RedisVectorStore if available, else None.

        The vector store is cached after first creation.

        Returns:
            RedisVectorStore instance if redis-py with RediSearch is available
            and semantic dependencies are installed, None otherwise.
        """
        if self._vector_store is not RedisStorage._UNINITIALIZED:
            return self._vector_store  # type: ignore[return-value]

        # RedisVectorStore is imported at module level (None if unavailable)
        if RedisVectorStore is None or not REDIS_VECTOR_AVAILABLE:
            self._vector_store = None
        else:
            try:
                from py_code_mode.skills import BackgroundEmbedder

                embedder = BackgroundEmbedder()
                self._vector_store = RedisVectorStore(
                    redis=self._redis,
                    embedder=embedder,
                    prefix=f"{self._prefix}:vectors",
                )
            except ImportError:
                self._vector_store = None
            except Exception as e:
                # RedisVectorStore requires RediSearch module and proper Redis
                # connection. If initialization fails (e.g., mock client in tests,
                # Redis without RediSearch), fall back to None.
                logger.debug(f"RedisVectorStore initialization failed: {e}")
                self._vector_store = None

        return self._vector_store  # type: ignore[return-value]

    def get_serializable_access(self) -> RedisStorageAccess:
        """Return RedisStorageAccess for cross-process communication."""
        # Use stored URL if available, otherwise reconstruct from client
        if self._url is not None:
            redis_url = self._url
        else:
            # Reconstruct Redis URL from client connection (backward compat)
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
        # vectors_prefix is set when RedisVectorStore dependencies are available
        # (redis-py with RediSearch). We check module availability, not actual
        # vector store creation, to avoid side effects during serialization.
        vectors_prefix = (
            f"{prefix}:vectors" if RedisVectorStore is not None and REDIS_VECTOR_AVAILABLE else None
        )
        return RedisStorageAccess(
            redis_url=redis_url,
            tools_prefix=f"{prefix}:tools",
            skills_prefix=f"{prefix}:skills",
            artifacts_prefix=f"{prefix}:artifacts",
            deps_prefix=f"{prefix}:deps",
            vectors_prefix=vectors_prefix,
        )

    async def get_tool_registry(self) -> ToolRegistry:
        """Return ToolRegistry for in-process execution.

        Uses registry_from_redis() to load both CLI and MCP tools from
        Redis. This is async because MCP tools require async initialization.

        The registry is cached after first load. MCP connections are bound to
        the task that first calls this method, so call from main task context
        before spawning handler tasks. New tool configs require server restart.
        """
        if self._tool_registry is not None:
            return self._tool_registry

        from py_code_mode.storage.redis_tools import registry_from_redis

        tool_store = self._get_tool_store()
        self._tool_registry = await registry_from_redis(tool_store)
        return self._tool_registry

    def get_skill_library(self) -> SkillLibrary:
        """Return SkillLibrary for in-process execution."""
        if self._skill_library is None:
            raw_store = RedisSkillStore(self._redis, prefix=f"{self._prefix}:skills")
            vector_store = self.get_vector_store()
            try:
                self._skill_library = create_skill_library(
                    store=raw_store,
                    vector_store=vector_store,
                )
            except ImportError:
                logger.warning(
                    "Semantic search dependencies not available, falling back to MockEmbedder. "
                    "Install with: pip install sentence-transformers scikit-learn"
                )
                from py_code_mode.skills import MockEmbedder

                self._skill_library = SkillLibrary(
                    embedder=MockEmbedder(),
                    store=raw_store,
                    vector_store=vector_store,
                )
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
