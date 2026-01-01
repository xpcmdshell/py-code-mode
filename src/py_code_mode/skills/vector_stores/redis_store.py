"""Redis-backed VectorStore implementation using RediSearch."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

import numpy as np

logger = logging.getLogger(__name__)

# Skill ID validation
_VALID_SKILL_ID = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
_MAX_ID_LENGTH = 128

from py_code_mode.skills.vector_store import ModelInfo, SearchResult  # noqa: E402

try:
    import redis.exceptions
    from redis import Redis
    from redis.commands.search.field import TagField, TextField, VectorField
    from redis.commands.search.index_definition import IndexDefinition, IndexType
    from redis.commands.search.query import Query

    REDIS_AVAILABLE = True
except ImportError:
    Redis = None  # type: ignore[assignment, misc]
    redis = None  # type: ignore[assignment]
    REDIS_AVAILABLE = False

if TYPE_CHECKING:
    from py_code_mode.skills.embeddings import EmbeddingProvider


# Metadata keys
_KEY_MODEL_NAME = "model_name"
_KEY_DIMENSION = "dimension"
_KEY_VERSION = "version"

# Document field names
_FIELD_DESC_VECTOR = "desc_vector"
_FIELD_CODE_VECTOR = "code_vector"
_FIELD_CONTENT_HASH = "content_hash"
_FIELD_SKILL_ID = "skill_id"


class RedisVectorStore:
    """VectorStore implementation backed by Redis with RediSearch.

    Stores skill embeddings in Redis using RediSearch vector fields. Each skill
    has two vectors (description and code) stored in a single hash. Supports
    weighted search combining both similarity scores.

    Model changes are detected via stored ModelInfo in a metadata key. When the
    model changes (different dimension), the index is cleared and recreated.

    Requires Redis with RediSearch module (e.g., redis-stack image).
    """

    def __init__(
        self,
        redis: Redis,
        embedder: EmbeddingProvider,
        prefix: str = "vectors",
        index_name: str = "skills_idx",
    ) -> None:
        """Initialize RedisVectorStore.

        Args:
            redis: Connected Redis client.
            embedder: Embedding provider for generating vectors.
            prefix: Key prefix for stored documents (default: "vectors").
            index_name: RediSearch index name (default: "skills_idx").

        Raises:
            ImportError: If redis is not installed.
        """
        if not REDIS_AVAILABLE:
            raise ImportError(
                "redis is required for RedisVectorStore. Install with: pip install redis"
            )

        self._redis = redis
        self._embedder = embedder
        self._prefix = prefix
        self._index_name = index_name
        # Use index-specific document prefix to isolate documents by index
        self._doc_prefix = f"{prefix}:{index_name}"
        # Store metadata outside the indexed prefix to avoid counting it
        self._metadata_key = f"__vectorstore_meta__:{index_name}"

        # Validate model and create/update index
        self._validate_or_clear_model()
        self._ensure_index_exists()

    def _get_model_info_from_embedder(self) -> ModelInfo:
        """Build ModelInfo from the current embedder."""
        model_name = getattr(self._embedder, "_resolved_model_name", type(self._embedder).__name__)
        return ModelInfo(
            model_name=model_name,
            dimension=self._embedder.dimension,
            version="1",
        )

    def _get_stored_model_info(self) -> ModelInfo | None:
        """Retrieve stored ModelInfo from Redis metadata key."""
        data = self._redis.hgetall(self._metadata_key)
        if not data:
            return None

        # Handle both string and bytes keys
        def get_value(key: str) -> str | None:
            # Try bytes key first, then string
            val = data.get(key.encode()) or data.get(key)
            if val is None:
                return None
            return val.decode() if isinstance(val, bytes) else val

        model_name = get_value(_KEY_MODEL_NAME)
        dimension_str = get_value(_KEY_DIMENSION)
        version = get_value(_KEY_VERSION)

        if model_name is None or dimension_str is None:
            return None

        return ModelInfo(
            model_name=model_name,
            dimension=int(dimension_str),
            version=version or "1",
        )

    def _store_model_info(self, info: ModelInfo) -> None:
        """Store ModelInfo in Redis metadata key."""
        self._redis.hset(
            self._metadata_key,
            mapping={
                _KEY_MODEL_NAME: info.model_name,
                _KEY_DIMENSION: str(info.dimension),
                _KEY_VERSION: info.version,
            },
        )

    def _validate_or_clear_model(self) -> None:
        """Check if model matches stored metadata, clear if different."""
        current_info = self._get_model_info_from_embedder()
        stored_info = self._get_stored_model_info()

        if stored_info is not None:
            # Model mismatch check - dimension is the critical factor
            if stored_info.dimension != current_info.dimension:
                # Model changed, clear all vectors and index
                self.clear()

        # Update stored model info
        self._store_model_info(current_info)

    def _ensure_index_exists(self) -> None:
        """Create RediSearch index if it doesn't exist."""
        dim = self._embedder.dimension

        # Check if index already exists
        try:
            self._redis.ft(self._index_name).info()
            return  # Index exists
        except redis.exceptions.ResponseError as e:
            if "Unknown Index name" not in str(e) and "Unknown index name" not in str(e):
                raise  # Unexpected error
            # Index doesn't exist, create it below

        # Create index with vector fields
        schema = (
            VectorField(
                _FIELD_DESC_VECTOR,
                "HNSW",
                {
                    "TYPE": "FLOAT32",
                    "DIM": dim,
                    "DISTANCE_METRIC": "COSINE",
                },
            ),
            VectorField(
                _FIELD_CODE_VECTOR,
                "HNSW",
                {
                    "TYPE": "FLOAT32",
                    "DIM": dim,
                    "DISTANCE_METRIC": "COSINE",
                },
            ),
            TextField(_FIELD_CONTENT_HASH),
            TagField(_FIELD_SKILL_ID),
        )

        definition = IndexDefinition(
            prefix=[f"{self._doc_prefix}:"],
            index_type=IndexType.HASH,
        )

        self._redis.ft(self._index_name).create_index(
            schema,
            definition=definition,
        )

    def _doc_key(self, skill_id: str) -> str:
        """Build Redis key for a skill document."""
        return f"{self._doc_prefix}:{skill_id}"

    def _validate_skill_id(self, skill_id: str) -> None:
        """Validate skill ID format.

        Args:
            skill_id: The skill ID to validate.

        Raises:
            ValueError: If skill ID is empty, too long, or has invalid format.
        """
        if not skill_id or len(skill_id) > _MAX_ID_LENGTH:
            raise ValueError(f"Invalid skill ID length: {len(skill_id) if skill_id else 0}")
        if not _VALID_SKILL_ID.match(skill_id):
            raise ValueError(f"Invalid skill ID format: {skill_id!r}")

        # Defense-in-depth: explicit check for characters that would break Redis keys
        redis_unsafe = frozenset(":{}[]")
        if any(c in skill_id for c in redis_unsafe):
            raise ValueError(f"Skill ID contains unsafe characters: {skill_id!r}")

    def _vector_to_bytes(self, vector: list[float]) -> bytes:
        """Convert vector to bytes for Redis storage.

        Args:
            vector: The vector to convert.

        Returns:
            The vector as bytes in float32 format.

        Raises:
            ValueError: If vector dimension doesn't match embedder dimension.
        """
        if len(vector) != self._embedder.dimension:
            raise ValueError(
                f"Vector dimension mismatch: expected {self._embedder.dimension}, got {len(vector)}"
            )
        return np.array(vector, dtype=np.float32).tobytes()

    def add(self, id: str, description: str, source: str, content_hash: str) -> None:
        """Add or update a skill's embeddings.

        If the skill already exists with the same content_hash, this is a no-op.

        Args:
            id: Unique identifier for the skill.
            description: Skill description text to embed.
            source: Skill source code to embed.
            content_hash: Hash of description + source for change detection.

        Raises:
            ValueError: If skill ID format is invalid.
        """
        self._validate_skill_id(id)

        # Check if skill already exists with same hash (skip re-embedding)
        existing_hash = self.get_content_hash(id)
        if existing_hash == content_hash:
            return

        # Generate embeddings
        vectors = self._embedder.embed([description, source])
        desc_vector = vectors[0]
        code_vector = vectors[1]

        # Store document with both vectors
        self._redis.hset(
            self._doc_key(id),
            mapping={
                _FIELD_DESC_VECTOR: self._vector_to_bytes(desc_vector),
                _FIELD_CODE_VECTOR: self._vector_to_bytes(code_vector),
                _FIELD_CONTENT_HASH: content_hash,
                _FIELD_SKILL_ID: id,
            },
        )

    def remove(self, id: str) -> bool:
        """Remove a skill's embeddings.

        Args:
            id: Unique identifier for the skill.

        Returns:
            True if the skill was removed, False if it wasn't in the store.

        Raises:
            ValueError: If skill ID format is invalid.
        """
        self._validate_skill_id(id)

        # Check if skill exists
        if self.get_content_hash(id) is None:
            return False

        # Delete the document
        self._redis.delete(self._doc_key(id))
        return True

    def search(
        self,
        query: str,
        limit: int = 10,
        desc_weight: float = 0.7,
        code_weight: float = 0.3,
    ) -> list[SearchResult]:
        """Search for skills by semantic similarity.

        Searches both description and code vectors, combining scores with
        the given weights. Returns results sorted by combined score.

        Args:
            query: Search query text.
            limit: Maximum number of results to return.
            desc_weight: Weight for description similarity (0.0 to 1.0).
            code_weight: Weight for code similarity (0.0 to 1.0).

        Returns:
            List of SearchResult objects, sorted by score descending.
        """
        # Empty store returns empty results
        if self.count() == 0:
            return []

        # Embed query
        query_vector = self._embedder.embed_query(query)
        query_bytes = self._vector_to_bytes(query_vector)

        # Fetch enough results to combine scores
        fetch_limit = min(limit * 2, self.count())

        # Query for description similarity
        desc_scores = self._knn_search(_FIELD_DESC_VECTOR, query_bytes, fetch_limit, "desc_score")

        # Query for code similarity
        code_scores = self._knn_search(_FIELD_CODE_VECTOR, query_bytes, fetch_limit, "code_score")

        # Combine scores per skill
        skill_scores: dict[str, dict[str, float]] = {}

        for skill_id, distance in desc_scores.items():
            # RediSearch cosine distance: 0 = identical, 2 = opposite
            # Convert to similarity: 1 - (distance / 2)
            similarity = max(0.0, min(1.0, 1.0 - (distance / 2.0)))
            if skill_id not in skill_scores:
                skill_scores[skill_id] = {"desc": 0.0, "code": 0.0}
            skill_scores[skill_id]["desc"] = similarity

        for skill_id, distance in code_scores.items():
            similarity = max(0.0, min(1.0, 1.0 - (distance / 2.0)))
            if skill_id not in skill_scores:
                skill_scores[skill_id] = {"desc": 0.0, "code": 0.0}
            skill_scores[skill_id]["code"] = similarity

        # Build results with combined scores
        results: list[SearchResult] = []
        for skill_id, scores in skill_scores.items():
            combined_score = scores["desc"] * desc_weight + scores["code"] * code_weight
            results.append(
                SearchResult(
                    id=skill_id,
                    score=combined_score,
                    metadata={},
                )
            )

        # Sort by score descending and limit
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    def _knn_search(
        self, field: str, query_bytes: bytes, limit: int, score_alias: str
    ) -> dict[str, float]:
        """Run KNN search on a vector field.

        Args:
            field: Vector field name to search.
            query_bytes: Query vector as bytes.
            limit: Maximum results to return.
            score_alias: Alias for the distance score in results.

        Returns:
            Dict mapping skill_id to distance score.
        """
        query_str = f"*=>[KNN {limit} @{field} $vec AS {score_alias}]"
        q = (
            Query(query_str)
            .return_fields(_FIELD_SKILL_ID, score_alias)
            .sort_by(score_alias)
            .dialect(2)
        )

        try:
            results = self._redis.ft(self._index_name).search(q, query_params={"vec": query_bytes})
        except redis.exceptions.ResponseError as e:
            logger.error(f"RediSearch query failed: {e}")
            return {}
        except redis.exceptions.ConnectionError as e:
            logger.error(f"Redis connection failed during search: {e}")
            return {}

        scores: dict[str, float] = {}
        for doc in results.docs:
            skill_id = getattr(doc, _FIELD_SKILL_ID, None)
            score = getattr(doc, score_alias, None)

            if skill_id is None or score is None:
                continue

            # Handle bytes vs string
            if isinstance(skill_id, bytes):
                skill_id = skill_id.decode()
            if isinstance(score, bytes):
                score = float(score.decode())
            else:
                score = float(score)

            scores[skill_id] = score

        return scores

    def get_content_hash(self, id: str) -> str | None:
        """Get the stored content hash for a skill.

        Args:
            id: Unique identifier for the skill.

        Returns:
            The content hash if the skill exists, None otherwise.

        Raises:
            ValueError: If skill ID format is invalid.
        """
        self._validate_skill_id(id)
        value = self._redis.hget(self._doc_key(id), _FIELD_CONTENT_HASH)
        if value is None:
            return None
        return value.decode() if isinstance(value, bytes) else value

    def get_model_info(self) -> ModelInfo:
        """Get information about the embedding model.

        Returns:
            ModelInfo describing the model used for embeddings.
        """
        return self._get_model_info_from_embedder()

    def clear(self) -> None:
        """Remove all embeddings from the store.

        Drops the index and deletes all documents, then recreates the index.
        """
        # Drop index if it exists
        try:
            self._redis.ft(self._index_name).dropindex(delete_documents=True)
        except redis.exceptions.ResponseError as e:
            if "Unknown Index name" not in str(e) and "Unknown index name" not in str(e):
                raise
            # Index doesn't exist - that's fine for clear()

        # Delete any remaining keys with our document prefix
        # Metadata is stored outside the prefix, so no filtering needed
        cursor = 0
        while True:
            cursor, keys = self._redis.scan(cursor=cursor, match=f"{self._doc_prefix}:*", count=100)
            if keys:
                self._redis.delete(*keys)
            if cursor == 0:
                break

        # Recreate the index
        self._ensure_index_exists()

    def count(self) -> int:
        """Get the number of skills indexed in the store.

        Returns:
            Number of unique skills with embeddings.
        """
        # Count documents in the index (each skill is one document)
        try:
            info = self._redis.ft(self._index_name).info()
            # info is a dict-like object, num_docs gives total documents
            num_docs = info.get("num_docs", 0)
            return int(num_docs)
        except redis.exceptions.ResponseError as e:
            if "Unknown Index name" not in str(e) and "Unknown index name" not in str(e):
                raise
            return 0  # Index doesn't exist yet
