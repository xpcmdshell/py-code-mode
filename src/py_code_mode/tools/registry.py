"""Tool registry with flat namespace and tag-based scoping."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, TypeVar

from py_code_mode.errors import CodeModeError, ToolCallError, ToolNotFoundError
from py_code_mode.skills import EmbeddingProvider, cosine_similarity
from py_code_mode.tools.adapters.base import ToolAdapter
from py_code_mode.tools.types import Tool

logger = logging.getLogger(__name__)

# Type alias for MCP adapter to avoid import at module level
MCPAdapterType = "MCPAdapter"


async def _load_mcp_adapter(
    mcp_config: dict,
    log: logging.Logger,
) -> MCPAdapterType | None:
    """Load an MCP adapter from config.

    Args:
        mcp_config: MCP tool configuration dict with transport, command/url, etc.
        log: Logger instance for status and error messages.

    Returns:
        The MCPAdapter on success, None on failure (error is logged).
    """
    from py_code_mode.tools.adapters.mcp import MCPAdapter

    transport = mcp_config.get("transport", "stdio")
    tool_name = mcp_config.get("name", "unknown")

    try:
        if transport == "stdio":
            adapter = await MCPAdapter.connect_stdio(
                command=mcp_config["command"],
                args=mcp_config.get("args", []),
                env=mcp_config.get("env", {}),
            )
        elif transport == "sse":
            adapter = await MCPAdapter.connect_sse(
                url=mcp_config["url"],
                headers=mcp_config.get("headers"),
            )
        else:
            raise ValueError(f"Unknown MCP transport: {transport}")

        await adapter._refresh_tools()
        log.info("MCP tool loaded: %s", tool_name)
        return adapter

    except ImportError:
        log.warning(
            "MCP tool skipped: %s (mcp package not installed, install with: pip install mcp)",
            tool_name,
        )
    except KeyError as e:
        log.warning("MCP tool failed: %s - missing required key: %s", tool_name, e)
    except (OSError, ValueError, TimeoutError, ConnectionError) as e:
        log.warning("MCP tool failed: %s - %s: %s", tool_name, type(e).__name__, e)

    return None


# Substring search scoring constants
EXACT_NAME_MATCH_SCORE = 100
PARTIAL_NAME_MATCH_SCORE = 50
DESCRIPTION_MATCH_SCORE = 25

T = TypeVar("T")


def substring_search(
    query: str,
    items: list[T],
    get_name: Callable[[T], str],
    get_description: Callable[[T], str],
    limit: int = 10,
) -> list[T]:
    """Search items by substring matching on name and description.

    Args:
        query: Search query string.
        items: List of items to search.
        get_name: Function to extract name from an item.
        get_description: Function to extract description from an item.
        limit: Maximum number of results to return.

    Returns:
        List of matching items, sorted by relevance score.
    """
    query_lower = query.lower()
    matches: list[tuple[int, T]] = []

    for item in items:
        name = get_name(item)
        description = get_description(item)

        name_score = 0
        desc_score = 0

        if query_lower in name.lower():
            if name.lower() == query_lower:
                name_score = EXACT_NAME_MATCH_SCORE
            else:
                name_score = PARTIAL_NAME_MATCH_SCORE

        if description and query_lower in description.lower():
            desc_score = DESCRIPTION_MATCH_SCORE

        total_score = name_score + desc_score
        if total_score > 0:
            matches.append((total_score, item))

    matches.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in matches[:limit]]


class ToolRegistry:
    """Registry of tools with flat namespace and tag-based scoping.

    Tools are registered by name (e.g., "nmap", "curl") without namespace prefixes.
    Tags are used for scoping and filtering.

    Usage:
        registry = ToolRegistry()
        await registry.register_adapter(cli_adapter, tags={"network", "recon"})

        # Call tools by name
        result = await registry.call_tool("nmap", {"target": "10.0.0.1"})

        # Get scoped view
        recon_tools = registry.scoped_view({"recon"})
    """

    def __init__(
        self,
        embedder: EmbeddingProvider | None = None,
    ) -> None:
        self._embedder = embedder
        self._adapters: list[ToolAdapter] = []
        self._tools: dict[str, Tool] = {}  # name -> Tool
        self._tool_to_adapter: dict[str, ToolAdapter] = {}  # name -> adapter
        self._vectors: dict[str, list[float]] = {}  # name -> embedding vector

    @classmethod
    async def from_dir(
        cls,
        path: str,
        embedder: EmbeddingProvider | None = None,
    ) -> ToolRegistry:
        """Create registry from a directory of tool YAML files.

        Supports both CLI and MCP tools:

            # tools/nmap.yaml (CLI tool)
            name: nmap
            type: cli
            args: "{flags} {target}"

            # tools/brave_search.yaml (MCP tool via stdio)
            name: brave_search
            type: mcp
            transport: stdio
            command: npx
            args: ["-y", "@anthropic/mcp-brave-search"]

            # tools/weather.yaml (MCP tool via SSE)
            name: weather
            type: mcp
            transport: sse
            url: http://localhost:8080/mcp

        Args:
            path: Path to directory containing tool YAML files.
            embedder: Optional embedding provider for semantic search.

        Returns:
            ToolRegistry with tools loaded.

        Example:
            registry = await ToolRegistry.from_dir("./my_tools/")
        """
        from pathlib import Path as PathLib

        import yaml

        from py_code_mode.tools.adapters import CLIAdapter

        registry = cls(embedder=embedder)
        tools_path = PathLib(path)

        if not tools_path.exists():
            logger.warning("Tools path does not exist: %s", tools_path)
            return registry

        # Separate CLI and MCP tool configs
        cli_configs: list[dict] = []
        mcp_configs: list[dict] = []

        for tool_file in sorted(tools_path.glob("*.yaml")):
            try:
                with open(tool_file) as f:
                    tool = yaml.safe_load(f)
                    if not tool or not tool.get("name"):
                        logger.warning("Tool file %s missing 'name' field, skipping", tool_file)
                        continue
            except (OSError, yaml.YAMLError) as e:
                logger.warning("Failed to load tool file %s: %s", tool_file, e)
                continue

            tool_type = tool.get("type", "cli")

            if tool_type == "mcp":
                mcp_configs.append(tool)
            else:
                cli_configs.append(tool)

        # Load CLI tools first
        if cli_configs:
            cli_adapter = CLIAdapter.from_configs(cli_configs)
            if cli_adapter.list_tools():
                registry.register_adapter(cli_adapter)

        # Load MCP tools using shared helper
        for mcp_config in mcp_configs:
            adapter = await _load_mcp_adapter(mcp_config, logger)
            if adapter is not None:
                registry.register_adapter(adapter)

        return registry

    def add_adapter(self, adapter: ToolAdapter) -> None:
        """Add an adapter without registering its tools.

        Use this when you want to add an adapter but handle tool registration
        separately (e.g., when loading tools from a different source).

        For normal use, prefer register_adapter() which also registers the
        adapter's tools with conflict detection and tag merging.

        Args:
            adapter: The adapter to add.
        """
        self._adapters.append(adapter)

    def get_adapters(self) -> list[ToolAdapter]:
        """Get all registered adapters.

        Returns:
            List of adapters in registration order.
        """
        return list(self._adapters)

    def get_all_tools(self) -> list[Tool]:
        """Get all Tool objects from all adapters.

        This method collects Tool objects (with callables) from all adapters.
        Used by ToolsNamespace for agent-facing tool discovery.

        Returns:
            List of Tool objects from all adapters.
        """
        tools: list[Tool] = []
        for adapter in self._adapters:
            tools.extend(adapter.list_tools())
        return tools

    def find_adapter_for_tool(self, tool_name: str) -> ToolAdapter | None:
        """Find the adapter that owns a tool by name.

        Args:
            tool_name: Name of the tool to find.

        Returns:
            The adapter that owns the tool, or None if not found.
        """
        for adapter in self._adapters:
            tools = adapter.list_tools()
            if any(t.name == tool_name for t in tools):
                return adapter
        return None

    def register_adapter(
        self,
        adapter: ToolAdapter,
        tags: set[str] | None = None,
    ) -> list[Tool]:
        """Register an adapter's tools.

        Args:
            adapter: The adapter providing tools.
            tags: Tags to apply to all tools from this adapter.

        Returns:
            List of registered tools.

        Raises:
            ValueError: If a tool name conflicts with an existing tool.
        """
        self._adapters.append(adapter)
        adapter_tools = adapter.list_tools()
        registered = []

        for tool in adapter_tools:
            if tool.name in self._tools:
                raise ValueError(
                    f"Tool '{tool.name}' already registered. "
                    f"Use unique names or different tags for scoping."
                )

            # Merge tags if provided
            if tags:
                merged_tags = tool.tags | frozenset(tags)
                # Create new Tool with merged tags
                tool = Tool(
                    name=tool.name,
                    description=tool.description,
                    callables=tool.callables,
                    tags=merged_tags,
                )

            self._tools[tool.name] = tool
            self._tool_to_adapter[tool.name] = adapter
            registered.append(tool)

        # Embed tools if embedder is available
        if self._embedder and registered:
            self._embed_tools(registered)

        return registered

    def _embed_tools(self, tools: list[Tool]) -> None:
        """Embed tools and store their vectors."""
        if not self._embedder:
            return

        texts = [f"{t.name}: {t.description or ''}" for t in tools]
        vectors = self._embedder.embed(texts)

        for tool, vector in zip(tools, vectors, strict=True):
            self._vectors[tool.name] = vector

    def list_tools(self, scope: set[str] | None = None) -> list[Tool]:
        """List all tools, optionally filtered by scope.

        Args:
            scope: Set of tags to filter by. If None, returns all tools.
                   A tool matches if any of its tags are in the scope.

        Returns:
            List of matching tools.
        """
        if scope is None:
            return list(self._tools.values())

        return [tool for tool in self._tools.values() if tool.tags & scope]

    def get_tool(self, name: str) -> Tool:
        """Get a tool by name.

        Raises:
            ToolNotFoundError: If tool not found.
        """
        if name not in self._tools:
            raise ToolNotFoundError(name, list(self._tools.keys()))
        return self._tools[name]

    async def call_tool(
        self,
        name: str,
        callable_name: str | None,
        args: dict[str, Any],
    ) -> Any:
        """Call a tool by name.

        Args:
            name: Tool name (e.g., "nmap", "curl").
            callable_name: Callable/recipe name, or None for escape hatch.
            args: Arguments for the tool.

        Returns:
            Tool result.

        Raises:
            ToolNotFoundError: If tool not found.
            ToolCallError: If tool execution fails.
        """
        if name not in self._tools:
            raise ToolNotFoundError(name, list(self._tools.keys()))

        adapter = self._tool_to_adapter[name]

        try:
            return await adapter.call_tool(name, callable_name, args)
        except CodeModeError:
            # Our error types (ToolCallError, ToolTimeoutError, etc.) pass through
            raise
        except (OSError, TimeoutError, ValueError, RuntimeError) as e:
            # Known execution errors not caught by adapter
            raise ToolCallError(name, tool_args=args, cause=e) from e

    def scoped_view(self, scope: set[str]) -> ScopedToolRegistry:
        """Create a scoped view of the registry.

        The scoped view only exposes tools matching the given tags.
        This is used to restrict tool access for different agent roles.

        Args:
            scope: Set of tags that tools must match.

        Returns:
            A ScopedToolRegistry that only sees matching tools.
        """
        return ScopedToolRegistry(self, scope)

    def search(self, query: str, limit: int = 10) -> list[Tool]:
        """Search tools by name, description, or semantic similarity.

        Uses semantic search when embedder is available, otherwise falls back
        to substring search.

        Args:
            query: Search query.
            limit: Maximum results to return.

        Returns:
            Matching tools, sorted by relevance.
        """
        # Use semantic search if embedder and vectors available
        if self._embedder and self._vectors:
            return self._semantic_search(query, limit)

        # Fallback to substring search
        return self._substring_search(query, limit)

    def _semantic_search(self, query: str, limit: int) -> list[Tool]:
        """Search using cosine similarity with embeddings."""
        if not self._embedder or not self._vectors:
            return []

        # Embed the query (uses instruction prefix for retrieval models)
        query_vec = self._embedder.embed_query(query)

        # Compute cosine similarity with each tool
        scores: list[tuple[float, Tool]] = []
        for name, tool_vec in self._vectors.items():
            similarity = cosine_similarity(query_vec, tool_vec)
            tool = self._tools.get(name)
            if tool:
                scores.append((similarity, tool))

        # Sort by similarity descending
        scores.sort(key=lambda x: x[0], reverse=True)
        return [tool for _, tool in scores[:limit]]

    def _substring_search(self, query: str, limit: int) -> list[Tool]:
        """Search using substring matching (fallback)."""
        return substring_search(
            query=query,
            items=list(self._tools.values()),
            get_name=lambda t: t.name,
            get_description=lambda t: t.description or "",
            limit=limit,
        )

    async def refresh(self) -> None:
        """Refresh by closing adapters and clearing state.

        Closes all adapters and clears tools, vectors, and mappings.
        Without a backing store, tools must be re-registered manually.
        """
        for adapter in reversed(self._adapters):
            await adapter.close()
        self._adapters.clear()
        self._tools.clear()
        self._tool_to_adapter.clear()
        self._vectors.clear()

    async def close(self) -> None:
        """Close all adapters in reverse order (LIFO).

        Anyio cancel scopes must be exited in the reverse order they were
        entered. Since adapters are registered sequentially and each MCP
        adapter enters a cancel scope, we must close in reverse order.
        """
        for adapter in reversed(self._adapters):
            await adapter.close()
        self._adapters.clear()
        self._tools.clear()
        self._tool_to_adapter.clear()
        self._vectors.clear()


class ScopedToolRegistry:
    """A scoped view of a ToolRegistry that only exposes matching tools.

    This provides the same interface as ToolRegistry but filters
    tools based on a scope (set of allowed tags).
    """

    def __init__(self, registry: ToolRegistry, scope: set[str]) -> None:
        self._registry = registry
        self._scope = scope

    def list_tools(self) -> list[Tool]:
        """List tools matching this scope."""
        return self._registry.list_tools(self._scope)

    def get_tool(self, name: str) -> Tool:
        """Get a tool if it matches scope.

        Raises:
            ToolNotFoundError: If tool not found or not in scope.
        """
        tool = self._registry.get_tool(name)
        if not (tool.tags & self._scope):
            raise ToolNotFoundError(name, [t.name for t in self.list_tools()])
        return tool

    async def call_tool(
        self,
        name: str,
        callable_name: str | None,
        args: dict[str, Any],
    ) -> Any:
        """Call a tool if it matches scope.

        Raises:
            ToolNotFoundError: If tool not in scope.
            ToolCallError: If tool execution fails.
        """
        # Verify tool is in scope before calling
        self.get_tool(name)
        return await self._registry.call_tool(name, callable_name, args)

    def search(self, query: str, limit: int = 10) -> list[Tool]:
        """Search tools within scope."""
        all_matches = self._registry.search(query, limit=limit * 2)
        return [t for t in all_matches if t.tags & self._scope][:limit]

    @property
    def scope(self) -> set[str]:
        """The scope (allowed tags) for this view."""
        return self._scope.copy()

    def get_adapters(self) -> list[ToolAdapter]:
        """Get all registered adapters from the underlying registry.

        Returns:
            List of adapters in registration order.
        """
        return self._registry.get_adapters()

    def get_all_tools(self) -> list[Tool]:
        """Get all Tool objects from the underlying registry.

        Returns:
            List of Tool objects from all adapters.
        """
        return self._registry.get_all_tools()

    def find_adapter_for_tool(self, tool_name: str) -> ToolAdapter | None:
        """Find the adapter that owns a tool by name.

        Args:
            tool_name: Name of the tool to find.

        Returns:
            The adapter that owns the tool, or None if not found.
        """
        return self._registry.find_adapter_for_tool(tool_name)
