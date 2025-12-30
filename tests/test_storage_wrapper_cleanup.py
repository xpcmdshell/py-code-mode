"""Tests for Track B: Wrapper Cleanup.

Verifies that wrapper layers have been removed from StorageBackend and that
the simplified "protocol -> implementation" architecture is in place.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from py_code_mode.artifacts import ArtifactStoreProtocol
from py_code_mode.skills import SkillLibrary
from py_code_mode.storage import FileStorage, RedisStorage
from py_code_mode.tools import ToolRegistry

if TYPE_CHECKING:
    from tests.conftest import MockRedisClient


class TestWrapperPropertiesRemoved:
    """Verify .tools, .skills, .artifacts properties are REMOVED."""

    def test_file_storage_no_tools_property(self, tmp_path: Path) -> None:
        """FileStorage.tools property must be removed.

        Breaks when: Property still exists (should raise AttributeError).
        """
        storage = FileStorage(tmp_path)

        with pytest.raises(AttributeError):
            _ = storage.tools

    def test_file_storage_no_skills_property(self, tmp_path: Path) -> None:
        """FileStorage.skills property must be removed.

        Breaks when: Property still exists (should raise AttributeError).
        """
        storage = FileStorage(tmp_path)

        with pytest.raises(AttributeError):
            _ = storage.skills

    def test_file_storage_no_artifacts_property(self, tmp_path: Path) -> None:
        """FileStorage.artifacts property must be removed.

        Breaks when: Property still exists (should raise AttributeError).
        """
        storage = FileStorage(tmp_path)

        with pytest.raises(AttributeError):
            _ = storage.artifacts

    def test_redis_storage_no_tools_property(self, mock_redis: MockRedisClient) -> None:
        """RedisStorage.tools property must be removed.

        Breaks when: Property still exists (should raise AttributeError).
        """
        storage = RedisStorage(redis=mock_redis, prefix="test")

        with pytest.raises(AttributeError):
            _ = storage.tools

    def test_redis_storage_no_skills_property(self, mock_redis: MockRedisClient) -> None:
        """RedisStorage.skills property must be removed.

        Breaks when: Property still exists (should raise AttributeError).
        """
        storage = RedisStorage(redis=mock_redis, prefix="test")

        with pytest.raises(AttributeError):
            _ = storage.skills

    def test_redis_storage_no_artifacts_property(self, mock_redis: MockRedisClient) -> None:
        """RedisStorage.artifacts property must be removed.

        Breaks when: Property still exists (should raise AttributeError).
        """
        storage = RedisStorage(redis=mock_redis, prefix="test")

        with pytest.raises(AttributeError):
            _ = storage.artifacts


class TestGetMethodsReturnDirectTypes:
    """Verify get_X() methods return direct types, not wrappers."""

    @pytest.mark.asyncio
    async def test_file_storage_get_tool_registry_returns_tool_registry(
        self, tmp_path: Path
    ) -> None:
        """get_tool_registry() returns ToolRegistry directly.

        Breaks when: Returns dict wrapper or wrong type.
        """
        storage = FileStorage(tmp_path)

        result = await storage.get_tool_registry()

        assert isinstance(result, ToolRegistry)

    def test_file_storage_get_skill_library_returns_skill_library(self, tmp_path: Path) -> None:
        """get_skill_library() returns SkillLibrary directly.

        Breaks when: Returns SkillStoreWrapper or wrong type.
        """
        storage = FileStorage(tmp_path)

        result = storage.get_skill_library()

        assert isinstance(result, SkillLibrary)

    def test_file_storage_get_artifact_store_returns_artifact_store_protocol(
        self, tmp_path: Path
    ) -> None:
        """get_artifact_store() returns ArtifactStoreProtocol directly.

        Breaks when: Returns ArtifactStoreWrapper instead of protocol impl.
        """
        storage = FileStorage(tmp_path)

        result = storage.get_artifact_store()

        assert isinstance(result, ArtifactStoreProtocol)
        # Should NOT be ArtifactStoreWrapper - check type name
        assert type(result).__name__ != "ArtifactStoreWrapper"

    @pytest.mark.asyncio
    async def test_redis_storage_get_tool_registry_returns_tool_registry(
        self, mock_redis: MockRedisClient
    ) -> None:
        """get_tool_registry() returns ToolRegistry directly.

        Breaks when: Returns dict wrapper or wrong type.
        """
        storage = RedisStorage(redis=mock_redis, prefix="test")

        result = await storage.get_tool_registry()

        assert isinstance(result, ToolRegistry)

    def test_redis_storage_get_skill_library_returns_skill_library(
        self, mock_redis: MockRedisClient
    ) -> None:
        """get_skill_library() returns SkillLibrary directly.

        Breaks when: Returns SkillStoreWrapper or wrong type.
        """
        storage = RedisStorage(redis=mock_redis, prefix="test")

        result = storage.get_skill_library()

        assert isinstance(result, SkillLibrary)

    def test_redis_storage_get_artifact_store_returns_artifact_store_protocol(
        self, mock_redis: MockRedisClient
    ) -> None:
        """get_artifact_store() returns ArtifactStoreProtocol directly.

        Breaks when: Returns ArtifactStoreWrapper instead of protocol impl.
        """
        storage = RedisStorage(redis=mock_redis, prefix="test")

        result = storage.get_artifact_store()

        assert isinstance(result, ArtifactStoreProtocol)
        # Should NOT be ArtifactStoreWrapper - check type name
        assert type(result).__name__ != "ArtifactStoreWrapper"


class TestWrapperClassesNotExported:
    """Verify wrapper classes are removed from exports."""

    def test_file_tool_store_not_exported(self) -> None:
        """FileToolStore should not be in storage exports.

        Breaks when: Class is still exported from py_code_mode.storage.
        """
        from py_code_mode import storage

        assert not hasattr(storage, "FileToolStore")

    def test_redis_tool_store_wrapper_not_exported(self) -> None:
        """RedisToolStoreWrapper should not be in storage exports.

        Breaks when: Class is still exported from py_code_mode.storage.
        """
        from py_code_mode import storage

        assert not hasattr(storage, "RedisToolStoreWrapper")

    def test_skill_store_wrapper_not_exported(self) -> None:
        """SkillStoreWrapper should not be in storage exports.

        Breaks when: Class is still exported from py_code_mode.storage.
        """
        from py_code_mode import storage

        assert not hasattr(storage, "SkillStoreWrapper")

    def test_artifact_store_wrapper_not_exported(self) -> None:
        """ArtifactStoreWrapper should not be in storage exports.

        Breaks when: Class is still exported from py_code_mode.storage.
        """
        from py_code_mode import storage

        assert not hasattr(storage, "ArtifactStoreWrapper")

    def test_tool_store_protocol_not_exported(self) -> None:
        """ToolStore protocol should not be in storage exports.

        Breaks when: Protocol is still exported from py_code_mode.storage.
        """
        from py_code_mode import storage

        assert not hasattr(storage, "ToolStore")

    def test_skill_store_wrapper_protocol_not_exported(self) -> None:
        """SkillStoreWrapperProtocol should not be in storage exports.

        Breaks when: Protocol is still exported from py_code_mode.storage.
        """
        from py_code_mode import storage

        assert not hasattr(storage, "SkillStoreWrapperProtocol")

    def test_artifact_store_wrapper_protocol_not_exported(self) -> None:
        """ArtifactStoreWrapperProtocol should not be in storage exports.

        Breaks when: Protocol is still exported from py_code_mode.storage.
        """
        from py_code_mode import storage

        assert not hasattr(storage, "ArtifactStoreWrapperProtocol")


class TestArtifactStoreProtocolOptionalDescription:
    """Verify ArtifactStoreProtocol.save() accepts optional description."""

    def test_file_artifact_store_save_with_empty_description(self, tmp_path: Path) -> None:
        """FileArtifactStore.save() works with empty description.

        Breaks when: Empty description causes error.
        """
        from py_code_mode.artifacts import FileArtifactStore

        store = FileArtifactStore(tmp_path)

        artifact = store.save("test.txt", "content", "")

        assert artifact.description == ""
        assert store.exists("test.txt")

    def test_redis_artifact_store_save_with_empty_description(
        self, mock_redis: MockRedisClient
    ) -> None:
        """RedisArtifactStore.save() works with empty description.

        Breaks when: Empty description causes error.
        """
        from py_code_mode.artifacts import RedisArtifactStore

        store = RedisArtifactStore(mock_redis, prefix="test")

        artifact = store.save("test.txt", "content", "")

        assert artifact.description == ""
        assert store.exists("test.txt")


class TestStorageBackendProtocolSimplified:
    """Verify StorageBackend protocol has only the required methods."""

    def test_storage_backend_has_get_tool_registry(self) -> None:
        """StorageBackend protocol must have get_tool_registry method.

        Breaks when: Method is missing from protocol.
        """
        from py_code_mode.storage.backends import StorageBackend

        # Check method exists in protocol
        assert hasattr(StorageBackend, "get_tool_registry")

    def test_storage_backend_has_get_skill_library(self) -> None:
        """StorageBackend protocol must have get_skill_library method.

        Breaks when: Method is missing from protocol.
        """
        from py_code_mode.storage.backends import StorageBackend

        assert hasattr(StorageBackend, "get_skill_library")

    def test_storage_backend_has_get_artifact_store(self) -> None:
        """StorageBackend protocol must have get_artifact_store method.

        Breaks when: Method is missing from protocol.
        """
        from py_code_mode.storage.backends import StorageBackend

        assert hasattr(StorageBackend, "get_artifact_store")

    def test_storage_backend_has_get_serializable_access(self) -> None:
        """StorageBackend protocol must have get_serializable_access method.

        Breaks when: Method is missing from protocol.
        """
        from py_code_mode.storage.backends import StorageBackend

        assert hasattr(StorageBackend, "get_serializable_access")

    def test_storage_backend_no_tools_property(self) -> None:
        """StorageBackend protocol must NOT have tools property.

        Breaks when: Property still exists in protocol.
        """
        from py_code_mode.storage.backends import StorageBackend

        # Protocol should not have 'tools' as an attribute
        # Check annotations instead of hasattr (protocols use annotations)
        annotations = getattr(StorageBackend, "__protocol_attrs__", set())
        assert "tools" not in annotations

    def test_storage_backend_no_skills_property(self) -> None:
        """StorageBackend protocol must NOT have skills property.

        Breaks when: Property still exists in protocol.
        """
        from py_code_mode.storage.backends import StorageBackend

        annotations = getattr(StorageBackend, "__protocol_attrs__", set())
        assert "skills" not in annotations

    def test_storage_backend_no_artifacts_property(self) -> None:
        """StorageBackend protocol must NOT have artifacts property.

        Breaks when: Property still exists in protocol.
        """
        from py_code_mode.storage.backends import StorageBackend

        annotations = getattr(StorageBackend, "__protocol_attrs__", set())
        assert "artifacts" not in annotations
