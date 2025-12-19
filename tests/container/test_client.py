"""Tests for session server HTTP client."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from py_code_mode.backends.container.client import SessionClient


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

        assert result.value == 42
        assert result.error is None
        assert result.stdout == ""

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
            }
        )

        mock_http_client = AsyncMock()
        mock_http_client.post = AsyncMock(return_value=mock_response)
        client._client = mock_http_client

        result = await client.execute("1/0")

        assert result.error is not None
        assert "ZeroDivisionError" in result.error


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
                "active_sessions": 5,
            }
        )

        mock_http_client = AsyncMock()
        mock_http_client.get = AsyncMock(return_value=mock_response)
        client._client = mock_http_client

        health = await client.health()

        assert health.status == "healthy"
        assert health.uptime_seconds == 123.4
        assert health.active_sessions == 5


class TestSessionClientInfo:
    """Tests for info method."""

    @pytest.mark.asyncio
    async def test_info_returns_tools_and_skills(self) -> None:
        """Info returns available tools and skills."""
        client = SessionClient()

        mock_response = make_mock_response(
            {
                "tools": [{"name": "cli.nmap", "description": "Network scanner"}],
                "skills": [{"name": "scan", "description": "Port scanner"}],
                "artifacts_path": "/workspace/artifacts",
            }
        )

        mock_http_client = AsyncMock()
        mock_http_client.get = AsyncMock(return_value=mock_response)
        client._client = mock_http_client

        info = await client.info()

        assert len(info.tools) == 1
        assert info.tools[0]["name"] == "cli.nmap"
        assert len(info.skills) == 1
        assert info.skills[0]["name"] == "scan"


class TestSessionClientReset:
    """Tests for reset method."""

    @pytest.mark.asyncio
    async def test_reset_clears_state(self) -> None:
        """Reset returns status."""
        client = SessionClient()

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
        assert result.session_id == client.session_id


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
