"""Unified storage backend protocol for workflows and artifacts.

This module provides a protocol that unifies storage under a single interface,
enabling swapping between FileStorage and RedisStorage.

Tools and deps are owned by executors (via config), not storage.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Protocol, runtime_checkable
from urllib.parse import quote

from py_code_mode.artifacts import ArtifactStoreProtocol, FileArtifactStore, RedisArtifactStore
from py_code_mode.execution.protocol import FileStorageAccess, RedisStorageAccess
from py_code_mode.workflows import (
    FileWorkflowStore,
    RedisWorkflowStore,
    VectorStore,
    WorkflowLibrary,
    WorkflowStore,
    create_workflow_library,
)

# Import ChromaVectorStore at module level for test mocking support
# The actual import in get_vector_store() handles the ImportError gracefully
try:
    from py_code_mode.workflows.vector_stores.chroma import ChromaVectorStore
except ImportError:
    ChromaVectorStore = None  # type: ignore[misc, assignment]

# Import RedisVectorStore at module level for test mocking support
try:
    from py_code_mode.workflows.vector_stores.redis_store import (
        REDIS_AVAILABLE as REDIS_VECTOR_AVAILABLE,
    )
    from py_code_mode.workflows.vector_stores.redis_store import (
        RedisVectorStore,
    )
except ImportError:
    RedisVectorStore = None  # type: ignore[misc, assignment]
    REDIS_VECTOR_AVAILABLE = False

logger = logging.getLogger(__name__)

_WORKSPACE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

if TYPE_CHECKING:
    from redis import Redis


def _validate_workspace_id(workspace_id: str) -> str:
    """Validate a workspace identifier used in paths and Redis prefixes."""
    if not _WORKSPACE_ID_PATTERN.fullmatch(workspace_id):
        raise ValueError(
            "workspace_id must be 1-128 characters using only ASCII letters, digits, "
            "underscores, or hyphens"
        )
    return workspace_id


@runtime_checkable
class StorageBackend(Protocol):
    """Protocol for unified storage backend.

    Provides workflows and artifacts storage under a single interface.
    Tools and deps are owned by executors (via config), not storage.
    """

    def get_serializable_access(self) -> FileStorageAccess | RedisStorageAccess:
        """Return serializable access descriptor for cross-process communication.

        Used by executors that run in separate processes and need
        connection info rather than direct object references.
        """
        ...

    def get_workflow_library(self) -> WorkflowLibrary:
        """Return WorkflowLibrary for in-process execution.

        This method provides a library of workflows loaded from storage for executors.
        """
        ...

    def get_artifact_store(self) -> ArtifactStoreProtocol:
        """Return artifact store for in-process execution.

        This method provides access to the artifact store for executors.
        """
        ...


class FileStorage:
    """File-based storage using directories for workflows and artifacts.

    Tools and deps are owned by executors (via config), not storage.
    """

    _UNINITIALIZED: ClassVar[object] = object()

    def __init__(self, base_path: Path | str, workspace_id: str | None = None) -> None:
        """Initialize file storage.

        Args:
            base_path: Base directory for storage. Will create workflows/, artifacts/ subdirs.
            workspace_id: Optional workspace scope for workflows, artifacts, and vectors.
        """
        self._base_path = Path(base_path) if isinstance(base_path, str) else base_path
        self._base_path.mkdir(parents=True, exist_ok=True)
        self._workspace_id = (
            _validate_workspace_id(workspace_id) if workspace_id is not None else None
        )

        # Lazy-initialized stores (workflows and artifacts only)
        self._workflow_library: WorkflowLibrary | None = None
        self._artifact_store: FileArtifactStore | None = None
        self._vector_store: VectorStore | None | object = FileStorage._UNINITIALIZED

    @property
    def root(self) -> Path:
        """Get the root storage path."""
        return self._base_path

    @property
    def workspace_id(self) -> str | None:
        """Get the configured workspace scope."""
        return self._workspace_id

    def _get_storage_root(self) -> Path:
        """Get the scoped root for workflows, artifacts, and vectors."""
        if self._workspace_id is None:
            return self._base_path
        return self._base_path / "workspaces" / self._workspace_id

    def _get_workflows_path(self) -> Path:
        """Get the workflows directory path."""
        workflows_path = self._get_storage_root() / "workflows"
        workflows_path.mkdir(parents=True, exist_ok=True)
        return workflows_path

    def _get_artifacts_path(self) -> Path:
        """Get the artifacts directory path."""
        artifacts_path = self._get_storage_root() / "artifacts"
        artifacts_path.mkdir(parents=True, exist_ok=True)
        return artifacts_path

    def _get_vectors_path(self) -> Path:
        """Get the vectors directory path."""
        vectors_path = self._get_storage_root() / "vectors"
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
                from py_code_mode.workflows import Embedder

                vectors_path = self._get_vectors_path()
                embedder = Embedder()
                self._vector_store = ChromaVectorStore(path=vectors_path, embedder=embedder)
            except ImportError:
                self._vector_store = None

        return self._vector_store  # type: ignore[return-value]

    def get_serializable_access(self) -> FileStorageAccess:
        """Return FileStorageAccess for cross-process communication."""
        storage_root = self._get_storage_root()
        vectors_path = storage_root / "vectors"

        return FileStorageAccess(
            workflows_path=storage_root / "workflows",
            artifacts_path=storage_root / "artifacts",
            vectors_path=vectors_path if vectors_path.exists() else None,
            root_path=self._base_path,
        )

    def get_workflow_library(self) -> WorkflowLibrary:
        """Return WorkflowLibrary for in-process execution."""
        if self._workflow_library is None:
            workflows_path = self._get_workflows_path()
            raw_store = FileWorkflowStore(workflows_path)
            vector_store = self.get_vector_store()
            try:
                self._workflow_library = create_workflow_library(
                    store=raw_store,
                    vector_store=vector_store,
                )
            except ImportError:
                logger.warning(
                    "Semantic search dependencies not available, falling back to MockEmbedder. "
                    "Install with: pip install sentence-transformers scikit-learn"
                )
                from py_code_mode.workflows import MockEmbedder

                self._workflow_library = WorkflowLibrary(
                    embedder=MockEmbedder(),
                    store=raw_store,
                    vector_store=vector_store,
                )
        return self._workflow_library

    def get_artifact_store(self) -> ArtifactStoreProtocol:
        """Return artifact store for in-process execution."""
        if self._artifact_store is None:
            self._artifact_store = FileArtifactStore(self._get_artifacts_path())
        return self._artifact_store

    def get_workflow_store(self) -> WorkflowStore:
        """Return the underlying WorkflowStore for direct access."""
        workflows_path = self._get_workflows_path()
        return FileWorkflowStore(workflows_path)

    def to_bootstrap_config(self) -> dict[str, str]:
        """Serialize storage configuration for subprocess bootstrap.

        Returns:
            Dict with type="file" and base_path as string.
            This config can be passed to bootstrap_namespaces() to reconstruct
            the storage in a subprocess.
        """
        config = {
            "type": "file",
            "base_path": str(self._base_path),
        }
        if self._workspace_id is not None:
            config["workspace_id"] = self._workspace_id
        return config


class RedisStorage:
    """Redis-based storage for workflows and artifacts.

    Tools and deps are owned by executors (via config), not storage.
    """

    _UNINITIALIZED: ClassVar[object] = object()

    def __init__(
        self,
        url: str | None = None,
        redis: Redis | None = None,
        prefix: str = "py_code_mode",
        workspace_id: str | None = None,
    ) -> None:
        """Initialize Redis storage.

        Args:
            url: Redis URL (e.g., "redis://localhost:6379" or
                "rediss://:password@host:6380"). Preferred parameter.
            redis: Redis client instance. Use for advanced configurations
                (custom connection pools, etc.). Mutually exclusive with url.
            prefix: Key prefix for all storage. Default: "py_code_mode"
            workspace_id: Optional workspace scope for workflows, artifacts, and vectors.

        Raises:
            ValueError: If neither url nor redis is provided, or if both are.
        """
        if url is not None and redis is not None:
            raise ValueError("Provide either 'url' or 'redis', not both")
        if url is None and redis is None:
            raise ValueError("Either 'url' or 'redis' must be provided")

        self._url: str | None

        if url is not None:
            from redis import Redis as RedisClient

            self._redis = RedisClient.from_url(url)
            self._url = url
        else:
            if redis is None:
                raise ValueError("Redis client must be provided when url is None")
            self._redis = redis
            self._url = None  # Will be reconstructed if needed

        if self._redis is None:
            raise ValueError("Redis client is required")

        self._prefix = prefix
        self._workspace_id = (
            _validate_workspace_id(workspace_id) if workspace_id is not None else None
        )
        self._storage_prefix = (
            f"{prefix}:ws:{self._workspace_id}" if self._workspace_id is not None else prefix
        )

        # Lazy-initialized stores (workflows and artifacts only)
        self._workflow_library: WorkflowLibrary | None = None
        self._artifact_store: RedisArtifactStore | None = None
        self._vector_store: VectorStore | None | object = RedisStorage._UNINITIALIZED

    @property
    def prefix(self) -> str:
        """Get the configured prefix."""
        return self._prefix

    @property
    def workspace_id(self) -> str | None:
        """Get the configured workspace scope."""
        return self._workspace_id

    @property
    def client(self) -> Redis:
        """Get the Redis client."""
        return self._redis

    def _reconstruct_redis_url(self) -> str:
        """Reconstruct Redis URL from client connection pool.

        Returns:
            Redis URL string with host, port, db, and credentials (if present).
        """
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
            return f"redis://{encoded_user}:{encoded_pass}@{host}:{port}/{db}"
        elif password:
            return f"redis://:{quote(password, safe='')}@{host}:{port}/{db}"
        else:
            return f"redis://{host}:{port}/{db}"

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
                from py_code_mode.workflows import Embedder

                embedder = Embedder()
                self._vector_store = RedisVectorStore(
                    redis=self._redis,
                    embedder=embedder,
                    prefix=f"{self._storage_prefix}:vectors",
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
            redis_url = self._reconstruct_redis_url()

        prefix = self._storage_prefix
        # vectors_prefix is set when RedisVectorStore dependencies are available
        # (redis-py with RediSearch). We check module availability, not actual
        # vector store creation, to avoid side effects during serialization.
        vectors_prefix = (
            f"{prefix}:vectors" if RedisVectorStore is not None and REDIS_VECTOR_AVAILABLE else None
        )
        return RedisStorageAccess(
            redis_url=redis_url,
            workflows_prefix=f"{prefix}:workflows",
            artifacts_prefix=f"{prefix}:artifacts",
            vectors_prefix=vectors_prefix,
            root_prefix=self._prefix,
        )

    def get_workflow_library(self) -> WorkflowLibrary:
        """Return WorkflowLibrary for in-process execution."""
        if self._workflow_library is None:
            raw_store = RedisWorkflowStore(self._redis, prefix=f"{self._storage_prefix}:workflows")
            vector_store = self.get_vector_store()
            try:
                self._workflow_library = create_workflow_library(
                    store=raw_store,
                    vector_store=vector_store,
                )
            except ImportError:
                logger.warning(
                    "Semantic search dependencies not available, falling back to MockEmbedder. "
                    "Install with: pip install sentence-transformers scikit-learn"
                )
                from py_code_mode.workflows import MockEmbedder

                self._workflow_library = WorkflowLibrary(
                    embedder=MockEmbedder(),
                    store=raw_store,
                    vector_store=vector_store,
                )
        return self._workflow_library

    def get_artifact_store(self) -> ArtifactStoreProtocol:
        """Return artifact store for in-process execution."""
        if self._artifact_store is None:
            self._artifact_store = RedisArtifactStore(
                self._redis, prefix=f"{self._storage_prefix}:artifacts"
            )
        return self._artifact_store

    def get_workflow_store(self) -> WorkflowStore:
        """Return the underlying WorkflowStore for direct access."""
        return RedisWorkflowStore(self._redis, prefix=f"{self._storage_prefix}:workflows")

    def to_bootstrap_config(self) -> dict[str, str]:
        """Serialize storage configuration for subprocess bootstrap.

        Returns:
            Dict with type="redis", url, and prefix.
            This config can be passed to bootstrap_namespaces() to reconstruct
            the storage in a subprocess.
        """
        config = {
            "type": "redis",
            "url": self._reconstruct_redis_url(),
            "prefix": self._prefix,
        }
        if self._workspace_id is not None:
            config["workspace_id"] = self._workspace_id
        return config
