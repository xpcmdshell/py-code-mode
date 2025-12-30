"""Tests for RedisVectorStore implementation - TDD RED phase.

These tests define the Redis vector store behavior through failing tests.
Tests fail because RedisVectorStore doesn't exist yet.

RedisVectorStore uses Redis with RediSearch module for distributed vector storage,
enabling multiple agents to share skill embeddings across deployments.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

if TYPE_CHECKING:
    from redis import Redis

    from py_code_mode.skills.embeddings import EmbeddingProvider


@pytest.fixture
def redis_container():
    """Redis container with RediSearch support."""
    pytest.importorskip("testcontainers")
    from testcontainers.redis import RedisContainer

    # redis-stack includes RediSearch module
    container = RedisContainer(image="redis/redis-stack:latest")
    container.start()
    yield container
    container.stop()


@pytest.fixture
def redis_client(redis_container):
    """Connected Redis client."""
    pytest.importorskip("redis")
    from redis import Redis

    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)

    client = Redis(host=host, port=int(port), decode_responses=False)

    # Verify connection
    assert client.ping()

    yield client

    # Cleanup: flush all keys after test
    client.flushall()
    client.close()


class TestRedisVectorStoreImport:
    """Tests for RedisVectorStore availability and imports."""

    def test_redis_vector_store_importable_when_redis_available(self) -> None:
        """RedisVectorStore should be importable when redis is installed."""
        pytest.importorskip("redis")
        from py_code_mode.skills.vector_stores.redis_store import RedisVectorStore

        assert RedisVectorStore is not None

    def test_redis_vector_store_satisfies_protocol(self, redis_client: Redis) -> None:
        """RedisVectorStore should implement VectorStore protocol."""
        pytest.importorskip("redis")
        from py_code_mode.skills.embeddings import MockEmbedder
        from py_code_mode.skills.vector_store import VectorStore
        from py_code_mode.skills.vector_stores.redis_store import RedisVectorStore

        # Protocol compliance via isinstance check
        embedder = MockEmbedder()
        store = RedisVectorStore(
            redis=redis_client,
            embedder=embedder,
            prefix="test",
            index_name="test_idx",
        )

        assert isinstance(store, VectorStore)


class TestRedisVectorStoreInitialization:
    """Tests for RedisVectorStore initialization and index creation."""

    @pytest.fixture
    def mock_embedder(self) -> EmbeddingProvider:
        """Mock embedder with consistent behavior."""
        from py_code_mode.skills.embeddings import MockEmbedder

        return MockEmbedder(dimension=384)

    def test_creates_search_index_on_init(
        self, redis_client: Redis, mock_embedder: EmbeddingProvider
    ) -> None:
        """Should create RediSearch index with vector fields on initialization."""
        pytest.importorskip("redis")
        from py_code_mode.skills.vector_stores.redis_store import RedisVectorStore

        store = RedisVectorStore(
            redis=redis_client,
            embedder=mock_embedder,
            prefix="skills",
            index_name="skills_idx",
        )

        # Index should be created (verify via count - empty index returns 0)
        assert store.count() == 0

    def test_stores_model_info_in_index_metadata(
        self, redis_client: Redis, mock_embedder: EmbeddingProvider
    ) -> None:
        """Should persist ModelInfo in index for validation."""
        pytest.importorskip("redis")
        from py_code_mode.skills.vector_stores.redis_store import RedisVectorStore

        store = RedisVectorStore(
            redis=redis_client,
            embedder=mock_embedder,
            prefix="skills",
            index_name="skills_idx",
        )

        # Should be able to retrieve model info
        model_info = store.get_model_info()

        assert model_info.dimension == 384
        assert model_info.model_name is not None
        assert model_info.version is not None

    def test_uses_cosine_similarity_metric(
        self, redis_client: Redis, mock_embedder: EmbeddingProvider
    ) -> None:
        """Index should be configured for cosine similarity search."""
        pytest.importorskip("redis")
        from py_code_mode.skills.vector_stores.redis_store import RedisVectorStore

        store = RedisVectorStore(
            redis=redis_client,
            embedder=mock_embedder,
            prefix="skills",
            index_name="skills_idx",
        )

        # Implementation should use COSINE distance metric
        # We verify this indirectly through search behavior in later tests
        assert store is not None

    def test_reuses_existing_compatible_index(
        self, redis_client: Redis, mock_embedder: EmbeddingProvider
    ) -> None:
        """Should reuse existing index if model matches."""
        pytest.importorskip("redis")
        from py_code_mode.skills.embeddings import MockEmbedder
        from py_code_mode.skills.vector_stores.redis_store import RedisVectorStore

        # Create first store and add data
        store1 = RedisVectorStore(
            redis=redis_client,
            embedder=mock_embedder,
            prefix="skills",
            index_name="skills_idx",
        )
        store1.add("skill1", "Test skill", "def run(): pass", "hash1")
        assert store1.count() == 1

        # Create second store with same config - should reuse index
        same_embedder = MockEmbedder(dimension=384)
        store2 = RedisVectorStore(
            redis=redis_client,
            embedder=same_embedder,
            prefix="skills",
            index_name="skills_idx",
        )

        # Data should still be present
        assert store2.count() == 1
        assert store2.get_content_hash("skill1") == "hash1"


class TestRedisVectorStoreModelValidation:
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
        self,
        redis_client: Redis,
        mock_embedder: EmbeddingProvider,
        different_embedder: EmbeddingProvider,
    ) -> None:
        """Should detect when model dimension changes."""
        pytest.importorskip("redis")
        from py_code_mode.skills.vector_stores.redis_store import RedisVectorStore

        # Create store with first embedder (384-dim)
        store1 = RedisVectorStore(
            redis=redis_client,
            embedder=mock_embedder,
            prefix="skills",
            index_name="skills_idx",
        )
        store1.add(
            id="skill1",
            description="Test skill",
            source="def run(): pass",
            content_hash="abc123",
        )
        assert store1.count() == 1

        # Reopen with different embedder (768-dim) - should detect change
        store2 = RedisVectorStore(
            redis=redis_client,
            embedder=different_embedder,
            prefix="skills",
            index_name="skills_idx",
        )

        # Model change should have cleared vectors
        assert store2.count() == 0

    def test_preserves_vectors_when_model_unchanged(
        self, redis_client: Redis, mock_embedder: EmbeddingProvider
    ) -> None:
        """Should keep vectors when reopening with same model."""
        pytest.importorskip("redis")
        from py_code_mode.skills.embeddings import MockEmbedder
        from py_code_mode.skills.vector_stores.redis_store import RedisVectorStore

        # Create store and add vectors
        store1 = RedisVectorStore(
            redis=redis_client,
            embedder=mock_embedder,
            prefix="skills",
            index_name="skills_idx",
        )
        store1.add(
            id="skill1",
            description="Test skill",
            source="def run(): pass",
            content_hash="abc123",
        )
        assert store1.count() == 1

        # Create fresh MockEmbedder with same dimension
        same_embedder = MockEmbedder(dimension=384)

        # Reopen with same model spec
        store2 = RedisVectorStore(
            redis=redis_client,
            embedder=same_embedder,
            prefix="skills",
            index_name="skills_idx",
        )

        # Vectors should be preserved
        assert store2.count() == 1

    def test_clears_all_vectors_on_model_change(
        self,
        redis_client: Redis,
        mock_embedder: EmbeddingProvider,
        different_embedder: EmbeddingProvider,
    ) -> None:
        """Model change should clear entire index, not partial."""
        pytest.importorskip("redis")
        from py_code_mode.skills.vector_stores.redis_store import RedisVectorStore

        # Add multiple skills
        store1 = RedisVectorStore(
            redis=redis_client,
            embedder=mock_embedder,
            prefix="skills",
            index_name="skills_idx",
        )
        for i in range(5):
            store1.add(
                id=f"skill{i}",
                description=f"Skill {i}",
                source=f"def run(): return {i}",
                content_hash=f"hash{i}",
            )
        assert store1.count() == 5

        # Reopen with different model
        store2 = RedisVectorStore(
            redis=redis_client,
            embedder=different_embedder,
            prefix="skills",
            index_name="skills_idx",
        )

        # All vectors should be cleared
        assert store2.count() == 0


class TestRedisVectorStoreCRUD:
    """Tests for add, remove, get_content_hash operations."""

    @pytest.fixture
    def mock_embedder(self) -> EmbeddingProvider:
        """Mock embedder for testing."""
        from py_code_mode.skills.embeddings import MockEmbedder

        return MockEmbedder(dimension=384)

    @pytest.fixture
    def store(self, redis_client: Redis, mock_embedder: EmbeddingProvider):
        """Fresh RedisVectorStore for each test."""
        pytest.importorskip("redis")
        from py_code_mode.skills.vector_stores.redis_store import RedisVectorStore

        return RedisVectorStore(
            redis=redis_client,
            embedder=mock_embedder,
            prefix="test",
            index_name="test_idx",
        )

    def test_add_embeds_and_stores_vectors(self, store) -> None:
        """add() should embed description and code, store vectors in Redis."""
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
        """clear() should remove all indexed skills and drop index."""
        # Add multiple skills
        for i in range(5):
            store.add(f"skill{i}", f"desc{i}", f"code{i}", f"hash{i}")
        assert store.count() == 5

        store.clear()

        assert store.count() == 0


class TestRedisVectorStoreSimilaritySearch:
    """Tests for semantic similarity search."""

    @pytest.fixture
    def mock_embedder(self) -> EmbeddingProvider:
        """Mock embedder for deterministic testing."""
        from py_code_mode.skills.embeddings import MockEmbedder

        return MockEmbedder(dimension=384)

    @pytest.fixture
    def store(self, redis_client: Redis, mock_embedder: EmbeddingProvider):
        """Fresh store with sample skills."""
        pytest.importorskip("redis")
        from py_code_mode.skills.vector_stores.redis_store import RedisVectorStore

        store = RedisVectorStore(
            redis=redis_client,
            embedder=mock_embedder,
            prefix="test",
            index_name="test_idx",
        )

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

    def test_search_returns_empty_for_no_matches(
        self, redis_client: Redis, mock_embedder: EmbeddingProvider
    ) -> None:
        """search() on empty index should return empty list."""
        pytest.importorskip("redis")
        from py_code_mode.skills.vector_stores.redis_store import RedisVectorStore

        empty_store = RedisVectorStore(
            redis=redis_client,
            embedder=mock_embedder,
            prefix="empty",
            index_name="empty_idx",
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


class TestRedisVectorStoreContentHashInvalidation:
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
        self, redis_client: Redis, embedder_with_call_tracking
    ) -> None:
        """Adding skill with same hash should skip embedding (idempotent)."""
        pytest.importorskip("redis")
        from py_code_mode.skills.vector_stores.redis_store import RedisVectorStore

        store = RedisVectorStore(
            redis=redis_client,
            embedder=embedder_with_call_tracking,
            prefix="test",
            index_name="test_idx",
        )

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
        self, redis_client: Redis, embedder_with_call_tracking
    ) -> None:
        """Adding skill with different hash should re-embed."""
        pytest.importorskip("redis")
        from py_code_mode.skills.vector_stores.redis_store import RedisVectorStore

        store = RedisVectorStore(
            redis=redis_client,
            embedder=embedder_with_call_tracking,
            prefix="test",
            index_name="test_idx",
        )

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


class TestRedisVectorStorePersistence:
    """Tests for persistence across store instances."""

    @pytest.fixture
    def mock_embedder(self) -> EmbeddingProvider:
        """Mock embedder."""
        from py_code_mode.skills.embeddings import MockEmbedder

        return MockEmbedder(dimension=384)

    def test_vectors_persist_across_connections(
        self, redis_client: Redis, mock_embedder: EmbeddingProvider
    ) -> None:
        """Vectors should persist in Redis and reload on next connection."""
        pytest.importorskip("redis")
        from py_code_mode.skills.embeddings import MockEmbedder
        from py_code_mode.skills.vector_stores.redis_store import RedisVectorStore

        # Create store, add data
        store1 = RedisVectorStore(
            redis=redis_client,
            embedder=mock_embedder,
            prefix="skills",
            index_name="skills_idx",
        )
        store1.add("skill1", "Network scanner", "nmap code", "hash1")
        store1.add("skill2", "File reader", "file code", "hash2")
        assert store1.count() == 2

        # Create new store instance (simulates reconnection)
        fresh_embedder = MockEmbedder(dimension=384)
        store2 = RedisVectorStore(
            redis=redis_client,
            embedder=fresh_embedder,
            prefix="skills",
            index_name="skills_idx",
        )

        # Vectors should be reloaded from Redis
        assert store2.count() == 2
        assert store2.get_content_hash("skill1") == "hash1"
        assert store2.get_content_hash("skill2") == "hash2"

    def test_model_metadata_persists_across_sessions(
        self, redis_client: Redis, mock_embedder: EmbeddingProvider
    ) -> None:
        """Model info should persist and be validated on reconnect."""
        pytest.importorskip("redis")
        from py_code_mode.skills.embeddings import MockEmbedder
        from py_code_mode.skills.vector_stores.redis_store import RedisVectorStore

        # First session
        store1 = RedisVectorStore(
            redis=redis_client,
            embedder=mock_embedder,
            prefix="skills",
            index_name="skills_idx",
        )
        model_info1 = store1.get_model_info()

        # Second session (same model)
        same_embedder = MockEmbedder(dimension=384)
        store2 = RedisVectorStore(
            redis=redis_client,
            embedder=same_embedder,
            prefix="skills",
            index_name="skills_idx",
        )
        model_info2 = store2.get_model_info()

        # Model info should match
        assert model_info1.dimension == model_info2.dimension

    def test_search_works_on_persisted_vectors(
        self, redis_client: Redis, mock_embedder: EmbeddingProvider
    ) -> None:
        """Search should work on vectors loaded from Redis."""
        pytest.importorskip("redis")
        from py_code_mode.skills.embeddings import MockEmbedder
        from py_code_mode.skills.vector_stores.redis_store import RedisVectorStore

        # First session: add skills
        store1 = RedisVectorStore(
            redis=redis_client,
            embedder=mock_embedder,
            prefix="skills",
            index_name="skills_idx",
        )
        store1.add(
            "port_scanner",
            "Scan network ports",
            "nmap code here",
            "hash1",
        )

        # Second session: search should work
        fresh_embedder = MockEmbedder(dimension=384)
        store2 = RedisVectorStore(
            redis=redis_client,
            embedder=fresh_embedder,
            prefix="skills",
            index_name="skills_idx",
        )

        results = store2.search(
            query="network scanning",
            limit=10,
            desc_weight=0.7,
            code_weight=0.3,
        )

        # Should find the persisted skill
        assert len(results) > 0
        assert any(r.id == "port_scanner" for r in results)


class TestRedisVectorStoreIndexIsolation:
    """Tests for prefix-based namespace isolation."""

    @pytest.fixture
    def mock_embedder(self) -> EmbeddingProvider:
        """Mock embedder."""
        from py_code_mode.skills.embeddings import MockEmbedder

        return MockEmbedder(dimension=384)

    def test_different_prefixes_isolate_skills(
        self, redis_client: Redis, mock_embedder: EmbeddingProvider
    ) -> None:
        """Skills in different prefixes should not interfere."""
        pytest.importorskip("redis")
        from py_code_mode.skills.vector_stores.redis_store import RedisVectorStore

        # Create two stores with different prefixes
        store1 = RedisVectorStore(
            redis=redis_client,
            embedder=mock_embedder,
            prefix="project_a",
            index_name="project_a_idx",
        )

        store2 = RedisVectorStore(
            redis=redis_client,
            embedder=mock_embedder,
            prefix="project_b",
            index_name="project_b_idx",
        )

        # Add skills to each
        store1.add("skill1", "Project A skill", "code1", "hash1")
        store2.add("skill2", "Project B skill", "code2", "hash2")

        # Each store should only see its own skills
        assert store1.count() == 1
        assert store2.count() == 1
        assert store1.get_content_hash("skill1") == "hash1"
        assert store1.get_content_hash("skill2") is None
        assert store2.get_content_hash("skill2") == "hash2"
        assert store2.get_content_hash("skill1") is None

    def test_different_index_names_create_separate_indexes(
        self, redis_client: Redis, mock_embedder: EmbeddingProvider
    ) -> None:
        """Different index names should create independent search indexes."""
        pytest.importorskip("redis")
        from py_code_mode.skills.vector_stores.redis_store import RedisVectorStore

        # Create two stores with same prefix but different index names
        store1 = RedisVectorStore(
            redis=redis_client,
            embedder=mock_embedder,
            prefix="skills",
            index_name="idx_v1",
        )

        store2 = RedisVectorStore(
            redis=redis_client,
            embedder=mock_embedder,
            prefix="skills",
            index_name="idx_v2",
        )

        # Add skills to first index
        store1.add("skill1", "First index skill", "code1", "hash1")

        # Second index should be empty
        assert store1.count() == 1
        assert store2.count() == 0
