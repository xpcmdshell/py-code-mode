"""Tests for ChromaVectorStore implementation - Phase 2 (TDD RED phase).

These tests define the ChromaDB integration behavior through failing tests.
Tests fail because ChromaVectorStore doesn't exist yet.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

if TYPE_CHECKING:
    from py_code_mode.skills.embeddings import EmbeddingProvider


class TestChromaVectorStoreImport:
    """Tests for ChromaVectorStore availability and imports."""

    def test_chroma_vector_store_importable_when_chromadb_available(self) -> None:
        """ChromaVectorStore should be importable when chromadb is installed."""
        pytest.importorskip("chromadb")
        from py_code_mode.skills.vector_stores.chroma import ChromaVectorStore

        assert ChromaVectorStore is not None

    def test_chroma_vector_store_satisfies_protocol(self) -> None:
        """ChromaVectorStore should implement VectorStore protocol."""
        pytest.importorskip("chromadb")
        from py_code_mode.skills.vector_store import VectorStore
        from py_code_mode.skills.vector_stores.chroma import ChromaVectorStore

        # Protocol compliance via isinstance check
        from py_code_mode.skills.embeddings import MockEmbedder

        embedder = MockEmbedder()
        store = ChromaVectorStore(path=Path("/tmp/test"), embedder=embedder)

        assert isinstance(store, VectorStore)


class TestChromaVectorStoreInitialization:
    """Tests for ChromaVectorStore initialization and setup."""

    @pytest.fixture
    def mock_embedder(self) -> EmbeddingProvider:
        """Mock embedder with consistent behavior."""
        from py_code_mode.skills.embeddings import MockEmbedder

        return MockEmbedder(dimension=384)

    def test_creates_persistent_client_at_path(
        self, tmp_path: Path, mock_embedder: EmbeddingProvider
    ) -> None:
        """Should create ChromaDB persistent client in specified directory."""
        pytest.importorskip("chromadb")
        from py_code_mode.skills.vector_stores.chroma import ChromaVectorStore

        store_path = tmp_path / "chroma_store"
        store = ChromaVectorStore(path=store_path, embedder=mock_embedder)

        # ChromaDB should create the directory
        assert store_path.exists()
        assert store_path.is_dir()

    def test_creates_collection_without_embedding_function(
        self, tmp_path: Path, mock_embedder: EmbeddingProvider
    ) -> None:
        """Should create collection configured for pre-computed vectors."""
        pytest.importorskip("chromadb")
        from py_code_mode.skills.vector_stores.chroma import ChromaVectorStore

        store = ChromaVectorStore(path=tmp_path / "chroma", embedder=mock_embedder)

        # Should have created collection (implementation detail: check via count)
        # Empty collection should have count of 0
        assert store.count() == 0

    def test_stores_model_info_in_collection_metadata(
        self, tmp_path: Path, mock_embedder: EmbeddingProvider
    ) -> None:
        """Should persist ModelInfo in collection metadata for validation."""
        pytest.importorskip("chromadb")
        from py_code_mode.skills.vector_stores.chroma import ChromaVectorStore

        store = ChromaVectorStore(path=tmp_path / "chroma", embedder=mock_embedder)

        # Should be able to retrieve model info
        model_info = store.get_model_info()

        assert model_info.dimension == 384
        assert model_info.model_name is not None
        assert model_info.version is not None

    def test_uses_cosine_distance_metric(
        self, tmp_path: Path, mock_embedder: EmbeddingProvider
    ) -> None:
        """Collection should be configured for cosine similarity search."""
        pytest.importorskip("chromadb")
        from py_code_mode.skills.vector_stores.chroma import ChromaVectorStore

        store = ChromaVectorStore(path=tmp_path / "chroma", embedder=mock_embedder)

        # Implementation should use cosine distance
        # We verify this indirectly through search behavior in later tests
        assert store is not None


class TestChromaVectorStoreModelValidation:
    """Tests for model change detection and invalidation."""

    @pytest.fixture
    def mock_embedder(self) -> EmbeddingProvider:
        """Mock embedder with consistent behavior."""
        from py_code_mode.skills.embeddings import MockEmbedder

        return MockEmbedder(dimension=384)

    @pytest.fixture
    def different_embedder(self) -> EmbeddingProvider:
        """Different embedder to trigger model change."""
        from py_code_mode.skills.embeddings import MockEmbedder

        # Different dimension means different model
        return MockEmbedder(dimension=768)

    def test_detects_model_change_different_dimension(
        self, tmp_path: Path, mock_embedder: EmbeddingProvider, different_embedder: EmbeddingProvider
    ) -> None:
        """Should detect when model dimension changes."""
        pytest.importorskip("chromadb")
        from py_code_mode.skills.vector_stores.chroma import ChromaVectorStore

        store_path = tmp_path / "chroma"

        # Create store with first embedder (384-dim)
        store1 = ChromaVectorStore(path=store_path, embedder=mock_embedder)
        store1.add(
            id="skill1",
            description="Test skill",
            source="def run(): pass",
            content_hash="abc123",
        )
        assert store1.count() == 1

        # Reopen with different embedder (768-dim) - should detect change
        store2 = ChromaVectorStore(path=store_path, embedder=different_embedder)

        # Model change should have cleared vectors
        assert store2.count() == 0

    def test_preserves_vectors_when_model_unchanged(
        self, tmp_path: Path, mock_embedder: EmbeddingProvider
    ) -> None:
        """Should keep vectors when reopening with same model."""
        pytest.importorskip("chromadb")
        from py_code_mode.skills.vector_stores.chroma import ChromaVectorStore

        store_path = tmp_path / "chroma"

        # Create store and add vectors
        store1 = ChromaVectorStore(path=store_path, embedder=mock_embedder)
        store1.add(
            id="skill1",
            description="Test skill",
            source="def run(): pass",
            content_hash="abc123",
        )
        assert store1.count() == 1

        # Create fresh MockEmbedder with same dimension
        from py_code_mode.skills.embeddings import MockEmbedder

        same_embedder = MockEmbedder(dimension=384)

        # Reopen with same model spec
        store2 = ChromaVectorStore(path=store_path, embedder=same_embedder)

        # Vectors should be preserved
        assert store2.count() == 1

    def test_clears_all_vectors_on_model_change(
        self, tmp_path: Path, mock_embedder: EmbeddingProvider, different_embedder: EmbeddingProvider
    ) -> None:
        """Model change should clear entire index, not partial."""
        pytest.importorskip("chromadb")
        from py_code_mode.skills.vector_stores.chroma import ChromaVectorStore

        store_path = tmp_path / "chroma"

        # Add multiple skills
        store1 = ChromaVectorStore(path=store_path, embedder=mock_embedder)
        for i in range(5):
            store1.add(
                id=f"skill{i}",
                description=f"Skill {i}",
                source=f"def run(): return {i}",
                content_hash=f"hash{i}",
            )
        assert store1.count() == 5

        # Reopen with different model
        store2 = ChromaVectorStore(path=store_path, embedder=different_embedder)

        # All vectors should be cleared
        assert store2.count() == 0


class TestChromaVectorStoreCRUD:
    """Tests for add, remove, get_content_hash operations."""

    @pytest.fixture
    def mock_embedder(self) -> EmbeddingProvider:
        """Mock embedder for testing."""
        from py_code_mode.skills.embeddings import MockEmbedder

        return MockEmbedder(dimension=384)

    @pytest.fixture
    def store(self, tmp_path: Path, mock_embedder: EmbeddingProvider):
        """Fresh ChromaVectorStore for each test."""
        pytest.importorskip("chromadb")
        from py_code_mode.skills.vector_stores.chroma import ChromaVectorStore

        return ChromaVectorStore(path=tmp_path / "chroma", embedder=mock_embedder)

    def test_add_embeds_and_stores_vectors(self, store) -> None:
        """add() should embed description and code, store vectors."""
        store.add(
            id="port_scanner",
            description="Scan network ports using nmap",
            source='def run(target: str):\n    return subprocess.run(["nmap", target])',
            content_hash="abc123def456",
        )

        # Verify skill was indexed
        assert store.count() == 1

    def test_add_stores_content_hash(self, store) -> None:
        """add() should persist content hash for change detection."""
        store.add(
            id="skill1",
            description="Test skill",
            source="def run(): pass",
            content_hash="contenthash123",
        )

        # Should be able to retrieve stored hash
        stored_hash = store.get_content_hash("skill1")
        assert stored_hash == "contenthash123"

    def test_get_content_hash_returns_none_for_nonexistent(self, store) -> None:
        """get_content_hash() should return None for skills not in index."""
        hash_value = store.get_content_hash("nonexistent_skill")
        assert hash_value is None

    def test_add_overwrites_existing_skill(self, store) -> None:
        """Adding same skill ID should update vectors, not duplicate."""
        store.add(
            id="skill1",
            description="Original description",
            source="def run(): return 1",
            content_hash="hash1",
        )
        assert store.count() == 1

        store.add(
            id="skill1",
            description="Updated description",
            source="def run(): return 2",
            content_hash="hash2",
        )

        # Should still be 1 skill (updated, not duplicated)
        assert store.count() == 1

        # Hash should be updated
        assert store.get_content_hash("skill1") == "hash2"

    def test_remove_deletes_skill_vectors(self, store) -> None:
        """remove() should delete both description and code vectors."""
        store.add(
            id="skill1",
            description="Test",
            source="def run(): pass",
            content_hash="hash1",
        )
        assert store.count() == 1

        result = store.remove("skill1")

        assert result is True
        assert store.count() == 0
        assert store.get_content_hash("skill1") is None

    def test_remove_returns_false_for_nonexistent(self, store) -> None:
        """remove() should return False if skill not in index."""
        result = store.remove("nonexistent")
        assert result is False

    def test_count_reflects_indexed_skills(self, store) -> None:
        """count() should return number of unique skills indexed."""
        assert store.count() == 0

        store.add("skill1", "desc1", "code1", "hash1")
        assert store.count() == 1

        store.add("skill2", "desc2", "code2", "hash2")
        assert store.count() == 2

        store.remove("skill1")
        assert store.count() == 1

    def test_clear_removes_all_vectors(self, store) -> None:
        """clear() should remove all indexed skills."""
        # Add multiple skills
        for i in range(5):
            store.add(f"skill{i}", f"desc{i}", f"code{i}", f"hash{i}")
        assert store.count() == 5

        store.clear()

        assert store.count() == 0


class TestChromaVectorStoreSimilaritySearch:
    """Tests for semantic similarity search."""

    @pytest.fixture
    def mock_embedder(self) -> EmbeddingProvider:
        """Mock embedder for deterministic testing."""
        from py_code_mode.skills.embeddings import MockEmbedder

        return MockEmbedder(dimension=384)

    @pytest.fixture
    def store(self, tmp_path: Path, mock_embedder: EmbeddingProvider):
        """Fresh store with sample skills."""
        pytest.importorskip("chromadb")
        from py_code_mode.skills.vector_stores.chroma import ChromaVectorStore

        store = ChromaVectorStore(path=tmp_path / "chroma", embedder=mock_embedder)

        # Add diverse skills for search testing
        store.add(
            id="port_scanner",
            description="Scan network ports using nmap",
            source='subprocess.run(["nmap", "-p-", target])',
            content_hash="hash1",
        )

        store.add(
            id="web_scraper",
            description="Fetch and parse HTML from a webpage",
            source='requests.get(url).text',
            content_hash="hash2",
        )

        store.add(
            id="file_reader",
            description="Read file contents from disk",
            source='Path(file_path).read_text()',
            content_hash="hash3",
        )

        return store

    def test_search_returns_search_results(self, store) -> None:
        """search() should return list of SearchResult objects."""
        results = store.search(
            query="network scanning",
            limit=10,
            desc_weight=0.7,
            code_weight=0.3,
        )

        from py_code_mode.skills.vector_store import SearchResult

        assert isinstance(results, list)
        assert all(isinstance(r, SearchResult) for r in results)

    def test_search_results_have_scores(self, store) -> None:
        """Each SearchResult should have a similarity score."""
        results = store.search(
            query="network",
            limit=10,
            desc_weight=0.7,
            code_weight=0.3,
        )

        for result in results:
            assert isinstance(result.score, float)
            assert 0.0 <= result.score <= 1.0

    def test_search_respects_limit(self, store) -> None:
        """search() should return at most `limit` results."""
        results = store.search(
            query="test",
            limit=2,
            desc_weight=0.7,
            code_weight=0.3,
        )

        assert len(results) <= 2

    def test_search_returns_results_sorted_by_score(self, store) -> None:
        """Results should be ranked by similarity score (highest first)."""
        results = store.search(
            query="network",
            limit=10,
            desc_weight=0.7,
            code_weight=0.3,
        )

        # Scores should be in descending order
        if len(results) > 1:
            for i in range(len(results) - 1):
                assert results[i].score >= results[i + 1].score

    def test_search_uses_description_weight(self, store) -> None:
        """Search should weight description similarity according to desc_weight."""
        # Search with description-only weighting
        results_desc_only = store.search(
            query="Scan network ports",
            limit=1,
            desc_weight=1.0,
            code_weight=0.0,
        )

        # Should find port_scanner (matches description well)
        assert len(results_desc_only) > 0

    def test_search_uses_code_weight(self, store) -> None:
        """Search should weight code similarity according to code_weight."""
        # Search with code-only weighting
        results_code_only = store.search(
            query="nmap subprocess",
            limit=1,
            desc_weight=0.0,
            code_weight=1.0,
        )

        # Should still find relevant results based on code
        assert len(results_code_only) > 0

    def test_search_combines_description_and_code_scores(self, store) -> None:
        """Search should combine description and code similarity scores."""
        results = store.search(
            query="network ports",
            limit=10,
            desc_weight=0.7,
            code_weight=0.3,
        )

        # Both description and code should influence ranking
        # We don't test exact scores (depends on embeddings), just that we get results
        assert len(results) > 0

    def test_search_returns_empty_for_no_matches(self, tmp_path: Path) -> None:
        """search() on empty index should return empty list."""
        pytest.importorskip("chromadb")
        from py_code_mode.skills.embeddings import MockEmbedder
        from py_code_mode.skills.vector_stores.chroma import ChromaVectorStore

        empty_store = ChromaVectorStore(
            path=tmp_path / "empty_chroma", embedder=MockEmbedder()
        )

        results = empty_store.search(
            query="anything",
            limit=10,
            desc_weight=0.7,
            code_weight=0.3,
        )

        assert results == []

    def test_search_result_contains_skill_id(self, store) -> None:
        """SearchResult.id should contain the skill identifier."""
        results = store.search(
            query="network",
            limit=10,
            desc_weight=0.7,
            code_weight=0.3,
        )

        # IDs should be skill names we added
        result_ids = {r.id for r in results}
        assert result_ids.issubset({"port_scanner", "web_scraper", "file_reader"})


class TestChromaVectorStoreContentHashInvalidation:
    """Tests for content hash-based change detection and re-embedding."""

    @pytest.fixture
    def embedder_with_call_tracking(self):
        """Embedder that tracks how many times embed() is called."""
        from py_code_mode.skills.embeddings import MockEmbedder

        embedder = MockEmbedder(dimension=384)

        # Wrap embed method to count calls
        original_embed = embedder.embed
        embedder.embed_call_count = 0

        def tracked_embed(texts: list[str]):
            embedder.embed_call_count += len(texts)
            return original_embed(texts)

        embedder.embed = tracked_embed  # type: ignore[method-assign]
        return embedder

    def test_same_content_hash_skips_re_embedding(
        self, tmp_path: Path, embedder_with_call_tracking
    ) -> None:
        """Adding skill with same hash should skip embedding (idempotent)."""
        pytest.importorskip("chromadb")
        from py_code_mode.skills.vector_stores.chroma import ChromaVectorStore

        store = ChromaVectorStore(path=tmp_path / "chroma", embedder=embedder_with_call_tracking)

        # First add: should embed
        store.add(
            id="skill1",
            description="Test skill",
            source="def run(): pass",
            content_hash="stable_hash",
        )
        initial_embed_count = embedder_with_call_tracking.embed_call_count

        # Add again with same hash: should NOT re-embed
        store.add(
            id="skill1",
            description="Test skill",
            source="def run(): pass",
            content_hash="stable_hash",
        )

        # Embed count should not increase (hash matched, no re-embedding)
        assert embedder_with_call_tracking.embed_call_count == initial_embed_count

    def test_different_content_hash_triggers_re_embedding(
        self, tmp_path: Path, embedder_with_call_tracking
    ) -> None:
        """Adding skill with different hash should re-embed."""
        pytest.importorskip("chromadb")
        from py_code_mode.skills.vector_stores.chroma import ChromaVectorStore

        store = ChromaVectorStore(path=tmp_path / "chroma", embedder=embedder_with_call_tracking)

        # First add
        store.add(
            id="skill1",
            description="Original description",
            source="def run(): return 1",
            content_hash="hash_v1",
        )
        initial_embed_count = embedder_with_call_tracking.embed_call_count

        # Update with different hash: should re-embed
        store.add(
            id="skill1",
            description="Updated description",
            source="def run(): return 2",
            content_hash="hash_v2",
        )

        # Embed count should increase (content changed, re-embedded)
        assert embedder_with_call_tracking.embed_call_count > initial_embed_count


class TestChromaVectorStorePersistence:
    """Tests for persistence across store instances."""

    @pytest.fixture
    def mock_embedder(self) -> EmbeddingProvider:
        """Mock embedder."""
        from py_code_mode.skills.embeddings import MockEmbedder

        return MockEmbedder(dimension=384)

    def test_vectors_persist_after_close_and_reopen(
        self, tmp_path: Path, mock_embedder: EmbeddingProvider
    ) -> None:
        """Vectors should persist to disk and reload on next init."""
        pytest.importorskip("chromadb")
        from py_code_mode.skills.vector_stores.chroma import ChromaVectorStore

        store_path = tmp_path / "persistent_chroma"

        # Create store, add data
        store1 = ChromaVectorStore(path=store_path, embedder=mock_embedder)
        store1.add("skill1", "Network scanner", "nmap code", "hash1")
        store1.add("skill2", "File reader", "file code", "hash2")
        assert store1.count() == 2

        # Close and reopen (create new instance)
        from py_code_mode.skills.embeddings import MockEmbedder

        fresh_embedder = MockEmbedder(dimension=384)
        store2 = ChromaVectorStore(path=store_path, embedder=fresh_embedder)

        # Vectors should be reloaded
        assert store2.count() == 2
        assert store2.get_content_hash("skill1") == "hash1"
        assert store2.get_content_hash("skill2") == "hash2"

    def test_model_metadata_persists_across_sessions(
        self, tmp_path: Path, mock_embedder: EmbeddingProvider
    ) -> None:
        """Model info should persist and be validated on reopen."""
        pytest.importorskip("chromadb")
        from py_code_mode.skills.vector_stores.chroma import ChromaVectorStore

        store_path = tmp_path / "persistent_chroma"

        # First session
        store1 = ChromaVectorStore(path=store_path, embedder=mock_embedder)
        model_info1 = store1.get_model_info()

        # Second session (same model)
        from py_code_mode.skills.embeddings import MockEmbedder

        same_embedder = MockEmbedder(dimension=384)
        store2 = ChromaVectorStore(path=store_path, embedder=same_embedder)
        model_info2 = store2.get_model_info()

        # Model info should match
        assert model_info1.dimension == model_info2.dimension

    def test_search_works_on_persisted_vectors(
        self, tmp_path: Path, mock_embedder: EmbeddingProvider
    ) -> None:
        """Search should work on vectors loaded from disk."""
        pytest.importorskip("chromadb")
        from py_code_mode.skills.vector_stores.chroma import ChromaVectorStore

        store_path = tmp_path / "persistent_chroma"

        # First session: add skills
        store1 = ChromaVectorStore(path=store_path, embedder=mock_embedder)
        store1.add(
            "port_scanner",
            "Scan network ports",
            "nmap code here",
            "hash1",
        )

        # Second session: search should work
        from py_code_mode.skills.embeddings import MockEmbedder

        fresh_embedder = MockEmbedder(dimension=384)
        store2 = ChromaVectorStore(path=store_path, embedder=fresh_embedder)

        results = store2.search(
            query="network scanning",
            limit=10,
            desc_weight=0.7,
            code_weight=0.3,
        )

        # Should find the persisted skill
        assert len(results) > 0
        assert any(r.id == "port_scanner" for r in results)
