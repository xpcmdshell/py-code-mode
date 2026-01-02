"""Tests for MCP adapter - written first to define interface."""

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from py_code_mode.tools import Tool


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
        from py_code_mode.tools.adapters import ToolAdapter
        from py_code_mode.tools.adapters.mcp import MCPAdapter

        mock_session = MagicMock()
        adapter = MCPAdapter(session=mock_session, namespace="test")

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
        from py_code_mode.tools.adapters.mcp import MCPAdapter

        adapter = MCPAdapter(session=mock_session, namespace="test")
        await adapter._refresh_tools()
        return adapter

    @pytest.mark.asyncio
    async def test_list_tools_returns_single_namespaced_tool(self, adapter) -> None:
        """list_tools() returns single Tool named after namespace."""
        tools = adapter.list_tools()

        assert len(tools) == 1
        assert isinstance(tools[0], Tool)
        assert tools[0].name == "test"

    @pytest.mark.asyncio
    async def test_list_tools_has_mcp_tools_as_callables(self, adapter) -> None:
        """MCP tools become callables on the namespaced Tool."""
        tools = adapter.list_tools()
        tool = tools[0]
        callable_names = {c.name for c in tool.callables}

        assert callable_names == {"read_file", "write_file"}

    @pytest.mark.asyncio
    async def test_list_tools_callable_has_description(self, adapter) -> None:
        """Callable descriptions are preserved from MCP."""
        tools = adapter.list_tools()
        tool = tools[0]
        read_callable = next(c for c in tool.callables if c.name == "read_file")

        assert read_callable.description == "Read contents of a file"

    @pytest.mark.asyncio
    async def test_list_tools_callable_has_parameters(self, adapter) -> None:
        """Callables have parameters from MCP input schema."""
        tools = adapter.list_tools()
        tool = tools[0]
        read_callable = next(c for c in tool.callables if c.name == "read_file")

        param_names = {p.name for p in read_callable.parameters}
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
        from py_code_mode.tools.adapters.mcp import MCPAdapter

        return MCPAdapter(session=mock_session, namespace="test")

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
        from py_code_mode.tools.adapters.mcp import MCPAdapter

        # This test verifies the factory method exists
        # Actual connection would require a real server
        assert hasattr(MCPAdapter, "connect_stdio")

    @pytest.mark.asyncio
    async def test_connect_to_sse_server(self) -> None:
        """Can connect to MCP server via SSE transport."""
        from py_code_mode.tools.adapters.mcp import MCPAdapter

        # This test verifies the factory method exists
        assert hasattr(MCPAdapter, "connect_sse")

    @pytest.mark.asyncio
    async def test_close_cleans_up(self) -> None:
        """close() cleans up resources."""
        from py_code_mode.tools.adapters.mcp import MCPAdapter

        mock_session = AsyncMock()
        adapter = MCPAdapter(session=mock_session, namespace="test")

        await adapter.close()


class TestMCPAdapterSSETransport:
    """Tests for SSE transport connection."""

    @pytest.mark.asyncio
    async def test_connect_sse_uses_sse_client(self) -> None:
        """connect_sse uses mcp.client.sse.sse_client."""
        from py_code_mode.tools.adapters.mcp import MCPAdapter

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

            await MCPAdapter.connect_sse("http://localhost:8080/sse", namespace="test")

            mock_sse_client.assert_called_once()
            mock_sse_client.assert_called_once()
            call_args = mock_sse_client.call_args
            assert call_args[0][0] == "http://localhost:8080/sse"

    @pytest.mark.asyncio
    async def test_connect_sse_passes_headers(self) -> None:
        """connect_sse forwards headers to sse_client."""
        from py_code_mode.tools.adapters.mcp import MCPAdapter

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
            await MCPAdapter.connect_sse(
                "http://localhost:8080/sse", headers=headers, namespace="test"
            )

            call_kwargs = mock_sse_client.call_args[1]
            assert call_kwargs.get("headers") == headers

    @pytest.mark.asyncio
    async def test_connect_sse_initializes_session(self) -> None:
        """connect_sse calls session.initialize()."""
        from py_code_mode.tools.adapters.mcp import MCPAdapter

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

            await MCPAdapter.connect_sse("http://localhost:8080/sse", namespace="test")

            mock_session.initialize.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_sse_method_exists(self) -> None:
        """connect_sse method exists on MCPAdapter."""
        from py_code_mode.tools.adapters.mcp import MCPAdapter

        assert hasattr(MCPAdapter, "connect_sse")
        assert callable(MCPAdapter.connect_sse)


class TestMCPAdapterNamespacing:
    """Tests for MCP tool namespacing - tools grouped under namespace like CLI tools."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock MCP ClientSession with multiple tools."""
        session = AsyncMock()
        session.list_tools = AsyncMock(
            return_value=MockListToolsResult(
                tools=[
                    MockMCPTool(
                        name="get_current_time",
                        description="Get the current time",
                        inputSchema={"type": "object", "properties": {}},
                    ),
                    MockMCPTool(
                        name="convert_timezone",
                        description="Convert time between timezones",
                        inputSchema={
                            "type": "object",
                            "properties": {
                                "time": {"type": "string"},
                                "from_tz": {"type": "string"},
                                "to_tz": {"type": "string"},
                            },
                        },
                    ),
                ]
            )
        )
        return session

    @pytest.mark.asyncio
    async def test_namespaced_adapter_returns_single_tool(self, mock_session) -> None:
        """MCPAdapter with namespace returns ONE Tool with namespace as name."""
        from py_code_mode.tools.adapters.mcp import MCPAdapter

        adapter = MCPAdapter(session=mock_session, namespace="time")
        await adapter._refresh_tools()

        tools = adapter.list_tools()

        # Should return single tool named after namespace
        assert len(tools) == 1
        assert tools[0].name == "time"

    @pytest.mark.asyncio
    async def test_namespaced_adapter_tool_has_all_mcp_tools_as_callables(
        self, mock_session
    ) -> None:
        """The single namespaced Tool has callables for each MCP tool."""
        from py_code_mode.tools.adapters.mcp import MCPAdapter

        adapter = MCPAdapter(session=mock_session, namespace="time")
        await adapter._refresh_tools()

        tools = adapter.list_tools()
        tool = tools[0]

        # Should have 2 callables (one for each MCP tool)
        assert len(tool.callables) == 2
        callable_names = {c.name for c in tool.callables}
        assert callable_names == {"get_current_time", "convert_timezone"}

    @pytest.mark.asyncio
    async def test_namespaced_adapter_callable_has_correct_params(self, mock_session) -> None:
        """Callables preserve parameter info from MCP tools."""
        from py_code_mode.tools.adapters.mcp import MCPAdapter

        adapter = MCPAdapter(session=mock_session, namespace="time")
        await adapter._refresh_tools()

        tools = adapter.list_tools()
        tool = tools[0]

        # Find convert_timezone callable
        convert_callable = next(c for c in tool.callables if c.name == "convert_timezone")
        param_names = {p.name for p in convert_callable.parameters}
        assert param_names == {"time", "from_tz", "to_tz"}

    @pytest.mark.asyncio
    async def test_namespaced_call_tool_uses_callable_name(self, mock_session) -> None:
        """call_tool with namespace uses callable_name to identify MCP tool."""
        from py_code_mode.tools.adapters.mcp import MCPAdapter

        # Setup call_tool mock
        mock_result = MagicMock()
        mock_result.content = [MagicMock(type="text", text="2025-01-02T10:00:00Z")]
        mock_result.isError = False
        mock_session.call_tool = AsyncMock(return_value=mock_result)

        adapter = MCPAdapter(session=mock_session, namespace="time")
        await adapter._refresh_tools()

        # Call using namespace tool name and MCP tool as callable_name
        await adapter.call_tool("time", "get_current_time", {})

        # Should call MCP session with the original MCP tool name
        mock_session.call_tool.assert_called_once_with("get_current_time", {})

    @pytest.mark.asyncio
    async def test_connect_stdio_with_namespace(self) -> None:
        """connect_stdio accepts namespace parameter."""
        # Verify the method signature accepts namespace
        import inspect

        from py_code_mode.tools.adapters.mcp import MCPAdapter

        sig = inspect.signature(MCPAdapter.connect_stdio)
        assert "namespace" in sig.parameters

    @pytest.mark.asyncio
    async def test_connect_sse_with_namespace(self) -> None:
        """connect_sse accepts namespace parameter."""
        # Verify the method signature accepts namespace
        import inspect

        from py_code_mode.tools.adapters.mcp import MCPAdapter

        sig = inspect.signature(MCPAdapter.connect_sse)
        assert "namespace" in sig.parameters


class TestMCPAdapterWithRegistry:
    """Tests for MCPAdapter integration with ToolRegistry."""

    @pytest.mark.asyncio
    async def test_register_with_registry(self) -> None:
        """MCPAdapter can be registered with ToolRegistry."""
        from py_code_mode.tools.adapters.mcp import MCPAdapter
        from py_code_mode.tools.registry import ToolRegistry

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

        adapter = MCPAdapter(session=mock_session, namespace="test_mcp")
        await adapter._refresh_tools()  # Populate the cache
        registry = ToolRegistry()

        registry.register_adapter(adapter)

        tools = registry.list_tools()
        # Should find the namespace tool, not individual MCP tools
        assert any(t.name == "test_mcp" for t in tools)
        assert not any(t.name == "test" for t in tools)

    @pytest.mark.asyncio
    async def test_call_through_registry(self) -> None:
        """Can call MCP tools through registry using namespace."""
        from py_code_mode.tools.adapters.mcp import MCPAdapter
        from py_code_mode.tools.registry import ToolRegistry

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

        adapter = MCPAdapter(session=mock_session, namespace="greeter")
        await adapter._refresh_tools()
        registry = ToolRegistry()
        registry.register_adapter(adapter)

        result = await registry.call_tool("greeter", "greet", {})
        assert result == "Hello!"
