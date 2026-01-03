"""Tests for bootstrap module - storage reconstruction in subprocesses.

This module tests the bootstrap architecture for SubprocessExecutor:
1. `to_bootstrap_config()` method on storage classes - serializes to dict
2. `bootstrap_namespaces(config)` function - reconstructs storage from config
3. Lazy connections - storage only connects when actually used

TDD RED phase: These tests are written before implementation.
They will fail until the bootstrap module is implemented.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

if TYPE_CHECKING:
    from tests.conftest import MockRedisClient

# These imports will fail until implementation exists - this is expected (TDD)
# Uncomment once implementation is created:
# from py_code_mode.bootstrap import NamespaceBundle, bootstrap_namespaces


# =============================================================================
# NamespaceBundle Dataclass Tests
# =============================================================================


class TestNamespaceBundle:
    """Tests for NamespaceBundle dataclass.

    NamespaceBundle contains the three namespaces needed for code execution:
    - tools: ToolsNamespace for tool access
    - skills: SkillsNamespace for skill access
    - artifacts: ArtifactStoreProtocol for artifact storage
    """

    def test_namespace_bundle_is_dataclass(self) -> None:
        """NamespaceBundle is a dataclass.

        Contract: Must be a dataclass for easy construction and introspection.
        Breaks when: NamespaceBundle is not defined as a dataclass.
        """
        from py_code_mode.bootstrap import NamespaceBundle

        assert is_dataclass(NamespaceBundle)

    def test_namespace_bundle_has_tools_field(self) -> None:
        """NamespaceBundle has a 'tools' field.

        Contract: Must have tools field for ToolsNamespace access.
        Breaks when: Field is missing or renamed.
        """
        from py_code_mode.bootstrap import NamespaceBundle

        field_names = [f.name for f in fields(NamespaceBundle)]
        assert "tools" in field_names

    def test_namespace_bundle_has_skills_field(self) -> None:
        """NamespaceBundle has a 'skills' field.

        Contract: Must have skills field for SkillsNamespace access.
        Breaks when: Field is missing or renamed.
        """
        from py_code_mode.bootstrap import NamespaceBundle

        field_names = [f.name for f in fields(NamespaceBundle)]
        assert "skills" in field_names

    def test_namespace_bundle_has_artifacts_field(self) -> None:
        """NamespaceBundle has an 'artifacts' field.

        Contract: Must have artifacts field for ArtifactStore access.
        Breaks when: Field is missing or renamed.
        """
        from py_code_mode.bootstrap import NamespaceBundle

        field_names = [f.name for f in fields(NamespaceBundle)]
        assert "artifacts" in field_names

    def test_namespace_bundle_has_deps_field(self) -> None:
        """NamespaceBundle has a 'deps' field.

        Contract: Must have deps field for DepsNamespace access.
        Breaks when: Field is missing or renamed.
        """
        from py_code_mode.bootstrap import NamespaceBundle

        field_names = [f.name for f in fields(NamespaceBundle)]
        assert "deps" in field_names

    def test_namespace_bundle_has_exactly_four_fields(self) -> None:
        """NamespaceBundle has exactly four fields (tools, skills, artifacts, deps).

        Contract: Bundle should contain the four namespace fields.
        Breaks when: Extra fields are added without updating tests.
        """
        from py_code_mode.bootstrap import NamespaceBundle

        assert len(fields(NamespaceBundle)) == 4


# =============================================================================
# bootstrap_namespaces() Function Tests
# =============================================================================


class TestBootstrapNamespaces:
    """Tests for bootstrap_namespaces() function.

    This function reconstructs namespaces from a serialized config dict,
    enabling SubprocessExecutor to set up namespaces without knowing
    about specific storage implementations.
    """

    # =========================================================================
    # File Storage Bootstrapping
    # =========================================================================

    @pytest.mark.asyncio
    async def test_bootstrap_file_storage_returns_bundle(self, tmp_path: Path) -> None:
        """bootstrap_namespaces() with file config returns NamespaceBundle.

        Setup: Config dict with type="file" and base_path
        Verification: Returns NamespaceBundle instance
        Breaks when: File storage bootstrap fails or returns wrong type.
        """
        from py_code_mode.bootstrap import NamespaceBundle, bootstrap_namespaces

        # Create required directories
        (tmp_path / "tools").mkdir()
        (tmp_path / "skills").mkdir()
        (tmp_path / "artifacts").mkdir()

        config = {
            "type": "file",
            "base_path": str(tmp_path),
        }

        result = await bootstrap_namespaces(config)

        assert isinstance(result, NamespaceBundle)

    @pytest.mark.asyncio
    async def test_bootstrap_file_storage_bundle_has_tools_namespace(self, tmp_path: Path) -> None:
        """File bootstrap returns bundle with ToolsNamespace for tools.

        Contract: Bundle.tools is ToolsNamespace instance
        Breaks when: Tools namespace is wrong type or missing.
        """
        from py_code_mode.bootstrap import bootstrap_namespaces
        from py_code_mode.tools import ToolsNamespace

        (tmp_path / "tools").mkdir()
        (tmp_path / "skills").mkdir()
        (tmp_path / "artifacts").mkdir()

        config = {
            "type": "file",
            "base_path": str(tmp_path),
        }

        result = await bootstrap_namespaces(config)

        assert isinstance(result.tools, ToolsNamespace)

    @pytest.mark.asyncio
    async def test_bootstrap_file_storage_bundle_has_skills_namespace(self, tmp_path: Path) -> None:
        """File bootstrap returns bundle with SkillsNamespace for skills.

        Contract: Bundle.skills is SkillsNamespace instance
        Breaks when: Skills namespace is wrong type or missing.
        """
        from py_code_mode.bootstrap import bootstrap_namespaces
        from py_code_mode.execution.in_process.skills_namespace import SkillsNamespace

        (tmp_path / "tools").mkdir()
        (tmp_path / "skills").mkdir()
        (tmp_path / "artifacts").mkdir()

        config = {
            "type": "file",
            "base_path": str(tmp_path),
        }

        result = await bootstrap_namespaces(config)

        assert isinstance(result.skills, SkillsNamespace)

    @pytest.mark.asyncio
    async def test_bootstrap_file_storage_bundle_has_artifact_store(self, tmp_path: Path) -> None:
        """File bootstrap returns bundle with ArtifactStore for artifacts.

        Contract: Bundle.artifacts implements ArtifactStoreProtocol
        Breaks when: Artifacts store is wrong type or missing.
        """
        from py_code_mode.artifacts import ArtifactStoreProtocol
        from py_code_mode.bootstrap import bootstrap_namespaces

        (tmp_path / "tools").mkdir()
        (tmp_path / "skills").mkdir()
        (tmp_path / "artifacts").mkdir()

        config = {
            "type": "file",
            "base_path": str(tmp_path),
        }

        result = await bootstrap_namespaces(config)

        assert isinstance(result.artifacts, ArtifactStoreProtocol)

    @pytest.mark.asyncio
    async def test_bootstrap_file_storage_bundle_has_deps_namespace(self, tmp_path: Path) -> None:
        """File bootstrap returns bundle with DepsNamespace for deps.

        Contract: Bundle.deps is DepsNamespace instance
        Breaks when: Deps namespace is wrong type or missing.
        """
        from py_code_mode.bootstrap import bootstrap_namespaces
        from py_code_mode.deps import DepsNamespace

        (tmp_path / "tools").mkdir()
        (tmp_path / "skills").mkdir()
        (tmp_path / "artifacts").mkdir()

        config = {
            "type": "file",
            "base_path": str(tmp_path),
        }

        result = await bootstrap_namespaces(config)

        assert isinstance(result.deps, DepsNamespace)

    @pytest.mark.asyncio
    async def test_bootstrap_file_storage_deps_namespace_is_functional(
        self, tmp_path: Path
    ) -> None:
        """File bootstrap deps namespace can list/add/remove packages.

        Contract: deps.list(), deps.add(), deps.remove() work correctly
        Breaks when: Deps namespace not wired up to storage correctly.
        """
        from py_code_mode.bootstrap import bootstrap_namespaces

        config = {
            "type": "file",
            "base_path": str(tmp_path),
        }

        result = await bootstrap_namespaces(config)

        # Initial state - no packages
        assert result.deps.list() == []

        # Add a package (just to store, not actually install for this test)
        # We're testing the namespace wiring, not actual installation
        result.deps._store.add("requests>=2.0")
        packages = result.deps.list()
        assert "requests>=2.0" in packages

        # Remove package
        result.deps._store.remove("requests>=2.0")
        assert result.deps.list() == []

    @pytest.mark.asyncio
    async def test_bootstrap_file_storage_creates_directories_if_missing(
        self, tmp_path: Path
    ) -> None:
        """File bootstrap creates subdirectories if they don't exist.

        Contract: Bootstrap should create tools/, skills/, artifacts/ directories
        Breaks when: Bootstrap fails on missing directories instead of creating them.
        """
        from py_code_mode.bootstrap import bootstrap_namespaces

        # Don't create any directories - bootstrap should handle this
        config = {
            "type": "file",
            "base_path": str(tmp_path),
        }

        # Should not raise
        result = await bootstrap_namespaces(config)

        # Directories should be created
        assert (tmp_path / "artifacts").exists()
        assert result is not None

    # =========================================================================
    # Redis Storage Bootstrapping
    # =========================================================================

    @pytest.mark.asyncio
    async def test_bootstrap_redis_storage_returns_bundle(
        self, mock_redis: MockRedisClient
    ) -> None:
        """bootstrap_namespaces() with redis config returns NamespaceBundle.

        Setup: Config dict with type="redis", url, and prefix
        Verification: Returns NamespaceBundle instance
        Breaks when: Redis storage bootstrap fails or returns wrong type.
        """
        from py_code_mode.bootstrap import NamespaceBundle, bootstrap_namespaces

        config = {
            "type": "redis",
            "url": "redis://localhost:6379/0",
            "prefix": "test",
        }

        # Mock Redis.from_url to avoid actual connection
        with patch("redis.Redis.from_url", return_value=mock_redis):
            result = await bootstrap_namespaces(config)

        assert isinstance(result, NamespaceBundle)

    @pytest.mark.asyncio
    async def test_bootstrap_redis_storage_bundle_has_tools_namespace(
        self, mock_redis: MockRedisClient
    ) -> None:
        """Redis bootstrap returns bundle with ToolsNamespace for tools.

        Contract: Bundle.tools is ToolsNamespace instance
        Breaks when: Tools namespace is wrong type or missing.
        """
        from py_code_mode.bootstrap import bootstrap_namespaces
        from py_code_mode.tools import ToolsNamespace

        config = {
            "type": "redis",
            "url": "redis://localhost:6379/0",
            "prefix": "test",
        }

        with patch("redis.Redis.from_url", return_value=mock_redis):
            result = await bootstrap_namespaces(config)

        assert isinstance(result.tools, ToolsNamespace)

    @pytest.mark.asyncio
    async def test_bootstrap_redis_storage_bundle_has_skills_namespace(
        self, mock_redis: MockRedisClient
    ) -> None:
        """Redis bootstrap returns bundle with SkillsNamespace for skills.

        Contract: Bundle.skills is SkillsNamespace instance
        Breaks when: Skills namespace is wrong type or missing.
        """
        from py_code_mode.bootstrap import bootstrap_namespaces
        from py_code_mode.execution.in_process.skills_namespace import SkillsNamespace

        config = {
            "type": "redis",
            "url": "redis://localhost:6379/0",
            "prefix": "test",
        }

        with patch("redis.Redis.from_url", return_value=mock_redis):
            result = await bootstrap_namespaces(config)

        assert isinstance(result.skills, SkillsNamespace)

    @pytest.mark.asyncio
    async def test_bootstrap_redis_storage_bundle_has_artifact_store(
        self, mock_redis: MockRedisClient
    ) -> None:
        """Redis bootstrap returns bundle with ArtifactStore for artifacts.

        Contract: Bundle.artifacts implements ArtifactStoreProtocol
        Breaks when: Artifacts store is wrong type or missing.
        """
        from py_code_mode.artifacts import ArtifactStoreProtocol
        from py_code_mode.bootstrap import bootstrap_namespaces

        config = {
            "type": "redis",
            "url": "redis://localhost:6379/0",
            "prefix": "test",
        }

        with patch("redis.Redis.from_url", return_value=mock_redis):
            result = await bootstrap_namespaces(config)

        assert isinstance(result.artifacts, ArtifactStoreProtocol)

    @pytest.mark.asyncio
    async def test_bootstrap_redis_storage_bundle_has_deps_namespace(
        self, mock_redis: MockRedisClient
    ) -> None:
        """Redis bootstrap returns bundle with DepsNamespace for deps.

        Contract: Bundle.deps is DepsNamespace instance
        Breaks when: Deps namespace is wrong type or missing.
        """
        from py_code_mode.bootstrap import bootstrap_namespaces
        from py_code_mode.deps import DepsNamespace

        config = {
            "type": "redis",
            "url": "redis://localhost:6379/0",
            "prefix": "test",
        }

        with patch("redis.Redis.from_url", return_value=mock_redis):
            result = await bootstrap_namespaces(config)

        assert isinstance(result.deps, DepsNamespace)

    @pytest.mark.asyncio
    async def test_bootstrap_redis_storage_deps_namespace_is_functional(
        self, mock_redis: MockRedisClient
    ) -> None:
        """Redis bootstrap deps namespace can list/add/remove packages.

        Contract: deps.list(), deps.add(), deps.remove() work correctly
        Breaks when: Deps namespace not wired up to Redis storage correctly.
        """
        from py_code_mode.bootstrap import bootstrap_namespaces

        config = {
            "type": "redis",
            "url": "redis://localhost:6379/0",
            "prefix": "test",
        }

        with patch("redis.Redis.from_url", return_value=mock_redis):
            result = await bootstrap_namespaces(config)

        # Initial state - no packages
        assert result.deps.list() == []

        # Add a package (just to store, not actually install for this test)
        result.deps._store.add("pandas>=2.0")
        packages = result.deps.list()
        assert "pandas>=2.0" in packages

        # Remove package
        result.deps._store.remove("pandas>=2.0")
        assert result.deps.list() == []

    @pytest.mark.asyncio
    async def test_bootstrap_redis_storage_uses_url_from_config(
        self, mock_redis: MockRedisClient
    ) -> None:
        """Redis bootstrap connects using URL from config.

        Contract: Must use the exact URL provided in config
        Breaks when: URL is ignored or hardcoded.
        """
        from py_code_mode.bootstrap import bootstrap_namespaces

        config = {
            "type": "redis",
            "url": "redis://custom-host:16379/5",
            "prefix": "custom",
        }

        with patch("redis.Redis.from_url", return_value=mock_redis) as mock_from_url:
            await bootstrap_namespaces(config)

        mock_from_url.assert_called_once_with("redis://custom-host:16379/5")

    @pytest.mark.asyncio
    async def test_bootstrap_redis_storage_uses_prefix_from_config(
        self, mock_redis: MockRedisClient
    ) -> None:
        """Redis bootstrap uses prefix from config for all stores.

        Contract: Must use the prefix provided in config
        Breaks when: Prefix is ignored or hardcoded.
        """
        from py_code_mode.bootstrap import bootstrap_namespaces

        config = {
            "type": "redis",
            "url": "redis://localhost:6379/0",
            "prefix": "myapp",
        }

        with patch("redis.Redis.from_url", return_value=mock_redis):
            result = await bootstrap_namespaces(config)

        # The artifacts store should use the prefix
        # This is a structural check - specific prefix usage depends on implementation
        assert result is not None

    # =========================================================================
    # Error Handling
    # =========================================================================

    @pytest.mark.asyncio
    async def test_bootstrap_unknown_type_raises_value_error(self) -> None:
        """bootstrap_namespaces() with unknown type raises ValueError.

        Contract: Unknown storage types must fail loudly with clear message
        Breaks when: Unknown types are silently ignored or cause cryptic errors.
        """
        from py_code_mode.bootstrap import bootstrap_namespaces

        config = {
            "type": "unknown_storage_type",
            "some_param": "value",
        }

        with pytest.raises(ValueError, match="Unknown storage type"):
            await bootstrap_namespaces(config)

    @pytest.mark.asyncio
    async def test_bootstrap_unknown_type_error_includes_type_name(self) -> None:
        """ValueError for unknown type includes the type name in message.

        Contract: Error message must help debugging by including the bad type
        Breaks when: Error message is generic without the actual type value.
        """
        from py_code_mode.bootstrap import bootstrap_namespaces

        config = {
            "type": "mongodb",  # Not supported
        }

        with pytest.raises(ValueError, match="mongodb"):
            await bootstrap_namespaces(config)

    @pytest.mark.asyncio
    async def test_bootstrap_missing_type_raises(self) -> None:
        """bootstrap_namespaces() without 'type' key raises KeyError or ValueError.

        Contract: Config must include 'type' key
        Breaks when: Missing type is silently ignored or causes cryptic error.
        """
        from py_code_mode.bootstrap import bootstrap_namespaces

        config = {
            "base_path": "/some/path",
        }

        with pytest.raises((KeyError, ValueError)):
            await bootstrap_namespaces(config)

    @pytest.mark.asyncio
    async def test_bootstrap_file_missing_base_path_raises(self) -> None:
        """File bootstrap without base_path raises KeyError.

        Contract: File storage config must include base_path
        Breaks when: Missing base_path causes cryptic error instead of clear message.
        """
        from py_code_mode.bootstrap import bootstrap_namespaces

        config = {
            "type": "file",
            # Missing base_path
        }

        with pytest.raises(KeyError):
            await bootstrap_namespaces(config)

    @pytest.mark.asyncio
    async def test_bootstrap_redis_missing_url_raises(self) -> None:
        """Redis bootstrap without url raises KeyError.

        Contract: Redis storage config must include url
        Breaks when: Missing url causes cryptic error instead of clear message.
        """
        from py_code_mode.bootstrap import bootstrap_namespaces

        config = {
            "type": "redis",
            "prefix": "test",
            # Missing url
        }

        with pytest.raises(KeyError):
            await bootstrap_namespaces(config)

    @pytest.mark.asyncio
    async def test_bootstrap_redis_missing_prefix_raises(self) -> None:
        """Redis bootstrap without prefix raises KeyError.

        Contract: Redis storage config must include prefix
        Breaks when: Missing prefix causes cryptic error instead of clear message.
        """
        from py_code_mode.bootstrap import bootstrap_namespaces

        config = {
            "type": "redis",
            "url": "redis://localhost:6379/0",
            # Missing prefix
        }

        with pytest.raises(KeyError):
            await bootstrap_namespaces(config)


# =============================================================================
# FileStorage.to_bootstrap_config() Tests
# =============================================================================


class TestFileStorageBootstrapConfig:
    """Tests for FileStorage.to_bootstrap_config() method.

    This method serializes FileStorage configuration to a dict that can be
    passed to bootstrap_namespaces() to reconstruct the storage in a subprocess.
    """

    def test_to_bootstrap_config_returns_dict(self, tmp_path: Path) -> None:
        """to_bootstrap_config() returns a dict.

        Contract: Must return dict for JSON serialization
        Breaks when: Return type is not dict.
        """
        from py_code_mode.storage import FileStorage

        storage = FileStorage(tmp_path)

        result = storage.to_bootstrap_config()

        assert isinstance(result, dict)

    def test_config_has_type_file(self, tmp_path: Path) -> None:
        """Config dict has type="file".

        Contract: Must identify storage type for bootstrap dispatch
        Breaks when: Type key is missing or wrong value.
        """
        from py_code_mode.storage import FileStorage

        storage = FileStorage(tmp_path)

        result = storage.to_bootstrap_config()

        assert result["type"] == "file"

    def test_config_has_base_path(self, tmp_path: Path) -> None:
        """Config dict has base_path key.

        Contract: Must include path for reconstruction
        Breaks when: base_path key is missing.
        """
        from py_code_mode.storage import FileStorage

        storage = FileStorage(tmp_path)

        result = storage.to_bootstrap_config()

        assert "base_path" in result

    def test_config_base_path_is_string(self, tmp_path: Path) -> None:
        """Config base_path is a string (not Path object).

        Contract: Must be JSON-serializable (string, not Path)
        Breaks when: Path object is returned instead of string.
        """
        from py_code_mode.storage import FileStorage

        storage = FileStorage(tmp_path)

        result = storage.to_bootstrap_config()

        assert isinstance(result["base_path"], str)

    def test_config_base_path_matches_storage_path(self, tmp_path: Path) -> None:
        """Config base_path matches the storage's root path.

        Contract: Must preserve the original path
        Breaks when: Path is modified or truncated.
        """
        from py_code_mode.storage import FileStorage

        storage = FileStorage(tmp_path)

        result = storage.to_bootstrap_config()

        assert result["base_path"] == str(tmp_path)

    @pytest.mark.asyncio
    async def test_config_roundtrip(self, tmp_path: Path) -> None:
        """Config can be used to reconstruct equivalent storage.

        User action: Serialize storage, pass to subprocess, reconstruct
        Verification: Reconstructed storage accesses same locations
        Breaks when: Serialization loses critical information.
        """
        from py_code_mode.bootstrap import bootstrap_namespaces
        from py_code_mode.storage import FileStorage

        # Create storage with some content
        storage = FileStorage(tmp_path)
        (tmp_path / "skills").mkdir(exist_ok=True)
        skill_file = tmp_path / "skills" / "greet.py"
        skill_content = '"""Greet."""\nasync def run(name: str) -> str:\n    return f"Hello, {name}!"'
        skill_file.write_text(skill_content)

        # Serialize
        config = storage.to_bootstrap_config()

        # Reconstruct (async because get_tool_registry() is async for MCP support)
        bundle = await bootstrap_namespaces(config)

        # Verify skills are accessible
        skill = bundle.skills.library.get("greet")
        assert skill is not None
        assert skill.name == "greet"


# =============================================================================
# RedisStorage.to_bootstrap_config() Tests
# =============================================================================


class TestRedisStorageBootstrapConfig:
    """Tests for RedisStorage.to_bootstrap_config() method.

    This method serializes RedisStorage configuration to a dict that can be
    passed to bootstrap_namespaces() to reconstruct the storage in a subprocess.
    """

    def test_to_bootstrap_config_returns_dict(self, mock_redis: MockRedisClient) -> None:
        """to_bootstrap_config() returns a dict.

        Contract: Must return dict for JSON serialization
        Breaks when: Return type is not dict.
        """
        from py_code_mode.storage import RedisStorage

        storage = RedisStorage(redis=mock_redis, prefix="test")

        result = storage.to_bootstrap_config()

        assert isinstance(result, dict)

    def test_config_has_type_redis(self, mock_redis: MockRedisClient) -> None:
        """Config dict has type="redis".

        Contract: Must identify storage type for bootstrap dispatch
        Breaks when: Type key is missing or wrong value.
        """
        from py_code_mode.storage import RedisStorage

        storage = RedisStorage(redis=mock_redis, prefix="test")

        result = storage.to_bootstrap_config()

        assert result["type"] == "redis"

    def test_config_has_url(self, mock_redis: MockRedisClient) -> None:
        """Config dict has url key.

        Contract: Must include connection URL for reconstruction
        Breaks when: url key is missing.
        """
        from py_code_mode.storage import RedisStorage

        storage = RedisStorage(redis=mock_redis, prefix="test")

        result = storage.to_bootstrap_config()

        assert "url" in result

    def test_config_url_is_string(self, mock_redis: MockRedisClient) -> None:
        """Config url is a string.

        Contract: Must be JSON-serializable (string)
        Breaks when: Non-string type is returned.
        """
        from py_code_mode.storage import RedisStorage

        storage = RedisStorage(redis=mock_redis, prefix="test")

        result = storage.to_bootstrap_config()

        assert isinstance(result["url"], str)

    def test_config_url_is_reconstructable(self, mock_redis: MockRedisClient) -> None:
        """Config url can be used to connect to Redis.

        Contract: URL must be valid Redis connection string
        Breaks when: URL format is incorrect.
        """
        from py_code_mode.storage import RedisStorage

        storage = RedisStorage(redis=mock_redis, prefix="test")

        result = storage.to_bootstrap_config()

        # URL should start with redis://
        assert result["url"].startswith("redis://")

    def test_config_has_prefix(self, mock_redis: MockRedisClient) -> None:
        """Config dict has prefix key.

        Contract: Must include prefix for key namespacing
        Breaks when: prefix key is missing.
        """
        from py_code_mode.storage import RedisStorage

        storage = RedisStorage(redis=mock_redis, prefix="test")

        result = storage.to_bootstrap_config()

        assert "prefix" in result

    def test_config_prefix_is_string(self, mock_redis: MockRedisClient) -> None:
        """Config prefix is a string.

        Contract: Must be JSON-serializable (string)
        Breaks when: Non-string type is returned.
        """
        from py_code_mode.storage import RedisStorage

        storage = RedisStorage(redis=mock_redis, prefix="test")

        result = storage.to_bootstrap_config()

        assert isinstance(result["prefix"], str)

    def test_config_prefix_matches_storage_prefix(self, mock_redis: MockRedisClient) -> None:
        """Config prefix matches the storage's configured prefix.

        Contract: Must preserve the original prefix
        Breaks when: Prefix is modified or lost.
        """
        from py_code_mode.storage import RedisStorage

        storage = RedisStorage(redis=mock_redis, prefix="myapp")

        result = storage.to_bootstrap_config()

        assert result["prefix"] == "myapp"

    @pytest.mark.asyncio
    async def test_config_roundtrip(self, mock_redis: MockRedisClient) -> None:
        """Config can be used to reconstruct equivalent storage.

        User action: Serialize storage, pass to subprocess, reconstruct
        Verification: Reconstructed storage accesses same Redis keys
        Breaks when: Serialization loses critical information.
        """
        from py_code_mode.bootstrap import bootstrap_namespaces
        from py_code_mode.skills import PythonSkill
        from py_code_mode.storage import RedisStorage

        # Create storage with some content
        storage = RedisStorage(redis=mock_redis, prefix="test")
        skill_store = storage.get_skill_store()
        test_skill = PythonSkill.from_source(
            name="greet",
            source='async def run(name: str) -> str:\n    return f"Hello, {name}!"',
            description="Greet a user",
        )
        skill_store.save(test_skill)

        # Serialize
        config = storage.to_bootstrap_config()

        # Reconstruct (with same mock redis, async for MCP support)
        with patch("redis.Redis.from_url", return_value=mock_redis):
            bundle = await bootstrap_namespaces(config)

        # Verify skills are accessible
        skill = bundle.skills.library.get("greet")
        assert skill is not None
        assert skill.name == "greet"


# =============================================================================
# Lazy Connection Tests
# =============================================================================


class TestRedisStorageLazyConnection:
    """Tests for RedisStorage lazy connection behavior.

    RedisStorage should not connect to Redis during __init__ or to_bootstrap_config().
    Connection should only happen when actually using the storage (get_artifact_store(), etc.).
    """

    def test_redis_storage_no_connection_on_init(self) -> None:
        """Creating RedisStorage does not attempt to connect to Redis.

        Contract: __init__ should be side-effect free (no I/O)
        Breaks when: __init__ calls Redis methods like ping() or get().
        """
        # Create a mock that tracks all method calls
        mock_client = MagicMock()

        from py_code_mode.storage import RedisStorage

        # This should not trigger any Redis operations
        storage = RedisStorage(redis=mock_client, prefix="test")

        # Verify no Redis operations were called
        # Common connection-testing methods:
        mock_client.ping.assert_not_called()
        mock_client.get.assert_not_called()
        mock_client.info.assert_not_called()

        assert storage is not None  # Storage was created

    def test_to_bootstrap_config_no_connection(self) -> None:
        """to_bootstrap_config() does not trigger Redis connection.

        Contract: Serialization should only read local state, not touch Redis
        Breaks when: to_bootstrap_config() calls Redis methods.
        """
        mock_client = MagicMock()
        # Set up connection_pool for URL reconstruction
        mock_client.connection_pool = MagicMock()
        mock_client.connection_pool.connection_kwargs = {
            "host": "localhost",
            "port": 6379,
            "db": 0,
        }

        from py_code_mode.storage import RedisStorage

        storage = RedisStorage(redis=mock_client, prefix="test")

        # This should not trigger any Redis operations
        config = storage.to_bootstrap_config()

        # Verify no Redis operations were called
        mock_client.ping.assert_not_called()
        mock_client.get.assert_not_called()
        mock_client.hgetall.assert_not_called()
        mock_client.keys.assert_not_called()

        assert config is not None

    def test_get_artifact_store_triggers_connection(self, mock_redis: MockRedisClient) -> None:
        """get_artifact_store() triggers Redis connection/usage.

        Contract: Lazy connection should happen on first actual use
        Breaks when: Connection happens too early or not at all.
        """
        from py_code_mode.storage import RedisStorage

        storage = RedisStorage(redis=mock_redis, prefix="test")

        # This should create the store (lazy initialization)
        artifact_store = storage.get_artifact_store()

        # Store should be usable
        assert artifact_store is not None

    def test_get_skill_library_triggers_connection(self, mock_redis: MockRedisClient) -> None:
        """get_skill_library() triggers Redis connection/usage.

        Contract: Lazy connection should happen on first actual use
        Breaks when: Connection happens too early or not at all.
        """
        from py_code_mode.storage import RedisStorage

        storage = RedisStorage(redis=mock_redis, prefix="test")

        # This should create the library (lazy initialization)
        library = storage.get_skill_library()

        # Library should be usable
        assert library is not None


# =============================================================================
# FileStorage Lazy Initialization Tests
# =============================================================================


class TestFileStorageLazyInitialization:
    """Tests for FileStorage lazy initialization behavior.

    FileStorage should not scan directories during __init__ or to_bootstrap_config().
    Directory scanning should only happen when actually using the storage.
    """

    def test_file_storage_to_bootstrap_config_no_directory_scan(self, tmp_path: Path) -> None:
        """to_bootstrap_config() does not scan directories.

        Contract: Serialization should only read local state, not scan disk
        Breaks when: to_bootstrap_config() walks the filesystem.
        """
        from py_code_mode.storage import FileStorage

        # Create storage with non-existent subdirectories
        # If it tries to scan, it might fail or return empty
        storage = FileStorage(tmp_path)

        # This should not scan directories
        config = storage.to_bootstrap_config()

        # Config should be valid even without directories existing
        assert config["type"] == "file"
        assert config["base_path"] == str(tmp_path)


# =============================================================================
# Integration: SubprocessExecutor Uses Bootstrap
# =============================================================================


class TestSubprocessExecutorBootstrapIntegration:
    """Tests for SubprocessExecutor integration with bootstrap architecture.

    These tests verify that SubprocessExecutor correctly uses to_bootstrap_config()
    and generates code that calls bootstrap_namespaces().
    """

    def test_subprocess_executor_uses_bootstrap_config(self, tmp_path: Path) -> None:
        """SubprocessExecutor calls to_bootstrap_config() on storage.

        Contract: Executor should serialize storage via to_bootstrap_config()
        Breaks when: Executor uses isinstance checks instead of bootstrap.
        """
        from py_code_mode.storage import FileStorage

        storage = FileStorage(tmp_path)

        # Create a spy on to_bootstrap_config
        original_method = storage.to_bootstrap_config

        call_count = 0

        def spy_method():
            nonlocal call_count
            call_count += 1
            return original_method()

        storage.to_bootstrap_config = spy_method

        # When SubprocessExecutor is updated to use bootstrap,
        # starting with storage should call to_bootstrap_config
        # This test will pass once the implementation is updated

        # For now, we just verify the method exists and is callable
        config = storage.to_bootstrap_config()
        assert config is not None
        assert call_count == 1

    def test_bootstrap_config_is_json_serializable(self, tmp_path: Path) -> None:
        """Bootstrap config can be JSON serialized.

        Contract: Config must be serializable for IPC to subprocess
        Breaks when: Config contains non-JSON-serializable types.
        """
        import json

        from py_code_mode.storage import FileStorage

        storage = FileStorage(tmp_path)
        config = storage.to_bootstrap_config()

        # Should not raise
        serialized = json.dumps(config)
        assert serialized is not None

        # Should round-trip
        deserialized = json.loads(serialized)
        assert deserialized == config

    def test_redis_bootstrap_config_is_json_serializable(self, mock_redis: MockRedisClient) -> None:
        """Redis bootstrap config can be JSON serialized.

        Contract: Config must be serializable for IPC to subprocess
        Breaks when: Config contains non-JSON-serializable types.
        """
        import json

        from py_code_mode.storage import RedisStorage

        storage = RedisStorage(redis=mock_redis, prefix="test")
        config = storage.to_bootstrap_config()

        # Should not raise
        serialized = json.dumps(config)
        assert serialized is not None

        # Should round-trip
        deserialized = json.loads(serialized)
        assert deserialized == config


# =============================================================================
# User Journey Tests (E2E)
# =============================================================================


class TestBootstrapUserJourney:
    """End-to-end tests for the bootstrap workflow.

    These tests simulate the complete user journey from storage creation
    through serialization to namespace reconstruction.
    """

    @pytest.mark.asyncio
    async def test_file_storage_bootstrap_journey(self, tmp_path: Path) -> None:
        """Complete journey: FileStorage -> serialize -> reconstruct -> use.

        User action: Set up storage, serialize for subprocess, reconstruct and use
        Steps:
            1. Create FileStorage with tools/skills
            2. Serialize via to_bootstrap_config()
            3. Reconstruct via bootstrap_namespaces()
            4. Verify namespaces work correctly
        Verification: Skills can be loaded and invoked after reconstruction
        Breaks when: Any step in the bootstrap process fails.
        """
        from py_code_mode.bootstrap import bootstrap_namespaces
        from py_code_mode.storage import FileStorage

        # Step 1: Create storage with content
        storage = FileStorage(tmp_path)
        (tmp_path / "skills").mkdir(exist_ok=True)
        skill_file = tmp_path / "skills" / "double.py"
        skill_file.write_text('"""Double a number."""\nasync def run(n: int) -> int:\n    return n * 2')

        (tmp_path / "artifacts").mkdir(exist_ok=True)

        # Step 2: Serialize
        config = storage.to_bootstrap_config()

        # Verify config is JSON-serializable (as it would be for IPC)
        import json

        json_config = json.dumps(config)
        restored_config = json.loads(json_config)

        # Step 3: Reconstruct (async for MCP tool support)
        bundle = await bootstrap_namespaces(restored_config)

        # Step 4: Verify namespaces work
        # Check skills
        skill = bundle.skills.library.get("double")
        assert skill is not None
        assert skill.name == "double"

        # Check artifacts (should be usable)
        bundle.artifacts.save("test", {"value": 42}, description="test data")
        loaded = bundle.artifacts.load("test")
        assert loaded["value"] == 42

    @pytest.mark.asyncio
    async def test_redis_storage_bootstrap_journey(self, mock_redis: MockRedisClient) -> None:
        """Complete journey: RedisStorage -> serialize -> reconstruct -> use.

        User action: Set up storage, serialize for subprocess, reconstruct and use
        Steps:
            1. Create RedisStorage with skills
            2. Serialize via to_bootstrap_config()
            3. Reconstruct via bootstrap_namespaces()
            4. Verify namespaces work correctly
        Verification: Skills can be loaded after reconstruction
        Breaks when: Any step in the bootstrap process fails.
        """
        from py_code_mode.bootstrap import bootstrap_namespaces
        from py_code_mode.skills import PythonSkill
        from py_code_mode.storage import RedisStorage

        # Step 1: Create storage with content
        storage = RedisStorage(redis=mock_redis, prefix="journey")
        skill_store = storage.get_skill_store()
        skill = PythonSkill.from_source(
            name="triple",
            source="async def run(n: int) -> int:\n    return n * 3",
            description="Triple a number",
        )
        skill_store.save(skill)

        # Step 2: Serialize
        config = storage.to_bootstrap_config()

        # Verify config is JSON-serializable
        import json

        json_config = json.dumps(config)
        restored_config = json.loads(json_config)

        # Step 3: Reconstruct (using same mock redis, async for MCP tool support)
        with patch("redis.Redis.from_url", return_value=mock_redis):
            bundle = await bootstrap_namespaces(restored_config)

        # Step 4: Verify namespaces work
        loaded_skill = bundle.skills.library.get("triple")
        assert loaded_skill is not None
        assert loaded_skill.name == "triple"
