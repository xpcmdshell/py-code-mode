"""Tests for HTTP adapter - wraps REST APIs as tools."""

from unittest.mock import AsyncMock, patch

import pytest

from py_code_mode.tools import Tool
from py_code_mode.types import JsonSchema


class TestHTTPAdapterInterface:
    """Tests that define the HTTPAdapter interface."""

    def test_implements_tool_adapter_protocol(self) -> None:
        """HTTPAdapter satisfies ToolAdapter protocol."""
        from py_code_mode.tools.adapters import ToolAdapter
        from py_code_mode.tools.adapters.http import HTTPAdapter

        adapter = HTTPAdapter(base_url="http://api.example.com")
        assert isinstance(adapter, ToolAdapter)


class TestHTTPAdapterConfiguration:
    """Tests for HTTPAdapter configuration."""

    def test_accepts_base_url(self) -> None:
        """HTTPAdapter takes base_url parameter."""
        from py_code_mode.tools.adapters.http import HTTPAdapter

        adapter = HTTPAdapter(base_url="http://api.example.com")
        assert adapter.base_url == "http://api.example.com"

    def test_accepts_default_headers(self) -> None:
        """HTTPAdapter takes optional default headers."""
        from py_code_mode.tools.adapters.http import HTTPAdapter

        headers = {"Authorization": "Bearer token123"}
        adapter = HTTPAdapter(base_url="http://api.example.com", headers=headers)
        assert adapter.headers == headers

    def test_registers_endpoint(self) -> None:
        """HTTPAdapter can register API endpoints as tools."""
        from py_code_mode.tools.adapters.http import Endpoint, HTTPAdapter

        adapter = HTTPAdapter(base_url="http://api.example.com")
        adapter.add_endpoint(
            Endpoint(
                name="get_user",
                method="GET",
                path="/users/{user_id}",
                description="Get user by ID",
                parameters={"user_id": JsonSchema(type="integer", description="User ID")},
            )
        )

        assert len(adapter.endpoints) == 1


class TestEndpointDefinition:
    """Tests for Endpoint definition."""

    def test_endpoint_has_required_fields(self) -> None:
        """Endpoint has name, method, path."""
        from py_code_mode.tools.adapters.http import Endpoint

        endpoint = Endpoint(
            name="get_users", method="GET", path="/users", description="List all users"
        )

        assert endpoint.name == "get_users"
        assert endpoint.method == "GET"
        assert endpoint.path == "/users"
        assert endpoint.description == "List all users"

    def test_endpoint_has_optional_parameters(self) -> None:
        """Endpoint can define parameters schema."""
        from py_code_mode.tools.adapters.http import Endpoint

        endpoint = Endpoint(
            name="create_user",
            method="POST",
            path="/users",
            description="Create a user",
            parameters={
                "name": JsonSchema(type="string", description="User name"),
                "email": JsonSchema(type="string", description="Email address"),
            },
        )

        assert "name" in endpoint.parameters
        assert "email" in endpoint.parameters

    def test_endpoint_path_parameters(self) -> None:
        """Endpoint can have path parameters like {id}."""
        from py_code_mode.tools.adapters.http import Endpoint

        endpoint = Endpoint(
            name="get_user",
            method="GET",
            path="/users/{user_id}",
            description="Get user by ID",
            parameters={"user_id": JsonSchema(type="integer", description="User ID")},
        )

        assert "{user_id}" in endpoint.path


class TestHTTPAdapterListTools:
    """Tests for listing tools from HTTP endpoints."""

    @pytest.mark.asyncio
    async def test_list_tools_returns_tool_objects(self) -> None:
        """list_tools() returns Tool objects for each endpoint."""
        from py_code_mode.tools.adapters.http import Endpoint, HTTPAdapter

        adapter = HTTPAdapter(base_url="http://api.example.com")
        adapter.add_endpoint(
            Endpoint(name="get_users", method="GET", path="/users", description="List users")
        )
        adapter.add_endpoint(
            Endpoint(name="create_user", method="POST", path="/users", description="Create user")
        )

        tools = adapter.list_tools()

        assert len(tools) == 2
        assert all(isinstance(t, Tool) for t in tools)

    @pytest.mark.asyncio
    async def test_list_tools_maps_names(self) -> None:
        """Tool names come from endpoint names."""
        from py_code_mode.tools.adapters.http import Endpoint, HTTPAdapter

        adapter = HTTPAdapter(base_url="http://api.example.com")
        adapter.add_endpoint(
            Endpoint(name="get_user", method="GET", path="/users/{id}", description="Get user")
        )

        tools = adapter.list_tools()
        assert tools[0].name == "get_user"

    @pytest.mark.asyncio
    async def test_list_tools_maps_descriptions(self) -> None:
        """Tool descriptions come from endpoints."""
        from py_code_mode.tools.adapters.http import Endpoint, HTTPAdapter

        adapter = HTTPAdapter(base_url="http://api.example.com")
        adapter.add_endpoint(
            Endpoint(
                name="list_users",
                method="GET",
                path="/users",
                description="List all users in the system",
            )
        )

        tools = adapter.list_tools()
        assert tools[0].description == "List all users in the system"


class TestHTTPAdapterCallTool:
    """Tests for calling HTTP endpoints as tools."""

    @pytest.fixture
    def adapter(self):
        """Create adapter with test endpoints."""
        from py_code_mode.tools.adapters.http import Endpoint, HTTPAdapter

        adapter = HTTPAdapter(base_url="http://api.example.com")
        adapter.add_endpoint(
            Endpoint(
                name="get_user",
                method="GET",
                path="/users/{user_id}",
                description="Get user by ID",
                parameters={"user_id": JsonSchema(type="integer", description="User ID")},
            )
        )
        adapter.add_endpoint(
            Endpoint(
                name="create_user",
                method="POST",
                path="/users",
                description="Create a user",
                parameters={
                    "name": JsonSchema(type="string", description="Name"),
                    "email": JsonSchema(type="string", description="Email"),
                },
            )
        )
        return adapter

    @pytest.mark.asyncio
    async def test_call_tool_makes_get_request(self, adapter) -> None:
        """call_tool makes GET request with path parameters."""
        with patch("aiohttp.ClientSession") as mock_client_session:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value={"id": 42, "name": "Alice"})
            mock_response.text = AsyncMock(return_value='{"id": 42, "name": "Alice"}')

            mock_session = AsyncMock()
            mock_session.request = AsyncMock(return_value=mock_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)

            mock_client_session.return_value = mock_session

            await adapter.call_tool("get_user", None, {"user_id": 42})

            mock_session.request.assert_called_once()
            call_args = mock_session.request.call_args
            assert call_args[0][0] == "GET"
            assert "/users/42" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_call_tool_makes_post_request(self, adapter) -> None:
        """call_tool makes POST request with body."""
        with patch("aiohttp.ClientSession") as mock_client_session:
            mock_response = AsyncMock()
            mock_response.status = 201
            mock_response.json = AsyncMock(return_value={"id": 1, "name": "Bob"})

            mock_session = AsyncMock()
            mock_session.request = AsyncMock(return_value=mock_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)

            mock_client_session.return_value = mock_session

            await adapter.call_tool(
                "create_user", None, {"name": "Bob", "email": "bob@example.com"}
            )

            mock_session.request.assert_called_once()
            call_args = mock_session.request.call_args
            assert call_args[0][0] == "POST"
            assert call_args[1].get("json") == {"name": "Bob", "email": "bob@example.com"}

    @pytest.mark.asyncio
    async def test_call_tool_returns_json(self, adapter) -> None:
        """call_tool returns parsed JSON response."""
        with patch("aiohttp.ClientSession") as mock_client_session:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value={"id": 42, "name": "Alice"})

            mock_session = AsyncMock()
            mock_session.request = AsyncMock(return_value=mock_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)

            mock_client_session.return_value = mock_session

            result = await adapter.call_tool("get_user", None, {"user_id": 42})

            assert result == {"id": 42, "name": "Alice"}

    @pytest.mark.asyncio
    async def test_call_tool_not_found(self, adapter) -> None:
        """call_tool raises ToolNotFoundError for unknown endpoint."""
        from py_code_mode.errors import ToolNotFoundError

        with pytest.raises(ToolNotFoundError):
            await adapter.call_tool("nonexistent", None, {})

    @pytest.mark.asyncio
    async def test_call_tool_handles_http_error(self, adapter) -> None:
        """call_tool raises ToolCallError for HTTP errors."""
        from py_code_mode.errors import ToolCallError

        with patch("aiohttp.ClientSession") as mock_client_session:
            mock_response = AsyncMock()
            mock_response.status = 500
            mock_response.text = AsyncMock(return_value="Internal Server Error")

            mock_session = AsyncMock()
            mock_session.request = AsyncMock(return_value=mock_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)

            mock_client_session.return_value = mock_session

            with pytest.raises(ToolCallError):
                await adapter.call_tool("get_user", None, {"user_id": 42})


class TestHTTPAdapterWithRegistry:
    """Tests for HTTPAdapter integration with ToolRegistry."""

    @pytest.mark.asyncio
    async def test_register_with_registry(self) -> None:
        """HTTPAdapter can be registered with ToolRegistry."""
        from py_code_mode.tools.adapters.http import Endpoint, HTTPAdapter
        from py_code_mode.tools.registry import ToolRegistry

        adapter = HTTPAdapter(base_url="http://api.example.com")
        adapter.add_endpoint(
            Endpoint(name="get_status", method="GET", path="/status", description="Get API status")
        )

        registry = ToolRegistry()
        registry.register_adapter(adapter)

        tools = registry.list_tools()
        assert any(t.name == "get_status" for t in tools)
