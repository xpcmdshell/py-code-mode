"""MCP adapter for consuming tools from MCP servers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from py_code_mode.errors import ToolCallError, ToolNotFoundError
from py_code_mode.tools.types import Tool, ToolCallable, ToolParameter

logger = logging.getLogger(__name__)

# MCP SDK exception types (optional dependency)
try:
    from mcp import JSONRPCError, McpError

    MCP_ERRORS: tuple[type[Exception], ...] = (McpError, JSONRPCError)
except ImportError:
    MCP_ERRORS = ()

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
    All MCP tools are grouped under a single namespace.

    Usage:
        # With existing session
        adapter = MCPAdapter(session=client_session, namespace="time")

        # Or connect via stdio
        adapter = await MCPAdapter.connect_stdio("python", ["server.py"], namespace="time")

        # Use through registry - tools accessible as tools.time.get_current_time()
        registry = ToolRegistry()
        await registry.register_adapter(adapter)
    """

    def __init__(
        self,
        session: MCPSession,
        namespace: str,
        exit_stack: AsyncExitStack | None = None,
    ) -> None:
        """Initialize adapter with MCP session.

        Args:
            session: MCP ClientSession instance.
            namespace: Name for the tool namespace (e.g., "time", "web").
            exit_stack: Optional AsyncExitStack for resource management.
        """
        self._session = session
        self._namespace = namespace
        self._exit_stack = exit_stack
        self._tools_cache: list[Tool] | None = None

    @classmethod
    async def connect_stdio(
        cls,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        *,
        namespace: str,
    ) -> MCPAdapter:
        """Connect to an MCP server via stdio transport.

        Args:
            command: Command to run (e.g., "python", "node").
            args: Command arguments (e.g., ["server.py"]).
            env: Optional environment variables.
            namespace: Name for the tool namespace (e.g., "time", "web").

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

        stdio_transport = await exit_stack.enter_async_context(stdio_client(server_params))
        stdio, write = stdio_transport

        session = await exit_stack.enter_async_context(ClientSession(stdio, write))

        await session.initialize()

        return cls(session=session, namespace=namespace, exit_stack=exit_stack)

    @classmethod
    async def connect_sse(
        cls,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float = 5.0,
        sse_read_timeout: float = 300.0,
        *,
        namespace: str,
    ) -> MCPAdapter:
        """Connect to an MCP server via SSE transport.

        Args:
            url: SSE endpoint URL (e.g., "http://localhost:8080/sse").
            headers: Optional HTTP headers (e.g., for authentication).
            timeout: Connection timeout in seconds.
            sse_read_timeout: Read timeout for SSE events in seconds.
            namespace: Name for the tool namespace (e.g., "time", "web").

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
            sse_client(url, headers=headers, timeout=timeout, sse_read_timeout=sse_read_timeout)
        )
        read_stream, write_stream = sse_transport

        session = await exit_stack.enter_async_context(ClientSession(read_stream, write_stream))

        await session.initialize()

        return cls(session=session, namespace=namespace, exit_stack=exit_stack)

    def list_tools(self) -> list[Tool]:
        """List all tools from the MCP server.

        Returns:
            List of Tool objects.

        Note: Tools are cached after first async fetch. Call _refresh_tools()
        to update the cache if the server adds new tools.
        """
        if self._tools_cache is not None:
            return self._tools_cache
        # Return empty list if not yet fetched - call _refresh_tools() first
        return []

    async def _refresh_tools(self) -> list[Tool]:
        """Fetch tools from MCP server and update cache.

        Returns a single Tool named after the namespace, with all MCP tools
        as callables on that Tool.

        Returns:
            List containing one Tool with namespace as name.
        """
        response = await self._session.list_tools()

        callables = []
        descriptions = []
        for mcp_tool in response.tools:
            params = self._extract_parameters(mcp_tool.inputSchema)

            callable_obj = ToolCallable(
                name=mcp_tool.name,
                description=mcp_tool.description or "",
                parameters=tuple(params),
            )
            callables.append(callable_obj)
            if mcp_tool.description:
                descriptions.append(f"{mcp_tool.name}: {mcp_tool.description}")

        namespace_tool = Tool(
            name=self._namespace,
            description="; ".join(descriptions)
            if descriptions
            else f"MCP tools under {self._namespace}",
            callables=tuple(callables),
        )

        self._tools_cache = [namespace_tool]
        return self._tools_cache

    def _extract_parameters(self, schema: dict[str, Any]) -> list[ToolParameter]:
        """Extract ToolParameter list from MCP input schema."""
        params = []
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))

        for prop_name, prop_def in properties.items():
            params.append(
                ToolParameter(
                    name=prop_name,
                    type=prop_def.get("type", "string"),
                    required=prop_name in required,
                    default=prop_def.get("default"),
                    description=prop_def.get("description", ""),
                )
            )

        return params

    async def call_tool(
        self,
        name: str,
        callable_name: str | None,
        args: dict[str, Any],
    ) -> Any:
        """Call a tool on the MCP server.

        Args:
            name: Namespace name (e.g., "time").
            callable_name: The actual MCP tool name to call (e.g., "get_current_time").
            args: Tool arguments.

        Returns:
            Tool result (text content extracted from MCP response).

        Raises:
            ToolNotFoundError: If tool not found.
            ToolCallError: If tool execution fails.
        """
        mcp_tool_name = callable_name if callable_name else name
        try:
            result = await self._session.call_tool(mcp_tool_name, args)
        except Exception as e:
            # MCP SDK errors, I/O errors, and timeouts from tool execution
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

    async def describe(self, tool_name: str, callable_name: str) -> dict[str, str]:
        """Get parameter descriptions for a callable.

        Args:
            tool_name: Name of the tool.
            callable_name: Ignored for MCP (no recipes).

        Returns:
            Dict mapping parameter names to descriptions.
        """
        tools = self.list_tools()
        for tool in tools:
            if tool.name == tool_name:
                for c in tool.callables:
                    if c.name == callable_name:
                        return {p.name: p.description for p in c.parameters}
        return {}

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
            except (RuntimeError, OSError) as e:
                # RuntimeError from anyio TaskGroup in threaded context
                # OSError from subprocess/pipe issues
                logger.debug("MCP cleanup failed (expected in threaded context): %s", e)
        self._tools_cache = None
