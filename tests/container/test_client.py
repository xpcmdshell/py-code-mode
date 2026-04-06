"""Tests for session server HTTP client."""

import asyncio
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


def make_session_response(session_id: str = "server-session-1") -> MagicMock:
    """Create a mock session creation response."""
    return make_mock_response({"session_id": session_id})


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

        session_response = make_session_response()
        execute_response = make_mock_response(
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
        mock_http_client.post = AsyncMock(side_effect=[session_response, execute_response])
        client._client = mock_http_client

        result = await client.execute("21 * 2")

        assert mock_http_client.post.call_count == 2
        session_call = mock_http_client.post.call_args_list[0]
        assert session_call[0][0] == "http://localhost:8080/sessions"
        assert session_call[1]["json"] == {}
        assert session_call[1]["headers"] == {}

        execute_call = mock_http_client.post.call_args_list[1]
        assert execute_call[0][0] == "http://localhost:8080/execute"
        assert execute_call[1]["json"]["code"] == "21 * 2"
        assert execute_call[1]["headers"]["X-Session-ID"] == "server-session-1"

        assert result.value == 42
        assert result.error is None
        assert result.stdout == ""
        assert result.session_id == "server-session-1"
        assert client.session_id == "server-session-1"

    @pytest.mark.asyncio
    async def test_execute_with_timeout(self) -> None:
        """Execute passes timeout to server."""
        client = SessionClient()

        session_response = make_session_response()
        execute_response = make_mock_response(
            {
                "value": None,
                "stdout": "",
                "error": None,
                "execution_time_ms": 100.0,
                "session_id": "server-session-1",
            }
        )

        mock_http_client = AsyncMock()
        mock_http_client.post = AsyncMock(side_effect=[session_response, execute_response])
        client._client = mock_http_client

        await client.execute("import time; time.sleep(1)", timeout=60.0)

        call_args = mock_http_client.post.call_args_list[1]
        assert call_args[1]["json"]["timeout"] == 60.0

    @pytest.mark.asyncio
    async def test_execute_with_error(self) -> None:
        """Execute returns error from server."""
        client = SessionClient()

        session_response = make_session_response()
        execute_response = make_mock_response(
            {
                "value": None,
                "stdout": "",
                "error": "ZeroDivisionError: division by zero",
                "execution_time_ms": 1.0,
                "session_id": "server-session-1",
            }
        )

        mock_http_client = AsyncMock()
        mock_http_client.post = AsyncMock(side_effect=[session_response, execute_response])
        client._client = mock_http_client

        result = await client.execute("1/0")

        assert result.error is not None
        assert "ZeroDivisionError" in result.error
        assert client.session_id == "server-session-1"

    @pytest.mark.asyncio
    async def test_execute_reuses_server_assigned_session_id(self) -> None:
        """Second execute sends the server-issued session ID."""
        client = SessionClient()

        session_response = make_session_response()
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
        mock_http_client.post = AsyncMock(
            side_effect=[session_response, first_response, second_response]
        )
        client._client = mock_http_client

        await client.execute("x = 42")
        await client.execute("x * 2")

        second_call = mock_http_client.post.call_args_list[2]
        assert second_call[1]["headers"]["X-Session-ID"] == "server-session-1"

    @pytest.mark.asyncio
    async def test_concurrent_first_use_binds_only_one_remote_session(self) -> None:
        """Concurrent first use should not create multiple remote sessions."""
        client = SessionClient()

        session_response = make_session_response()
        execute_responses = [
            make_mock_response(
                {
                    "value": 1,
                    "stdout": "",
                    "error": None,
                    "execution_time_ms": 5.0,
                    "session_id": "server-session-1",
                }
            ),
            make_mock_response(
                {
                    "value": 2,
                    "stdout": "",
                    "error": None,
                    "execution_time_ms": 5.0,
                    "session_id": "server-session-1",
                }
            ),
        ]

        async def post_side_effect(url: str, **kwargs):
            if url.endswith("/sessions"):
                await asyncio.sleep(0)
                return session_response
            if url.endswith("/execute"):
                await asyncio.sleep(0)
                return execute_responses.pop(0)
            raise AssertionError(f"Unexpected URL {url}")

        mock_http_client = AsyncMock()
        mock_http_client.post = AsyncMock(side_effect=post_side_effect)
        client._client = mock_http_client

        results = await asyncio.gather(client.execute("1"), client.execute("2"))

        session_calls = [
            call
            for call in mock_http_client.post.call_args_list
            if call[0][0].endswith("/sessions")
        ]
        assert len(session_calls) == 1

        execute_calls = [
            call for call in mock_http_client.post.call_args_list if call[0][0].endswith("/execute")
        ]
        assert len(execute_calls) == 2
        assert all(
            call[1]["headers"]["X-Session-ID"] == "server-session-1" for call in execute_calls
        )
        assert [result.value for result in results] == [1, 2]

    @pytest.mark.asyncio
    async def test_concurrent_stale_session_rebinds_only_once(self) -> None:
        """Concurrent stale-session recovery should create only one replacement session."""
        client = SessionClient()
        client.session_id = "stale-session"
        client._workspace_id = "workspace-a"

        invalid_response = make_mock_response({"detail": "Invalid session ID"}, status_code=400)
        rebound_session = make_session_response("rebound-session")
        rebound_values = [10, 20]

        async def post_side_effect(url: str, **kwargs):
            if url.endswith("/sessions"):
                await asyncio.sleep(0)
                return rebound_session
            if url.endswith("/execute"):
                await asyncio.sleep(0)
                session_id = kwargs["headers"]["X-Session-ID"]
                if session_id == "stale-session":
                    return invalid_response
                if session_id == "rebound-session":
                    value = rebound_values.pop(0)
                    return make_mock_response(
                        {
                            "value": value,
                            "stdout": "",
                            "error": None,
                            "execution_time_ms": 5.0,
                            "session_id": "rebound-session",
                        }
                    )
            raise AssertionError(f"Unexpected call {url} {kwargs}")

        mock_http_client = AsyncMock()
        mock_http_client.post = AsyncMock(side_effect=post_side_effect)
        client._client = mock_http_client

        results = await asyncio.gather(client.execute("10"), client.execute("20"))

        session_calls = [
            call
            for call in mock_http_client.post.call_args_list
            if call[0][0].endswith("/sessions")
        ]
        assert len(session_calls) == 1

        execute_calls = [
            call for call in mock_http_client.post.call_args_list if call[0][0].endswith("/execute")
        ]
        stale_calls = [
            call for call in execute_calls if call[1]["headers"]["X-Session-ID"] == "stale-session"
        ]
        rebound_calls = [
            call
            for call in execute_calls
            if call[1]["headers"]["X-Session-ID"] == "rebound-session"
        ]
        assert len(stale_calls) == 1
        assert len(rebound_calls) == 2
        assert [result.value for result in results] == [10, 20]
        assert client.session_id == "rebound-session"

    @pytest.mark.asyncio
    async def test_init_session_waits_for_stale_rebind_before_switching_workspace(self) -> None:
        """Explicit rebinding should not redirect an in-flight retry into a new workspace."""
        client = SessionClient()
        client.session_id = "stale-session-a"
        client._workspace_id = "workspace-a"

        stale_seen = asyncio.Event()
        rebound_execute_seen = asyncio.Event()
        session_payloads: list[dict[str, str]] = []

        async def post_side_effect(url: str, **kwargs):
            if url.endswith("/execute"):
                session_id = kwargs["headers"]["X-Session-ID"]
                if session_id == "stale-session-a":
                    stale_seen.set()
                    return make_mock_response(
                        {"detail": "Invalid session ID"},
                        status_code=400,
                    )
                if session_id == "rebound-session-a":
                    rebound_execute_seen.set()
                    return make_mock_response(
                        {
                            "value": 1,
                            "stdout": "",
                            "error": None,
                            "execution_time_ms": 5.0,
                            "session_id": "rebound-session-a",
                        }
                    )
            if url.endswith("/sessions"):
                session_payloads.append(kwargs["json"])
                workspace_id = kwargs["json"].get("workspace_id")
                if workspace_id == "workspace-a":
                    return make_mock_response({"session_id": "rebound-session-a"})
                if workspace_id == "workspace-b":
                    return make_mock_response({"session_id": "session-b"})
            raise AssertionError(f"Unexpected call {url} {kwargs}")

        mock_http_client = AsyncMock()
        mock_http_client.post = AsyncMock(side_effect=post_side_effect)
        client._client = mock_http_client

        execute_task = asyncio.create_task(client.execute("1"))
        await stale_seen.wait()
        init_task = asyncio.create_task(client.init_session("workspace-b"))

        execute_result = await execute_task
        new_session_id = await init_task

        assert execute_result.value == 1
        assert execute_result.session_id == "rebound-session-a"
        assert rebound_execute_seen.is_set()
        assert new_session_id == "session-b"
        assert client.session_id == "session-b"
        assert session_payloads == [
            {"workspace_id": "workspace-a"},
            {"workspace_id": "workspace-b"},
        ]


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

        session_response = make_session_response()
        mock_response = make_mock_response(
            {
                "tools": [{"name": "cli.nmap", "description": "Network scanner"}],
                "workflows": [{"name": "scan", "description": "Port scanner"}],
                "artifacts_path": "/workspace/artifacts",
            }
        )

        mock_http_client = AsyncMock()
        mock_http_client.post = AsyncMock(return_value=session_response)
        mock_http_client.get = AsyncMock(return_value=mock_response)
        client._client = mock_http_client

        info = await client.info()

        assert len(info.tools) == 1
        assert info.tools[0]["name"] == "cli.nmap"
        assert len(info.workflows) == 1
        assert info.workflows[0]["name"] == "scan"
        call_args = mock_http_client.get.call_args
        assert call_args[1]["headers"]["X-Session-ID"] == "server-session-1"


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
