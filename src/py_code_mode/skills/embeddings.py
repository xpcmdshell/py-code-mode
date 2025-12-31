"""Embedding providers for semantic search."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

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

# Known dimensions for common models (avoids loading model just to get dimension)
MODEL_DIMENSIONS = {
    "BAAI/bge-small-en-v1.5": 384,
    "BAAI/bge-base-en-v1.5": 768,
    "ibm-granite/granite-embedding-small-english-r2": 384,
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

    The model is loaded lazily on first embed() or embed_query() call to avoid
    30+ second initialization overhead when embeddings aren't actually used.
    """

    DEFAULT_MODEL = "bge-small"
    QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "

    def __init__(self, model_name: str | None = None) -> None:
        """Initialize embedder.

        Args:
            model_name: Model alias or full HuggingFace name. Default: bge-small.

        Note: The model is not loaded until embed() or embed_query() is called.
        """
        # Suppress tokenizer parallelism warning when forking
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

        # Store model name for lazy loading
        model_name = model_name or self.DEFAULT_MODEL
        self._resolved_model_name = resolve_model_name(model_name)

        # Lazy-loaded attributes
        self._model: SentenceTransformer | None = None
        self._device: str | None = None

    def _detect_device(self) -> str:
        """Detect best available device."""
        import torch

        if torch.cuda.is_available():
            return "cuda"
        elif torch.backends.mps.is_available():
            return "mps"
        return "cpu"

    def _ensure_model_loaded(self) -> None:
        """Load the SentenceTransformer model if not already loaded."""
        if self._model is not None:
            return

        from sentence_transformers import SentenceTransformer

        self._device = self._detect_device()
        self._model = SentenceTransformer(self._resolved_model_name, device=self._device)

    @property
    def device(self) -> str:
        """Device the model runs on (cuda, mps, or cpu)."""
        self._ensure_model_loaded()
        assert self._device is not None  # Guaranteed after _ensure_model_loaded
        return self._device

    @property
    def dimension(self) -> int:
        """Embedding vector dimension.

        Uses known dimensions for common models to avoid loading the model.
        Falls back to loading the model for unknown models.
        """
        # Return known dimension without loading model if possible
        if self._resolved_model_name in MODEL_DIMENSIONS:
            return MODEL_DIMENSIONS[self._resolved_model_name]

        # Unknown model: must load to get dimension
        self._ensure_model_loaded()
        assert self._model is not None  # Guaranteed after _ensure_model_loaded
        dim = self._model.get_sentence_embedding_dimension()
        assert dim is not None
        return dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed document texts into vectors (no prefix).

        Args:
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors.
        """
        self._ensure_model_loaded()
        assert self._model is not None  # Guaranteed after _ensure_model_loaded
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
        self._ensure_model_loaded()
        assert self._model is not None  # Guaranteed after _ensure_model_loaded
        text = self.QUERY_INSTRUCTION + query
        embedding = self._model.encode([text], normalize_embeddings=True)[0]
        return embedding.tolist()  # type: ignore[return-value]


class LazyEmbedder:
    """Lazy wrapper for Embedder that defers construction until first use.

    This is useful when VectorStore construction should be instant but the
    embedding model (~100MB, ~4s load) is only needed when add() or search()
    is called.

    The dimension property uses MODEL_DIMENSIONS lookup for known models,
    avoiding model construction just to query dimension.
    """

    def __init__(self, model_name: str | None = None) -> None:
        """Initialize lazy embedder.

        Args:
            model_name: Model alias or full HuggingFace name. Default: bge-small.

        Note: The actual Embedder is not created until embed() or embed_query() is called.
        """
        self._model_name = model_name or Embedder.DEFAULT_MODEL
        self._resolved_model_name = resolve_model_name(self._model_name)
        self._embedder: Embedder | None = None

    def _ensure_embedder(self) -> Embedder:
        """Create the Embedder if not already created."""
        if self._embedder is None:
            self._embedder = Embedder(model_name=self._model_name)
        return self._embedder

    @property
    def dimension(self) -> int:
        """Embedding vector dimension.

        Returns from lookup table if possible to avoid model construction.
        Falls back to loading the model for unknown models.
        """
        if self._resolved_model_name in MODEL_DIMENSIONS:
            return MODEL_DIMENSIONS[self._resolved_model_name]
        # Unknown model - must construct to get dimension
        return self._ensure_embedder().dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed document texts into vectors.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors.
        """
        return self._ensure_embedder().embed(texts)

    def embed_query(self, query: str) -> list[float]:
        """Embed query text into vector.

        Args:
            query: Search query text.

        Returns:
            Embedding vector.
        """
        return self._ensure_embedder().embed_query(query)


class BackgroundEmbedder:
    """Embedder that loads model in a background thread.

    Construction returns immediately, starting model load in background.
    Methods block until the model is ready. This allows session startup
    to proceed while the model loads in parallel.

    The dimension property uses MODEL_DIMENSIONS lookup for known models,
    returning instantly without waiting for the model to load.
    """

    def __init__(self, model_name: str | None = None) -> None:
        """Initialize and start background model loading.

        Args:
            model_name: Model alias or full HuggingFace name. Default: bge-small.

        Note: Construction returns immediately. Model loading happens in a
        background thread. Methods that require the model will block until
        loading completes.
        """
        import threading

        self._model_name = model_name or Embedder.DEFAULT_MODEL
        self._resolved_model_name = resolve_model_name(self._model_name)
        self._embedder: Embedder | None = None
        self._ready = threading.Event()
        self._error: Exception | None = None

        # Start loading immediately in background
        self._thread = threading.Thread(target=self._load, daemon=True)
        self._thread.start()

    def _load(self) -> None:
        """Load the embedder in background thread."""
        try:
            self._embedder = Embedder(model_name=self._model_name)
        except Exception as e:
            self._error = e
        finally:
            self._ready.set()

    def _wait_for_ready(self) -> Embedder:
        """Wait for model to be ready and return it.

        Returns:
            The loaded Embedder instance.

        Raises:
            Exception: If model loading failed, re-raises the original error.
        """
        self._ready.wait()
        if self._error is not None:
            raise self._error
        assert self._embedder is not None
        return self._embedder

    @property
    def dimension(self) -> int:
        """Embedding vector dimension.

        Returns instantly for known models using the lookup table.
        Falls back to waiting for the model for unknown models.
        """
        if self._resolved_model_name in MODEL_DIMENSIONS:
            return MODEL_DIMENSIONS[self._resolved_model_name]
        return self._wait_for_ready().dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed document texts into vectors.

        Waits for the model to be ready if still loading.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors.
        """
        return self._wait_for_ready().embed(texts)

    def embed_query(self, query: str) -> list[float]:
        """Embed query text into vector.

        Waits for the model to be ready if still loading.

        Args:
            query: Search query text.

        Returns:
            Embedding vector.
        """
        return self._wait_for_ready().embed_query(query)
