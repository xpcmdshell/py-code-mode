"""Tests for BackgroundEmbedder."""

import time

import pytest


class TestBackgroundEmbedder:
    """Tests for background model loading."""

    def test_construction_returns_immediately(self) -> None:
        """Constructor should return without waiting for model load."""
        from py_code_mode.skills import BackgroundEmbedder

        start = time.time()
        embedder = BackgroundEmbedder()
        elapsed = time.time() - start

        # Construction should be nearly instant (< 0.5s)
        # Model load takes ~4s, so if this is fast, we're not blocking
        assert elapsed < 0.5, f"Construction took {elapsed:.2f}s, should be instant"

        # Clean up - wait for thread to finish to avoid resource warnings
        embedder._ready.wait(timeout=30)

    def test_dimension_returns_instantly_for_known_models(self) -> None:
        """Dimension should return from lookup table without waiting."""
        from py_code_mode.skills import BackgroundEmbedder

        embedder = BackgroundEmbedder()  # Starts background load

        start = time.time()
        dim = embedder.dimension
        elapsed = time.time() - start

        assert dim == 384  # bge-small dimension
        assert elapsed < 0.1, f"dimension took {elapsed:.2f}s, should be instant"

        # Clean up
        embedder._ready.wait(timeout=30)

    def test_embed_waits_for_model(self) -> None:
        """embed() should wait for model to be ready."""
        from py_code_mode.skills import BackgroundEmbedder

        embedder = BackgroundEmbedder()

        # This will block until model is ready
        result = embedder.embed(["test"])

        assert len(result) == 1
        assert len(result[0]) == 384

    def test_embed_query_waits_for_model(self) -> None:
        """embed_query() should wait for model to be ready."""
        from py_code_mode.skills import BackgroundEmbedder

        embedder = BackgroundEmbedder()

        result = embedder.embed_query("test query")

        assert len(result) == 384

    def test_model_loads_in_background(self) -> None:
        """Verify model actually loads in a separate thread."""
        from py_code_mode.skills import BackgroundEmbedder

        embedder = BackgroundEmbedder()

        # The loading thread should be running or already completed
        assert embedder._thread.is_alive() or embedder._ready.is_set()

        # Wait for it to complete
        embedder._ready.wait(timeout=30)
        assert embedder._ready.is_set()
        assert embedder._embedder is not None

    def test_error_propagates_on_first_use(self) -> None:
        """Errors during load should propagate when methods are called."""
        from py_code_mode.skills import BackgroundEmbedder

        # Use an invalid model name to trigger an error
        embedder = BackgroundEmbedder(model_name="nonexistent-model-xyz-123")

        # embed() should raise the error from the background thread
        with pytest.raises(Exception):  # OSError or similar from sentence-transformers
            embedder.embed(["test"])

    def test_multiple_calls_after_ready(self) -> None:
        """Multiple calls after model is ready should work without blocking."""
        from py_code_mode.skills import BackgroundEmbedder

        embedder = BackgroundEmbedder()

        # First call waits for model
        result1 = embedder.embed(["first"])

        # Subsequent calls should be fast
        start = time.time()
        result2 = embedder.embed(["second"])
        result3 = embedder.embed_query("third")
        elapsed = time.time() - start

        assert len(result1) == 1
        assert len(result2) == 1
        assert len(result3) == 384

        # Subsequent calls should complete quickly (model is already loaded)
        # Allow some time for embedding computation itself
        assert elapsed < 2.0, f"Subsequent calls took {elapsed:.2f}s, should be fast"

    def test_conforms_to_embedding_provider_protocol(self) -> None:
        """BackgroundEmbedder should conform to EmbeddingProvider protocol."""
        from py_code_mode.skills import BackgroundEmbedder, EmbeddingProvider

        embedder = BackgroundEmbedder()

        # Check protocol conformance
        assert isinstance(embedder, EmbeddingProvider)

        # Clean up
        embedder._ready.wait(timeout=30)
