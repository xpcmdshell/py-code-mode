"""MCP adapter for consuming tools from MCP servers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from py_code_mode.errors import ToolCallError, ToolNotFoundError
from py_code_mode.types import JsonSchema, ToolDefinition

if TYPE_CHECKING:
    from contextlib import AsyncExitStack


@runtime_checkable
class MCPSession(Protocol):
    """Protocol for MCP ClientSession interface."""

    async def list_tools(self) -> Any:
        """List available tools."""
        ...

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Call a tool by name."""
        ...


class MCPAdapter:
    """Adapter for MCP (Model Context Protocol) servers.

    Connects to an MCP server and exposes its tools through the ToolAdapter interface.

    Usage:
        # With existing session
        adapter = MCPAdapter(session=client_session)

        # Or connect via stdio
        adapter = await MCPAdapter.connect_stdio("python", ["server.py"])

        # Use through registry
        registry = ToolRegistry()
        await registry.register_adapter(adapter)
    """

    def __init__(
        self,
        session: MCPSession,
        exit_stack: AsyncExitStack | None = None,
    ) -> None:
        """Initialize adapter with MCP session.

        Args:
            session: MCP ClientSession instance.
            exit_stack: Optional AsyncExitStack for resource management.
        """
        self._session = session
        self._exit_stack = exit_stack
        self._tools_cache: list[ToolDefinition] | None = None

    @classmethod
    async def connect_stdio(
        cls,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> MCPAdapter:
        """Connect to an MCP server via stdio transport.

        Args:
            command: Command to run (e.g., "python", "node").
            args: Command arguments (e.g., ["server.py"]).
            env: Optional environment variables.

        Returns:
            Connected MCPAdapter instance.

        Raises:
            ImportError: If mcp package is not installed.
        """
        try:
            from contextlib import AsyncExitStack

            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError as e:
            raise ImportError(
                "MCP package required for stdio connection. Install with: pip install mcp"
            ) from e

        exit_stack = AsyncExitStack()

        server_params = StdioServerParameters(
            command=command,
            args=args or [],
            env=env,
        )

        stdio_transport = await exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        stdio, write = stdio_transport

        session = await exit_stack.enter_async_context(ClientSession(stdio, write))

        await session.initialize()

        return cls(session=session, exit_stack=exit_stack)

    @classmethod
    async def connect_sse(
        cls,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float = 5.0,
        sse_read_timeout: float = 300.0,
    ) -> MCPAdapter:
        """Connect to an MCP server via SSE transport.

        Args:
            url: SSE endpoint URL (e.g., "http://localhost:8080/sse").
            headers: Optional HTTP headers (e.g., for authentication).
            timeout: Connection timeout in seconds.
            sse_read_timeout: Read timeout for SSE events in seconds.

        Returns:
            Connected MCPAdapter instance.

        Raises:
            ImportError: If mcp package is not installed.
        """
        try:
            from contextlib import AsyncExitStack

            from mcp import ClientSession
            from mcp.client.sse import sse_client
        except ImportError as e:
            raise ImportError(
                "MCP package required for SSE connection. Install with: pip install mcp"
            ) from e

        exit_stack = AsyncExitStack()

        sse_transport = await exit_stack.enter_async_context(
            sse_client(
                url, headers=headers, timeout=timeout, sse_read_timeout=sse_read_timeout
            )
        )
        read_stream, write_stream = sse_transport

        session = await exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )

        await session.initialize()

        return cls(session=session, exit_stack=exit_stack)

    async def list_tools(self) -> list[ToolDefinition]:
        """List all tools from the MCP server.

        Returns:
            List of ToolDefinition objects.
        """
        if self._tools_cache is not None:
            return self._tools_cache

        response = await self._session.list_tools()

        tools = []
        for mcp_tool in response.tools:
            # Convert MCP inputSchema to our JsonSchema
            input_schema = self._convert_schema(mcp_tool.inputSchema)

            tool_def = ToolDefinition(
                name=mcp_tool.name,
                description=mcp_tool.description or "",
                input_schema=input_schema,
            )
            tools.append(tool_def)

        self._tools_cache = tools
        return tools

    async def call_tool(self, name: str, args: dict[str, Any]) -> Any:
        """Call a tool on the MCP server.

        Args:
            name: Tool name.
            args: Tool arguments.

        Returns:
            Tool result (text content extracted from MCP response).

        Raises:
            ToolNotFoundError: If tool not found.
            ToolCallError: If tool execution fails.
        """
        try:
            result = await self._session.call_tool(name, args)
        except Exception as e:
            # Check if it's a "not found" type error
            error_msg = str(e).lower()
            if "not found" in error_msg or "unknown" in error_msg:
                raise ToolNotFoundError(name) from e
            raise ToolCallError(name, tool_args=args, cause=e) from e

        # Check for error response
        if hasattr(result, "isError") and result.isError:
            error_text = self._extract_text(result)
            raise ToolCallError(name, tool_args=args, cause=RuntimeError(error_text))

        # Extract text content from response
        return self._extract_text(result)

    def _extract_text(self, result: Any) -> str:
        """Extract text content from MCP tool result."""
        if not hasattr(result, "content"):
            return str(result)

        texts = []
        for content in result.content:
            if hasattr(content, "type"):
                if content.type == "text" and hasattr(content, "text"):
                    texts.append(content.text)
                elif content.type == "error" and hasattr(content, "text"):
                    texts.append(content.text)

        return "\n".join(texts) if texts else str(result)

    def _convert_schema(self, mcp_schema: dict[str, Any]) -> JsonSchema:
        """Convert MCP input schema to JsonSchema."""
        schema_type = mcp_schema.get("type", "object")

        properties = {}
        if "properties" in mcp_schema:
            for prop_name, prop_def in mcp_schema["properties"].items():
                properties[prop_name] = JsonSchema(
                    type=prop_def.get("type", "string"),
                    description=prop_def.get("description"),
                )

        return JsonSchema(
            type=schema_type,
            properties=properties if properties else None,
            required=mcp_schema.get("required"),
            description=mcp_schema.get("description"),
        )

    async def close(self) -> None:
        """Clean up resources.

        Note: MCP's stdio_client uses anyio TaskGroups which require exit
        from the same task that entered. When tools are called via
        run_coroutine_threadsafe (from executor's threaded code execution),
        this invariant is violated. We suppress cleanup errors here since
        the subprocess terminates anyway.
        """
        if self._exit_stack is not None:
            try:
                await self._exit_stack.aclose()
            except Exception:
                pass
        self._tools_cache = None
