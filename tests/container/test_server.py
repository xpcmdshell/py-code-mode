"""Tests for session server."""

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

        config = SessionConfig.from_env()

        assert config.default_timeout == 45.0
        assert config.port == 8888
        assert config.artifact_backend == "redis"
        assert config.redis_url == "redis://localhost:6379"


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
        config = SessionConfig(artifacts_path=tmp_path / "artifacts")
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
        assert "active_sessions" in data

    def test_info_endpoint(self, client) -> None:
        """Info endpoint returns tools and skills."""
        response = client.get("/info")

        assert response.status_code == 200
        data = response.json()
        assert "tools" in data
        assert "skills" in data
        assert "artifacts_path" in data

    def test_execute_simple_expression(self, client) -> None:
        """Can execute simple expression."""
        response = client.post("/execute", json={"code": "1 + 1"})

        assert response.status_code == 200
        data = response.json()
        assert data["value"] == 2
        assert data["error"] is None

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
        session_id = "test-persist-session"
        headers = {"X-Session-ID": session_id}

        # Set variable
        client.post("/execute", json={"code": "x = 42"}, headers=headers)

        # Access variable (same session)
        response = client.post("/execute", json={"code": "x * 2"}, headers=headers)

        assert response.status_code == 200
        data = response.json()
        assert data["value"] == 84
        assert data["session_id"] == session_id

    def test_reset_clears_state(self, client) -> None:
        """Reset clears session state."""
        session_id = "test-reset-session"
        headers = {"X-Session-ID": session_id}

        # Set variable
        client.post("/execute", json={"code": "x = 42"}, headers=headers)

        # Reset this session
        response = client.post("/reset", headers=headers)
        assert response.status_code == 200

        # Variable should be gone (new session created with same ID)
        response = client.post("/execute", json={"code": "x"}, headers=headers)
        data = response.json()
        assert data["error"] is not None
        assert "NameError" in data["error"]

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
