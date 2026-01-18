"""VectorStore protocol and core types for workflow embedding caching."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class ModelInfo:
    """Information about the embedding model used by a VectorStore.

    Used to detect model changes and invalidate cached embeddings.
    """

    model_name: str
    dimension: int
    version: str = "1"


@dataclass(frozen=True)
class SearchResult:
    """Result from a VectorStore similarity search.

    Attributes:
        id: The workflow identifier.
        score: Similarity score (0.0 to 1.0, higher is more similar).
        metadata: Additional metadata about the match.
    """

    id: str
    score: float
    metadata: dict[str, Any]


@runtime_checkable
class VectorStore(Protocol):
    """Protocol for vector stores that cache workflow embeddings.

    VectorStore implementations persist embeddings for workflows, enabling
    fast semantic search without re-embedding on every startup.
    """

    def add(self, id: str, description: str, source: str, content_hash: str) -> None:
        """Add or update a workflow's embeddings in the store.

        Args:
            id: Unique identifier for the workflow.
            description: Workflow description text to embed.
            source: Workflow source code to embed.
            content_hash: Hash of description + source for change detection.
        """
        ...

    def remove(self, id: str) -> bool:
        """Remove a workflow's embeddings from the store.

        Args:
            id: Unique identifier for the workflow.

        Returns:
            True if the workflow was removed, False if it wasn't in the store.
        """
        ...

    def search(
        self,
        query: str,
        limit: int,
        desc_weight: float,
        code_weight: float,
    ) -> list[SearchResult]:
        """Search for workflows by semantic similarity.

        Args:
            query: Search query text.
            limit: Maximum number of results to return.
            desc_weight: Weight for description similarity (0.0 to 1.0).
            code_weight: Weight for code similarity (0.0 to 1.0).

        Returns:
            List of SearchResult objects, sorted by score descending.
        """
        ...

    def get_content_hash(self, id: str) -> str | None:
        """Get the stored content hash for a workflow.

        Args:
            id: Unique identifier for the workflow.

        Returns:
            The content hash if the workflow exists, None otherwise.
        """
        ...

    def count(self) -> int:
        """Get the number of workflows indexed in the store.

        Returns:
            Number of unique workflows with embeddings.
        """
        ...

    def get_model_info(self) -> ModelInfo:
        """Return embedder model identity for cache validation."""
        ...

    def clear(self) -> None:
        """Remove all stored embeddings."""
        ...


def compute_content_hash(description: str, source: str) -> str:
    """Compute a content hash for change detection.

    Uses SHA-256 and returns the first 16 characters (8 bytes) of the hex digest.

    Args:
        description: Workflow description text.
        source: Workflow source code.

    Returns:
        16-character hex string hash.
    """
    combined = f"{description}|||{source}"
    return hashlib.sha256(combined.encode()).hexdigest()[:16]
