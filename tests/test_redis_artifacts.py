"""Tests for Redis artifact store - written first to define interface."""

import json
from unittest.mock import MagicMock

import pytest

from py_code_mode.artifacts import Artifact, ArtifactStoreProtocol
from py_code_mode.errors import ArtifactNotFoundError


class TestRedisArtifactStoreInterface:
    """Tests that RedisArtifactStore implements the protocol."""

    def test_implements_protocol(self) -> None:
        """RedisArtifactStore satisfies ArtifactStoreProtocol."""
        from py_code_mode.artifacts import RedisArtifactStore

        # Mock redis client
        mock_redis = MagicMock()
        store = RedisArtifactStore(mock_redis, prefix="artifacts")

        assert isinstance(store, ArtifactStoreProtocol)

    def test_has_path_property(self) -> None:
        """Store exposes prefix as path."""
        from py_code_mode.artifacts import RedisArtifactStore

        mock_redis = MagicMock()
        store = RedisArtifactStore(mock_redis, prefix="my-artifacts")

        assert store.path == "my-artifacts"

    def test_default_prefix(self) -> None:
        """Default prefix is 'artifacts'."""
        from py_code_mode.artifacts import RedisArtifactStore

        mock_redis = MagicMock()
        store = RedisArtifactStore(mock_redis)

        assert store.path == "artifacts"


class TestRedisArtifactStoreSave:
    """Tests for save operation."""

    @pytest.fixture
    def store(self):
        """Create store with mocked redis."""
        from py_code_mode.artifacts import RedisArtifactStore

        mock_redis = MagicMock()
        return RedisArtifactStore(mock_redis, prefix="test")

    def test_save_returns_artifact(self, store) -> None:
        """save() returns Artifact metadata."""
        artifact = store.save("data.json", {"key": "value"}, description="Test data")

        assert isinstance(artifact, Artifact)
        assert artifact.name == "data.json"
        assert artifact.description == "Test data"

    def test_save_path_uses_prefix(self, store) -> None:
        """Artifact path includes prefix."""
        artifact = store.save("data.json", {}, description="Test")

        # Path should be prefix:name format for Redis keys
        assert artifact.path == "test:data.json"

    def test_save_json_data(self, store) -> None:
        """save() serializes dicts/lists as JSON and stores."""
        data = {"hosts": ["10.0.0.1", "10.0.0.2"]}
        store.save("hosts.json", data, description="Host list")

        # Verify redis set was called with JSON
        store._redis.set.assert_called()
        call_args = store._redis.set.call_args
        stored_value = call_args[0][1]
        assert json.loads(stored_value) == data

    def test_save_string_data(self, store) -> None:
        """save() stores strings directly."""
        store.save("notes.txt", "hello world", description="Notes")

        store._redis.set.assert_called()
        call_args = store._redis.set.call_args
        stored_value = call_args[0][1]
        assert stored_value == "hello world"

    def test_save_bytes_data(self, store) -> None:
        """save() stores bytes directly."""
        data = b"\x89PNG\r\n\x1a\n"
        store.save("image.png", data, description="Image")

        store._redis.set.assert_called()
        call_args = store._redis.set.call_args
        stored_value = call_args[0][1]
        assert stored_value == data

    def test_save_updates_index(self, store) -> None:
        """save() updates metadata index in Redis."""
        store.save("test.json", {}, description="Test data")

        # Should call hset for index
        store._redis.hset.assert_called()

    def test_save_with_metadata(self, store) -> None:
        """save() accepts additional metadata."""
        artifact = store.save(
            "results.json",
            {},
            description="Scan results",
            metadata={"tool": "nmap", "duration": 120},
        )

        assert artifact.metadata["tool"] == "nmap"


class TestRedisArtifactStoreLoad:
    """Tests for load operation."""

    @pytest.fixture
    def store(self):
        from py_code_mode.artifacts import RedisArtifactStore

        mock_redis = MagicMock()
        return RedisArtifactStore(mock_redis, prefix="test")

    def test_load_returns_data(self, store) -> None:
        """load() retrieves stored data."""
        store._redis.get.return_value = '{"key": "value"}'

        data = store.load("data.json")

        assert data == {"key": "value"}

    def test_load_text_file(self, store) -> None:
        """load() returns text for non-json files."""
        store._redis.get.return_value = "some notes"

        data = store.load("notes.txt")

        assert data == "some notes"

    def test_load_not_found(self, store) -> None:
        """load() raises for missing artifact."""
        store._redis.get.return_value = None

        with pytest.raises(ArtifactNotFoundError):
            store.load("nonexistent.json")

    def test_load_uses_correct_key(self, store) -> None:
        """load() uses prefixed key."""
        store._redis.get.return_value = "{}"

        store.load("data.json")

        store._redis.get.assert_called_with("test:data.json")


class TestRedisArtifactStoreList:
    """Tests for list operation."""

    @pytest.fixture
    def store(self):
        from py_code_mode.artifacts import RedisArtifactStore

        mock_redis = MagicMock()
        return RedisArtifactStore(mock_redis, prefix="test")

    def test_list_returns_artifacts(self, store) -> None:
        """list() returns Artifact objects."""
        # Mock index with two entries
        store._redis.hgetall.return_value = {
            "a.json": json.dumps(
                {
                    "description": "First",
                    "created_at": "2024-01-01T00:00:00+00:00",
                    "metadata": {},
                }
            ),
            "b.json": json.dumps(
                {
                    "description": "Second",
                    "created_at": "2024-01-01T00:00:00+00:00",
                    "metadata": {},
                }
            ),
        }

        artifacts = store.list()

        assert len(artifacts) == 2
        names = {a.name for a in artifacts}
        assert names == {"a.json", "b.json"}

    def test_list_includes_descriptions(self, store) -> None:
        """list() includes descriptions from index."""
        store._redis.hgetall.return_value = {
            "scan.json": json.dumps(
                {
                    "description": "Network scan results",
                    "created_at": "2024-01-01T00:00:00+00:00",
                    "metadata": {},
                }
            ),
        }

        artifacts = store.list()

        assert artifacts[0].description == "Network scan results"

    def test_list_empty_store(self, store) -> None:
        """list() returns empty for new store."""
        store._redis.hgetall.return_value = {}

        assert store.list() == []


class TestRedisArtifactStoreGet:
    """Tests for get operation."""

    @pytest.fixture
    def store(self):
        from py_code_mode.artifacts import RedisArtifactStore

        mock_redis = MagicMock()
        return RedisArtifactStore(mock_redis, prefix="test")

    def test_get_returns_artifact(self, store) -> None:
        """get() returns single Artifact by name."""
        store._redis.hget.return_value = json.dumps(
            {
                "description": "Target info",
                "created_at": "2024-01-01T00:00:00+00:00",
                "metadata": {},
            }
        )

        artifact = store.get("target.json")

        assert artifact is not None
        assert artifact.name == "target.json"
        assert artifact.description == "Target info"

    def test_get_not_found(self, store) -> None:
        """get() returns None for missing artifact."""
        store._redis.hget.return_value = None

        assert store.get("missing.json") is None


class TestRedisArtifactStoreExists:
    """Tests for exists operation."""

    @pytest.fixture
    def store(self):
        from py_code_mode.artifacts import RedisArtifactStore

        mock_redis = MagicMock()
        return RedisArtifactStore(mock_redis, prefix="test")

    def test_exists_true(self, store) -> None:
        """exists() returns True when present."""
        store._redis.hexists.return_value = True

        assert store.exists("present.json") is True

    def test_exists_false(self, store) -> None:
        """exists() returns False when missing."""
        store._redis.hexists.return_value = False

        assert store.exists("missing.json") is False


class TestRedisArtifactStoreDelete:
    """Tests for delete operation."""

    @pytest.fixture
    def store(self):
        from py_code_mode.artifacts import RedisArtifactStore

        mock_redis = MagicMock()
        return RedisArtifactStore(mock_redis, prefix="test")

    def test_delete_removes_data_and_index(self, store) -> None:
        """delete() removes both data key and index entry."""
        store.delete("temp.json")

        # Should delete data key
        store._redis.delete.assert_called_with("test:temp.json")
        # Should remove from index
        store._redis.hdel.assert_called()


class TestRedisArtifactStoreSubpaths:
    """Tests for subdirectory-like paths."""

    @pytest.fixture
    def store(self):
        from py_code_mode.artifacts import RedisArtifactStore

        mock_redis = MagicMock()
        return RedisArtifactStore(mock_redis, prefix="test")

    def test_save_with_subpath(self, store) -> None:
        """save() handles paths with slashes like directories."""
        artifact = store.save("scans/nmap/results.json", {}, description="Nmap scan")

        # Key should preserve full path structure
        assert artifact.path == "test:scans/nmap/results.json"

    def test_load_with_subpath(self, store) -> None:
        """load() works with subdirectory-like paths."""
        store._redis.get.return_value = '{"nested": true}'

        data = store.load("deep/path/data.json")

        store._redis.get.assert_called_with("test:deep/path/data.json")
        assert data == {"nested": True}


class TestRedisArtifactStoreIntegration:
    """Integration tests with real Redis (skipped if Redis not available)."""

    @pytest.fixture
    def redis_client(self, request):
        """Get real Redis client with unique prefix per test."""
        try:
            import redis

            client = redis.Redis(host="localhost", port=6379, decode_responses=True)
            client.ping()  # Test connection

            # Use unique prefix per test to avoid parallel test interference
            test_name = request.node.name.replace("[", "_").replace("]", "_")
            prefix = f"test-artifacts-{test_name}"

            # Cleanup before test (leftover from previous run)
            for key in client.keys(f"{prefix}:*"):
                client.delete(key)
            client.delete(f"{prefix}:__index__")

            # Store prefix on client for tests to use
            client._test_prefix = prefix

            yield client

            # Cleanup after test
            for key in client.keys(f"{prefix}:*"):
                client.delete(key)
            client.delete(f"{prefix}:__index__")
        except Exception:
            pytest.skip("Redis not available")

    def test_roundtrip_json(self, redis_client) -> None:
        """Save and load JSON data through real Redis."""
        from py_code_mode.artifacts import RedisArtifactStore

        store = RedisArtifactStore(redis_client, prefix=redis_client._test_prefix)

        data = {"hosts": ["10.0.0.1", "10.0.0.2"], "count": 2}
        store.save("hosts.json", data, description="Host list")

        loaded = store.load("hosts.json")
        assert loaded == data

    def test_list_after_saves(self, redis_client) -> None:
        """List returns all saved artifacts."""
        from py_code_mode.artifacts import RedisArtifactStore

        store = RedisArtifactStore(redis_client, prefix=redis_client._test_prefix)

        store.save("a.json", {}, description="First")
        store.save("b.json", {}, description="Second")

        artifacts = store.list()
        names = {a.name for a in artifacts}
        assert names == {"a.json", "b.json"}

    def test_delete_removes(self, redis_client) -> None:
        """Delete removes artifact completely."""
        from py_code_mode.artifacts import RedisArtifactStore

        store = RedisArtifactStore(redis_client, prefix=redis_client._test_prefix)

        store.save("temp.json", {}, description="Temporary")
        assert store.exists("temp.json")

        store.delete("temp.json")
        assert not store.exists("temp.json")
