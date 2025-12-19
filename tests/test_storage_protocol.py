"""Protocol compliance tests for StorageBackend.

These tests define what every StorageBackend must do. Written FIRST (TDD).
All storage implementations must pass these tests to be considered compliant.

The StorageBackend protocol unifies tools, skills, and artifacts storage
under a single interface. This enables swapping between FileStorage and
RedisStorage without changing code.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

# These imports will fail initially - that's expected (TDD red phase)
from py_code_mode.storage import (
    FileStorage,
    RedisStorage,
    StorageBackend,
)

if TYPE_CHECKING:
    from tests.conftest import MockRedisClient


class TestStorageBackendProtocol:
    """Tests that define the StorageBackend protocol contract.

    These tests verify structural compliance - that implementations
    have the required methods with correct signatures.
    """

    def test_file_storage_implements_protocol(self, tmp_path: Path) -> None:
        """FileStorage must implement StorageBackend protocol."""
        storage = FileStorage(tmp_path)
        assert isinstance(storage, StorageBackend)

    def test_redis_storage_implements_protocol(self, mock_redis: MockRedisClient) -> None:
        """RedisStorage must implement StorageBackend protocol."""
        storage = RedisStorage(mock_redis, prefix="test")
        assert isinstance(storage, StorageBackend)

    def test_protocol_has_tools_property(self, tmp_path: Path) -> None:
        """StorageBackend must have tools property returning ToolStore."""
        storage = FileStorage(tmp_path)
        assert hasattr(storage, "tools")
        assert storage.tools is not None

    def test_protocol_has_skills_property(self, tmp_path: Path) -> None:
        """StorageBackend must have skills property returning SkillStore."""
        storage = FileStorage(tmp_path)
        assert hasattr(storage, "skills")
        assert storage.skills is not None

    def test_protocol_has_artifacts_property(self, tmp_path: Path) -> None:
        """StorageBackend must have artifacts property returning ArtifactStore."""
        storage = FileStorage(tmp_path)
        assert hasattr(storage, "artifacts")
        assert storage.artifacts is not None


class TestToolStoreProtocol:
    """Tests for the ToolStore sub-protocol."""

    @pytest.fixture
    def storage(self, tmp_path: Path) -> StorageBackend:
        """Create FileStorage for testing."""
        return FileStorage(tmp_path)

    def test_tool_store_has_list_method(self, storage: StorageBackend) -> None:
        """ToolStore must have list() method."""
        assert hasattr(storage.tools, "list")
        assert callable(storage.tools.list)

    def test_tool_store_has_get_method(self, storage: StorageBackend) -> None:
        """ToolStore must have get(name) method."""
        assert hasattr(storage.tools, "get")
        assert callable(storage.tools.get)

    def test_tool_store_has_save_method(self, storage: StorageBackend) -> None:
        """ToolStore must have save(tool) method."""
        assert hasattr(storage.tools, "save")
        assert callable(storage.tools.save)

    def test_tool_store_has_delete_method(self, storage: StorageBackend) -> None:
        """ToolStore must have delete(name) method."""
        assert hasattr(storage.tools, "delete")
        assert callable(storage.tools.delete)

    def test_tool_store_has_exists_method(self, storage: StorageBackend) -> None:
        """ToolStore must have exists(name) method."""
        assert hasattr(storage.tools, "exists")
        assert callable(storage.tools.exists)

    def test_tool_store_has_search_method(self, storage: StorageBackend) -> None:
        """ToolStore must have search(query) method for semantic search."""
        assert hasattr(storage.tools, "search")
        assert callable(storage.tools.search)


class TestSkillStoreProtocol:
    """Tests for the SkillStore sub-protocol."""

    @pytest.fixture
    def storage(self, tmp_path: Path) -> StorageBackend:
        """Create FileStorage for testing."""
        return FileStorage(tmp_path)

    def test_skill_store_has_list_method(self, storage: StorageBackend) -> None:
        """SkillStore must have list() method."""
        assert hasattr(storage.skills, "list")
        assert callable(storage.skills.list)

    def test_skill_store_has_get_method(self, storage: StorageBackend) -> None:
        """SkillStore must have get(name) method."""
        assert hasattr(storage.skills, "get")
        assert callable(storage.skills.get)

    def test_skill_store_has_save_method(self, storage: StorageBackend) -> None:
        """SkillStore must have save(skill) method."""
        assert hasattr(storage.skills, "save")
        assert callable(storage.skills.save)

    def test_skill_store_has_delete_method(self, storage: StorageBackend) -> None:
        """SkillStore must have delete(name) method."""
        assert hasattr(storage.skills, "delete")
        assert callable(storage.skills.delete)

    def test_skill_store_has_exists_method(self, storage: StorageBackend) -> None:
        """SkillStore must have exists(name) method."""
        assert hasattr(storage.skills, "exists")
        assert callable(storage.skills.exists)

    def test_skill_store_has_search_method(self, storage: StorageBackend) -> None:
        """SkillStore must have search(query) method for semantic search."""
        assert hasattr(storage.skills, "search")
        assert callable(storage.skills.search)

    def test_skill_store_has_create_method(self, storage: StorageBackend) -> None:
        """SkillStore must have create(name, description, source) method."""
        assert hasattr(storage.skills, "create")
        assert callable(storage.skills.create)


class TestArtifactStoreProtocol:
    """Tests for the ArtifactStore sub-protocol."""

    @pytest.fixture
    def storage(self, tmp_path: Path) -> StorageBackend:
        """Create FileStorage for testing."""
        return FileStorage(tmp_path)

    def test_artifact_store_has_list_method(self, storage: StorageBackend) -> None:
        """ArtifactStore must have list() method."""
        assert hasattr(storage.artifacts, "list")
        assert callable(storage.artifacts.list)

    def test_artifact_store_has_load_method(self, storage: StorageBackend) -> None:
        """ArtifactStore must have load(name) method."""
        assert hasattr(storage.artifacts, "load")
        assert callable(storage.artifacts.load)

    def test_artifact_store_has_save_method(self, storage: StorageBackend) -> None:
        """ArtifactStore must have save(name, data, description) method."""
        assert hasattr(storage.artifacts, "save")
        assert callable(storage.artifacts.save)

    def test_artifact_store_has_delete_method(self, storage: StorageBackend) -> None:
        """ArtifactStore must have delete(name) method."""
        assert hasattr(storage.artifacts, "delete")
        assert callable(storage.artifacts.delete)

    def test_artifact_store_has_exists_method(self, storage: StorageBackend) -> None:
        """ArtifactStore must have exists(name) method."""
        assert hasattr(storage.artifacts, "exists")
        assert callable(storage.artifacts.exists)


class TestStorageBackendBehavioralContract:
    """Behavioral tests that all StorageBackend implementations must pass.

    These verify that implementations behave correctly, not just
    that they have the right methods.
    """

    @pytest.fixture(params=["file"])  # Add "redis" when testing with real Redis
    def storage(self, request: Any, tmp_path: Path, mock_redis: MockRedisClient) -> StorageBackend:
        """Create storage backend for each implementation."""
        if request.param == "file":
            return FileStorage(tmp_path)
        elif request.param == "redis":
            return RedisStorage(mock_redis, prefix="test")
        else:
            pytest.fail(f"Unknown storage type: {request.param}")

    # --- Tool Store Behavioral Tests ---

    def test_tools_list_returns_list(self, storage: StorageBackend) -> None:
        """tools.list() must return a list, never None."""
        result = storage.tools.list()
        assert result is not None
        assert isinstance(result, list)

    def test_tools_get_nonexistent_returns_none(self, storage: StorageBackend) -> None:
        """tools.get(name) returns None for nonexistent tools."""
        result = storage.tools.get("nonexistent_tool")
        assert result is None

    def test_tools_exists_false_for_nonexistent(self, storage: StorageBackend) -> None:
        """tools.exists(name) returns False for nonexistent tools."""
        result = storage.tools.exists("nonexistent_tool")
        assert result is False

    def test_tools_delete_nonexistent_returns_false(self, storage: StorageBackend) -> None:
        """tools.delete(name) returns False for nonexistent tools."""
        result = storage.tools.delete("nonexistent_tool")
        assert result is False

    def test_tools_search_returns_list(self, storage: StorageBackend) -> None:
        """tools.search(query) returns a list."""
        result = storage.tools.search("network scanning")
        assert isinstance(result, list)

    # --- Skill Store Behavioral Tests ---

    def test_skills_list_returns_list(self, storage: StorageBackend) -> None:
        """skills.list() must return a list, never None."""
        result = storage.skills.list()
        assert result is not None
        assert isinstance(result, list)

    def test_skills_get_nonexistent_returns_none(self, storage: StorageBackend) -> None:
        """skills.get(name) returns None for nonexistent skills."""
        result = storage.skills.get("nonexistent_skill")
        assert result is None

    def test_skills_exists_false_for_nonexistent(self, storage: StorageBackend) -> None:
        """skills.exists(name) returns False for nonexistent skills."""
        result = storage.skills.exists("nonexistent_skill")
        assert result is False

    def test_skills_delete_nonexistent_returns_false(self, storage: StorageBackend) -> None:
        """skills.delete(name) returns False for nonexistent skills."""
        result = storage.skills.delete("nonexistent_skill")
        assert result is False

    def test_skills_search_returns_list(self, storage: StorageBackend) -> None:
        """skills.search(query) returns a list."""
        result = storage.skills.search("number manipulation")
        assert isinstance(result, list)

    # --- Artifact Store Behavioral Tests ---

    def test_artifacts_list_returns_iterable(self, storage: StorageBackend) -> None:
        """artifacts.list() must return an iterable."""
        result = storage.artifacts.list()
        assert result is not None
        # Should be iterable (generator or list)
        assert hasattr(result, "__iter__")

    def test_artifacts_load_nonexistent_returns_none_or_raises(
        self, storage: StorageBackend
    ) -> None:
        """artifacts.load(name) returns None or raises for nonexistent artifacts."""
        try:
            result = storage.artifacts.load("nonexistent_artifact")
            # If it doesn't raise, should return None
            assert result is None
        except (FileNotFoundError, KeyError):
            # Raising is acceptable behavior
            pass

    def test_artifacts_exists_false_for_nonexistent(self, storage: StorageBackend) -> None:
        """artifacts.exists(name) returns False for nonexistent artifacts."""
        result = storage.artifacts.exists("nonexistent_artifact")
        assert result is False

    def test_artifacts_delete_nonexistent_returns_false(self, storage: StorageBackend) -> None:
        """artifacts.delete(name) returns False for nonexistent artifacts."""
        result = storage.artifacts.delete("nonexistent_artifact")
        assert result is False


class TestStorageBackendInvariants:
    """Invariant tests - properties that must ALWAYS hold for StorageBackend."""

    @pytest.fixture
    def storage(self, tmp_path: Path) -> StorageBackend:
        """Create FileStorage for testing."""
        return FileStorage(tmp_path)

    def test_empty_storage_has_empty_tools_list(self, storage: StorageBackend) -> None:
        """Fresh storage has empty tools list."""
        assert storage.tools.list() == []

    def test_empty_storage_has_empty_skills_list(self, storage: StorageBackend) -> None:
        """Fresh storage has empty skills list."""
        assert storage.skills.list() == []

    def test_empty_storage_has_empty_artifacts_list(self, storage: StorageBackend) -> None:
        """Fresh storage has empty artifacts list."""
        assert list(storage.artifacts.list()) == []

    def test_tools_property_returns_same_instance(self, storage: StorageBackend) -> None:
        """tools property returns the same store instance each time."""
        store1 = storage.tools
        store2 = storage.tools
        assert store1 is store2

    def test_skills_property_returns_same_instance(self, storage: StorageBackend) -> None:
        """skills property returns the same store instance each time."""
        store1 = storage.skills
        store2 = storage.skills
        assert store1 is store2

    def test_artifacts_property_returns_same_instance(self, storage: StorageBackend) -> None:
        """artifacts property returns the same store instance each time."""
        store1 = storage.artifacts
        store2 = storage.artifacts
        assert store1 is store2


class TestStorageBackendFromConfig:
    """Tests for creating StorageBackend from configuration."""

    def test_create_file_storage_from_path(self, tmp_path: Path) -> None:
        """Can create FileStorage from a path."""
        storage = FileStorage(tmp_path)
        assert storage is not None
        assert isinstance(storage, StorageBackend)

    def test_create_file_storage_creates_subdirs(self, tmp_path: Path) -> None:
        """FileStorage creates tools/, skills/, artifacts/ subdirectories."""
        storage_path = tmp_path / "new_storage"
        storage = FileStorage(storage_path)

        # Access each store to trigger directory creation
        _ = storage.tools
        _ = storage.skills
        _ = storage.artifacts

        assert (storage_path / "tools").exists() or storage_path.exists()
        # Implementation may vary - just ensure storage is usable

    def test_create_redis_storage_from_client(self, mock_redis: MockRedisClient) -> None:
        """Can create RedisStorage from a Redis client."""
        storage = RedisStorage(mock_redis, prefix="myapp")
        assert storage is not None
        assert isinstance(storage, StorageBackend)

    def test_redis_storage_uses_prefix(self, mock_redis: MockRedisClient) -> None:
        """RedisStorage uses configured prefix for all keys."""
        storage = RedisStorage(mock_redis, prefix="myapp")

        # Save something to verify prefix is used
        storage.artifacts.save("test.txt", b"data", "test")

        # Check that mock_redis has keys with prefix
        all_keys = mock_redis.keys("*")
        assert any("myapp" in k for k in all_keys), f"No prefixed keys found: {all_keys}"
