"""Base protocol for tool adapters."""

from typing import Any, Protocol, runtime_checkable

from py_code_mode.types import ToolDefinition


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
        adapter = CLIAdapter(tool_definitions)
        tools = await adapter.list_tools()
        result = await adapter.call_tool("grep", {"pattern": "error", "file": "log.txt"})
        await adapter.close()
    """

    async def list_tools(self) -> list[ToolDefinition]:
        """List all tools available from this adapter.

        Returns:
            List of tool definitions with schemas and metadata.
        """
        ...

    async def call_tool(self, name: str, args: dict[str, Any]) -> Any:
        """Call a tool by name with the given arguments.

        Args:
            name: The tool name (without namespace prefix).
            args: Arguments matching the tool's input schema.

        Returns:
            Tool result, typically a dict matching the output schema.

        Raises:
            ToolNotFoundError: If tool name not recognized by this adapter.
            ToolCallError: If tool execution fails.
            ToolTimeoutError: If tool exceeds timeout.
        """
        ...

    async def close(self) -> None:
        """Clean up adapter resources.

        Called when the adapter is no longer needed. Should close
        connections, terminate processes, etc.
        """
        ...
