"""ChromaDB-backed VectorStore implementation."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

from py_code_mode.skills.vector_store import ModelInfo, SearchResult  # noqa: E402

try:
    import chromadb

    CHROMADB_AVAILABLE = True
except ImportError:
    chromadb = None  # type: ignore[assignment]
    CHROMADB_AVAILABLE = False

if TYPE_CHECKING:
    from py_code_mode.skills.embeddings import EmbeddingProvider


# Metadata keys used in ChromaDB collection
_KEY_MODEL_NAME = "model_name"
_KEY_DIMENSION = "dimension"
_KEY_VERSION = "version"

# Metadata keys used in vector documents
_KEY_CONTENT_HASH = "content_hash"
_KEY_TYPE = "type"
_KEY_SKILL_ID = "skill_id"

# Vector type suffixes
_TYPE_DESC = "desc"
_TYPE_CODE = "code"


class ChromaVectorStore:
    """VectorStore implementation backed by ChromaDB.

    Stores skill embeddings in a persistent ChromaDB collection with two
    vectors per skill: one for description, one for source code. Supports
    weighted search combining both similarity scores.

    Model changes are detected via stored ModelInfo metadata. When the model
    changes (different dimension, name, or version), the collection is cleared.
    """

    COLLECTION_NAME = "skills"

    def __init__(self, path: Path, embedder: EmbeddingProvider) -> None:
        """Initialize ChromaVectorStore.

        Args:
            path: Directory path for ChromaDB persistent storage.
            embedder: Embedding provider for generating vectors.

        Raises:
            ImportError: If chromadb is not installed.
        """
        if not CHROMADB_AVAILABLE:
            raise ImportError(
                "chromadb is required for ChromaVectorStore. Install with: pip install chromadb"
            )

        self._embedder = embedder
        self._path = path

        # Ensure path exists
        path.mkdir(parents=True, exist_ok=True)

        # Create persistent client
        self._client = chromadb.PersistentClient(path=str(path))

        # Get or create collection without embedding function
        # (we pass pre-computed vectors)
        self._collection = self._client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

        # Validate model and clear if changed
        self._validate_or_clear_model()

    def _get_model_info_from_embedder(self) -> ModelInfo:
        """Build ModelInfo from the current embedder."""
        # Use embedder class name as model name for mock embedders
        model_name = getattr(self._embedder, "_resolved_model_name", type(self._embedder).__name__)
        return ModelInfo(
            model_name=model_name,
            dimension=self._embedder.dimension,
            version="1",
        )

    def _validate_or_clear_model(self) -> None:
        """Check if model matches stored metadata, clear if different."""
        current_info = self._get_model_info_from_embedder()
        collection_meta = self._collection.metadata or {}

        stored_dimension = collection_meta.get(_KEY_DIMENSION)

        # Check if we have stored model info
        if stored_dimension is not None:
            # Model mismatch check - dimension is the critical factor
            if stored_dimension != current_info.dimension:
                logger.warning(
                    "Embedding model dimension changed "
                    f"({stored_dimension} -> {current_info.dimension}). "
                    f"Clearing {self.count()} cached embeddings."
                )
                self.clear()

        # Update collection metadata with current model info
        # Note: hnsw:space cannot be modified after creation, so we don't include it
        self._collection.modify(
            metadata={
                _KEY_MODEL_NAME: current_info.model_name,
                _KEY_DIMENSION: current_info.dimension,
                _KEY_VERSION: current_info.version,
            }
        )

    def _desc_id(self, skill_id: str) -> str:
        """Build vector ID for description embedding."""
        return f"{skill_id}:{_TYPE_DESC}"

    def _code_id(self, skill_id: str) -> str:
        """Build vector ID for code embedding."""
        return f"{skill_id}:{_TYPE_CODE}"

    def add(self, id: str, description: str, source: str, content_hash: str) -> None:
        """Add or update a skill's embeddings.

        If the skill already exists with the same content_hash, this is a no-op.
        """
        # Check if skill already exists with same hash (skip re-embedding)
        existing_hash = self.get_content_hash(id)
        if existing_hash == content_hash:
            return

        # Generate embeddings
        vectors = self._embedder.embed([description, source])
        desc_vector = vectors[0]
        code_vector = vectors[1]

        # Upsert both vectors
        self._collection.upsert(
            ids=[self._desc_id(id), self._code_id(id)],
            embeddings=[desc_vector, code_vector],
            metadatas=[
                {
                    _KEY_CONTENT_HASH: content_hash,
                    _KEY_TYPE: _TYPE_DESC,
                    _KEY_SKILL_ID: id,
                },
                {
                    _KEY_CONTENT_HASH: content_hash,
                    _KEY_TYPE: _TYPE_CODE,
                    _KEY_SKILL_ID: id,
                },
            ],
        )

    def remove(self, id: str) -> bool:
        """Remove a skill's embeddings.

        Returns True if the skill was removed, False if it wasn't found.
        """
        # Check if skill exists
        if self.get_content_hash(id) is None:
            return False

        # Delete both vectors
        self._collection.delete(ids=[self._desc_id(id), self._code_id(id)])
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
        """
        # Empty collection returns empty results
        if self._collection.count() == 0:
            return []

        # Embed query
        query_vector = self._embedder.embed_query(query)

        # Query collection - get enough results to merge
        # ChromaDB returns distance for cosine, we need similarity
        results = self._collection.query(
            query_embeddings=[query_vector],
            n_results=min(limit * 2, self._collection.count()),
            include=["metadatas", "distances"],
        )

        # Process results - combine desc and code scores per skill
        skill_scores: dict[str, dict[str, float]] = {}

        if results["ids"] and results["ids"][0]:
            ids = results["ids"][0]
            distances = results["distances"][0] if results["distances"] else []
            metadatas = results["metadatas"][0] if results["metadatas"] else []

            for i, doc_id in enumerate(ids):
                metadata = metadatas[i] if i < len(metadatas) else {}
                distance = distances[i] if i < len(distances) else 1.0

                # Convert cosine distance to similarity
                # ChromaDB cosine distance = 1 - similarity for normalized vectors
                similarity = max(0.0, min(1.0, 1.0 - distance))

                skill_id = metadata.get(_KEY_SKILL_ID, doc_id.rsplit(":", 1)[0])
                doc_type = metadata.get(_KEY_TYPE)

                if skill_id not in skill_scores:
                    skill_scores[skill_id] = {"desc": 0.0, "code": 0.0}

                if doc_type == _TYPE_DESC:
                    skill_scores[skill_id]["desc"] = similarity
                elif doc_type == _TYPE_CODE:
                    skill_scores[skill_id]["code"] = similarity

        # Combine scores and build results
        search_results: list[SearchResult] = []
        for skill_id, scores in skill_scores.items():
            combined_score = scores["desc"] * desc_weight + scores["code"] * code_weight
            search_results.append(
                SearchResult(
                    id=skill_id,
                    score=combined_score,
                    metadata={},
                )
            )

        # Sort by score descending and limit
        search_results.sort(key=lambda r: r.score, reverse=True)
        return search_results[:limit]

    def get_content_hash(self, id: str) -> str | None:
        """Get the stored content hash for a skill."""
        try:
            result = self._collection.get(
                ids=[self._desc_id(id)],
                include=["metadatas"],
            )
            if result["ids"] and result["metadatas"]:
                metadata = result["metadatas"][0]
                return metadata.get(_KEY_CONTENT_HASH)
        except (KeyError, IndexError):
            # Malformed result structure - skill doesn't exist
            return None
        except Exception as e:
            logger.debug(f"Failed to get content hash for {id}: {e}")
        return None

    def get_model_info(self) -> ModelInfo:
        """Get information about the embedding model."""
        return self._get_model_info_from_embedder()

    def clear(self) -> None:
        """Remove all embeddings from the store."""
        # Get all IDs and delete them
        all_data = self._collection.get()
        if all_data["ids"]:
            self._collection.delete(ids=all_data["ids"])

    def count(self) -> int:
        """Get the number of skills indexed.

        Returns the number of unique skills, not vector count.
        Each skill has 2 vectors (desc + code), so we divide by 2.
        """
        vector_count = self._collection.count()
        return vector_count // 2
