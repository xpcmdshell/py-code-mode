"""Workflow library with semantic search capabilities."""

from __future__ import annotations

import builtins
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from py_code_mode.workflows.embeddings import (
    Embedder,
    EmbeddingProvider,
    cosine_similarity,
)
from py_code_mode.workflows.store import WorkflowStore
from py_code_mode.workflows.vector_store import VectorStore, compute_content_hash
from py_code_mode.workflows.workflow import PythonWorkflow

if TYPE_CHECKING:
    pass


@dataclass
class RankingConfig:
    """Configuration for search ranking formula.

    Tune these based on your workflow library characteristics.
    """

    description_weight: float = 0.7
    code_weight: float = 0.3
    min_score_threshold: float = 0.0  # 0 = return all, 0.8 = high confidence only
    code_min_length: int = 0  # Min code chars to include code embedding (0 = always)


@dataclass
class WorkflowLibrary:
    """Workflow management with semantic search.

    The primary interface for working with workflows. Provides:
    - Semantic search using embeddings
    - Optional persistence via WorkflowStore
    - Optional VectorStore for embedding caching
    - Workflow lifecycle management (add, remove, get, list)

    If a store is provided, workflows are persisted there and loaded at
    construction time. Use refresh() to reload from store.

    If a vector_store is provided, embeddings are cached there and
    search is delegated to the vector_store. Otherwise, in-memory
    embeddings are used.

    Ranking formula is configurable via RankingConfig.
    """

    embedder: EmbeddingProvider
    store: WorkflowStore | None = None
    vector_store: VectorStore | None = None
    ranking: RankingConfig = field(default_factory=RankingConfig)
    _workflows: dict[str, PythonWorkflow] = field(default_factory=dict)
    _description_vectors: dict[str, list[float]] = field(default_factory=dict)
    _code_vectors: dict[str, list[float]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Load and index workflows from store if provided."""
        if self.store is not None:
            self.refresh()

    def __len__(self) -> int:
        return len(self._workflows)

    def refresh(self) -> None:
        """Reload all workflows from store and rebuild embedding index.

        Clears in-memory state and reloads from the store. When a VectorStore
        is configured, content-hash checking in _index_workflow() handles caching:
        - New workflows: indexed (hash not found)
        - Changed workflows: re-indexed (hash mismatch)
        - Unchanged workflows: skipped (hash match, fast path)
        - Deleted workflows: stale vectors remain in VectorStore but search()
          filters results via _workflows dict

        No-op if no store is configured.
        """
        if self.store is None:
            return

        # Clear current in-memory index
        self._workflows.clear()
        self._description_vectors.clear()
        self._code_vectors.clear()

        # Load and index all workflows from store
        # Note: VectorStore is NOT cleared - _index_workflow() uses content hashes
        # to skip re-embedding unchanged workflows
        for workflow in self.store.list_all():
            self._index_workflow(workflow)

    def _index_workflow(self, workflow: PythonWorkflow) -> None:
        """Add workflow to local embedding index without touching store.

        If vector_store is configured, embeddings are cached there with
        content hash checking to skip re-embedding unchanged workflows.
        """
        # Always add to _workflows dict for get() by name
        self._workflows[workflow.name] = workflow

        if self.vector_store is not None:
            # Use vector_store with content hash checking
            content_hash = compute_content_hash(workflow.description, workflow.source)
            stored_hash = self.vector_store.get_content_hash(workflow.name)

            if stored_hash != content_hash:
                # New or changed workflow - add to vector_store
                self.vector_store.add(
                    id=workflow.name,
                    description=workflow.description,
                    source=workflow.source,
                    content_hash=content_hash,
                )
        else:
            # Fallback: in-memory vectors
            # Embed description
            desc_vec = self.embedder.embed([workflow.description])[0]
            self._description_vectors[workflow.name] = desc_vec

            # Embed source code
            code_vec = self.embedder.embed([workflow.source])[0]
            self._code_vectors[workflow.name] = code_vec

    def add(self, workflow: PythonWorkflow) -> None:
        """Add a workflow to the library.

        Stores in store (if configured) and indexes embeddings for search.
        """
        # Store if configured
        if self.store is not None:
            self.store.save(workflow)

        # Index locally for semantic search
        self._index_workflow(workflow)

    def list(self) -> builtins.list[PythonWorkflow]:
        """List all workflows."""
        return list(self._workflows.values())

    def remove(self, name: str) -> bool:
        """Remove a workflow from the library.

        Removes from store (if configured), vector_store (if configured),
        and from local embedding index.

        Returns:
            True if workflow was removed, False if not found.
        """
        # Remove from store if configured
        if self.store is not None:
            self.store.delete(name)

        # Remove from vector_store if configured
        if self.vector_store is not None:
            self.vector_store.remove(name)

        # Remove from local index
        if name not in self._workflows:
            return False
        del self._workflows[name]
        if name in self._description_vectors:
            del self._description_vectors[name]
        if name in self._code_vectors:
            del self._code_vectors[name]
        return True

    def search(
        self,
        query: str,
        limit: int = 10,
    ) -> builtins.list[PythonWorkflow]:
        """Search for workflows by semantic similarity.

        Args:
            query: Natural language search query.
            limit: Maximum results to return.

        Returns:
            Workflows ranked by combined semantic similarity.
        """
        if not self._workflows:
            return []

        # Delegate to vector_store if configured
        if self.vector_store is not None:
            results = self.vector_store.search(
                query=query,
                limit=limit,
                desc_weight=self.ranking.description_weight,
                code_weight=self.ranking.code_weight,
            )
            # Filter out stale vectors: if a workflow was deleted from the store
            # but its vectors remain in VectorStore (refresh doesn't clear VectorStore),
            # exclude it from results by checking _workflows membership
            return [self._workflows[r.id] for r in results if r.id in self._workflows]

        # Fallback: in-memory cosine similarity
        # Embed query (uses instruction prefix for retrieval models)
        query_vec = self.embedder.embed_query(query)

        # Score each workflow
        scored: list[tuple[float, str]] = []
        for name, workflow in self._workflows.items():
            # Cosine similarity with description
            desc_sim = cosine_similarity(query_vec, self._description_vectors[name])

            # Cosine similarity with code (if code is substantial enough)
            if (
                len(workflow.source) >= self.ranking.code_min_length
                and self.ranking.code_weight > 0
            ):
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

        # Return top workflows
        return [self._workflows[name] for _, name in scored[:limit]]

    def get(self, name: str) -> PythonWorkflow | None:
        """Get workflow by exact name."""
        return self._workflows.get(name)


def create_workflow_library(
    store: WorkflowStore | None = None,
    embedder: EmbeddingProvider | None = None,
    embedding_model: str | None = None,
    vector_store: VectorStore | None = None,
) -> WorkflowLibrary:
    """Create a workflow library, optionally backed by storage.

    This is the recommended way to create a WorkflowLibrary for production use.

    Args:
        store: Optional storage (MemoryWorkflowStore, FileWorkflowStore, RedisWorkflowStore, etc.).
               If provided, workflows are loaded and indexed at creation time.
        embedder: Optional embedding provider. If not provided, creates Embedder
                  with the specified embedding_model.
        embedding_model: Model alias ("bge-small", "bge-base", "granite") or full
                        HuggingFace model name. Default: "bge-small".
        vector_store: Optional VectorStore for embedding caching. If provided,
                      embeddings are cached there and search is delegated to it.

    Returns:
        WorkflowLibrary configured with the provided store, embedder, and vector_store.

    Example:
        # In-memory only (default BGE-small model)
        library = create_workflow_library()

        # With file-based store
        from py_code_mode.workflows.store import FileWorkflowStore
        store = FileWorkflowStore(Path("./workflows"))
        library = create_workflow_library(store=store)

        # With custom model
        library = create_workflow_library(embedding_model="bge-base")

        # With vector store for embedding caching
        library = create_workflow_library(store=store, vector_store=my_vector_store)
    """
    if embedder is None:
        embedder = Embedder(model_name=embedding_model)
    return WorkflowLibrary(embedder=embedder, store=store, vector_store=vector_store)
