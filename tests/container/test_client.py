"""Tests for session server HTTP client."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from py_code_mode.execution.container.client import SessionClient


def make_mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    """Create a mock httpx Response."""
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.json.return_value = json_data  # json() is synchronous in httpx
    mock_response.raise_for_status = MagicMock()
    return mock_response


class TestSessionClient:
    """Tests for SessionClient."""

    def test_default_base_url(self) -> None:
        """SessionClient has default localhost URL."""
        client = SessionClient()
        assert client.base_url == "http://localhost:8080"

    def test_custom_base_url(self) -> None:
        """Can set custom base URL."""
        client = SessionClient(base_url="http://container:9000")
        assert client.base_url == "http://container:9000"

    def test_strips_trailing_slash(self) -> None:
        """Strips trailing slash from base URL."""
        client = SessionClient(base_url="http://localhost:8080/")
        assert client.base_url == "http://localhost:8080"
        assert client.session_id is None


class TestSessionClientExecute:
    """Tests for execute method."""

    @pytest.mark.asyncio
    async def test_execute_simple_code(self) -> None:
        """Execute returns result from server."""
        client = SessionClient()

        mock_response = make_mock_response(
            {
                "value": 42,
                "stdout": "",
                "error": None,
                "execution_time_ms": 5.0,
                "session_id": "server-session-1",
            }
        )

        # Mock the internal client's post method
        mock_http_client = AsyncMock()
        mock_http_client.post = AsyncMock(return_value=mock_response)
        client._client = mock_http_client

        result = await client.execute("21 * 2")

        mock_http_client.post.assert_called_once()
        call_args = mock_http_client.post.call_args
        assert call_args[0][0] == "http://localhost:8080/execute"
        assert call_args[1]["json"]["code"] == "21 * 2"
        assert call_args[1]["headers"] == {}

        assert result.value == 42
        assert result.error is None
        assert result.stdout == ""
        assert result.session_id == "server-session-1"
        assert client.session_id == "server-session-1"

    @pytest.mark.asyncio
    async def test_execute_with_timeout(self) -> None:
        """Execute passes timeout to server."""
        client = SessionClient()

        mock_response = make_mock_response(
            {
                "value": None,
                "stdout": "",
                "error": None,
                "execution_time_ms": 100.0,
                "session_id": "server-session-1",
            }
        )

        mock_http_client = AsyncMock()
        mock_http_client.post = AsyncMock(return_value=mock_response)
        client._client = mock_http_client

        await client.execute("import time; time.sleep(1)", timeout=60.0)

        call_args = mock_http_client.post.call_args
        assert call_args[1]["json"]["timeout"] == 60.0

    @pytest.mark.asyncio
    async def test_execute_with_error(self) -> None:
        """Execute returns error from server."""
        client = SessionClient()

        mock_response = make_mock_response(
            {
                "value": None,
                "stdout": "",
                "error": "ZeroDivisionError: division by zero",
                "execution_time_ms": 1.0,
                "session_id": "server-session-1",
            }
        )

        mock_http_client = AsyncMock()
        mock_http_client.post = AsyncMock(return_value=mock_response)
        client._client = mock_http_client

        result = await client.execute("1/0")

        assert result.error is not None
        assert "ZeroDivisionError" in result.error
        assert client.session_id == "server-session-1"

    @pytest.mark.asyncio
    async def test_execute_reuses_server_assigned_session_id(self) -> None:
        """Second execute sends the server-issued session ID."""
        client = SessionClient()

        first_response = make_mock_response(
            {
                "value": 42,
                "stdout": "",
                "error": None,
                "execution_time_ms": 5.0,
                "session_id": "server-session-1",
            }
        )
        second_response = make_mock_response(
            {
                "value": 84,
                "stdout": "",
                "error": None,
                "execution_time_ms": 5.0,
                "session_id": "server-session-1",
            }
        )

        mock_http_client = AsyncMock()
        mock_http_client.post = AsyncMock(side_effect=[first_response, second_response])
        client._client = mock_http_client

        await client.execute("x = 42")
        await client.execute("x * 2")

        second_call = mock_http_client.post.call_args_list[1]
        assert second_call[1]["headers"]["X-Session-ID"] == "server-session-1"


class TestSessionClientHealth:
    """Tests for health check method."""

    @pytest.mark.asyncio
    async def test_health_returns_status(self) -> None:
        """Health check returns server status."""
        client = SessionClient()

        mock_response = make_mock_response(
            {
                "status": "healthy",
                "uptime_seconds": 123.4,
            }
        )

        mock_http_client = AsyncMock()
        mock_http_client.get = AsyncMock(return_value=mock_response)
        client._client = mock_http_client

        health = await client.health()

        assert health.status == "healthy"
        assert health.uptime_seconds == 123.4


class TestSessionClientInfo:
    """Tests for info method."""

    @pytest.mark.asyncio
    async def test_info_returns_tools_and_workflows(self) -> None:
        """Info returns available tools and workflows."""
        client = SessionClient()

        mock_response = make_mock_response(
            {
                "tools": [{"name": "cli.nmap", "description": "Network scanner"}],
                "workflows": [{"name": "scan", "description": "Port scanner"}],
                "artifacts_path": "/workspace/artifacts",
            }
        )

        mock_http_client = AsyncMock()
        mock_http_client.get = AsyncMock(return_value=mock_response)
        client._client = mock_http_client

        info = await client.info()

        assert len(info.tools) == 1
        assert info.tools[0]["name"] == "cli.nmap"
        assert len(info.workflows) == 1
        assert info.workflows[0]["name"] == "scan"
        call_args = mock_http_client.get.call_args
        assert call_args[1]["headers"] == {}


class TestSessionClientReset:
    """Tests for reset method."""

    @pytest.mark.asyncio
    async def test_reset_clears_state(self) -> None:
        """Reset returns status."""
        client = SessionClient()
        client.session_id = "server-session-1"

        mock_response = make_mock_response(
            {
                "status": "reset",
                "session_id": client.session_id,
            }
        )

        mock_http_client = AsyncMock()
        mock_http_client.post = AsyncMock(return_value=mock_response)
        client._client = mock_http_client

        result = await client.reset()

        assert result.status == "reset"
        assert result.session_id == "server-session-1"
        assert client.session_id is None

    @pytest.mark.asyncio
    async def test_reset_without_session_is_local_noop(self) -> None:
        """Reset without a server-issued session does not make a request."""
        client = SessionClient()
        mock_http_client = AsyncMock()
        client._client = mock_http_client

        result = await client.reset()

        assert result.status == "reset"
        assert result.session_id is None
        mock_http_client.post.assert_not_called()


class TestSessionClientDeps:
    """Tests for dependency-related HTTP behavior."""

    @pytest.mark.asyncio
    async def test_install_deps_raises_http_status_error(self) -> None:
        """install_deps propagates HTTP auth failures via raise_for_status()."""
        client = SessionClient(auth_token="wrong-token")
        request = httpx.Request("POST", "http://localhost:8080/install_deps")
        response = httpx.Response(401, request=request, json={"detail": "Invalid token"})
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "401 Unauthorized", request=request, response=response
        )

        mock_http_client = AsyncMock()
        mock_http_client.post = AsyncMock(return_value=mock_response)
        client._client = mock_http_client

        with pytest.raises(httpx.HTTPStatusError):
            await client.install_deps(["requests"])

    @pytest.mark.asyncio
    async def test_api_add_dep_raises_http_status_error(self) -> None:
        """api_add_dep propagates HTTP auth failures via raise_for_status()."""
        client = SessionClient(auth_token="wrong-token")
        request = httpx.Request("POST", "http://localhost:8080/api/deps/add")
        response = httpx.Response(401, request=request, json={"detail": "Invalid token"})
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "401 Unauthorized", request=request, response=response
        )

        mock_http_client = AsyncMock()
        mock_http_client.post = AsyncMock(return_value=mock_response)
        client._client = mock_http_client

        with pytest.raises(httpx.HTTPStatusError):
            await client.api_add_dep("requests")


class TestSessionClientContextManager:
    """Tests for async context manager."""

    @pytest.mark.asyncio
    async def test_context_manager(self) -> None:
        """Can use as async context manager."""
        async with SessionClient() as client:
            assert client is not None

    @pytest.mark.asyncio
    async def test_close_method(self) -> None:
        """Close method closes HTTP client."""
        client = SessionClient()

        # Mock the internal httpx client
        mock_http_client = MagicMock()
        mock_http_client.aclose = AsyncMock()
        client._client = mock_http_client

        await client.close()
        mock_http_client.aclose.assert_called_once()
