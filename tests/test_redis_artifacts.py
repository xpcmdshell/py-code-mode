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
        store._redis.hget.return_value = json.dumps(
            {
                "description": "Stored JSON",
                "created_at": "2024-01-01T00:00:00+00:00",
                "metadata": {"_data_type": "json"},
            }
        )
        store._redis.get.return_value = '{"key": "value"}'

        data = store.load("data.json")

        assert data == {"key": "value"}

    def test_load_text_file(self, store) -> None:
        """load() returns text for non-json files."""
        store._redis.hget.return_value = json.dumps(
            {
                "description": "Notes",
                "created_at": "2024-01-01T00:00:00+00:00",
                "metadata": {"_data_type": "text"},
            }
        )
        store._redis.get.return_value = "some notes"

        data = store.load("notes.txt")

        assert data == "some notes"

    def test_load_not_found(self, store) -> None:
        """load() raises for missing artifact."""
        store._redis.hget.return_value = None
        store._redis.get.return_value = None

        with pytest.raises(ArtifactNotFoundError):
            store.load("nonexistent.json")

    def test_load_uses_correct_key(self, store) -> None:
        """load() uses prefixed key."""
        store._redis.hget.return_value = json.dumps(
            {
                "description": "Stored JSON",
                "created_at": "2024-01-01T00:00:00+00:00",
                "metadata": {"_data_type": "json"},
            }
        )
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
        store._redis.exists.return_value = 1
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
        store._redis.exists.return_value = 1
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
        store._redis.exists.return_value = 1
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
        store._redis.exists.return_value = 1

        assert store.exists("present.json") is True

    def test_exists_false(self, store) -> None:
        """exists() returns False when missing."""
        store._redis.hexists.return_value = False
        store._redis.exists.return_value = 0

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
        store._redis.hget.return_value = json.dumps(
            {
                "description": "Nested JSON",
                "created_at": "2024-01-01T00:00:00+00:00",
                "metadata": {"_data_type": "json"},
            }
        )
        store._redis.get.return_value = '{"nested": true}'

        data = store.load("deep/path/data.json")

        store._redis.get.assert_called_with("test:deep/path/data.json")
        assert data == {"nested": True}


class TestRedisArtifactStoreIntegration:
    """Integration tests with real Redis using testcontainers."""

    def test_roundtrip_json(self, redis_client, request) -> None:
        """Save and load JSON data through real Redis."""
        from py_code_mode.artifacts import RedisArtifactStore

        # Use unique prefix per test for isolation
        test_name = request.node.name.replace("[", "_").replace("]", "_")
        prefix = f"test-artifacts-{test_name}"

        store = RedisArtifactStore(redis_client, prefix=prefix)

        data = {"hosts": ["10.0.0.1", "10.0.0.2"], "count": 2}
        store.save("hosts.json", data, description="Host list")

        loaded = store.load("hosts.json")
        assert loaded == data

    def test_list_after_saves(self, redis_client, request) -> None:
        """List returns all saved artifacts."""
        from py_code_mode.artifacts import RedisArtifactStore

        test_name = request.node.name.replace("[", "_").replace("]", "_")
        prefix = f"test-artifacts-{test_name}"

        store = RedisArtifactStore(redis_client, prefix=prefix)

        store.save("a.json", {}, description="First")
        store.save("b.json", {}, description="Second")

        artifacts = store.list()
        # Handle both bytes and string names (depends on decode_responses setting)
        names = {a.name.decode() if isinstance(a.name, bytes) else a.name for a in artifacts}
        assert names == {"a.json", "b.json"}

    def test_delete_removes(self, redis_client, request) -> None:
        """Delete removes artifact completely."""
        from py_code_mode.artifacts import RedisArtifactStore

        test_name = request.node.name.replace("[", "_").replace("]", "_")
        prefix = f"test-artifacts-{test_name}"

        store = RedisArtifactStore(redis_client, prefix=prefix)

        store.save("temp.json", {}, description="Temporary")
        assert store.exists("temp.json")

        store.delete("temp.json")
        assert not store.exists("temp.json")


class TestRedisArtifactStoreReconciliation:
    """Redis artifact metadata is reconciled against payload keys on read."""

    def test_list_prunes_stale_metadata_after_payload_delete(self, mock_redis) -> None:
        """list() drops tracked artifacts whose payload keys were removed externally."""
        from py_code_mode.artifacts import RedisArtifactStore

        store = RedisArtifactStore(mock_redis, prefix="test")
        store.save("stale.json", {"ok": True}, description="stale")

        mock_redis.delete("test:stale.json")

        assert store.list() == []
        assert store.get("stale.json") is None
        assert store.exists("stale.json") is False

    def test_load_prunes_stale_metadata_after_payload_delete(self, mock_redis) -> None:
        """load() removes stale metadata before raising not found."""
        from py_code_mode.artifacts import RedisArtifactStore

        store = RedisArtifactStore(mock_redis, prefix="test")
        store.save("stale.json", {"ok": True}, description="stale")

        mock_redis.delete("test:stale.json")

        with pytest.raises(ArtifactNotFoundError):
            store.load("stale.json")

        assert store.get("stale.json") is None
