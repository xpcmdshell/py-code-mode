"""Tests for session server."""

import asyncio
from unittest.mock import MagicMock

import pytest

from py_code_mode.execution.container.config import SessionConfig


class TestSessionConfig:
    """Tests for SessionConfig loading."""

    def test_default_values(self) -> None:
        """SessionConfig has sensible defaults."""
        config = SessionConfig()

        assert config.default_timeout == 30.0
        assert config.max_execution_time == 300.0
        assert config.artifact_backend == "file"
        assert config.port == 8080

    def test_from_yaml(self, tmp_path) -> None:
        """Can load config from YAML file."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
default_timeout: 60.0
port: 9000
""")

        config = SessionConfig.from_yaml(config_file)

        assert config.default_timeout == 60.0
        assert config.port == 9000

    def test_from_env(self, monkeypatch) -> None:
        """Can load config from environment variables."""
        monkeypatch.setenv("DEFAULT_TIMEOUT", "45.0")
        monkeypatch.setenv("PORT", "8888")
        monkeypatch.setenv("ARTIFACT_BACKEND", "redis")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
        # Auth is required - set disabled for this test
        monkeypatch.setenv("CONTAINER_AUTH_DISABLED", "true")

        config = SessionConfig.from_env()

        assert config.default_timeout == 45.0
        assert config.port == 8888
        assert config.artifact_backend == "redis"
        assert config.redis_url == "redis://localhost:6379"
        assert config.auth_disabled is True


class TestSessionServer:
    """Tests for session server endpoints."""

    @pytest.fixture
    def client(self, tmp_path):
        """Create test client for session server."""
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("FastAPI not installed")

        from py_code_mode.execution.container.server import create_app

        # Use temp directory for artifacts
        # Auth disabled for these functional tests (auth tested separately)
        config = SessionConfig(artifacts_path=tmp_path / "artifacts", auth_disabled=True)
        app = create_app(config)
        # Use context manager to trigger lifespan events
        with TestClient(app) as client:
            yield client

    def test_health_endpoint(self, client) -> None:
        """Health endpoint returns status."""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "uptime_seconds" in data
        # Note: active_sessions removed for security (information disclosure)

    def test_info_endpoint(self, client) -> None:
        """Info endpoint returns tools and workflows."""
        response = client.get("/info")

        assert response.status_code == 200
        data = response.json()
        assert "tools" in data
        assert "workflows" in data
        assert "artifacts_path" in data

    def test_execute_simple_expression(self, client) -> None:
        """Can execute simple expression."""
        response = client.post("/execute", json={"code": "1 + 1"})

        assert response.status_code == 200
        data = response.json()
        assert data["value"] == 2
        assert data["error"] is None
        assert data["session_id"]

    def test_execute_with_stdout(self, client) -> None:
        """Captures stdout from print statements."""
        response = client.post("/execute", json={"code": "print('hello')"})

        assert response.status_code == 200
        data = response.json()
        assert "hello" in data["stdout"]
        assert data["error"] is None

    def test_execute_with_error(self, client) -> None:
        """Returns error for invalid code."""
        response = client.post("/execute", json={"code": "1/0"})

        assert response.status_code == 200
        data = response.json()
        assert data["error"] is not None
        assert "ZeroDivisionError" in data["error"]

    def test_execute_state_persists(self, client) -> None:
        """Variables persist across executions within same session."""
        create_response = client.post("/execute", json={"code": "x = 42"})
        session_id = create_response.json()["session_id"]
        headers = {"X-Session-ID": session_id}

        # Access variable (same session)
        response = client.post("/execute", json={"code": "x * 2"}, headers=headers)

        assert response.status_code == 200
        data = response.json()
        assert data["value"] == 84
        assert data["session_id"] == session_id

    def test_reset_clears_state(self, client) -> None:
        """Reset clears session state."""
        create_response = client.post("/execute", json={"code": "x = 42"})
        session_id = create_response.json()["session_id"]
        headers = {"X-Session-ID": session_id}

        # Reset this session
        response = client.post("/reset", headers=headers)
        assert response.status_code == 200

        # Reusing a reset session ID is invalid.
        response = client.post("/execute", json={"code": "x"}, headers=headers)
        assert response.status_code == 400

    def test_execute_with_unknown_session_id_returns_400(self, client) -> None:
        """Unknown session IDs are rejected instead of creating sessions."""
        response = client.post(
            "/execute",
            json={"code": "1 + 1"},
            headers={"X-Session-ID": "missing-session"},
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid session ID"

    def test_reset_requires_known_session_id(self, client) -> None:
        """Reset rejects missing or unknown session IDs."""
        missing_response = client.post("/reset")
        assert missing_response.status_code == 400
        assert missing_response.json()["detail"] == "Invalid session ID"

        unknown_response = client.post("/reset", headers={"X-Session-ID": "missing-session"})
        assert unknown_response.status_code == 400
        assert unknown_response.json()["detail"] == "Invalid session ID"

    def test_execute_returns_execution_time(self, client) -> None:
        """Execute response includes execution time."""
        response = client.post("/execute", json={"code": "1 + 1"})

        data = response.json()
        assert "execution_time_ms" in data
        assert data["execution_time_ms"] >= 0


class TestSessionServerWithTools:
    """Tests for session server with tools loaded from TOOLS_PATH."""

    @pytest.fixture
    def config_with_artifacts(self, tmp_path):
        """Create config for artifacts."""
        return SessionConfig(
            artifacts_path=tmp_path / "artifacts",
        )

    @pytest.fixture
    def client_with_tools(self, tmp_path, monkeypatch):
        """Create test client with tools loaded via TOOLS_PATH."""
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("FastAPI not installed")

        from py_code_mode.execution.container.server import create_app

        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        tool_yaml = tools_dir / "echo.yaml"
        tool_yaml.write_text(
            """
name: echo
description: Echo text
command: echo
schema:
  positional:
    - name: text
      type: string
      required: true
      description: Text to echo
recipes:
  say:
    description: Echo text
    params:
      text: {}
""".strip()
        )

        monkeypatch.setenv("TOOLS_PATH", str(tools_dir))

        config = SessionConfig(artifacts_path=tmp_path / "artifacts", auth_disabled=True)
        app = create_app(config)
        with TestClient(app) as client:
            yield client

    def test_info_endpoint_includes_tools(self, client_with_tools) -> None:
        """Info endpoint lists tools loaded from TOOLS_PATH."""
        response = client_with_tools.get("/info")

        assert response.status_code == 200
        data = response.json()
        assert "tools" in data
        tool_names = {tool["name"] for tool in data["tools"]}
        assert "echo" in tool_names

    def test_session_creates_artifact_store(self, config_with_artifacts) -> None:
        """Sessions have artifact store initialized."""
        import asyncio

        from py_code_mode.execution.container.server import initialize_server

        # Initialize server
        asyncio.run(initialize_server(config_with_artifacts))

        from py_code_mode.execution.container.server import create_session

        session = create_session("test-session")

        from py_code_mode.artifacts import FileArtifactStore

        # Session has a file artifact store pointing to artifacts_path
        assert isinstance(session.artifact_store, FileArtifactStore)
        assert "artifacts" in str(session.artifact_store._path)


class TestRedisDepsFallback:
    """Tests for Redis deps initialization in the container server."""

    def test_redis_deps_fallback_stays_unscoped_when_workflows_are_scoped(
        self, monkeypatch, mock_redis
    ) -> None:
        """Deps fallback should use the root prefix, not the workspace-scoped workflows prefix."""
        from py_code_mode.execution.container import server as server_module
        from py_code_mode.tools import ToolRegistry

        async def fake_registry_from_redis(_tool_store):
            return ToolRegistry()

        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        monkeypatch.setenv("REDIS_TOOLS_PREFIX", "app:tools")
        monkeypatch.setenv("REDIS_WORKFLOWS_PREFIX", "app:ws:client_a:workflows")
        monkeypatch.setenv("REDIS_ARTIFACTS_PREFIX", "app:ws:client_a:artifacts")
        monkeypatch.delenv("REDIS_DEPS_PREFIX", raising=False)

        config = SessionConfig(auth_disabled=True)

        monkeypatch.setattr("redis.from_url", lambda _url: mock_redis)
        monkeypatch.setattr(
            "py_code_mode.storage.registry_from_redis",
            fake_registry_from_redis,
        )
        monkeypatch.setattr(
            server_module,
            "create_workflow_library",
            lambda *, store: MagicMock(
                refresh=lambda: None, list=lambda: [], search=lambda *_a, **_k: []
            ),
        )

        asyncio.run(server_module.initialize_server(config))

        assert server_module._state.deps_store is not None
        server_module._state.deps_store.add("requests")

        assert "requests" in mock_redis.smembers("app:deps")
        assert mock_redis.smembers("app:ws:client_a:deps") == set()

    def test_explicit_redis_deps_prefix_takes_precedence(self, monkeypatch, mock_redis) -> None:
        """Explicit REDIS_DEPS_PREFIX should override any fallback derivation."""
        from py_code_mode.execution.container import server as server_module
        from py_code_mode.tools import ToolRegistry

        async def fake_registry_from_redis(_tool_store):
            return ToolRegistry()

        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        monkeypatch.setenv("REDIS_TOOLS_PREFIX", "app:tools")
        monkeypatch.setenv("REDIS_WORKFLOWS_PREFIX", "app:ws:client_a:workflows")
        monkeypatch.setenv("REDIS_ARTIFACTS_PREFIX", "app:ws:client_a:artifacts")
        monkeypatch.setenv("REDIS_DEPS_PREFIX", "custom-root")

        config = SessionConfig(auth_disabled=True)

        monkeypatch.setattr("redis.from_url", lambda _url: mock_redis)
        monkeypatch.setattr(
            "py_code_mode.storage.registry_from_redis",
            fake_registry_from_redis,
        )
        monkeypatch.setattr(
            server_module,
            "create_workflow_library",
            lambda *, store: MagicMock(
                refresh=lambda: None, list=lambda: [], search=lambda *_a, **_k: []
            ),
        )

        asyncio.run(server_module.initialize_server(config))

        assert server_module._state.deps_store is not None
        server_module._state.deps_store.add("requests")

        assert "requests" in mock_redis.smembers("custom-root:deps")
        assert mock_redis.smembers("app:deps") == set()
