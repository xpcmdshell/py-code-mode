"""Skill library with semantic search capabilities."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from py_code_mode.skills.embeddings import (
    Embedder,
    EmbeddingProvider,
    cosine_similarity,
)
from py_code_mode.skills.skill import PythonSkill
from py_code_mode.skills.store import SkillStore
from py_code_mode.skills.vector_store import VectorStore, compute_content_hash

if TYPE_CHECKING:
    pass


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
    - Optional VectorStore for embedding caching
    - Skill lifecycle management (add, remove, get, list)

    If a store is provided, skills are persisted there and loaded at
    construction time. Use refresh() to reload from store.

    If a vector_store is provided, embeddings are cached there and
    search is delegated to the vector_store. Otherwise, in-memory
    embeddings are used.

    Ranking formula is configurable via RankingConfig.
    """

    embedder: EmbeddingProvider
    store: SkillStore | None = None
    vector_store: VectorStore | None = None
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

        Clears in-memory state and reloads from the store. When a VectorStore
        is configured, content-hash checking in _index_skill() handles caching:
        - New skills: indexed (hash not found)
        - Changed skills: re-indexed (hash mismatch)
        - Unchanged skills: skipped (hash match, fast path)
        - Deleted skills: stale vectors remain in VectorStore but search()
          filters results via _skills dict

        No-op if no store is configured.
        """
        if self.store is None:
            return

        # Clear current in-memory index
        self._skills.clear()
        self._description_vectors.clear()
        self._code_vectors.clear()

        # Load and index all skills from store
        # Note: VectorStore is NOT cleared - _index_skill() uses content hashes
        # to skip re-embedding unchanged skills
        for skill in self.store.list_all():
            self._index_skill(skill)

    def _index_skill(self, skill: PythonSkill) -> None:
        """Add skill to local embedding index without touching store.

        If vector_store is configured, embeddings are cached there with
        content hash checking to skip re-embedding unchanged skills.
        """
        # Always add to _skills dict for get() by name
        self._skills[skill.name] = skill

        if self.vector_store is not None:
            # Use vector_store with content hash checking
            content_hash = compute_content_hash(skill.description, skill.source)
            stored_hash = self.vector_store.get_content_hash(skill.name)

            if stored_hash != content_hash:
                # New or changed skill - add to vector_store
                self.vector_store.add(
                    id=skill.name,
                    description=skill.description,
                    source=skill.source,
                    content_hash=content_hash,
                )
        else:
            # Fallback: in-memory vectors
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

        Removes from store (if configured), vector_store (if configured),
        and from local embedding index.

        Returns:
            True if skill was removed, False if not found.
        """
        # Remove from store if configured
        if self.store is not None:
            self.store.delete(name)

        # Remove from vector_store if configured
        if self.vector_store is not None:
            self.vector_store.remove(name)

        # Remove from local index
        if name not in self._skills:
            return False
        del self._skills[name]
        if name in self._description_vectors:
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

        # Delegate to vector_store if configured
        if self.vector_store is not None:
            results = self.vector_store.search(
                query=query,
                limit=limit,
                desc_weight=self.ranking.description_weight,
                code_weight=self.ranking.code_weight,
            )
            # Filter out stale vectors: if a skill was deleted from the store
            # but its vectors remain in VectorStore (refresh doesn't clear VectorStore),
            # exclude it from results by checking _skills membership
            return [self._skills[r.id] for r in results if r.id in self._skills]

        # Fallback: in-memory cosine similarity
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
    vector_store: VectorStore | None = None,
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
        vector_store: Optional VectorStore for embedding caching. If provided,
                      embeddings are cached there and search is delegated to it.

    Returns:
        SkillLibrary configured with the provided store, embedder, and vector_store.

    Example:
        # In-memory only (default BGE-small model)
        library = create_skill_library()

        # With file-based store
        from py_code_mode.skills.store import FileSkillStore
        store = FileSkillStore(Path("./skills"))
        library = create_skill_library(store=store)

        # With custom model
        library = create_skill_library(embedding_model="bge-base")

        # With vector store for embedding caching
        library = create_skill_library(store=store, vector_store=my_vector_store)
    """
    if embedder is None:
        embedder = Embedder(model_name=embedding_model)
    return SkillLibrary(embedder=embedder, store=store, vector_store=vector_store)
