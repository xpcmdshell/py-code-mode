"""Redis-backed tool configuration storage."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from redis import Redis

    from py_code_mode.tools import ToolRegistry


class RedisToolStore:
    """Redis-backed storage for tool configurations.

    Stores tool YAML configs in Redis, enabling:
    - Distributed tool configuration across container restarts
    - Shared tools between multiple agent instances
    - Dynamic tool updates without redeployment

    Key format: {prefix}:__tools__ (hash containing all tool configs)
    """

    INDEX_KEY = ":__tools__"

    def __init__(self, redis: Redis, prefix: str = "tools") -> None:
        """Initialize Redis tool store.

        Args:
            redis: Redis client instance.
            prefix: Key prefix for all tools. Defaults to 'tools'.
        """
        self._redis = redis
        self._prefix = prefix

    def _index_key(self) -> str:
        """Build index hash key."""
        return f"{self._prefix}{self.INDEX_KEY}"

    def __len__(self) -> int:
        """Return number of tools in store."""
        return self._redis.hlen(self._index_key())

    def add(self, name: str, config: dict[str, Any]) -> None:
        """Store tool configuration in Redis.

        Args:
            name: Tool name.
            config: Tool configuration dict (same format as YAML).
        """
        self._redis.hset(self._index_key(), name, json.dumps(config))

    def get(self, name: str) -> dict[str, Any] | None:
        """Get tool configuration by name.

        Args:
            name: Tool name.

        Returns:
            Tool config dict if found, None otherwise.
        """
        value = self._redis.hget(self._index_key(), name)
        if value is None:
            return None

        if isinstance(value, bytes):
            value = value.decode()

        return json.loads(value)

    def list(self) -> dict[str, dict[str, Any]]:
        """List all tool configurations.

        Returns:
            Dict mapping tool name to config.
        """
        all_data = self._redis.hgetall(self._index_key())
        if not all_data:
            return {}

        result = {}
        for name, value in all_data.items():
            if isinstance(name, bytes):
                name = name.decode()
            if isinstance(value, bytes):
                value = value.decode()
            result[name] = json.loads(value)

        return result

    def remove(self, name: str) -> bool:
        """Remove a tool from Redis.

        Args:
            name: Tool name to remove.

        Returns:
            True if tool was removed, False if it didn't exist.
        """
        result = self._redis.hdel(self._index_key(), name)
        return result > 0

    @classmethod
    def from_directory(
        cls,
        redis: Redis,
        path: Path | str,
        prefix: str = "tools",
    ) -> RedisToolStore:
        """Load tools from directory into Redis.

        Args:
            redis: Redis client instance.
            path: Path to directory containing tool YAML files.
            prefix: Redis key prefix.

        Returns:
            RedisToolStore with tools loaded from directory.
        """
        store = cls(redis, prefix)
        tools_path = Path(path)

        if not tools_path.exists():
            logger.warning("Tools path does not exist: %s", tools_path)
            return store

        for tool_file in sorted(tools_path.glob("*.yaml")):
            with open(tool_file) as f:
                tool = yaml.safe_load(f)
                if not tool or not tool.get("name"):
                    continue

            store.add(tool["name"], tool)

        return store


async def registry_from_redis(
    store: RedisToolStore,
    embedder: Any | None = None,
) -> ToolRegistry:
    """Create a ToolRegistry from tools stored in Redis.

    Args:
        store: RedisToolStore containing tool configurations.
        embedder: Optional embedding provider for semantic search.

    Returns:
        ToolRegistry with tools from Redis.
    """
    from py_code_mode.tools import ToolRegistry
    from py_code_mode.tools.adapters import CLIAdapter
    from py_code_mode.tools.adapters.mcp import MCPAdapter

    registry = ToolRegistry(embedder=embedder)
    tools = store.list()

    if not tools:
        return registry

    # Separate CLI and MCP tools
    cli_configs: list[dict[str, Any]] = []
    mcp_configs: list[dict[str, Any]] = []

    for name, config in tools.items():
        tool_type = config.get("type", "cli")

        if tool_type == "cli":
            cli_configs.append(config)
        elif tool_type == "mcp":
            mcp_configs.append(config)

    # Register CLI tools using new unified interface
    if cli_configs:
        adapter = CLIAdapter.from_configs(cli_configs)
        if adapter.list_tools():
            registry._adapters.append(adapter)

    # Register MCP tools
    for mcp_config in mcp_configs:
        transport = mcp_config.get("transport", "stdio")
        tool_name = mcp_config.get("name", "unknown")
        try:
            if transport == "stdio":
                mcp_adapter = await MCPAdapter.connect_stdio(
                    command=mcp_config["command"],
                    args=mcp_config.get("args", []),
                    env=mcp_config.get("env", {}),
                )
            elif transport == "sse":
                mcp_adapter = await MCPAdapter.connect_sse(
                    url=mcp_config["url"],
                    headers=mcp_config.get("headers"),
                )
            else:
                raise ValueError(f"Unknown MCP transport: {transport}")

            await mcp_adapter._refresh_tools()
            registry.register_adapter(mcp_adapter)
            logger.info("MCP tool loaded: %s", tool_name)
        except ImportError:
            logger.info("MCP tool skipped (mcp package not installed): %s", tool_name)
        except (OSError, ValueError, KeyError, TimeoutError, ConnectionError) as e:
            logger.warning("MCP tool failed: %s - %s: %s", tool_name, type(e).__name__, e)

    return registry
