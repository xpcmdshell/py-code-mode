"""Tool registry with flat namespace and tag-based scoping."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from py_code_mode.adapters.base import ToolAdapter
from py_code_mode.errors import ToolCallError, ToolNotFoundError
from py_code_mode.types import ToolDefinition

if TYPE_CHECKING:
    from py_code_mode.adapters import CLIAdapter


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

    def __init__(self) -> None:
        self._adapters: list[ToolAdapter] = []
        self._tools: dict[str, ToolDefinition] = {}  # name -> definition
        self._tool_to_adapter: dict[str, ToolAdapter] = {}  # name -> adapter

    @classmethod
    async def from_dir(cls, path: str) -> "ToolRegistry":
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

        Returns:
            ToolRegistry with tools loaded.

        Example:
            registry = await ToolRegistry.from_dir("./my_tools/")
        """
        from pathlib import Path as PathLib

        import yaml

        from py_code_mode.adapters import CLIAdapter
        from py_code_mode.mcp_adapter import MCPAdapter

        registry = cls()
        tools_path = PathLib(path)

        if not tools_path.exists():
            return registry

        # Separate CLI and MCP tools
        cli_specs = []
        mcp_configs = []

        for tool_file in sorted(tools_path.glob("*.yaml")):
            with open(tool_file) as f:
                tool = yaml.safe_load(f)
                if not tool or not tool.get("name"):
                    continue

            tool_type = tool.get("type", "cli")

            if tool_type == "cli":
                cli_specs.append(tool_file)
            elif tool_type == "mcp":
                mcp_configs.append(tool)

        # Load CLI tools
        if cli_specs:
            adapter = CLIAdapter.from_dir(path)
            if await adapter.list_tools():
                await registry.register_adapter(adapter)

        # Load MCP tools
        for mcp_config in mcp_configs:
            transport = mcp_config.get("transport", "stdio")
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

                await registry.register_adapter(adapter)
            except ImportError:
                # MCP package not installed, skip
                pass

        return registry

    async def register_adapter(
        self,
        adapter: ToolAdapter,
        tags: set[str] | None = None,
    ) -> list[ToolDefinition]:
        """Register an adapter's tools.

        Args:
            adapter: The adapter providing tools.
            tags: Tags to apply to all tools from this adapter.

        Returns:
            List of registered tool definitions.

        Raises:
            ValueError: If a tool name conflicts with an existing tool.
        """
        self._adapters.append(adapter)
        adapter_tools = await adapter.list_tools()
        registered = []

        for tool in adapter_tools:
            if tool.name in self._tools:
                raise ValueError(
                    f"Tool '{tool.name}' already registered. "
                    f"Use unique names or different tags for scoping."
                )

            # Merge tags
            merged_tags = tool.tags | frozenset(tags or set())

            # Create definition with merged tags
            registered_tool = ToolDefinition(
                name=tool.name,
                description=tool.description,
                input_schema=tool.input_schema,
                output_schema=tool.output_schema,
                tags=merged_tags,
                python_deps=tool.python_deps,
                timeout_seconds=tool.timeout_seconds,
            )

            self._tools[tool.name] = registered_tool
            self._tool_to_adapter[tool.name] = adapter
            registered.append(registered_tool)

        return registered

    def list_tools(self, scope: set[str] | None = None) -> list[ToolDefinition]:
        """List all tools, optionally filtered by scope.

        Args:
            scope: Set of tags to filter by. If None, returns all tools.
                   A tool matches if any of its tags are in the scope.

        Returns:
            List of matching tool definitions.
        """
        if scope is None:
            return list(self._tools.values())

        return [tool for tool in self._tools.values() if tool.matches_scope(scope)]

    def get_tool(self, name: str) -> ToolDefinition:
        """Get a tool definition by name.

        Raises:
            ToolNotFoundError: If tool not found.
        """
        if name not in self._tools:
            raise ToolNotFoundError(name, list(self._tools.keys()))
        return self._tools[name]

    async def call_tool(self, name: str, args: dict[str, Any]) -> Any:
        """Call a tool by name.

        Args:
            name: Tool name (e.g., "nmap", "curl").
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
            return await adapter.call_tool(name, args)
        except Exception as e:
            if isinstance(e, ToolCallError):
                raise
            raise ToolCallError(name, tool_args=args, cause=e) from e

    def scoped_view(self, scope: set[str]) -> "ScopedToolRegistry":
        """Create a scoped view of the registry.

        The scoped view only exposes tools matching the given tags.
        This is used to restrict tool access for different agent roles.

        Args:
            scope: Set of tags that tools must match.

        Returns:
            A ScopedToolRegistry that only sees matching tools.
        """
        return ScopedToolRegistry(self, scope)

    def search(self, query: str, limit: int = 10) -> list[ToolDefinition]:
        """Search tools by name or description.

        Simple substring search. For semantic search, use SkillLibrary.

        Args:
            query: Search query (case-insensitive).
            limit: Maximum results to return.

        Returns:
            Matching tool definitions, sorted by relevance.
        """
        query_lower = query.lower()
        matches = []

        for tool in self._tools.values():
            # Score based on where query appears
            name_score = 0
            desc_score = 0

            if query_lower in tool.name.lower():
                # Exact name match is best
                name_score = 100 if tool.name.lower() == query_lower else 50

            if tool.description and query_lower in tool.description.lower():
                desc_score = 25

            total_score = name_score + desc_score
            if total_score > 0:
                matches.append((total_score, tool))

        # Sort by score descending
        matches.sort(key=lambda x: x[0], reverse=True)
        return [tool for _, tool in matches[:limit]]

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


class ScopedToolRegistry:
    """A scoped view of a ToolRegistry that only exposes matching tools.

    This provides the same interface as ToolRegistry but filters
    tools based on a scope (set of allowed tags).
    """

    def __init__(self, registry: ToolRegistry, scope: set[str]) -> None:
        self._registry = registry
        self._scope = scope

    def list_tools(self) -> list[ToolDefinition]:
        """List tools matching this scope."""
        return self._registry.list_tools(self._scope)

    def get_tool(self, name: str) -> ToolDefinition:
        """Get a tool if it matches scope.

        Raises:
            ToolNotFoundError: If tool not found or not in scope.
        """
        tool = self._registry.get_tool(name)
        if not tool.matches_scope(self._scope):
            raise ToolNotFoundError(name, [t.name for t in self.list_tools()])
        return tool

    async def call_tool(self, name: str, args: dict[str, Any]) -> Any:
        """Call a tool if it matches scope.

        Raises:
            ToolNotFoundError: If tool not in scope.
            ToolCallError: If tool execution fails.
        """
        # Verify tool is in scope before calling
        self.get_tool(name)
        return await self._registry.call_tool(name, args)

    def search(self, query: str, limit: int = 10) -> list[ToolDefinition]:
        """Search tools within scope."""
        all_matches = self._registry.search(query, limit=limit * 2)
        return [t for t in all_matches if t.matches_scope(self._scope)][:limit]

    @property
    def scope(self) -> set[str]:
        """The scope (allowed tags) for this view."""
        return self._scope.copy()
