"""Tests for MCP adapter - written first to define interface."""

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from py_code_mode.tool_types import Tool


# Mock MCP types for testing without the mcp package installed
@dataclass
class MockMCPTool:
    """Mock of MCP's Tool type."""

    name: str
    description: str
    inputSchema: dict  # noqa: N815 - matches MCP's actual schema


@dataclass
class MockListToolsResult:
    """Mock of MCP's list_tools response."""

    tools: list


class TestMCPAdapterInterface:
    """Tests that define the MCPAdapter interface."""

    def test_implements_tool_adapter_protocol(self) -> None:
        """MCPAdapter satisfies ToolAdapter protocol."""
        from py_code_mode.adapters import ToolAdapter
        from py_code_mode.mcp_adapter import MCPAdapter

        # Create with mocked session
        mock_session = MagicMock()
        adapter = MCPAdapter(session=mock_session)

        assert isinstance(adapter, ToolAdapter)


class TestMCPAdapterListTools:
    """Tests for listing tools from MCP server."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock MCP ClientSession."""
        session = AsyncMock()
        session.list_tools = AsyncMock(
            return_value=MockListToolsResult(
                tools=[
                    MockMCPTool(
                        name="read_file",
                        description="Read contents of a file",
                        inputSchema={
                            "type": "object",
                            "properties": {"path": {"type": "string", "description": "File path"}},
                            "required": ["path"],
                        },
                    ),
                    MockMCPTool(
                        name="write_file",
                        description="Write content to a file",
                        inputSchema={
                            "type": "object",
                            "properties": {
                                "path": {"type": "string"},
                                "content": {"type": "string"},
                            },
                            "required": ["path", "content"],
                        },
                    ),
                ]
            )
        )
        return session

    @pytest.fixture
    async def adapter(self, mock_session):
        from py_code_mode.mcp_adapter import MCPAdapter

        adapter = MCPAdapter(session=mock_session)
        await adapter._refresh_tools()  # Populate the cache
        return adapter

    @pytest.mark.asyncio
    async def test_list_tools_returns_tool_objects(self, adapter) -> None:
        """list_tools() returns list of Tool objects."""
        tools = adapter.list_tools()

        assert len(tools) == 2
        assert all(isinstance(t, Tool) for t in tools)

    @pytest.mark.asyncio
    async def test_list_tools_maps_names(self, adapter) -> None:
        """Tool names are preserved from MCP."""
        tools = adapter.list_tools()
        names = {t.name for t in tools}

        assert names == {"read_file", "write_file"}

    @pytest.mark.asyncio
    async def test_list_tools_maps_descriptions(self, adapter) -> None:
        """Tool descriptions are preserved from MCP."""
        tools = adapter.list_tools()
        tool = next(t for t in tools if t.name == "read_file")

        assert tool.description == "Read contents of a file"

    @pytest.mark.asyncio
    async def test_list_tools_has_callable_with_parameters(self, adapter) -> None:
        """Tools have callables with parameters from input schema."""
        tools = adapter.list_tools()
        tool = next(t for t in tools if t.name == "read_file")

        assert len(tool.callables) == 1
        callable_obj = tool.callables[0]
        param_names = {p.name for p in callable_obj.parameters}
        assert "path" in param_names


class TestMCPAdapterCallTool:
    """Tests for calling tools on MCP server."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock MCP ClientSession."""
        session = AsyncMock()
        session.list_tools = AsyncMock(
            return_value=MockListToolsResult(
                tools=[
                    MockMCPTool(
                        name="echo",
                        description="Echo back input",
                        inputSchema={"type": "object", "properties": {"text": {"type": "string"}}},
                    ),
                ]
            )
        )

        # Mock call_tool response
        mock_result = MagicMock()
        mock_result.content = [MagicMock(type="text", text="hello back")]
        mock_result.isError = False
        session.call_tool = AsyncMock(return_value=mock_result)

        return session

    @pytest.fixture
    def adapter(self, mock_session):
        from py_code_mode.mcp_adapter import MCPAdapter

        return MCPAdapter(session=mock_session)

    @pytest.mark.asyncio
    async def test_call_tool_invokes_session(self, adapter, mock_session) -> None:
        """call_tool() calls session.call_tool with correct args."""
        await adapter.call_tool("echo", None, {"text": "hello"})

        mock_session.call_tool.assert_called_once_with("echo", {"text": "hello"})

    @pytest.mark.asyncio
    async def test_call_tool_returns_text_content(self, adapter) -> None:
        """call_tool() extracts text from MCP response."""
        result = await adapter.call_tool("echo", None, {"text": "hello"})

        assert result == "hello back"

    @pytest.mark.asyncio
    async def test_call_tool_not_found(self, adapter, mock_session) -> None:
        """call_tool() raises ToolNotFoundError for unknown tool."""
        from py_code_mode.errors import ToolNotFoundError

        mock_session.call_tool.side_effect = Exception("Tool not found")

        with pytest.raises(ToolNotFoundError):
            await adapter.call_tool("nonexistent", None, {})

    @pytest.mark.asyncio
    async def test_call_tool_handles_error_response(self, adapter, mock_session) -> None:
        """call_tool() handles MCP error responses."""
        from py_code_mode.errors import ToolCallError

        mock_result = MagicMock()
        mock_result.content = [MagicMock(type="error", text="Something went wrong")]
        mock_result.isError = True
        mock_session.call_tool.return_value = mock_result

        with pytest.raises(ToolCallError):
            await adapter.call_tool("echo", None, {"text": "hello"})


class TestMCPAdapterConnection:
    """Tests for MCP server connection management."""

    @pytest.mark.asyncio
    async def test_connect_to_stdio_server(self) -> None:
        """Can connect to MCP server via stdio."""
        from py_code_mode.mcp_adapter import MCPAdapter

        # This test verifies the factory method exists
        # Actual connection would require a real server
        assert hasattr(MCPAdapter, "connect_stdio")

    @pytest.mark.asyncio
    async def test_connect_to_sse_server(self) -> None:
        """Can connect to MCP server via SSE transport."""
        from py_code_mode.mcp_adapter import MCPAdapter

        # This test verifies the factory method exists
        assert hasattr(MCPAdapter, "connect_sse")

    @pytest.mark.asyncio
    async def test_close_cleans_up(self) -> None:
        """close() cleans up resources."""
        from py_code_mode.mcp_adapter import MCPAdapter

        mock_session = AsyncMock()
        adapter = MCPAdapter(session=mock_session)

        await adapter.close()

        # Should not raise


class TestMCPAdapterSSETransport:
    """Tests for SSE transport connection."""

    @pytest.mark.asyncio
    async def test_connect_sse_uses_sse_client(self) -> None:
        """connect_sse uses mcp.client.sse.sse_client."""
        from py_code_mode.mcp_adapter import MCPAdapter

        # Mock the MCP imports at their source
        with (
            patch("mcp.client.sse.sse_client") as mock_sse_client,
            patch("mcp.ClientSession") as mock_session_class,
        ):
            # Setup mock SSE client context manager
            mock_read = AsyncMock()
            mock_write = AsyncMock()
            mock_sse_cm = AsyncMock()
            mock_sse_cm.__aenter__.return_value = (mock_read, mock_write)
            mock_sse_cm.__aexit__.return_value = None
            mock_sse_client.return_value = mock_sse_cm

            # Setup mock session
            mock_session = AsyncMock()
            mock_session.initialize = AsyncMock()
            mock_session_cm = AsyncMock()
            mock_session_cm.__aenter__.return_value = mock_session
            mock_session_cm.__aexit__.return_value = None
            mock_session_class.return_value = mock_session_cm

            await MCPAdapter.connect_sse("http://localhost:8080/sse")

            # Verify SSE client was called with URL
            mock_sse_client.assert_called_once()
            call_args = mock_sse_client.call_args
            assert call_args[0][0] == "http://localhost:8080/sse"

    @pytest.mark.asyncio
    async def test_connect_sse_passes_headers(self) -> None:
        """connect_sse forwards headers to sse_client."""
        from py_code_mode.mcp_adapter import MCPAdapter

        with (
            patch("mcp.client.sse.sse_client") as mock_sse_client,
            patch("mcp.ClientSession") as mock_session_class,
        ):
            mock_read = AsyncMock()
            mock_write = AsyncMock()
            mock_sse_cm = AsyncMock()
            mock_sse_cm.__aenter__.return_value = (mock_read, mock_write)
            mock_sse_cm.__aexit__.return_value = None
            mock_sse_client.return_value = mock_sse_cm

            mock_session = AsyncMock()
            mock_session.initialize = AsyncMock()
            mock_session_cm = AsyncMock()
            mock_session_cm.__aenter__.return_value = mock_session
            mock_session_cm.__aexit__.return_value = None
            mock_session_class.return_value = mock_session_cm

            headers = {"Authorization": "Bearer token123"}
            await MCPAdapter.connect_sse("http://localhost:8080/sse", headers=headers)

            call_kwargs = mock_sse_client.call_args[1]
            assert call_kwargs.get("headers") == headers

    @pytest.mark.asyncio
    async def test_connect_sse_initializes_session(self) -> None:
        """connect_sse calls session.initialize()."""
        from py_code_mode.mcp_adapter import MCPAdapter

        with (
            patch("mcp.client.sse.sse_client") as mock_sse_client,
            patch("mcp.ClientSession") as mock_session_class,
        ):
            mock_read = AsyncMock()
            mock_write = AsyncMock()
            mock_sse_cm = AsyncMock()
            mock_sse_cm.__aenter__.return_value = (mock_read, mock_write)
            mock_sse_cm.__aexit__.return_value = None
            mock_sse_client.return_value = mock_sse_cm

            mock_session = AsyncMock()
            mock_session.initialize = AsyncMock()
            mock_session_cm = AsyncMock()
            mock_session_cm.__aenter__.return_value = mock_session
            mock_session_cm.__aexit__.return_value = None
            mock_session_class.return_value = mock_session_cm

            await MCPAdapter.connect_sse("http://localhost:8080/sse")

            mock_session.initialize.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_sse_method_exists(self) -> None:
        """connect_sse method exists on MCPAdapter."""
        from py_code_mode.mcp_adapter import MCPAdapter

        assert hasattr(MCPAdapter, "connect_sse")
        assert callable(MCPAdapter.connect_sse)


class TestMCPAdapterWithRegistry:
    """Tests for MCPAdapter integration with ToolRegistry."""

    @pytest.mark.asyncio
    async def test_register_with_registry(self) -> None:
        """MCPAdapter can be registered with ToolRegistry."""
        from py_code_mode import ToolRegistry
        from py_code_mode.mcp_adapter import MCPAdapter

        # Create adapter with mock session
        mock_session = AsyncMock()
        mock_session.list_tools = AsyncMock(
            return_value=MockListToolsResult(
                tools=[
                    MockMCPTool(
                        name="test", description="Test tool", inputSchema={"type": "object"}
                    )
                ]
            )
        )

        adapter = MCPAdapter(session=mock_session)
        await adapter._refresh_tools()  # Populate the cache
        registry = ToolRegistry()

        registry.register_adapter(adapter)

        tools = registry.list_tools()
        assert any(t.name == "test" for t in tools)

    @pytest.mark.asyncio
    async def test_call_through_registry(self) -> None:
        """Can call MCP tools through registry."""
        from py_code_mode import ToolRegistry
        from py_code_mode.mcp_adapter import MCPAdapter

        mock_session = AsyncMock()
        mock_session.list_tools = AsyncMock(
            return_value=MockListToolsResult(
                tools=[
                    MockMCPTool(name="greet", description="Greet", inputSchema={"type": "object"})
                ]
            )
        )

        mock_result = MagicMock()
        mock_result.content = [MagicMock(type="text", text="Hello!")]
        mock_result.isError = False
        mock_session.call_tool = AsyncMock(return_value=mock_result)

        adapter = MCPAdapter(session=mock_session)
        await adapter._refresh_tools()  # Populate the cache
        registry = ToolRegistry()
        registry.register_adapter(adapter)

        result = await registry.call_tool("greet", None, {})
        assert result == "Hello!"
