"""Unit tests for RedisStorage implementation.

RedisStorage stores tools, skills, and artifacts in Redis.
This is the production storage backend for distributed deployments.

Structure:
    {prefix}:tools:__index__     # Hash of tool name -> tool JSON
    {prefix}:skills:__index__    # Hash of skill name -> skill JSON
    {prefix}:artifacts:{name}    # Individual artifact data
    {prefix}:artifacts:__meta__  # Hash of artifact name -> metadata JSON
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

# These imports will fail initially - that's expected (TDD red phase)
from py_code_mode.storage import RedisStorage

if TYPE_CHECKING:
    from tests.conftest import MockRedisClient


class TestRedisStorageConstruction:
    """Tests for RedisStorage initialization."""

    def test_create_with_client_and_prefix(self, mock_redis: MockRedisClient) -> None:
        """RedisStorage can be created with a Redis client and prefix."""
        storage = RedisStorage(mock_redis, prefix="myapp")
        assert storage is not None

    def test_default_prefix(self, mock_redis: MockRedisClient) -> None:
        """RedisStorage has a default prefix if none provided."""
        storage = RedisStorage(mock_redis)
        assert storage is not None
        # Should have some default prefix

    def test_prefix_property(self, mock_redis: MockRedisClient) -> None:
        """RedisStorage exposes the configured prefix."""
        storage = RedisStorage(mock_redis, prefix="myapp")
        assert storage.prefix == "myapp"

    def test_client_property(self, mock_redis: MockRedisClient) -> None:
        """RedisStorage exposes the Redis client."""
        storage = RedisStorage(mock_redis, prefix="test")
        assert storage.client is mock_redis


class TestRedisStorageTools:
    """Tests for RedisStorage.tools - tool storage operations."""

    @pytest.fixture
    def storage(self, mock_redis: MockRedisClient) -> RedisStorage:
        """Create RedisStorage for testing."""
        return RedisStorage(mock_redis, prefix="test")

    def test_list_empty_returns_empty_list(self, storage: RedisStorage) -> None:
        """tools.list() returns empty list when no tools exist."""
        result = storage.tools.list()
        assert result == []

    def test_save_and_list_tool(self, storage: RedisStorage) -> None:
        """Can save a tool and see it in list."""
        tool = {
            "name": "nmap",
            "type": "cli",
            "command": "nmap",
            "args": "{flags} {target}",
            "description": "Network port scanner",
        }

        storage.tools.save(tool)
        result = storage.tools.list()

        assert len(result) == 1
        assert result[0]["name"] == "nmap"

    def test_list_returns_tool_info(self, storage: RedisStorage) -> None:
        """tools.list() returns list of tool info dicts."""
        tool = {
            "name": "curl",
            "type": "cli",
            "command": "curl",
            "args": "{url}",
            "description": "HTTP client",
        }
        storage.tools.save(tool)

        result = storage.tools.list()

        assert len(result) == 1
        assert isinstance(result[0], dict)
        assert "name" in result[0]
        assert "description" in result[0]
        assert "params" in result[0]

    def test_list_multiple_tools(self, storage: RedisStorage) -> None:
        """tools.list() returns all tools."""
        storage.tools.save(
            {
                "name": "tool1",
                "type": "cli",
                "command": "echo",
                "args": "test",
                "description": "Tool 1",
            }
        )
        storage.tools.save(
            {
                "name": "tool2",
                "type": "cli",
                "command": "cat",
                "args": "test",
                "description": "Tool 2",
            }
        )

        result = storage.tools.list()

        assert len(result) == 2
        names = {t["name"] for t in result}
        assert names == {"tool1", "tool2"}

    def test_get_existing_tool(self, storage: RedisStorage) -> None:
        """tools.get(name) returns tool definition."""
        tool = {
            "name": "nmap",
            "type": "cli",
            "command": "nmap",
            "args": "{target}",
            "description": "Network scanner",
        }
        storage.tools.save(tool)

        result = storage.tools.get("nmap")

        assert result is not None
        assert result["name"] == "nmap"
        assert result["description"] == "Network scanner"

    def test_get_nonexistent_returns_none(self, storage: RedisStorage) -> None:
        """tools.get(name) returns None for nonexistent tool."""
        result = storage.tools.get("nonexistent")
        assert result is None

    def test_exists_true_for_existing(self, storage: RedisStorage) -> None:
        """tools.exists(name) returns True for existing tool."""
        storage.tools.save(
            {"name": "nmap", "type": "cli", "command": "nmap", "args": "", "description": "Scanner"}
        )

        assert storage.tools.exists("nmap") is True

    def test_exists_false_for_nonexistent(self, storage: RedisStorage) -> None:
        """tools.exists(name) returns False for nonexistent tool."""
        assert storage.tools.exists("nonexistent") is False

    def test_save_overwrites_existing(self, storage: RedisStorage) -> None:
        """tools.save(tool) overwrites existing tool."""
        storage.tools.save(
            {
                "name": "mytool",
                "type": "cli",
                "command": "v1",
                "args": "",
                "description": "Version 1",
            }
        )
        storage.tools.save(
            {
                "name": "mytool",
                "type": "cli",
                "command": "v2",
                "args": "",
                "description": "Version 2",
            }
        )

        result = storage.tools.get("mytool")
        assert result["description"] == "Version 2"

    def test_delete_removes_tool(self, storage: RedisStorage) -> None:
        """tools.delete(name) removes the tool from Redis."""
        storage.tools.save(
            {
                "name": "todelete",
                "type": "cli",
                "command": "rm",
                "args": "",
                "description": "Delete me",
            }
        )

        result = storage.tools.delete("todelete")

        assert result is True
        assert storage.tools.get("todelete") is None

    def test_delete_nonexistent_returns_false(self, storage: RedisStorage) -> None:
        """tools.delete(name) returns False for nonexistent tool."""
        result = storage.tools.delete("nonexistent")
        assert result is False

    def test_search_returns_list(self, storage: RedisStorage) -> None:
        """tools.search(query) returns a list."""
        result = storage.tools.search("network")
        assert isinstance(result, list)


class TestRedisStorageSkills:
    """Tests for RedisStorage.skills - skill storage operations."""

    @pytest.fixture
    def storage(self, mock_redis: MockRedisClient) -> RedisStorage:
        """Create RedisStorage for testing."""
        return RedisStorage(mock_redis, prefix="test")

    def test_list_empty_returns_empty_list(self, storage: RedisStorage) -> None:
        """skills.list() returns empty list when no skills exist."""
        result = storage.skills.list()
        assert result == []

    def test_save_and_list_skill(self, storage: RedisStorage) -> None:
        """Can save a skill and see it in list."""
        skill = {
            "name": "double",
            "source": "def run(n: int) -> int:\n    return n * 2",
            "description": "Double a number",
        }

        storage.skills.save(skill)
        result = storage.skills.list()

        assert len(result) == 1
        assert result[0]["name"] == "double"

    def test_list_returns_skill_info(self, storage: RedisStorage) -> None:
        """skills.list() returns list of skill info dicts."""
        skill = {
            "name": "greet",
            "source": 'def run(name: str) -> str:\n    return f"Hello, {name}!"',
            "description": "Greet someone",
        }
        storage.skills.save(skill)

        result = storage.skills.list()

        assert len(result) == 1
        assert isinstance(result[0], dict)
        assert "name" in result[0]
        assert "description" in result[0]
        assert "params" in result[0]

    def test_get_existing_skill(self, storage: RedisStorage) -> None:
        """skills.get(name) returns skill definition."""
        skill = {
            "name": "double",
            "source": "def run(n: int) -> int:\n    return n * 2",
            "description": "Double a number",
        }
        storage.skills.save(skill)

        result = storage.skills.get("double")

        assert result is not None
        assert result["name"] == "double"
        assert "Double" in result["description"]

    def test_get_nonexistent_returns_none(self, storage: RedisStorage) -> None:
        """skills.get(name) returns None for nonexistent skill."""
        result = storage.skills.get("nonexistent")
        assert result is None

    def test_exists_true_for_existing(self, storage: RedisStorage) -> None:
        """skills.exists(name) returns True for existing skill."""
        storage.skills.save(
            {"name": "exists", "source": "def run(): return 1", "description": "Exists"}
        )

        assert storage.skills.exists("exists") is True

    def test_exists_false_for_nonexistent(self, storage: RedisStorage) -> None:
        """skills.exists(name) returns False for nonexistent skill."""
        assert storage.skills.exists("nonexistent") is False

    def test_create_skill(self, storage: RedisStorage) -> None:
        """skills.create(name, description, source) creates and saves a skill."""
        storage.skills.create(
            name="triple",
            description="Triple a number",
            source="def run(n: int) -> int:\n    return n * 3",
        )

        assert storage.skills.exists("triple")
        skill = storage.skills.get("triple")
        assert skill is not None
        assert skill["name"] == "triple"

    def test_save_overwrites_existing(self, storage: RedisStorage) -> None:
        """skills.save(skill) overwrites existing skill."""
        storage.skills.save(
            {"name": "myskill", "source": "def run(): return 1", "description": "Version 1"}
        )
        storage.skills.save(
            {"name": "myskill", "source": "def run(): return 2", "description": "Version 2"}
        )

        result = storage.skills.get("myskill")
        assert result["description"] == "Version 2"

    def test_delete_removes_skill(self, storage: RedisStorage) -> None:
        """skills.delete(name) removes the skill from Redis."""
        storage.skills.save(
            {"name": "todelete", "source": "def run(): pass", "description": "Delete me"}
        )

        result = storage.skills.delete("todelete")

        assert result is True
        assert storage.skills.get("todelete") is None

    def test_delete_nonexistent_returns_false(self, storage: RedisStorage) -> None:
        """skills.delete(name) returns False for nonexistent skill."""
        result = storage.skills.delete("nonexistent")
        assert result is False

    def test_search_returns_list(self, storage: RedisStorage) -> None:
        """skills.search(query) returns a list."""
        result = storage.skills.search("number")
        assert isinstance(result, list)


class TestRedisStorageArtifacts:
    """Tests for RedisStorage.artifacts - artifact storage operations."""

    @pytest.fixture
    def storage(self, mock_redis: MockRedisClient) -> RedisStorage:
        """Create RedisStorage for testing."""
        return RedisStorage(mock_redis, prefix="test")

    def test_list_empty_returns_empty(self, storage: RedisStorage) -> None:
        """artifacts.list() returns empty iterable when no artifacts exist."""
        result = list(storage.artifacts.list())
        assert result == []

    def test_save_and_load_json_data(self, storage: RedisStorage) -> None:
        """Can save and load JSON-serializable data."""
        data = {"key": "value", "count": 42, "items": [1, 2, 3]}

        storage.artifacts.save("test.json", data, "Test artifact")

        loaded = storage.artifacts.load("test.json")
        assert loaded == data

    def test_save_and_load_bytes(self, storage: RedisStorage) -> None:
        """Can save and load binary data."""
        data = b"binary content here"

        storage.artifacts.save("test.bin", data, "Binary artifact")

        loaded = storage.artifacts.load("test.bin")
        # May return bytes or decoded string depending on implementation
        assert data == loaded or data.decode() in str(loaded)

    def test_save_and_load_string(self, storage: RedisStorage) -> None:
        """Can save and load string data."""
        data = "plain text content"

        storage.artifacts.save("test.txt", data, "Text artifact")

        loaded = storage.artifacts.load("test.txt")
        assert data in str(loaded)

    def test_list_returns_artifact_info(self, storage: RedisStorage) -> None:
        """artifacts.list() returns artifact metadata."""
        storage.artifacts.save("file1.json", {"a": 1}, "First file")
        storage.artifacts.save("file2.json", {"b": 2}, "Second file")

        result = list(storage.artifacts.list())

        assert len(result) == 2

    def test_load_nonexistent_returns_none_or_raises(self, storage: RedisStorage) -> None:
        """artifacts.load(name) returns None or raises for nonexistent."""
        try:
            result = storage.artifacts.load("nonexistent.json")
            assert result is None
        except (KeyError, FileNotFoundError):
            pass  # Raising is acceptable

    def test_exists_true_for_existing(self, storage: RedisStorage) -> None:
        """artifacts.exists(name) returns True for existing artifact."""
        storage.artifacts.save("exists.json", {"test": True}, "Exists")

        assert storage.artifacts.exists("exists.json") is True

    def test_exists_false_for_nonexistent(self, storage: RedisStorage) -> None:
        """artifacts.exists(name) returns False for nonexistent artifact."""
        assert storage.artifacts.exists("nonexistent.json") is False

    def test_delete_removes_artifact(self, storage: RedisStorage) -> None:
        """artifacts.delete(name) removes the artifact."""
        storage.artifacts.save("to_delete.json", {}, "Will be deleted")

        result = storage.artifacts.delete("to_delete.json")

        assert result is True
        assert storage.artifacts.exists("to_delete.json") is False

    def test_delete_nonexistent_returns_false(self, storage: RedisStorage) -> None:
        """artifacts.delete(name) returns False for nonexistent artifact."""
        result = storage.artifacts.delete("nonexistent.json")
        assert result is False

    def test_save_overwrites_existing(self, storage: RedisStorage) -> None:
        """artifacts.save() overwrites existing artifact."""
        storage.artifacts.save("data.json", {"version": 1}, "Version 1")
        storage.artifacts.save("data.json", {"version": 2}, "Version 2")

        loaded = storage.artifacts.load("data.json")
        assert loaded["version"] == 2


class TestRedisStorageKeyStructure:
    """Tests verifying Redis key structure and prefix usage."""

    def test_tools_use_prefix(self, mock_redis: MockRedisClient) -> None:
        """Tool operations use the configured prefix."""
        storage = RedisStorage(mock_redis, prefix="myapp")

        storage.tools.save(
            {"name": "test", "type": "cli", "command": "echo", "args": "", "description": "Test"}
        )

        # Check that mock_redis has keys with prefix
        all_keys = mock_redis.keys("*")
        assert any("myapp" in str(k) for k in all_keys), f"No prefixed keys: {all_keys}"

    def test_skills_use_prefix(self, mock_redis: MockRedisClient) -> None:
        """Skill operations use the configured prefix."""
        storage = RedisStorage(mock_redis, prefix="myapp")

        storage.skills.save(
            {"name": "test", "source": "def run(): return 1", "description": "Test"}
        )

        all_keys = mock_redis.keys("*")
        assert any("myapp" in str(k) for k in all_keys), f"No prefixed keys: {all_keys}"

    def test_artifacts_use_prefix(self, mock_redis: MockRedisClient) -> None:
        """Artifact operations use the configured prefix."""
        storage = RedisStorage(mock_redis, prefix="myapp")

        storage.artifacts.save("test.json", {"key": "value"}, "Test")

        all_keys = mock_redis.keys("*")
        assert any("myapp" in str(k) for k in all_keys), f"No prefixed keys: {all_keys}"

    def test_different_prefixes_isolate_data(self, mock_redis: MockRedisClient) -> None:
        """Different prefixes create isolated namespaces."""
        storage1 = RedisStorage(mock_redis, prefix="app1")
        storage2 = RedisStorage(mock_redis, prefix="app2")

        storage1.tools.save(
            {
                "name": "tool1",
                "type": "cli",
                "command": "echo",
                "args": "",
                "description": "App 1 tool",
            }
        )
        storage2.tools.save(
            {
                "name": "tool2",
                "type": "cli",
                "command": "cat",
                "args": "",
                "description": "App 2 tool",
            }
        )

        # Each should only see its own tools
        app1_tools = storage1.tools.list()
        app2_tools = storage2.tools.list()

        assert len(app1_tools) == 1
        assert app1_tools[0]["name"] == "tool1"
        assert len(app2_tools) == 1
        assert app2_tools[0]["name"] == "tool2"


class TestRedisStorageRealRedis:
    """Integration tests that require a real Redis instance.

    These tests are skipped if Redis is not available.
    Run with: TEST_REDIS_URL=redis://localhost:6379 pytest
    """

    @pytest.fixture
    def real_redis_storage(self) -> RedisStorage | None:
        """Create RedisStorage with real Redis client."""
        import os

        try:
            import redis
        except ImportError:
            pytest.skip("redis package not installed")
            return None

        redis_url = os.environ.get("TEST_REDIS_URL")
        if not redis_url:
            pytest.skip("TEST_REDIS_URL not set")
            return None

        try:
            client = redis.from_url(redis_url)
            client.ping()
        except Exception:
            pytest.skip("Redis not available")
            return None

        # Use unique prefix to avoid conflicts
        import uuid

        prefix = f"test-{uuid.uuid4().hex[:8]}"
        storage = RedisStorage(client, prefix=prefix)

        yield storage

        # Cleanup: delete all keys with this prefix
        for key in client.keys(f"{prefix}:*"):
            client.delete(key)

    @pytest.mark.requires_redis
    def test_real_redis_tool_roundtrip(self, real_redis_storage: RedisStorage) -> None:
        """Tool save/load works with real Redis."""
        if real_redis_storage is None:
            pytest.skip("Redis not available")

        tool = {
            "name": "realtest",
            "type": "cli",
            "command": "echo",
            "args": "{msg}",
            "description": "Real Redis test",
        }

        real_redis_storage.tools.save(tool)
        loaded = real_redis_storage.tools.get("realtest")

        assert loaded is not None
        assert loaded["name"] == "realtest"

    @pytest.mark.requires_redis
    def test_real_redis_skill_roundtrip(self, real_redis_storage: RedisStorage) -> None:
        """Skill save/load works with real Redis."""
        if real_redis_storage is None:
            pytest.skip("Redis not available")

        skill = {
            "name": "realskill",
            "source": "def run(): return 'real'",
            "description": "Real Redis skill test",
        }

        real_redis_storage.skills.save(skill)
        loaded = real_redis_storage.skills.get("realskill")

        assert loaded is not None
        assert loaded["name"] == "realskill"

    @pytest.mark.requires_redis
    def test_real_redis_artifact_roundtrip(self, real_redis_storage: RedisStorage) -> None:
        """Artifact save/load works with real Redis."""
        if real_redis_storage is None:
            pytest.skip("Redis not available")

        data = {"real": True, "numbers": [1, 2, 3]}

        real_redis_storage.artifacts.save("real.json", data, "Real test")
        loaded = real_redis_storage.artifacts.load("real.json")

        assert loaded == data
