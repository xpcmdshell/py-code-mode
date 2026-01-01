"""Unified storage backend protocol for skills and artifacts.

This module provides a protocol that unifies storage under a single interface,
enabling swapping between FileStorage and RedisStorage.

Tools and deps are owned by executors (via config), not storage.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Protocol, runtime_checkable
from urllib.parse import quote

from py_code_mode.artifacts import ArtifactStoreProtocol, FileArtifactStore, RedisArtifactStore
from py_code_mode.execution.protocol import FileStorageAccess, RedisStorageAccess
from py_code_mode.skills import (
    FileSkillStore,
    RedisSkillStore,
    SkillLibrary,
    SkillStore,
    VectorStore,
    create_skill_library,
)

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


@runtime_checkable
class StorageBackend(Protocol):
    """Protocol for unified storage backend.

    Provides skills and artifacts storage under a single interface.
    Tools and deps are owned by executors (via config), not storage.
    """

    def get_serializable_access(self) -> FileStorageAccess | RedisStorageAccess:
        """Return serializable access descriptor for cross-process communication.

        Used by executors that run in separate processes and need
        connection info rather than direct object references.
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


class FileStorage:
    """File-based storage using directories for skills and artifacts.

    Tools and deps are owned by executors (via config), not storage.
    """

    _UNINITIALIZED: ClassVar[object] = object()

    def __init__(self, base_path: Path | str) -> None:
        """Initialize file storage.

        Args:
            base_path: Base directory for storage. Will create skills/, artifacts/ subdirs.
        """
        self._base_path = Path(base_path) if isinstance(base_path, str) else base_path
        self._base_path.mkdir(parents=True, exist_ok=True)

        # Lazy-initialized stores (skills and artifacts only)
        self._skill_library: SkillLibrary | None = None
        self._artifact_store: FileArtifactStore | None = None
        self._vector_store: VectorStore | None | object = FileStorage._UNINITIALIZED

    @property
    def root(self) -> Path:
        """Get the root storage path."""
        return self._base_path

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
                from py_code_mode.skills import Embedder

                vectors_path = self._get_vectors_path()
                embedder = Embedder()
                self._vector_store = ChromaVectorStore(path=vectors_path, embedder=embedder)
            except ImportError:
                self._vector_store = None

        return self._vector_store  # type: ignore[return-value]

    def get_serializable_access(self) -> FileStorageAccess:
        """Return FileStorageAccess for cross-process communication."""
        base_path = self._base_path
        vectors_path = base_path / "vectors"

        return FileStorageAccess(
            skills_path=base_path / "skills",
            artifacts_path=base_path / "artifacts",
            vectors_path=vectors_path if vectors_path.exists() else None,
        )

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
    """Redis-based storage for skills and artifacts.

    Tools and deps are owned by executors (via config), not storage.
    """

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

        # Lazy-initialized stores (skills and artifacts only)
        self._skill_library: SkillLibrary | None = None
        self._artifact_store: RedisArtifactStore | None = None
        self._vector_store: VectorStore | None | object = RedisStorage._UNINITIALIZED

    @property
    def prefix(self) -> str:
        """Get the configured prefix."""
        return self._prefix

    @property
    def client(self) -> Redis:
        """Get the Redis client."""
        return self._redis

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
                from py_code_mode.skills import Embedder

                embedder = Embedder()
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
        # vectors_prefix is set when RedisVectorStore dependencies are available
        # (redis-py with RediSearch). We check module availability, not actual
        # vector store creation, to avoid side effects during serialization.
        vectors_prefix = (
            f"{prefix}:vectors" if RedisVectorStore is not None and REDIS_VECTOR_AVAILABLE else None
        )
        return RedisStorageAccess(
            redis_url=redis_url,
            skills_prefix=f"{prefix}:skills",
            artifacts_prefix=f"{prefix}:artifacts",
            vectors_prefix=vectors_prefix,
        )

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
