"""Tests for StorageBackend.get_serializable_access() method.

This method returns serializable access descriptors for cross-process communication.
Used by executors that run in separate processes (like ContainerExecutor) and need
connection info rather than direct object references.

TDD RED phase: These tests are written before implementation.
They will fail until get_serializable_access() is implemented on both backends.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from py_code_mode.execution.protocol import FileStorageAccess, RedisStorageAccess
from py_code_mode.storage import FileStorage, RedisStorage

if TYPE_CHECKING:
    from tests.conftest import MockRedisClient


class TestGetSerializableAccess:
    """Tests for StorageBackend.get_serializable_access() method.

    This method enables cross-process communication by returning
    serializable descriptors that contain paths/URLs instead of
    live object references.
    """

    # =========================================================================
    # FileStorage.get_serializable_access() tests
    # =========================================================================

    class TestFileStorageAccess:
        """Tests for FileStorage.get_serializable_access()."""

        def test_returns_file_storage_access_type(self, tmp_path: Path) -> None:
            """get_serializable_access() returns FileStorageAccess instance.

            Breaks when: Return type is wrong or method doesn't exist.
            """
            storage = FileStorage(tmp_path)

            result = storage.get_serializable_access()

            assert isinstance(result, FileStorageAccess)

        # NOTE: tools_path tests removed - tools now owned by executors, not storage

        def test_skills_path_is_always_set(self, tmp_path: Path) -> None:
            """skills_path is always set (points to skills/ subdirectory).

            Breaks when: skills_path is None or points to wrong location.
            """
            storage = FileStorage(tmp_path)

            result = storage.get_serializable_access()

            expected_skills_path = tmp_path / "skills"
            assert result.skills_path == expected_skills_path

        def test_artifacts_path_is_always_set(self, tmp_path: Path) -> None:
            """artifacts_path is always set (points to artifacts/ subdirectory).

            Breaks when: artifacts_path is None or points to wrong location.
            """
            storage = FileStorage(tmp_path)

            result = storage.get_serializable_access()

            expected_artifacts_path = tmp_path / "artifacts"
            assert result.artifacts_path == expected_artifacts_path

        def test_paths_are_absolute(self, tmp_path: Path) -> None:
            """All returned paths are absolute paths.

            Breaks when: Relative paths are returned (would break cross-process use).
            """
            storage = FileStorage(tmp_path)

            result = storage.get_serializable_access()

            # skills_path may be None if skills directory doesn't exist
            if result.skills_path is not None:
                assert result.skills_path.is_absolute()
            assert result.artifacts_path.is_absolute()

        def test_access_descriptor_is_frozen_dataclass(self, tmp_path: Path) -> None:
            """FileStorageAccess is immutable (frozen dataclass).

            Breaks when: Descriptor can be mutated after creation.
            """
            storage = FileStorage(tmp_path)

            result = storage.get_serializable_access()

            with pytest.raises(AttributeError):
                result.artifacts_path = Path("/hacked")  # type: ignore[misc]

    # =========================================================================
    # RedisStorage.get_serializable_access() tests
    # =========================================================================

    class TestRedisStorageAccess:
        """Tests for RedisStorage.get_serializable_access()."""

        def test_returns_redis_storage_access_type(self, mock_redis: MockRedisClient) -> None:
            """get_serializable_access() returns RedisStorageAccess instance.

            Breaks when: Return type is wrong or method doesn't exist.
            """
            storage = RedisStorage(redis=mock_redis, prefix="test")

            result = storage.get_serializable_access()

            assert isinstance(result, RedisStorageAccess)

        def test_redis_url_is_correctly_reconstructed(self, mock_redis: MockRedisClient) -> None:
            """redis_url is reconstructed from connection pool kwargs.

            Breaks when: URL format is wrong or components are missing.
            """
            storage = RedisStorage(redis=mock_redis, prefix="test")

            result = storage.get_serializable_access()

            # MockRedisClient defaults: host=localhost, port=6379, db=0
            assert result.redis_url == "redis://localhost:6379/0"

        def test_redis_url_includes_password_when_present(self) -> None:
            """redis_url includes password in URL format when set.

            Breaks when: Password is omitted or URL format is wrong.
            """
            from tests.conftest import MockRedisClient

            # Create mock with password
            mock_with_password = MockRedisClient(
                host="redis.example.com",
                port=6380,
                db=2,
                password="secret123",
            )
            storage = RedisStorage(redis=mock_with_password, prefix="secure")

            result = storage.get_serializable_access()

            assert result.redis_url == "redis://:secret123@redis.example.com:6380/2"

        def test_redis_url_without_password(self) -> None:
            """redis_url works correctly when no password is set.

            Breaks when: Empty password breaks URL format.
            """
            from tests.conftest import MockRedisClient

            mock_no_password = MockRedisClient(
                host="localhost",
                port=6379,
                db=0,
                password=None,
            )
            storage = RedisStorage(redis=mock_no_password, prefix="test")

            result = storage.get_serializable_access()

            # Should not have :password@ in URL
            assert "@" not in result.redis_url
            assert result.redis_url == "redis://localhost:6379/0"

        # NOTE: tools_prefix test removed - tools now owned by executors, not storage

        def test_skills_prefix_is_correctly_formatted(self, mock_redis: MockRedisClient) -> None:
            """skills_prefix follows {prefix}:skills format.

            Breaks when: Prefix format doesn't match expected pattern.
            """
            storage = RedisStorage(redis=mock_redis, prefix="myapp")

            result = storage.get_serializable_access()

            assert result.skills_prefix == "myapp:skills"

        def test_artifacts_prefix_is_correctly_formatted(self, mock_redis: MockRedisClient) -> None:
            """artifacts_prefix follows {prefix}:artifacts format.

            Breaks when: Prefix format doesn't match expected pattern.
            """
            storage = RedisStorage(redis=mock_redis, prefix="myapp")

            result = storage.get_serializable_access()

            assert result.artifacts_prefix == "myapp:artifacts"

        def test_access_descriptor_is_frozen_dataclass(self, mock_redis: MockRedisClient) -> None:
            """RedisStorageAccess is immutable (frozen dataclass).

            Breaks when: Descriptor can be mutated after creation.
            """
            storage = RedisStorage(redis=mock_redis, prefix="test")

            result = storage.get_serializable_access()

            with pytest.raises(AttributeError):
                result.redis_url = "redis://hacked:6379/0"  # type: ignore[misc]

        def test_uses_custom_host_and_port(self) -> None:
            """redis_url uses custom host and port from connection.

            Breaks when: Default host/port is used instead of actual values.
            """
            from tests.conftest import MockRedisClient

            mock_custom = MockRedisClient(
                host="redis-cluster.internal",
                port=16379,
                db=5,
            )
            storage = RedisStorage(redis=mock_custom, prefix="production")

            result = storage.get_serializable_access()

            assert result.redis_url == "redis://redis-cluster.internal:16379/5"

    # =========================================================================
    # Protocol compliance tests
    # =========================================================================

    class TestProtocolCompliance:
        """Tests verifying both implementations satisfy the protocol."""

        def test_file_storage_returns_union_type(self, tmp_path: Path) -> None:
            """FileStorage returns type compatible with StorageAccess union.

            Breaks when: Return type doesn't match expected union.
            """
            storage = FileStorage(tmp_path)

            result = storage.get_serializable_access()

            # Should be FileStorageAccess (part of the union)
            assert isinstance(result, FileStorageAccess)

        def test_redis_storage_returns_union_type(self, mock_redis: MockRedisClient) -> None:
            """RedisStorage returns type compatible with StorageAccess union.

            Breaks when: Return type doesn't match expected union.
            """
            storage = RedisStorage(redis=mock_redis, prefix="test")

            result = storage.get_serializable_access()

            # Should be RedisStorageAccess (part of the union)
            assert isinstance(result, RedisStorageAccess)

        def test_method_exists_on_file_storage(self, tmp_path: Path) -> None:
            """FileStorage has get_serializable_access method.

            Breaks when: Method is missing from implementation.
            """
            storage = FileStorage(tmp_path)

            assert hasattr(storage, "get_serializable_access")
            assert callable(storage.get_serializable_access)

        def test_method_exists_on_redis_storage(self, mock_redis: MockRedisClient) -> None:
            """RedisStorage has get_serializable_access method.

            Breaks when: Method is missing from implementation.
            """
            storage = RedisStorage(redis=mock_redis, prefix="test")

            assert hasattr(storage, "get_serializable_access")
            assert callable(storage.get_serializable_access)


# NOTE: TestStorageBackendExecutionMethods was removed in the executor-ownership refactor.
# storage.get_tool_registry() was removed - tools are now owned by executors via config.
# storage.get_skill_library() tests remain in test_skills.py and test_semantic.py.
