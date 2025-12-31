"""Tests for LazyEmbedder - deferred embedding model construction."""

from unittest.mock import MagicMock, patch

import pytest

from py_code_mode.skills.embeddings import (
    MODEL_DIMENSIONS,
    Embedder,
    LazyEmbedder,
    resolve_model_name,
)


class TestLazyEmbedderDimension:
    """Tests for LazyEmbedder.dimension property."""

    def test_dimension_returns_without_loading_model_for_known_models(self) -> None:
        """For known models, dimension should return without constructing Embedder."""
        # Use a known model
        embedder = LazyEmbedder(model_name="bge-small")

        # Verify embedder is not constructed yet
        assert embedder._embedder is None

        # Get dimension
        dim = embedder.dimension

        # Should still not have constructed the embedder (used lookup table)
        assert embedder._embedder is None

        # Should return correct dimension from lookup table
        resolved_name = resolve_model_name("bge-small")
        assert dim == MODEL_DIMENSIONS[resolved_name]

    def test_dimension_for_default_model_uses_lookup(self) -> None:
        """Default model (bge-small) should use lookup table for dimension."""
        embedder = LazyEmbedder()

        # Get dimension without constructing embedder
        dim = embedder.dimension

        # Embedder should not be constructed
        assert embedder._embedder is None

        # Should return 384 for bge-small
        assert dim == 384

    def test_unknown_model_dimension_triggers_construction(self) -> None:
        """For unknown models, dimension must construct the Embedder."""
        with (
            patch.object(Embedder, "_ensure_model_loaded"),
            patch.object(Embedder, "dimension", new_callable=lambda: property(lambda self: 512)),
        ):
            # Use an unknown model name
            embedder = LazyEmbedder(model_name="some-unknown-model/custom")

            # Verify embedder is not constructed yet
            assert embedder._embedder is None

            # Getting dimension should trigger construction
            dim = embedder.dimension

            # Embedder should now be constructed
            assert embedder._embedder is not None
            assert dim == 512


class TestLazyEmbedderConstruction:
    """Tests for LazyEmbedder construction behavior."""

    def test_embed_triggers_construction(self) -> None:
        """First embed() call should construct the Embedder."""
        embedder = LazyEmbedder(model_name="bge-small")

        # Verify embedder is not constructed yet
        assert embedder._embedder is None

        # Mock the Embedder class to avoid actually loading the model
        mock_inner_embedder = MagicMock()
        mock_inner_embedder.embed.return_value = [[0.1, 0.2, 0.3]]

        with patch.object(LazyEmbedder, "_ensure_embedder", return_value=mock_inner_embedder):
            result = embedder.embed(["test text"])

        # Should have called embed on the inner embedder
        mock_inner_embedder.embed.assert_called_once_with(["test text"])
        assert result == [[0.1, 0.2, 0.3]]

    def test_embed_query_triggers_construction(self) -> None:
        """First embed_query() call should construct the Embedder."""
        embedder = LazyEmbedder(model_name="bge-small")

        # Verify embedder is not constructed yet
        assert embedder._embedder is None

        # Mock the Embedder class to avoid actually loading the model
        mock_inner_embedder = MagicMock()
        mock_inner_embedder.embed_query.return_value = [0.1, 0.2, 0.3]

        with patch.object(LazyEmbedder, "_ensure_embedder", return_value=mock_inner_embedder):
            result = embedder.embed_query("test query")

        # Should have called embed_query on the inner embedder
        mock_inner_embedder.embed_query.assert_called_once_with("test query")
        assert result == [0.1, 0.2, 0.3]

    def test_multiple_calls_reuse_embedder(self) -> None:
        """Multiple embed/embed_query calls should reuse the same Embedder instance."""
        embedder = LazyEmbedder(model_name="bge-small")

        # Track how many times Embedder is constructed
        construction_count = 0
        original_ensure = embedder._ensure_embedder

        def counting_ensure() -> Embedder:
            nonlocal construction_count
            result = original_ensure()
            if embedder._embedder is not None:
                construction_count += 1
            return result

        # Create a mock that still calls through to real construction
        # but we can track it
        mock_inner = MagicMock()
        mock_inner.embed.return_value = [[0.1, 0.2, 0.3]]
        mock_inner.embed_query.return_value = [0.4, 0.5, 0.6]

        # First call constructs
        with patch.object(LazyEmbedder, "_ensure_embedder", return_value=mock_inner) as mock_ensure:
            embedder.embed(["text1"])
            embedder.embed(["text2"])
            embedder.embed_query("query1")
            embedder.embed_query("query2")

            # _ensure_embedder should be called for each operation
            assert mock_ensure.call_count == 4

        # But if we use the real implementation, the inner embedder is reused
        embedder2 = LazyEmbedder(model_name="bge-small")

        # Manually set a mock embedder
        embedder2._embedder = mock_inner

        # Now calls should use the existing embedder
        embedder2.embed(["text"])
        embedder2.embed_query("query")

        # The mock should have been called
        assert mock_inner.embed.call_count == 3  # 2 from first batch + 1 new
        assert mock_inner.embed_query.call_count == 3  # 2 from first batch + 1 new


class TestLazyEmbedderProtocol:
    """Tests that LazyEmbedder satisfies EmbeddingProvider protocol."""

    def test_has_required_methods(self) -> None:
        """LazyEmbedder should have all methods required by EmbeddingProvider."""
        embedder = LazyEmbedder()

        # Check required attributes/methods exist
        assert hasattr(embedder, "dimension")
        assert hasattr(embedder, "embed")
        assert hasattr(embedder, "embed_query")

        # dimension should be a property
        assert isinstance(type(embedder).dimension, property)

        # embed and embed_query should be callable
        assert callable(embedder.embed)
        assert callable(embedder.embed_query)

    def test_dimension_is_int(self) -> None:
        """dimension property should return an int."""
        embedder = LazyEmbedder()
        dim = embedder.dimension
        assert isinstance(dim, int)
        assert dim > 0


class TestLazyEmbedderModelNames:
    """Tests for model name handling in LazyEmbedder."""

    @pytest.mark.parametrize(
        "alias,expected_resolved",
        [
            ("bge-small", "BAAI/bge-small-en-v1.5"),
            ("bge-base", "BAAI/bge-base-en-v1.5"),
            ("granite", "ibm-granite/granite-embedding-small-english-r2"),
        ],
    )
    def test_model_alias_resolution(self, alias: str, expected_resolved: str) -> None:
        """Model aliases should be resolved correctly."""
        embedder = LazyEmbedder(model_name=alias)
        assert embedder._resolved_model_name == expected_resolved

    def test_full_model_name_passthrough(self) -> None:
        """Full HuggingFace model names should pass through unchanged."""
        full_name = "sentence-transformers/all-MiniLM-L6-v2"
        embedder = LazyEmbedder(model_name=full_name)
        assert embedder._resolved_model_name == full_name

    def test_default_model_is_bge_small(self) -> None:
        """Default model should be bge-small."""
        embedder = LazyEmbedder()
        assert embedder._model_name == Embedder.DEFAULT_MODEL
        assert embedder._resolved_model_name == resolve_model_name(Embedder.DEFAULT_MODEL)
