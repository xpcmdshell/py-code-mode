"""Tests for Redis-backed tool configuration storage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from py_code_mode.tools.adapters.base import ToolAdapter

if TYPE_CHECKING:
    pass


class TestRedisToolStore:
    """Test Redis-backed tool storage with mocked Redis."""

    def _make_tool_config(
        self,
        name: str = "curl",
        description: str = "Make HTTP requests",
        tool_type: str = "cli",
    ) -> dict:
        """Create a test tool config."""
        return {
            "name": name,
            "type": tool_type,
            "args": "{url}",
            "description": description,
            "timeout": 60,
        }

    def test_add_and_get_tool(self) -> None:
        """Can add a tool config and retrieve it by name."""
        from py_code_mode.storage.redis_tools import RedisToolStore

        mock_redis = MagicMock()
        stored_data: dict[str, bytes] = {}

        def mock_hset(key: str, field: str, value: str) -> None:
            stored_data[f"{key}:{field}"] = value.encode()

        def mock_hget(key: str, field: str) -> bytes | None:
            return stored_data.get(f"{key}:{field}")

        mock_redis.hset.side_effect = mock_hset
        mock_redis.hget.side_effect = mock_hget

        store = RedisToolStore(mock_redis, prefix="test-tools")
        config = self._make_tool_config()
        store.add("curl", config)

        retrieved = store.get("curl")
        assert retrieved is not None
        assert retrieved["name"] == "curl"
        assert retrieved["description"] == "Make HTTP requests"

    def test_list_tools(self) -> None:
        """List returns all added tools."""
        from py_code_mode.storage.redis_tools import RedisToolStore

        mock_redis = MagicMock()
        stored_data: dict[str, bytes] = {}

        def mock_hset(key: str, field: str, value: str) -> None:
            stored_data[f"{key}:{field}"] = value.encode()

        def mock_hgetall(key: str) -> dict[str, bytes]:
            result = {}
            prefix = f"{key}:"
            for k, v in stored_data.items():
                if k.startswith(prefix):
                    field = k[len(prefix) :]
                    result[field.encode()] = v
            return result

        mock_redis.hset.side_effect = mock_hset
        mock_redis.hgetall.side_effect = mock_hgetall

        store = RedisToolStore(mock_redis, prefix="test-tools")
        store.add("curl", self._make_tool_config("curl", "HTTP client"))
        store.add("jq", self._make_tool_config("jq", "JSON processor"))

        tools = store.list()
        assert len(tools) == 2
        assert set(tools.keys()) == {"curl", "jq"}

    def test_get_nonexistent_returns_none(self) -> None:
        """get() returns None for missing tool."""
        from py_code_mode.storage.redis_tools import RedisToolStore

        mock_redis = MagicMock()
        mock_redis.hget.return_value = None

        store = RedisToolStore(mock_redis, prefix="test-tools")
        result = store.get("nonexistent")
        assert result is None

    def test_len_returns_tool_count(self) -> None:
        """__len__ returns number of tools."""
        from py_code_mode.storage.redis_tools import RedisToolStore

        mock_redis = MagicMock()
        mock_redis.hlen.return_value = 5

        store = RedisToolStore(mock_redis, prefix="test-tools")
        assert len(store) == 5

    def test_remove_tool(self) -> None:
        """Can remove a tool from Redis."""
        from py_code_mode.storage.redis_tools import RedisToolStore

        mock_redis = MagicMock()
        mock_redis.hdel.return_value = 1

        store = RedisToolStore(mock_redis, prefix="test-tools")
        result = store.remove("curl")

        assert result is True
        mock_redis.hdel.assert_called_once_with("test-tools:__tools__", "curl")

    def test_remove_nonexistent_returns_false(self) -> None:
        """Removing nonexistent tool returns False."""
        from py_code_mode.storage.redis_tools import RedisToolStore

        mock_redis = MagicMock()
        mock_redis.hdel.return_value = 0

        store = RedisToolStore(mock_redis, prefix="test-tools")
        result = store.remove("nonexistent")

        assert result is False

    def test_from_directory(self, tmp_path: Path) -> None:
        """Loads tools from directory into Redis."""
        from py_code_mode.storage.redis_tools import RedisToolStore

        # Create test tool file
        tool_file = tmp_path / "echo.yaml"
        tool_file.write_text("""
name: echo
type: cli
command: echo
args: "{text}"
description: Echo text
""")

        mock_redis = MagicMock()
        stored_data: dict[str, bytes] = {}

        def mock_hset(key: str, field: str, value: str) -> None:
            stored_data[f"{key}:{field}"] = value.encode()

        def mock_hgetall(key: str) -> dict[str, bytes]:
            result = {}
            prefix = f"{key}:"
            for k, v in stored_data.items():
                if k.startswith(prefix):
                    field = k[len(prefix) :]
                    result[field.encode()] = v
            return result

        mock_redis.hset.side_effect = mock_hset
        mock_redis.hgetall.side_effect = mock_hgetall

        store = RedisToolStore.from_directory(mock_redis, tmp_path, prefix="test-tools")

        tools = store.list()
        assert len(tools) == 1
        assert "echo" in tools
        assert tools["echo"]["description"] == "Echo text"


class TestRegistryFromRedis:
    """Tests for registry_from_redis() function."""

    @pytest.mark.asyncio
    async def test_creates_registry_with_cli_tools(self) -> None:
        """Creates ToolRegistry from CLI tool configs in Redis."""
        from py_code_mode.storage.redis_tools import RedisToolStore, registry_from_redis

        mock_redis = MagicMock()

        # Return CLI tool configs
        tool_configs = {
            b"curl": json.dumps(
                {
                    "name": "curl",
                    "type": "cli",
                    "command": "curl",
                    "description": "HTTP client",
                    "schema": {"positional": [{"name": "url", "type": "string", "required": True}]},
                    "recipes": {"get": {"description": "GET request", "params": {"url": {}}}},
                }
            ).encode(),
            b"jq": json.dumps(
                {
                    "name": "jq",
                    "type": "cli",
                    "command": "jq",
                    "description": "JSON processor",
                    "schema": {
                        "positional": [{"name": "filter", "type": "string", "required": True}]
                    },
                    "recipes": {"query": {"description": "Query JSON", "params": {"filter": {}}}},
                }
            ).encode(),
        }
        mock_redis.hgetall.return_value = tool_configs
        mock_redis.hlen.return_value = 2

        store = RedisToolStore(mock_redis, prefix="test-tools")
        registry = await registry_from_redis(store)

        # Check adapters directly
        tools = []
        for adapter in registry._adapters:
            if isinstance(adapter, ToolAdapter):
                tools.extend(adapter.list_tools())
        assert len(tools) == 2
        tool_names = {t.name for t in tools}
        assert tool_names == {"curl", "jq"}

    @pytest.mark.asyncio
    async def test_empty_store_returns_empty_registry(self) -> None:
        """Empty Redis store returns empty registry."""
        from py_code_mode.storage.redis_tools import RedisToolStore, registry_from_redis

        mock_redis = MagicMock()
        mock_redis.hgetall.return_value = {}
        mock_redis.hlen.return_value = 0

        store = RedisToolStore(mock_redis, prefix="test-tools")
        registry = await registry_from_redis(store)

        tools = registry.list_tools()
        assert len(tools) == 0

    @pytest.mark.asyncio
    async def test_mcp_tools_without_package_skipped(self) -> None:
        """MCP tools are skipped when mcp package not installed."""
        from py_code_mode.storage.redis_tools import RedisToolStore, registry_from_redis

        mock_redis = MagicMock()

        # Mix of CLI and MCP tools
        tool_configs = {
            b"curl": json.dumps(
                {
                    "name": "curl",
                    "type": "cli",
                    "command": "curl",
                    "description": "HTTP client",
                    "schema": {"positional": [{"name": "url", "type": "string", "required": True}]},
                    "recipes": {"get": {"description": "GET request", "params": {"url": {}}}},
                }
            ).encode(),
            b"fetch": json.dumps(
                {
                    "name": "fetch",
                    "type": "mcp",
                    "transport": "stdio",
                    "command": "uvx",
                    "args": ["mcp-server-fetch"],
                }
            ).encode(),
        }
        mock_redis.hgetall.return_value = tool_configs
        mock_redis.hlen.return_value = 2

        store = RedisToolStore(mock_redis, prefix="test-tools")
        registry = await registry_from_redis(store)

        # Should have at least CLI tool; MCP may or may not load depending on environment
        tools = []
        for adapter in registry._adapters:
            if isinstance(adapter, ToolAdapter):
                tools.extend(adapter.list_tools())
        tool_names = {t.name for t in tools}
        assert "curl" in tool_names


@pytest.mark.integration
class TestRedisToolStoreIntegration:
    """Integration tests requiring live Redis."""

    @pytest.fixture
    def redis_client(self):
        """Get Redis client, skip if unavailable."""
        try:
            import redis

            r = redis.Redis()
            r.ping()
            yield r
            # Cleanup
            for key in r.keys("test-tools:*"):
                r.delete(key)
        except Exception:
            pytest.skip("Redis not available")

    def test_round_trip_tool(self, redis_client) -> None:
        """Tool config survives Redis round-trip."""
        from py_code_mode.storage.redis_tools import RedisToolStore

        store = RedisToolStore(redis_client, prefix="test-tools")

        config = {
            "name": "test_tool",
            "type": "cli",
            "command": "echo",
            "args": "{text}",
            "description": "Test tool",
            "timeout": 30,
            "tags": ["test", "example"],
        }
        store.add("test_tool", config)

        retrieved = store.get("test_tool")
        assert retrieved is not None
        assert retrieved["name"] == "test_tool"
        assert retrieved["description"] == "Test tool"
        assert retrieved["tags"] == ["test", "example"]

    @pytest.mark.asyncio
    async def test_registry_from_redis_integration(self, redis_client) -> None:
        """registry_from_redis works with real Redis."""
        from py_code_mode.storage.redis_tools import RedisToolStore, registry_from_redis

        store = RedisToolStore(redis_client, prefix="test-tools")

        store.add(
            "echo",
            {
                "name": "echo",
                "type": "cli",
                "command": "echo",
                "description": "Echo text",
                "schema": {"positional": [{"name": "text", "type": "string", "required": True}]},
                "recipes": {"run": {"description": "Echo text", "params": {"text": {}}}},
            },
        )
        store.add(
            "cat",
            {
                "name": "cat",
                "type": "cli",
                "command": "cat",
                "description": "Show file contents",
                "schema": {"positional": [{"name": "file", "type": "string", "required": True}]},
                "recipes": {"show": {"description": "Show file", "params": {"file": {}}}},
            },
        )

        registry = await registry_from_redis(store)
        # Check via adapter interface
        tools = []
        for adapter in registry._adapters:
            if isinstance(adapter, ToolAdapter):
                tools.extend(adapter.list_tools())

        assert len(tools) == 2
        tool_names = {t.name for t in tools}
        assert tool_names == {"echo", "cat"}
