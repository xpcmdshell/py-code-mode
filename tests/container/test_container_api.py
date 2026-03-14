"""Tests for ContainerExecutor HTTP API endpoints.

Tests the /api/* endpoints for structured queries of tools, workflows, artifacts, and deps.
These endpoints allow the executor to query metadata directly via HTTP instead of
executing Python code.

Feature areas covered:
1. Tools API (list, search)
2. Workflows API (list, search, get, create, delete)
3. Artifacts API (list, load, save, delete)
4. Deps API (list, add, remove, sync)
5. Auth enforcement on all /api/* endpoints
"""

from unittest.mock import MagicMock

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
# SECTION 2: WORKFLOWS API
# =============================================================================


class TestWorkflowsAPI:
    """Tests for /api/workflows endpoints."""

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
            workflows_path=tmp_path / "workflows",
        )
        config.auth_token = "test-token"

        app = create_app(config)
        with TestClient(app) as client:
            yield client, "test-token"

    def test_list_workflows_returns_empty_when_no_workflows(self, auth_client) -> None:
        """GET /api/workflows returns empty list when no workflows registered."""
        client, token = auth_client
        response = client.get(
            "/api/workflows",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_list_workflows_requires_auth(self, auth_client) -> None:
        """GET /api/workflows requires authentication."""
        client, _ = auth_client
        response = client.get("/api/workflows")
        assert response.status_code == 401

    def test_search_workflows_returns_empty_when_no_workflows(self, auth_client) -> None:
        """GET /api/workflows/search returns empty list when no workflows registered."""
        client, token = auth_client
        response = client.get(
            "/api/workflows/search",
            params={"query": "fetch"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_search_workflows_requires_auth(self, auth_client) -> None:
        """GET /api/workflows/search requires authentication."""
        client, _ = auth_client
        response = client.get("/api/workflows/search", params={"query": "fetch"})
        assert response.status_code == 401

    def test_workflows_endpoints_return_503_if_library_not_initialized(self, tmp_path) -> None:
        """Workflows endpoints should not silently return empty results if init failed."""
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("FastAPI not installed")

        from py_code_mode.execution.container.config import SessionConfig
        from py_code_mode.execution.container.server import create_app

        # Force workflow library init failure: workflows_path exists as a FILE.
        workflows_path = tmp_path / "workflows"
        workflows_path.write_text("not a directory")

        config = SessionConfig(
            artifacts_path=tmp_path / "artifacts",
            workflows_path=workflows_path,
        )
        config.auth_token = "test-token"

        app = create_app(config)
        with TestClient(app) as client:
            headers = {"Authorization": "Bearer test-token"}

            resp = client.get("/api/workflows", headers=headers)
            assert resp.status_code == 503

            resp = client.get("/api/workflows/search", params={"query": "x"}, headers=headers)
            assert resp.status_code == 503

    def test_get_workflow_returns_none_when_not_found(self, auth_client) -> None:
        """GET /api/workflows/{name} returns null when workflow not found."""
        client, token = auth_client
        response = client.get(
            "/api/workflows/nonexistent",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data is None

    def test_get_workflow_requires_auth(self, auth_client) -> None:
        """GET /api/workflows/{name} requires authentication."""
        client, _ = auth_client
        response = client.get("/api/workflows/nonexistent")
        assert response.status_code == 401

    def test_create_workflow_success(self, auth_client) -> None:
        """POST /api/workflows creates a new workflow."""
        client, token = auth_client
        response = client.post(
            "/api/workflows",
            json={
                "name": "test_workflow",
                "source": "async def run(x: int) -> int:\n    return x * 2",
                "description": "Doubles a number",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "test_workflow"
        assert data["description"] == "Doubles a number"
        assert "source" in data

    def test_list_workflows_refreshes_after_external_create(self, auth_client, tmp_path) -> None:
        """GET /api/workflows sees workflows created after app startup."""
        from py_code_mode.workflows import FileWorkflowStore, PythonWorkflow

        client, token = auth_client
        store = FileWorkflowStore(tmp_path / "workflows")
        store.save(
            PythonWorkflow.from_source(
                name="late_added",
                source='"""Added later."""\n\nasync def run() -> str:\n    return "ok"\n',
                description="Added later",
            )
        )

        response = client.get(
            "/api/workflows",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        assert any(workflow["name"] == "late_added" for workflow in response.json())

    def test_get_workflow_refreshes_after_external_edit(self, auth_client, tmp_path) -> None:
        """GET /api/workflows/{name} reflects external edits after startup."""
        from py_code_mode.workflows import FileWorkflowStore, PythonWorkflow

        client, token = auth_client
        store = FileWorkflowStore(tmp_path / "workflows")
        store.save(
            PythonWorkflow.from_source(
                name="editable",
                source='"""First version."""\n\nasync def run() -> int:\n    return 1\n',
                description="First version",
            )
        )

        store.save(
            PythonWorkflow.from_source(
                name="editable",
                source='"""Second version."""\n\nasync def run() -> int:\n    return 2\n',
                description="Second version",
            )
        )

        response = client.get(
            "/api/workflows/editable",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        assert "return 2" in response.json()["source"]

    def test_info_refreshes_after_external_workflow_create(self, auth_client, tmp_path) -> None:
        """GET /info includes workflows created after server initialization."""
        from py_code_mode.workflows import FileWorkflowStore, PythonWorkflow

        client, token = auth_client
        store = FileWorkflowStore(tmp_path / "workflows")
        store.save(
            PythonWorkflow.from_source(
                name="visible_in_info",
                source='"""Info workflow."""\n\nasync def run() -> str:\n    return "info"\n',
                description="Info workflow",
            )
        )

        response = client.get(
            "/info",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        assert any(
            workflow["name"] == "visible_in_info" for workflow in response.json()["workflows"]
        )

    def test_create_workflow_requires_auth(self, auth_client) -> None:
        """POST /api/workflows requires authentication."""
        client, _ = auth_client
        response = client.post(
            "/api/workflows",
            json={
                "name": "test_workflow",
                "source": "async def run(): pass",
                "description": "Test",
            },
        )
        assert response.status_code == 401

    def test_create_workflow_invalid_source_returns_400(self, auth_client) -> None:
        """POST /api/workflows returns 400 for invalid source code."""
        client, token = auth_client
        response = client.post(
            "/api/workflows",
            json={
                "name": "bad_workflow",
                "source": "not valid python +++",
                "description": "Invalid",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 400

    def test_create_workflow_no_run_returns_400(self, auth_client) -> None:
        """POST /api/workflows returns 400 when source has no run() function."""
        client, token = auth_client
        response = client.post(
            "/api/workflows",
            json={
                "name": "no_run_workflow",
                "source": "def other_func(): pass",
                "description": "No run",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 400

    def test_delete_workflow_requires_auth(self, auth_client) -> None:
        """DELETE /api/workflows/{name} requires authentication."""
        client, _ = auth_client
        response = client.delete("/api/workflows/test_workflow")
        assert response.status_code == 401

    def test_delete_workflow_returns_false_when_not_found(self, auth_client) -> None:
        """DELETE /api/workflows/{name} returns false when workflow not found."""
        client, token = auth_client
        response = client.delete(
            "/api/workflows/nonexistent",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.json() is False

    def test_workflow_lifecycle_create_get_delete(self, auth_client) -> None:
        """Full workflow lifecycle: create, get, delete."""
        client, token = auth_client
        headers = {"Authorization": f"Bearer {token}"}

        # Create
        workflow_source = (
            'async def run(n: int) -> int:\n    """Square a number."""\n    return n ** 2'
        )
        response = client.post(
            "/api/workflows",
            json={
                "name": "lifecycle_workflow",
                "source": workflow_source,
                "description": "Squares a number",
            },
            headers=headers,
        )
        assert response.status_code == 200
        created = response.json()
        assert created["name"] == "lifecycle_workflow"

        # Get
        response = client.get("/api/workflows/lifecycle_workflow", headers=headers)
        assert response.status_code == 200
        fetched = response.json()
        assert fetched["name"] == "lifecycle_workflow"
        assert fetched["source"] is not None

        # Delete
        response = client.delete("/api/workflows/lifecycle_workflow", headers=headers)
        assert response.status_code == 200
        assert response.json() is True

        # Verify deleted
        response = client.get("/api/workflows/lifecycle_workflow", headers=headers)
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

    def test_list_artifacts_omits_externally_deleted_artifact(self, auth_client, tmp_path) -> None:
        """GET /api/artifacts prunes stale metadata after external file deletion."""
        client, token = auth_client
        headers = {"Authorization": f"Bearer {token}"}

        response = client.post(
            "/api/artifacts",
            json={
                "name": "stale.json",
                "data": {"key": "value"},
                "description": "Stale artifact",
            },
            headers=headers,
        )
        assert response.status_code == 200

        (tmp_path / "artifacts" / "stale.json").unlink()

        response = client.get("/api/artifacts", headers=headers)
        assert response.status_code == 200
        assert response.json() == []

    def test_load_artifact_returns_404_after_external_file_delete(
        self, auth_client, tmp_path
    ) -> None:
        """GET /api/artifacts/{name} returns 404 when a tracked file is deleted externally."""
        client, token = auth_client
        headers = {"Authorization": f"Bearer {token}"}

        response = client.post(
            "/api/artifacts",
            json={
                "name": "stale.json",
                "data": {"key": "value"},
                "description": "Stale artifact",
            },
            headers=headers,
        )
        assert response.status_code == 200

        (tmp_path / "artifacts" / "stale.json").unlink()

        response = client.get("/api/artifacts/stale.json", headers=headers)
        assert response.status_code == 404

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

    def test_remove_dep_returns_uninstall_result(self, auth_client, monkeypatch, tmp_path) -> None:
        """POST /api/deps/remove removes from config and uninstalls from the environment."""
        client, token = auth_client
        deps_dir = tmp_path / "deps"
        deps_dir.mkdir(parents=True, exist_ok=True)
        (deps_dir / "requirements.txt").write_text("colorama\n")

        monkeypatch.setattr(
            "py_code_mode.execution.container.server.subprocess.run",
            lambda *args, **kwargs: MagicMock(returncode=0, stdout="", stderr=""),
        )

        response = client.post(
            "/api/deps/remove",
            json={"package": "colorama"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        assert response.json() == {
            "removed": ["colorama"],
            "not_found": [],
            "failed": [],
            "removed_from_config": True,
        }
        assert (deps_dir / "requirements.txt").read_text() == ""

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
            # Workflows
            ("/api/workflows", "get"),
            ("/api/workflows/search?query=test", "get"),
            ("/api/workflows/test", "get"),
            ("/api/workflows", "post"),
            ("/api/workflows/test", "delete"),
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
