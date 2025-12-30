"""VectorStore implementations for skill embedding caching."""

from __future__ import annotations

# ChromaDB is an optional dependency
try:
    from py_code_mode.skills.vector_stores.chroma import ChromaVectorStore

    CHROMA_AVAILABLE = True
except ImportError:
    ChromaVectorStore = None  # type: ignore[assignment, misc]
    CHROMA_AVAILABLE = False

# Redis is an optional dependency
try:
    from py_code_mode.skills.vector_stores.redis_store import RedisVectorStore

    REDIS_AVAILABLE = True
except ImportError:
    RedisVectorStore = None  # type: ignore[assignment, misc]
    REDIS_AVAILABLE = False

__all__ = [
    "ChromaVectorStore",
    "CHROMA_AVAILABLE",
    "RedisVectorStore",
    "REDIS_AVAILABLE",
]
