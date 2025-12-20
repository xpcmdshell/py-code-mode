"""Base protocol for tool adapters."""

from typing import Any, Protocol, runtime_checkable

from py_code_mode.tool_types import Tool


@runtime_checkable
class ToolAdapter(Protocol):
    """Protocol for tool source adapters.

    Adapters connect to different tool sources (CLI, MCP, HTTP, etc.)
    and provide a uniform interface for tool discovery and execution.

    Example implementations:
    - CLIAdapter: Wraps command-line tools
    - MCPAdapter: Connects to MCP servers
    - HTTPAdapter: Calls REST APIs

    Usage:
        adapter = CLIAdapter(tools_path=Path("./tools"))
        tools = adapter.list_tools()
        result = await adapter.call_tool("grep", "search", {"pattern": "error"})
        await adapter.close()
    """

    def list_tools(self) -> list[Tool]:
        """List all tools available from this adapter.

        Returns:
            List of Tool objects with callables and metadata.
        """
        ...

    async def call_tool(
        self,
        name: str,
        callable_name: str | None,
        args: dict[str, Any],
    ) -> Any:
        """Call a tool with optional callable specification.

        Args:
            name: Tool name.
            callable_name: Callable name (recipe) or None for escape hatch.
            args: Arguments for the callable.

        Returns:
            Tool result.

        Raises:
            ToolNotFoundError: If tool not found.
            ToolCallError: If tool execution fails.
            ToolTimeoutError: If tool exceeds timeout.
        """
        ...

    async def describe(self, tool_name: str, callable_name: str) -> dict[str, str]:
        """Get parameter descriptions for a callable.

        Args:
            tool_name: Name of the tool.
            callable_name: Name of the callable.

        Returns:
            Dict mapping parameter names to descriptions.
        """
        ...

    async def close(self) -> None:
        """Clean up adapter resources.

        Called when the adapter is no longer needed. Should close
        connections, terminate processes, etc.
        """
        ...
