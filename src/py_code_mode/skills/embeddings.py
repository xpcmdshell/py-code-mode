"""Embedding providers for semantic search."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np


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
        # Suppress tokenizer parallelism warning when forking
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

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
