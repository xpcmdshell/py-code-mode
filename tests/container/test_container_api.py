"""Tests for ContainerExecutor HTTP API endpoints.

Tests the /api/* endpoints for structured queries of tools, skills, artifacts, and deps.
These endpoints allow the executor to query metadata directly via HTTP instead of
executing Python code.

Feature areas covered:
1. Tools API (list, search)
2. Skills API (list, search, get, create, delete)
3. Artifacts API (list, load, save, delete)
4. Deps API (list, add, remove, sync)
5. Auth enforcement on all /api/* endpoints
"""


import pytest

# =============================================================================
# SECTION 1: TOOLS API
# =============================================================================


class TestToolsAPI:
    """Tests for /api/tools endpoints."""

    @pytest.fixture
    def auth_client(self, tmp_path):
        """Create test client with auth enabled."""
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("FastAPI not installed")

        from py_code_mode.execution.container.config import SessionConfig
        from py_code_mode.execution.container.server import create_app

        config = SessionConfig(artifacts_path=tmp_path / "artifacts")
        config.auth_token = "test-token"

        app = create_app(config)
        with TestClient(app) as client:
            yield client, "test-token"

    def test_list_tools_returns_empty_when_no_tools(self, auth_client) -> None:
        """GET /api/tools returns empty list when no tools registered."""
        client, token = auth_client
        response = client.get(
            "/api/tools",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_list_tools_requires_auth(self, auth_client) -> None:
        """GET /api/tools requires authentication."""
        client, _ = auth_client
        response = client.get("/api/tools")
        assert response.status_code == 401

    def test_search_tools_returns_empty_when_no_tools(self, auth_client) -> None:
        """GET /api/tools/search returns empty list when no tools registered."""
        client, token = auth_client
        response = client.get(
            "/api/tools/search",
            params={"query": "http"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_search_tools_requires_auth(self, auth_client) -> None:
        """GET /api/tools/search requires authentication."""
        client, _ = auth_client
        response = client.get("/api/tools/search", params={"query": "http"})
        assert response.status_code == 401


# =============================================================================
# SECTION 2: SKILLS API
# =============================================================================


class TestSkillsAPI:
    """Tests for /api/skills endpoints."""

    @pytest.fixture
    def auth_client(self, tmp_path):
        """Create test client with auth enabled."""
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("FastAPI not installed")

        from py_code_mode.execution.container.config import SessionConfig
        from py_code_mode.execution.container.server import create_app

        config = SessionConfig(
            artifacts_path=tmp_path / "artifacts",
            skills_path=tmp_path / "skills",
        )
        config.auth_token = "test-token"

        app = create_app(config)
        with TestClient(app) as client:
            yield client, "test-token"

    def test_list_skills_returns_empty_when_no_skills(self, auth_client) -> None:
        """GET /api/skills returns empty list when no skills registered."""
        client, token = auth_client
        response = client.get(
            "/api/skills",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_list_skills_requires_auth(self, auth_client) -> None:
        """GET /api/skills requires authentication."""
        client, _ = auth_client
        response = client.get("/api/skills")
        assert response.status_code == 401

    def test_search_skills_returns_empty_when_no_skills(self, auth_client) -> None:
        """GET /api/skills/search returns empty list when no skills registered."""
        client, token = auth_client
        response = client.get(
            "/api/skills/search",
            params={"query": "fetch"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_search_skills_requires_auth(self, auth_client) -> None:
        """GET /api/skills/search requires authentication."""
        client, _ = auth_client
        response = client.get("/api/skills/search", params={"query": "fetch"})
        assert response.status_code == 401

    def test_get_skill_returns_none_when_not_found(self, auth_client) -> None:
        """GET /api/skills/{name} returns null when skill not found."""
        client, token = auth_client
        response = client.get(
            "/api/skills/nonexistent",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data is None

    def test_get_skill_requires_auth(self, auth_client) -> None:
        """GET /api/skills/{name} requires authentication."""
        client, _ = auth_client
        response = client.get("/api/skills/nonexistent")
        assert response.status_code == 401

    def test_create_skill_success(self, auth_client) -> None:
        """POST /api/skills creates a new skill."""
        client, token = auth_client
        response = client.post(
            "/api/skills",
            json={
                "name": "test_skill",
                "source": "def run(x: int) -> int:\n    return x * 2",
                "description": "Doubles a number",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "test_skill"
        assert data["description"] == "Doubles a number"
        assert "source" in data

    def test_create_skill_requires_auth(self, auth_client) -> None:
        """POST /api/skills requires authentication."""
        client, _ = auth_client
        response = client.post(
            "/api/skills",
            json={
                "name": "test_skill",
                "source": "def run(): pass",
                "description": "Test",
            },
        )
        assert response.status_code == 401

    def test_create_skill_invalid_source_returns_400(self, auth_client) -> None:
        """POST /api/skills returns 400 for invalid source code."""
        client, token = auth_client
        response = client.post(
            "/api/skills",
            json={
                "name": "bad_skill",
                "source": "not valid python +++",
                "description": "Invalid",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 400

    def test_create_skill_no_run_returns_400(self, auth_client) -> None:
        """POST /api/skills returns 400 when source has no run() function."""
        client, token = auth_client
        response = client.post(
            "/api/skills",
            json={
                "name": "no_run_skill",
                "source": "def other_func(): pass",
                "description": "No run",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 400

    def test_delete_skill_requires_auth(self, auth_client) -> None:
        """DELETE /api/skills/{name} requires authentication."""
        client, _ = auth_client
        response = client.delete("/api/skills/test_skill")
        assert response.status_code == 401

    def test_delete_skill_returns_false_when_not_found(self, auth_client) -> None:
        """DELETE /api/skills/{name} returns false when skill not found."""
        client, token = auth_client
        response = client.delete(
            "/api/skills/nonexistent",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.json() is False

    def test_skill_lifecycle_create_get_delete(self, auth_client) -> None:
        """Full skill lifecycle: create, get, delete."""
        client, token = auth_client
        headers = {"Authorization": f"Bearer {token}"}

        # Create
        response = client.post(
            "/api/skills",
            json={
                "name": "lifecycle_skill",
                "source": 'def run(n: int) -> int:\n    """Square a number."""\n    return n ** 2',
                "description": "Squares a number",
            },
            headers=headers,
        )
        assert response.status_code == 200
        created = response.json()
        assert created["name"] == "lifecycle_skill"

        # Get
        response = client.get("/api/skills/lifecycle_skill", headers=headers)
        assert response.status_code == 200
        fetched = response.json()
        assert fetched["name"] == "lifecycle_skill"
        assert fetched["source"] is not None

        # Delete
        response = client.delete("/api/skills/lifecycle_skill", headers=headers)
        assert response.status_code == 200
        assert response.json() is True

        # Verify deleted
        response = client.get("/api/skills/lifecycle_skill", headers=headers)
        assert response.status_code == 200
        assert response.json() is None


# =============================================================================
# SECTION 3: ARTIFACTS API
# =============================================================================


class TestArtifactsAPI:
    """Tests for /api/artifacts endpoints."""

    @pytest.fixture
    def auth_client(self, tmp_path):
        """Create test client with auth enabled."""
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("FastAPI not installed")

        from py_code_mode.execution.container.config import SessionConfig
        from py_code_mode.execution.container.server import create_app

        config = SessionConfig(artifacts_path=tmp_path / "artifacts")
        config.auth_token = "test-token"

        app = create_app(config)
        with TestClient(app) as client:
            yield client, "test-token"

    def test_list_artifacts_returns_empty_when_no_artifacts(self, auth_client) -> None:
        """GET /api/artifacts returns empty list when no artifacts saved."""
        client, token = auth_client
        response = client.get(
            "/api/artifacts",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 0

    def test_list_artifacts_requires_auth(self, auth_client) -> None:
        """GET /api/artifacts requires authentication."""
        client, _ = auth_client
        response = client.get("/api/artifacts")
        assert response.status_code == 401

    def test_load_artifact_returns_404_when_not_found(self, auth_client) -> None:
        """GET /api/artifacts/{name} returns 404 when artifact not found."""
        client, token = auth_client
        response = client.get(
            "/api/artifacts/nonexistent",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404

    def test_load_artifact_requires_auth(self, auth_client) -> None:
        """GET /api/artifacts/{name} requires authentication."""
        client, _ = auth_client
        response = client.get("/api/artifacts/nonexistent")
        assert response.status_code == 401

    def test_save_artifact_success(self, auth_client) -> None:
        """POST /api/artifacts saves an artifact."""
        client, token = auth_client
        response = client.post(
            "/api/artifacts",
            json={
                "name": "test_artifact",
                "data": {"key": "value", "number": 42},
                "description": "Test artifact",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "test_artifact"
        assert data["description"] == "Test artifact"

    def test_save_artifact_requires_auth(self, auth_client) -> None:
        """POST /api/artifacts requires authentication."""
        client, _ = auth_client
        response = client.post(
            "/api/artifacts",
            json={"name": "test", "data": "value"},
        )
        assert response.status_code == 401

    def test_delete_artifact_requires_auth(self, auth_client) -> None:
        """DELETE /api/artifacts/{name} requires authentication."""
        client, _ = auth_client
        response = client.delete("/api/artifacts/test_artifact")
        assert response.status_code == 401

    def test_delete_artifact_returns_404_when_not_found(self, auth_client) -> None:
        """DELETE /api/artifacts/{name} returns 404 when artifact not found."""
        client, token = auth_client
        response = client.delete(
            "/api/artifacts/nonexistent",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404

    def test_artifact_lifecycle_save_load_delete(self, auth_client) -> None:
        """Full artifact lifecycle: save, load, delete."""
        client, token = auth_client
        headers = {"Authorization": f"Bearer {token}"}

        # Save
        response = client.post(
            "/api/artifacts",
            json={
                "name": "lifecycle_artifact",
                "data": {"items": [1, 2, 3]},
                "description": "Lifecycle test",
                "metadata": {"version": 1},
            },
            headers=headers,
        )
        assert response.status_code == 200
        saved = response.json()
        assert saved["name"] == "lifecycle_artifact"
        assert saved["metadata"]["version"] == 1

        # Load
        response = client.get("/api/artifacts/lifecycle_artifact", headers=headers)
        assert response.status_code == 200
        loaded = response.json()
        assert loaded == {"items": [1, 2, 3]}

        # List
        response = client.get("/api/artifacts", headers=headers)
        assert response.status_code == 200
        artifacts = response.json()
        assert len(artifacts) == 1
        assert artifacts[0]["name"] == "lifecycle_artifact"

        # Delete
        response = client.delete("/api/artifacts/lifecycle_artifact", headers=headers)
        assert response.status_code == 200

        # Verify deleted
        response = client.get("/api/artifacts/lifecycle_artifact", headers=headers)
        assert response.status_code == 404


# =============================================================================
# SECTION 4: DEPS API
# =============================================================================


class TestDepsAPI:
    """Tests for /api/deps endpoints."""

    @pytest.fixture
    def auth_client(self, tmp_path):
        """Create test client with auth enabled and runtime deps allowed."""
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("FastAPI not installed")

        from py_code_mode.execution.container.config import SessionConfig
        from py_code_mode.execution.container.server import create_app

        config = SessionConfig(
            artifacts_path=tmp_path / "artifacts",
            allow_runtime_deps=True,
        )
        config.auth_token = "test-token"

        app = create_app(config)
        with TestClient(app) as client:
            yield client, "test-token"

    @pytest.fixture
    def locked_deps_client(self, tmp_path):
        """Create test client with runtime deps DISABLED."""
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("FastAPI not installed")

        from py_code_mode.execution.container.config import SessionConfig
        from py_code_mode.execution.container.server import create_app

        config = SessionConfig(
            artifacts_path=tmp_path / "artifacts",
            allow_runtime_deps=False,
        )
        config.auth_token = "test-token"

        app = create_app(config)
        with TestClient(app) as client:
            yield client, "test-token"

    def test_list_deps_returns_empty_when_no_deps(self, auth_client) -> None:
        """GET /api/deps returns empty list when no deps configured."""
        client, token = auth_client
        response = client.get(
            "/api/deps",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_list_deps_requires_auth(self, auth_client) -> None:
        """GET /api/deps requires authentication."""
        client, _ = auth_client
        response = client.get("/api/deps")
        assert response.status_code == 401

    def test_add_dep_requires_auth(self, auth_client) -> None:
        """POST /api/deps/add requires authentication."""
        client, _ = auth_client
        response = client.post("/api/deps/add", json={"package": "requests"})
        assert response.status_code == 401

    def test_add_dep_blocked_when_runtime_deps_disabled(self, locked_deps_client) -> None:
        """POST /api/deps/add returns 403 when runtime deps disabled."""
        client, token = locked_deps_client
        response = client.post(
            "/api/deps/add",
            json={"package": "requests"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403

    def test_remove_dep_requires_auth(self, auth_client) -> None:
        """POST /api/deps/remove requires authentication."""
        client, _ = auth_client
        response = client.post("/api/deps/remove", json={"package": "requests"})
        assert response.status_code == 401

    def test_remove_dep_blocked_when_runtime_deps_disabled(self, locked_deps_client) -> None:
        """POST /api/deps/remove returns 403 when runtime deps disabled."""
        client, token = locked_deps_client
        response = client.post(
            "/api/deps/remove",
            json={"package": "requests"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403

    def test_sync_deps_requires_auth(self, auth_client) -> None:
        """POST /api/deps/sync requires authentication."""
        client, _ = auth_client
        response = client.post("/api/deps/sync")
        assert response.status_code == 401

    def test_sync_deps_allowed_when_runtime_deps_disabled(self, locked_deps_client) -> None:
        """POST /api/deps/sync is allowed even when runtime deps disabled."""
        client, token = locked_deps_client
        response = client.post(
            "/api/deps/sync",
            headers={"Authorization": f"Bearer {token}"},
        )
        # sync() is always allowed because it only installs pre-configured deps
        assert response.status_code == 200


# =============================================================================
# SECTION 5: AUTH ENFORCEMENT
# =============================================================================


class TestAPIAuthEnforcement:
    """Tests verifying auth is enforced on all /api/* endpoints."""

    @pytest.fixture
    def auth_client(self, tmp_path):
        """Create test client with auth enabled."""
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("FastAPI not installed")

        from py_code_mode.execution.container.config import SessionConfig
        from py_code_mode.execution.container.server import create_app

        config = SessionConfig(artifacts_path=tmp_path / "artifacts")
        config.auth_token = "test-token"

        app = create_app(config)
        with TestClient(app) as client:
            yield client

    @pytest.mark.parametrize(
        "endpoint,method",
        [
            # Tools
            ("/api/tools", "get"),
            ("/api/tools/search?query=test", "get"),
            # Skills
            ("/api/skills", "get"),
            ("/api/skills/search?query=test", "get"),
            ("/api/skills/test", "get"),
            ("/api/skills", "post"),
            ("/api/skills/test", "delete"),
            # Artifacts
            ("/api/artifacts", "get"),
            ("/api/artifacts/test", "get"),
            ("/api/artifacts", "post"),
            ("/api/artifacts/test", "delete"),
            # Deps
            ("/api/deps", "get"),
            ("/api/deps/add", "post"),
            ("/api/deps/remove", "post"),
            ("/api/deps/sync", "post"),
        ],
    )
    def test_all_api_endpoints_require_auth(self, auth_client, endpoint: str, method: str) -> None:
        """All /api/* endpoints return 401 without authentication."""
        if method == "get":
            response = auth_client.get(endpoint)
        elif method == "post":
            response = auth_client.post(endpoint, json={})
        elif method == "delete":
            response = auth_client.delete(endpoint)
        else:
            pytest.fail(f"Unknown method: {method}")

        assert response.status_code == 401, f"{method.upper()} {endpoint} should require auth"
