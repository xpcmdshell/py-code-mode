"""Semantic search for skills using embeddings.

This module provides SkillLibrary, the primary interface for skill management
and semantic search. It combines storage (via SkillStore) with embedding-based
search for finding skills by natural language queries.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import numpy as np

if TYPE_CHECKING:
    from py_code_mode.skill_store import SkillStore
    from py_code_mode.skills import PythonSkill


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Protocol for embedding providers."""

    @property
    def dimension(self) -> int:
        """Embedding vector dimension."""
        ...

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts (documents) into vectors."""
        ...

    def embed_query(self, query: str) -> list[float]:
        """Embed a query text into a vector (may use instruction prefix)."""
        ...


@dataclass
class MockEmbedder:
    """Mock embedder for testing without GPU/model."""

    dimension: int = 384

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return deterministic mock embeddings based on text hash."""
        vectors = []
        for text in texts:
            # Use hash to generate deterministic pseudo-random vector
            seed = hash(text) % (2**32)
            rng = np.random.default_rng(seed)
            vec = rng.random(self.dimension).tolist()
            # Normalize to unit vector
            norm = sum(v * v for v in vec) ** 0.5
            vec = [v / norm for v in vec]
            vectors.append(vec)
        return vectors

    def embed_query(self, query: str) -> list[float]:
        """Return deterministic mock embedding for query."""
        return self.embed([query])[0]


MODEL_ALIASES = {
    "bge-small": "BAAI/bge-small-en-v1.5",
    "bge-base": "BAAI/bge-base-en-v1.5",
    "granite": "ibm-granite/granite-embedding-small-english-r2",
}


def resolve_model_name(model: str) -> str:
    """Resolve alias or pass through full model name."""
    return MODEL_ALIASES.get(model, model)


class Embedder:
    """Embedding provider using sentence-transformers.

    Default: BGE-small (33M params, 384-dim) with instruction prefix for queries.
    Automatically uses MPS on Apple Silicon, CUDA if available, else CPU.

    Supports model aliases:
        - "bge-small": BAAI/bge-small-en-v1.5 (default)
        - "bge-base": BAAI/bge-base-en-v1.5
        - "granite": ibm-granite/granite-embedding-small-english-r2

    Or pass full HuggingFace model name directly.
    """

    DEFAULT_MODEL = "bge-small"
    QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "

    def __init__(self, model_name: str | None = None) -> None:
        """Initialize embedder.

        Args:
            model_name: Model alias or full HuggingFace name. Default: bge-small.
        """
        from sentence_transformers import SentenceTransformer

        os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

        self.device = self._detect_device()

        model_name = model_name or self.DEFAULT_MODEL
        resolved = resolve_model_name(model_name)
        self._model = SentenceTransformer(resolved, device=self.device)
        self._dimension = self._model.get_sentence_embedding_dimension()

    def _detect_device(self) -> str:
        """Detect best available device."""
        import torch

        if torch.cuda.is_available():
            return "cuda"
        elif torch.backends.mps.is_available():
            return "mps"
        return "cpu"

    @property
    def dimension(self) -> int:
        """Embedding vector dimension."""
        return self._dimension  # type: ignore[return-value]

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed document texts into vectors (no prefix).

        Args:
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors.
        """
        embeddings = self._model.encode(texts, normalize_embeddings=True)
        return embeddings.tolist()  # type: ignore[return-value]

    def embed_query(self, query: str) -> list[float]:
        """Embed query text into vector (with instruction prefix).

        BGE models use instruction prefix for better retrieval performance.

        Args:
            query: Search query text.

        Returns:
            Embedding vector.
        """
        text = self.QUERY_INSTRUCTION + query
        embedding = self._model.encode([text], normalize_embeddings=True)[0]
        return embedding.tolist()  # type: ignore[return-value]


@dataclass
class RankingConfig:
    """Configuration for search ranking formula.

    Tune these based on your skill library characteristics.
    """

    description_weight: float = 0.7
    code_weight: float = 0.3
    min_score_threshold: float = 0.0  # 0 = return all, 0.8 = high confidence only
    code_min_length: int = 0  # Min code chars to include code embedding (0 = always)


@dataclass
class SkillLibrary:
    """Skill management with semantic search.

    The primary interface for working with skills. Provides:
    - Semantic search using embeddings
    - Optional persistence via SkillStore
    - Skill lifecycle management (add, remove, get, list)

    If a store is provided, skills are persisted there and loaded at
    construction time. Use refresh() to reload from store.

    Ranking formula is configurable via RankingConfig.
    """

    embedder: EmbeddingProvider
    store: SkillStore | None = None
    ranking: RankingConfig = field(default_factory=RankingConfig)
    _skills: dict[str, PythonSkill] = field(default_factory=dict)
    _description_vectors: dict[str, list[float]] = field(default_factory=dict)
    _code_vectors: dict[str, list[float]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Load and index skills from store if provided."""
        if self.store is not None:
            self.refresh()

    def __len__(self) -> int:
        return len(self._skills)

    def refresh(self) -> None:
        """Reload all skills from store and rebuild embedding index.

        This clears the current index and re-embeds all skills from the store.
        No-op if no store is configured.

        Note: Intentionally re-embeds everything. The store is the source of truth,
        and skills may have been modified/added/removed externally. Re-embedding
        ensures consistency at the cost of O(n) embeddings per refresh.
        """
        if self.store is None:
            return

        # Clear current index
        self._skills.clear()
        self._description_vectors.clear()
        self._code_vectors.clear()

        # Load and index all skills from store
        for skill in self.store.list_all():
            self._index_skill(skill)

    def _index_skill(self, skill: PythonSkill) -> None:
        """Add skill to local embedding index without touching store."""
        self._skills[skill.name] = skill

        # Embed description
        desc_vec = self.embedder.embed([skill.description])[0]
        self._description_vectors[skill.name] = desc_vec

        # Embed source code
        code_vec = self.embedder.embed([skill.source])[0]
        self._code_vectors[skill.name] = code_vec

    def add(self, skill: PythonSkill) -> None:
        """Add a skill to the library.

        Stores in store (if configured) and indexes embeddings for search.
        """
        # Store if configured
        if self.store is not None:
            self.store.save(skill)

        # Index locally for semantic search
        self._index_skill(skill)

    def list(self) -> list[PythonSkill]:
        """List all skills."""
        return list(self._skills.values())

    def remove(self, name: str) -> bool:
        """Remove a skill from the library.

        Removes from store (if configured) and from local embedding index.

        Returns:
            True if skill was removed, False if not found.
        """
        # Remove from store if configured
        if self.store is not None:
            self.store.delete(name)

        # Remove from local index
        if name not in self._skills:
            return False
        del self._skills[name]
        del self._description_vectors[name]
        if name in self._code_vectors:
            del self._code_vectors[name]
        return True

    def search(
        self,
        query: str,
        limit: int = 10,
    ) -> list[PythonSkill]:
        """Search for skills by semantic similarity.

        Args:
            query: Natural language search query.
            limit: Maximum results to return.

        Returns:
            Skills ranked by combined semantic similarity.
        """
        if not self._skills:
            return []

        # Embed query (uses instruction prefix for retrieval models)
        query_vec = self.embedder.embed_query(query)

        # Score each skill
        scored: list[tuple[float, str]] = []
        for name, skill in self._skills.items():
            # Cosine similarity with description
            desc_sim = cosine_similarity(query_vec, self._description_vectors[name])

            # Cosine similarity with code (if code is substantial enough)
            if len(skill.source) >= self.ranking.code_min_length and self.ranking.code_weight > 0:
                code_sim = cosine_similarity(query_vec, self._code_vectors[name])
                score = (
                    self.ranking.description_weight * desc_sim + self.ranking.code_weight * code_sim
                )
            else:
                # Description only
                score = desc_sim

            # Apply threshold
            if score >= self.ranking.min_score_threshold:
                scored.append((score, name))

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)

        # Return top skills
        return [self._skills[name] for _, name in scored[:limit]]

    def get(self, name: str) -> PythonSkill | None:
        """Get skill by exact name."""
        return self._skills.get(name)


def create_skill_library(
    store: SkillStore | None = None,
    embedder: EmbeddingProvider | None = None,
    embedding_model: str | None = None,
) -> SkillLibrary:
    """Create a skill library, optionally backed by storage.

    This is the recommended way to create a SkillLibrary for production use.

    Args:
        store: Optional storage (MemorySkillStore, FileSkillStore, RedisSkillStore, etc.).
               If provided, skills are loaded and indexed at creation time.
        embedder: Optional embedding provider. If not provided, creates Embedder
                  with the specified embedding_model.
        embedding_model: Model alias ("bge-small", "bge-base", "granite") or full
                        HuggingFace model name. Default: "bge-small".

    Returns:
        SkillLibrary configured with the provided store and embedder.

    Example:
        # In-memory only (default BGE-small model)
        library = create_skill_library()

        # With file-based store
        from py_code_mode.skill_store import FileSkillStore
        store = FileSkillStore(Path("./skills"))
        library = create_skill_library(store=store)

        # With custom model
        library = create_skill_library(embedding_model="bge-base")
    """
    if embedder is None:
        embedder = Embedder(model_name=embedding_model)
    return SkillLibrary(embedder=embedder, store=store)
