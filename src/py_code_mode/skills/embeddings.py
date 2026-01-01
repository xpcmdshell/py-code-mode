"""Embedding providers for semantic search."""

from __future__ import annotations

import os
import threading
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

    def __init__(self, model_name: str | None = None, start_loading: bool = False) -> None:
        """Initialize embedder.

        Args:
            model_name: Model alias or full HuggingFace name. Default: bge-small.
            start_loading: If True, start loading the model in a background thread
                immediately. The first embed() call will block until loading completes.

        Note: By default, the model is not loaded until embed() or embed_query()
        is called. Use start_loading=True for MCP servers to reduce first-search latency.
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
        self._loading_lock = threading.Lock()
        self._loading_thread: threading.Thread | None = None

        if start_loading:
            self._start_background_loading()

    def _detect_device(self) -> str:
        """Detect best available device."""
        import torch

        if torch.cuda.is_available():
            return "cuda"
        elif torch.backends.mps.is_available():
            return "mps"
        return "cpu"

    def _start_background_loading(self) -> None:
        """Start loading the model in a background thread."""
        if self._loading_thread is not None:
            return

        def load():
            self._load_model()

        self._loading_thread = threading.Thread(target=load, daemon=True)
        self._loading_thread.start()

    def _load_model(self) -> None:
        """Load the SentenceTransformer model (thread-safe)."""
        with self._loading_lock:
            if self._model is not None:
                return

            from sentence_transformers import SentenceTransformer

            self._device = self._detect_device()
            self._model = SentenceTransformer(self._resolved_model_name, device=self._device)

    def _ensure_model_loaded(self) -> None:
        """Ensure model is loaded, blocking if background loading is in progress."""
        # Wait for background thread if it's running
        if self._loading_thread is not None:
            self._loading_thread.join()

        # Load if not already loaded (handles case where no background loading)
        if self._model is None:
            self._load_model()

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
