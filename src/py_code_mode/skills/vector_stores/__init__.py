"""VectorStore implementations for skill embedding caching."""

from __future__ import annotations

# ChromaDB is an optional dependency
try:
    from py_code_mode.skills.vector_stores.chroma import ChromaVectorStore

    CHROMA_AVAILABLE = True
except ImportError:
    ChromaVectorStore = None  # type: ignore[assignment, misc]
    CHROMA_AVAILABLE = False

__all__ = [
    "ChromaVectorStore",
    "CHROMA_AVAILABLE",
]
