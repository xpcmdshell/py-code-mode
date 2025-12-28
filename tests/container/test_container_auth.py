"""TDD tests for ContainerExecutor authentication.

These tests define the expected behavior for the authentication feature.
They should FAIL initially until the implementation is complete.

Feature areas covered:
1. Auth rejection (missing/invalid/malformed tokens)
2. Auth acceptance (valid tokens)
3. Auth disabled mode (explicit opt-out)
4. Fail-closed server configuration
5. Health endpoint access
6. Sessions endpoint removal
7. Fail-safe (exception handling)
8. Integration (end-to-end flow)
"""

import secrets
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from py_code_mode.execution.container.config import ContainerConfig, SessionConfig

# =============================================================================
# SECTION 1: AUTH REJECTION (Critical Security)
# =============================================================================


class TestAuthRejectionMissingToken:
    """Tests for requests without authentication token."""

    @pytest.fixture
    def auth_enabled_client(self, tmp_path):
        """Create test client with auth ENABLED."""
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("FastAPI not installed")

        from py_code_mode.execution.container.server import create_app

        # Create config with auth token set
        config = SessionConfig(
            artifacts_path=tmp_path / "artifacts",
            # auth_token should be set to enable auth
        )
        # Set auth token on config (implementation will add this field)
        config.auth_token = "test-secret-token"

        app = create_app(config)
        with TestClient(app) as client:
            yield client

    @pytest.mark.parametrize(
        "endpoint,method,body",
        [
            ("/execute", "post", {"code": "1 + 1"}),
            ("/install_deps", "post", {"packages": ["requests"]}),
            ("/uninstall_deps", "post", {"packages": ["requests"]}),
            ("/reset", "post", None),
            ("/info", "get", None),
        ],
    )
    def test_protected_endpoint_without_token_returns_401(
        self, auth_enabled_client, endpoint: str, method: str, body: dict | None
    ) -> None:
        """Protected endpoints return 401 when no Authorization header is present."""
        if method == "post":
            response = auth_enabled_client.post(endpoint, json=body)
        else:
            response = auth_enabled_client.get(endpoint)

        assert response.status_code == 401, f"{endpoint} should require auth"
        data = response.json()
        assert "detail" in data


class TestAuthRejectionInvalidToken:
    """Tests for requests with invalid authentication tokens."""

    @pytest.fixture
    def auth_enabled_client(self, tmp_path):
        """Create test client with auth ENABLED."""
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("FastAPI not installed")

        from py_code_mode.execution.container.server import create_app

        config = SessionConfig(artifacts_path=tmp_path / "artifacts")
        config.auth_token = "correct-secret-token"

        app = create_app(config)
        with TestClient(app) as client:
            yield client

    @pytest.mark.parametrize(
        "endpoint,method,body",
        [
            ("/execute", "post", {"code": "1 + 1"}),
            ("/install_deps", "post", {"packages": ["requests"]}),
            ("/uninstall_deps", "post", {"packages": ["requests"]}),
            ("/reset", "post", None),
            ("/info", "get", None),
        ],
    )
    def test_protected_endpoint_with_wrong_token_returns_401(
        self, auth_enabled_client, endpoint: str, method: str, body: dict | None
    ) -> None:
        """Protected endpoints return 401 when token is incorrect."""
        headers = {"Authorization": "Bearer wrong-token"}

        if method == "post":
            response = auth_enabled_client.post(endpoint, json=body, headers=headers)
        else:
            response = auth_enabled_client.get(endpoint, headers=headers)

        assert response.status_code == 401, f"{endpoint} should reject wrong token"


class TestAuthRejectionMalformedHeader:
    """Tests for requests with malformed Authorization headers."""

    @pytest.fixture
    def auth_enabled_client(self, tmp_path):
        """Create test client with auth ENABLED."""
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("FastAPI not installed")

        from py_code_mode.execution.container.server import create_app

        config = SessionConfig(artifacts_path=tmp_path / "artifacts")
        config.auth_token = "correct-secret-token"

        app = create_app(config)
        with TestClient(app) as client:
            yield client

    @pytest.mark.parametrize(
        "auth_header",
        [
            "Basic dXNlcjpwYXNz",  # Wrong scheme (Basic instead of Bearer)
            "Bearer",  # Missing token after Bearer
            "Bearer ",  # Just whitespace after Bearer
            "Bearer  ",  # Multiple spaces, no token
            "bearer correct-secret-token",  # Wrong case for scheme
            "BEARER correct-secret-token",  # Wrong case for scheme
            "Bearercorrect-secret-token",  # No space after Bearer
            "",  # Empty header
            "   ",  # Whitespace only
        ],
    )
    def test_malformed_authorization_header_returns_401(
        self, auth_enabled_client, auth_header: str
    ) -> None:
        """Malformed Authorization headers are rejected with 401."""
        headers = {"Authorization": auth_header}
        response = auth_enabled_client.post("/execute", json={"code": "1 + 1"}, headers=headers)

        assert response.status_code == 401, f"Header '{auth_header}' should be rejected"


class TestAuthRejectionEmptyToken:
    """Tests for requests with empty or whitespace-only tokens."""

    @pytest.fixture
    def auth_enabled_client(self, tmp_path):
        """Create test client with auth ENABLED."""
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("FastAPI not installed")

        from py_code_mode.execution.container.server import create_app

        config = SessionConfig(artifacts_path=tmp_path / "artifacts")
        config.auth_token = "correct-secret-token"

        app = create_app(config)
        with TestClient(app) as client:
            yield client

    @pytest.mark.parametrize(
        "token",
        [
            "",
            " ",
            "  ",
            "\t",
            "\n",
            " \t\n ",
        ],
    )
    def test_empty_or_whitespace_token_returns_401(self, auth_enabled_client, token: str) -> None:
        """Empty or whitespace-only tokens are rejected."""
        headers = {"Authorization": f"Bearer {token}"}
        response = auth_enabled_client.post("/execute", json={"code": "1 + 1"}, headers=headers)

        assert response.status_code == 401


# =============================================================================
# SECTION 2: AUTH ACCEPTANCE
# =============================================================================


class TestAuthAcceptance:
    """Tests for requests with valid authentication tokens."""

    @pytest.fixture
    def auth_token(self) -> str:
        """Generate a test auth token."""
        return "test-valid-token-12345"

    @pytest.fixture
    def auth_enabled_client(self, tmp_path, auth_token):
        """Create test client with auth ENABLED."""
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("FastAPI not installed")

        from py_code_mode.execution.container.server import create_app

        config = SessionConfig(artifacts_path=tmp_path / "artifacts")
        config.auth_token = auth_token

        app = create_app(config)
        with TestClient(app) as client:
            yield client

    @pytest.mark.parametrize(
        "endpoint,method,body",
        [
            ("/execute", "post", {"code": "1 + 1"}),
            ("/install_deps", "post", {"packages": []}),  # Empty list to avoid actual install
            ("/uninstall_deps", "post", {"packages": []}),  # Empty list to avoid actual uninstall
            ("/reset", "post", None),
            ("/info", "get", None),
        ],
    )
    def test_protected_endpoint_with_valid_token_succeeds(
        self, auth_enabled_client, auth_token: str, endpoint: str, method: str, body: dict | None
    ) -> None:
        """Protected endpoints succeed with valid token."""
        headers = {"Authorization": f"Bearer {auth_token}"}

        if method == "post":
            response = auth_enabled_client.post(endpoint, json=body, headers=headers)
        else:
            response = auth_enabled_client.get(endpoint, headers=headers)

        assert response.status_code == 200, f"{endpoint} should succeed with valid token"

    def test_token_with_urlsafe_special_chars_succeeds(self, tmp_path) -> None:
        """Tokens generated by secrets.token_urlsafe work correctly."""
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("FastAPI not installed")

        from py_code_mode.execution.container.server import create_app

        # Generate token with URL-safe special characters
        special_token = secrets.token_urlsafe(32)  # Contains -, _

        config = SessionConfig(artifacts_path=tmp_path / "artifacts")
        config.auth_token = special_token

        app = create_app(config)
        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {special_token}"}
            response = client.post("/execute", json={"code": "1 + 1"}, headers=headers)

            assert response.status_code == 200


# =============================================================================
# SECTION 3: AUTH DISABLED MODE (Explicit Opt-Out)
# =============================================================================


class TestAuthDisabledMode:
    """Tests for explicitly disabled authentication."""

    @pytest.fixture
    def auth_disabled_client(self, tmp_path, monkeypatch):
        """Create test client with auth explicitly DISABLED."""
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("FastAPI not installed")

        # Set environment variable to disable auth
        monkeypatch.setenv("CONTAINER_AUTH_DISABLED", "true")

        from py_code_mode.execution.container.server import create_app

        config = SessionConfig.from_env()
        config.artifacts_path = tmp_path / "artifacts"

        app = create_app(config)
        with TestClient(app) as client:
            yield client

    def test_requests_without_token_succeed_when_auth_disabled(self, auth_disabled_client) -> None:
        """Requests without token succeed when auth is explicitly disabled."""
        response = auth_disabled_client.post("/execute", json={"code": "1 + 1"})
        assert response.status_code == 200

    def test_token_sent_to_disabled_server_is_ignored(self, auth_disabled_client) -> None:
        """Token sent to auth-disabled server is ignored (not validated)."""
        # Even an invalid token should be accepted (ignored)
        headers = {"Authorization": "Bearer some-random-token"}
        response = auth_disabled_client.post("/execute", json={"code": "1 + 1"}, headers=headers)
        assert response.status_code == 200


# =============================================================================
# SECTION 4: FAIL-CLOSED SERVER CONFIGURATION
# =============================================================================


class TestSessionConfigFailClosed:
    """Tests for SessionConfig fail-closed behavior."""

    def test_from_env_without_auth_config_raises_error(self, monkeypatch) -> None:
        """SessionConfig.from_env() raises ValueError without auth configuration.

        Server must be configured with either:
        - CONTAINER_AUTH_TOKEN (auth enabled)
        - CONTAINER_AUTH_DISABLED=true (auth explicitly disabled)

        Without either, server refuses to start (fail-closed).
        """
        # Clear both auth-related env vars
        monkeypatch.delenv("CONTAINER_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("CONTAINER_AUTH_DISABLED", raising=False)

        with pytest.raises(ValueError, match="auth"):
            SessionConfig.from_env()

    def test_from_env_with_auth_token_succeeds(self, monkeypatch) -> None:
        """SessionConfig.from_env() succeeds with CONTAINER_AUTH_TOKEN set."""
        monkeypatch.delenv("CONTAINER_AUTH_DISABLED", raising=False)
        monkeypatch.setenv("CONTAINER_AUTH_TOKEN", "my-secret-token")

        config = SessionConfig.from_env()

        assert config.auth_token == "my-secret-token"
        assert not config.auth_disabled

    def test_from_env_with_auth_disabled_succeeds(self, monkeypatch) -> None:
        """SessionConfig.from_env() succeeds with CONTAINER_AUTH_DISABLED=true."""
        monkeypatch.delenv("CONTAINER_AUTH_TOKEN", raising=False)
        monkeypatch.setenv("CONTAINER_AUTH_DISABLED", "true")

        config = SessionConfig.from_env()

        assert config.auth_disabled is True

    @pytest.mark.parametrize(
        "disabled_value",
        ["false", "no", "0", "FALSE", "No"],
    )
    def test_from_env_with_auth_disabled_false_requires_token(
        self, monkeypatch, disabled_value: str
    ) -> None:
        """CONTAINER_AUTH_DISABLED set to false/no/0 still requires token."""
        monkeypatch.delenv("CONTAINER_AUTH_TOKEN", raising=False)
        monkeypatch.setenv("CONTAINER_AUTH_DISABLED", disabled_value)

        with pytest.raises(ValueError, match="auth"):
            SessionConfig.from_env()


class TestContainerConfigClientSide:
    """Tests for ContainerConfig (client/host side configuration)."""

    def test_container_config_no_args_is_valid(self) -> None:
        """ContainerConfig() without args is valid (simple client side)."""
        config = ContainerConfig()
        assert config is not None

    def test_container_config_with_auth_token_is_valid(self) -> None:
        """ContainerConfig(auth_token='secret') is valid."""
        config = ContainerConfig(auth_token="my-secret")
        assert config.auth_token == "my-secret"

    def test_container_config_passes_auth_token_to_environment(self) -> None:
        """ContainerConfig.to_docker_config() includes CONTAINER_AUTH_TOKEN in env."""
        config = ContainerConfig(auth_token="my-secret-token")

        docker_config = config.to_docker_config()

        assert "environment" in docker_config
        assert "CONTAINER_AUTH_TOKEN" in docker_config["environment"]
        assert docker_config["environment"]["CONTAINER_AUTH_TOKEN"] == "my-secret-token"


# =============================================================================
# SECTION 5: HEALTH ENDPOINT
# =============================================================================


class TestHealthEndpointAuth:
    """Tests for health endpoint authentication behavior."""

    @pytest.fixture
    def auth_enabled_client(self, tmp_path):
        """Create test client with auth ENABLED."""
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("FastAPI not installed")

        from py_code_mode.execution.container.server import create_app

        config = SessionConfig(artifacts_path=tmp_path / "artifacts")
        config.auth_token = "secret-token"

        app = create_app(config)
        with TestClient(app) as client:
            yield client

    def test_health_endpoint_accessible_without_auth(self, auth_enabled_client) -> None:
        """Health endpoint is accessible without authentication token.

        This allows orchestration systems (Kubernetes, Docker) to check health
        without needing the auth token.
        """
        response = auth_enabled_client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_health_endpoint_does_not_expose_active_sessions(self, auth_enabled_client) -> None:
        """Health endpoint response does NOT include active_sessions count.

        Session count is information leakage - remove from unauthenticated response.
        """
        response = auth_enabled_client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert "active_sessions" not in data

    def test_health_endpoint_with_valid_token_also_works(self, auth_enabled_client) -> None:
        """Health endpoint accepts (but doesn't require) valid token."""
        headers = {"Authorization": "Bearer secret-token"}
        response = auth_enabled_client.get("/health", headers=headers)

        assert response.status_code == 200


# =============================================================================
# SECTION 6: SESSIONS ENDPOINT REMOVED
# =============================================================================


class TestSessionsEndpointRemoved:
    """Tests verifying sessions endpoint is removed (information leakage)."""

    @pytest.fixture
    def client(self, tmp_path):
        """Create test client."""
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("FastAPI not installed")

        from py_code_mode.execution.container.server import create_app

        config = SessionConfig(artifacts_path=tmp_path / "artifacts")
        config.auth_token = "secret-token"

        app = create_app(config)
        with TestClient(app) as client:
            yield client

    def test_sessions_endpoint_returns_404(self, client) -> None:
        """GET /sessions returns 404 (endpoint removed)."""
        response = client.get("/sessions")
        assert response.status_code == 404

    def test_sessions_endpoint_with_valid_auth_still_returns_404(self, client) -> None:
        """GET /sessions with valid auth still returns 404 (endpoint removed)."""
        headers = {"Authorization": "Bearer secret-token"}
        response = client.get("/sessions", headers=headers)
        assert response.status_code == 404


# =============================================================================
# SECTION 7: FAIL-SAFE (Exception Handling)
# =============================================================================


class TestAuthFailSafe:
    """Tests for fail-safe authentication error handling."""

    def test_exception_in_auth_check_returns_500_not_200(self, tmp_path) -> None:
        """If auth check raises exception, return 500 (fail-safe), not 200.

        Never allow requests through if auth verification fails due to internal error.
        """
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("FastAPI not installed")

        from py_code_mode.execution.container.server import create_app

        config = SessionConfig(artifacts_path=tmp_path / "artifacts")
        config.auth_token = "valid-token"

        app = create_app(config)

        # Patch the auth verification to raise an exception
        with TestClient(app) as client:
            # We'll need to patch the internal auth function to raise
            # The implementation will need to handle this case
            with patch(
                "py_code_mode.execution.container.server.verify_auth_token",
                side_effect=Exception("Internal error"),
            ):
                headers = {"Authorization": "Bearer valid-token"}
                response = client.post("/execute", json={"code": "1 + 1"}, headers=headers)

                # Should return 500, NOT 200 (fail-safe)
                assert response.status_code == 500

    def test_empty_string_token_on_server_does_not_disable_auth(
        self, tmp_path, monkeypatch
    ) -> None:
        """Setting CONTAINER_AUTH_TOKEN='' should not disable auth.

        Empty string token is invalid, server should refuse to start or
        reject all requests.
        """
        monkeypatch.setenv("CONTAINER_AUTH_TOKEN", "")
        monkeypatch.delenv("CONTAINER_AUTH_DISABLED", raising=False)

        # Empty token should either:
        # 1. Raise ValueError in from_env() (preferred - fail fast)
        # 2. Or server should reject all requests with that token

        with pytest.raises(ValueError, match="auth"):
            SessionConfig.from_env()


# =============================================================================
# SECTION 8: INTEGRATION TESTS
# =============================================================================


class TestAuthIntegration:
    """Integration tests for end-to-end authentication flow."""

    def test_container_config_auth_token_flows_to_container_env(self, tmp_path) -> None:
        """ContainerConfig.auth_token is passed to container via CONTAINER_AUTH_TOKEN env var."""
        config = ContainerConfig(
            auth_token="integration-test-token",
            image="py-code-mode:test",
        )

        docker_config = config.to_docker_config(
            artifacts_path=tmp_path / "artifacts",
        )

        # Verify environment variable is set
        assert docker_config["environment"]["CONTAINER_AUTH_TOKEN"] == "integration-test-token"

    @pytest.mark.asyncio
    async def test_session_client_sends_authorization_header(self) -> None:
        """SessionClient sends Authorization: Bearer header when auth_token is set."""
        from py_code_mode.execution.container.client import SessionClient

        # Create client with auth token
        client = SessionClient(
            base_url="http://localhost:8080",
            auth_token="client-auth-token",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "value": 42,
            "stdout": "",
            "error": None,
            "execution_time_ms": 1.0,
            "session_id": "test",
        }
        mock_response.raise_for_status = MagicMock()

        mock_http_client = AsyncMock()
        mock_http_client.post = AsyncMock(return_value=mock_response)
        client._client = mock_http_client

        await client.execute("1 + 1")

        # Verify Authorization header was sent
        call_args = mock_http_client.post.call_args
        headers = call_args[1].get("headers", {})
        assert "Authorization" in headers
        assert headers["Authorization"] == "Bearer client-auth-token"

        await client.close()

    @pytest.mark.asyncio
    async def test_full_flow_config_to_executor_to_server(self, tmp_path) -> None:
        """Full integration: ContainerConfig -> ContainerExecutor -> Server -> Execute.

        This test verifies the complete flow of authentication from configuration
        through execution. Uses mocks to avoid actual container startup.
        """
        from py_code_mode.execution.container.client import ExecuteResult
        from py_code_mode.execution.container.executor import ContainerExecutor

        auth_token = "full-integration-token"

        # Configure executor with auth
        config = ContainerConfig(
            image="py-code-mode:test",
            auth_token=auth_token,
        )
        executor = ContainerExecutor(config)

        # Mock Docker container
        mock_container = MagicMock()
        mock_container.id = "test-container"
        mock_container.status = "running"
        mock_container.attrs = {
            "NetworkSettings": {"Ports": {"8080/tcp": [{"HostIp": "0.0.0.0", "HostPort": "32768"}]}}
        }
        mock_container.reload = MagicMock()

        mock_docker = MagicMock()
        mock_docker.containers.run.return_value = mock_container

        mock_result = ExecuteResult(
            value=42,
            stdout="",
            error=None,
            execution_time_ms=5.0,
            session_id="test-session",
        )

        with patch("docker.from_env", return_value=mock_docker):
            with patch.object(executor, "_wait_for_healthy", new_callable=AsyncMock):
                async with executor:
                    # Verify Docker was called with auth token in environment
                    call_args = mock_docker.containers.run.call_args
                    env = call_args[1].get("environment", {})
                    assert "CONTAINER_AUTH_TOKEN" in env
                    assert env["CONTAINER_AUTH_TOKEN"] == auth_token

                    # Mock client execute for the result
                    executor._client.execute = AsyncMock(return_value=mock_result)

                    result = await executor.run("21 * 2")
                    assert result.value == 42


# =============================================================================
# SECTION 9: TIMING ATTACK RESISTANCE (Placeholder)
# =============================================================================


class TestTimingAttackResistance:
    """Tests for timing attack resistance.

    Note: These tests are placeholders. Timing attacks are notoriously difficult
    to test reliably in unit tests due to system load, scheduling, etc.

    The implementation should use `secrets.compare_digest()` for constant-time
    string comparison to prevent timing attacks on token verification.
    """

    def test_implementation_uses_constant_time_comparison(self) -> None:
        """Verify implementation uses secrets.compare_digest for token comparison.

        This is a code inspection test - we check that the right function is used
        rather than trying to measure timing (which is unreliable in tests).
        """
        # This test inspects the source code to verify correct implementation
        import inspect

        from py_code_mode.execution.container import server

        source = inspect.getsource(server)

        # The implementation should use secrets.compare_digest
        # This is the only reliable way to do constant-time comparison in Python
        assert "compare_digest" in source or "hmac.compare_digest" in source, (
            "Token comparison should use secrets.compare_digest or hmac.compare_digest "
            "for timing attack resistance"
        )
