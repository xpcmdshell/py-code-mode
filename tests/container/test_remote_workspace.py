"""Real-behavior tests for remote workspace scoping in the session server."""

import asyncio
import os

import pytest
import redis
import uvicorn

import docker
from py_code_mode.execution.container import ContainerConfig, ContainerExecutor
from py_code_mode.execution.container.config import SessionConfig
from py_code_mode.session import Session
from py_code_mode.storage import FileStorage, RedisStorage
from tests.docker_diagnostics import did_test_fail, emit_testcontainer_logs

REMOTE_REDIS_STORAGE_PREFIX = "remote_workspace_journey"


def auth_headers(token: str, session_id: str | None = None) -> dict[str, str]:
    """Build auth headers for container API requests."""
    headers = {"Authorization": f"Bearer {token}"}
    if session_id is not None:
        headers["X-Session-ID"] = session_id
    return headers


def create_scoped_session(client, token: str, workspace_id: str | None = None) -> str:
    """Create a server session optionally bound to a workspace."""
    payload = {} if workspace_id is None else {"workspace_id": workspace_id}
    response = client.post("/sessions", json=payload, headers=auth_headers(token))
    assert response.status_code == 200
    data = response.json()
    assert data["session_id"]
    return data["session_id"]


def _docker_daemon_is_available() -> bool:
    """Check whether Docker is available for real Redis container tests."""
    try:
        client = docker.from_env()
        client.ping()
    except Exception:
        return False
    return True


class TestRemoteWorkspaceSessions:
    """Tests for workspace-aware remote session behavior."""

    @pytest.fixture
    def auth_client(self, tmp_path):
        """Create authenticated client with real workflow and artifact storage."""
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("FastAPI not installed")

        from py_code_mode.execution.container.server import create_app

        config = SessionConfig(
            artifacts_path=tmp_path / "artifacts",
            workflows_path=tmp_path / "workflows",
        )
        config.auth_token = "test-token"

        app = create_app(config)
        with TestClient(app) as client:
            yield client, "test-token"

    def test_create_session_accepts_workspace_id(self, auth_client) -> None:
        """POST /sessions should allow explicit workspace binding."""
        client, token = auth_client

        response = client.post(
            "/sessions",
            json={"workspace_id": "client_a"},
            headers=auth_headers(token),
        )

        assert response.status_code == 200
        assert response.json()["session_id"]

    def test_create_session_rejects_invalid_workspace_id(self, auth_client) -> None:
        """POST /sessions should reject invalid workspace IDs."""
        client, token = auth_client

        response = client.post(
            "/sessions",
            json={"workspace_id": "../escape"},
            headers=auth_headers(token),
        )

        assert response.status_code == 400

    def test_same_workspace_sessions_share_workflows(self, auth_client) -> None:
        """Sessions in the same workspace should see the same workflows."""
        client, token = auth_client
        session_a = create_scoped_session(client, token, "client_a")
        session_b = create_scoped_session(client, token, "client_a")

        response = client.post(
            "/api/workflows",
            json={
                "name": "shared_workflow",
                "source": 'async def run() -> str:\n    return "ok"\n',
                "description": "Shared workflow",
            },
            headers=auth_headers(token, session_a),
        )
        assert response.status_code == 200

        response = client.get(
            "/api/workflows",
            headers=auth_headers(token, session_b),
        )
        assert response.status_code == 200
        assert any(workflow["name"] == "shared_workflow" for workflow in response.json())

    def test_different_workspace_sessions_isolate_workflows(self, auth_client) -> None:
        """Sessions in different workspaces should not share workflows."""
        client, token = auth_client
        session_a = create_scoped_session(client, token, "client_a")
        session_b = create_scoped_session(client, token, "client_b")

        response = client.post(
            "/api/workflows",
            json={
                "name": "isolated_workflow",
                "source": 'async def run() -> str:\n    return "ok"\n',
                "description": "Workspace A only",
            },
            headers=auth_headers(token, session_a),
        )
        assert response.status_code == 200

        response = client.get(
            "/api/workflows",
            headers=auth_headers(token, session_b),
        )
        assert response.status_code == 200
        assert all(workflow["name"] != "isolated_workflow" for workflow in response.json())

    def test_different_workspace_sessions_isolate_workflow_search(self, auth_client) -> None:
        """Workflow search should respect workspace boundaries."""
        client, token = auth_client
        session_a = create_scoped_session(client, token, "client_a")
        session_b = create_scoped_session(client, token, "client_b")

        response = client.post(
            "/api/workflows",
            json={
                "name": "summarize_notes",
                "source": 'async def run() -> str:\n    return "ok"\n',
                "description": "Summarize notes",
            },
            headers=auth_headers(token, session_a),
        )
        assert response.status_code == 200

        response = client.get(
            "/api/workflows/search",
            params={"query": "summarize"},
            headers=auth_headers(token, session_b),
        )
        assert response.status_code == 200
        assert response.json() == []

    def test_different_workspace_sessions_isolate_artifacts(self, auth_client) -> None:
        """Sessions in different workspaces should not share artifacts."""
        client, token = auth_client
        session_a = create_scoped_session(client, token, "client_a")
        session_b = create_scoped_session(client, token, "client_b")

        response = client.post(
            "/api/artifacts",
            json={
                "name": "notes.json",
                "data": {"owner": "workspace-a"},
                "description": "Workspace artifact",
            },
            headers=auth_headers(token, session_a),
        )
        assert response.status_code == 200

        response = client.get(
            "/api/artifacts",
            headers=auth_headers(token, session_b),
        )
        assert response.status_code == 200
        assert response.json() == []

    def test_info_uses_bound_session_workspace(self, auth_client) -> None:
        """GET /info should return workflows from the bound session's workspace."""
        client, token = auth_client
        session_a = create_scoped_session(client, token, "client_a")
        session_b = create_scoped_session(client, token, "client_b")

        response = client.post(
            "/api/workflows",
            json={
                "name": "workspace_a_only",
                "source": 'async def run() -> str:\n    return "ok"\n',
                "description": "Visible only to workspace A",
            },
            headers=auth_headers(token, session_a),
        )
        assert response.status_code == 200

        response = client.get("/info", headers=auth_headers(token, session_b))
        assert response.status_code == 200
        assert all(
            workflow["name"] != "workspace_a_only" for workflow in response.json()["workflows"]
        )

    def test_unknown_session_is_rejected_by_session_aware_api(self, auth_client) -> None:
        """Session-aware workflow APIs should reject unknown session IDs."""
        client, token = auth_client

        response = client.get(
            "/api/workflows",
            headers=auth_headers(token, "missing-session"),
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid session ID"

    def test_requests_without_session_header_use_legacy_default_namespace(
        self, auth_client
    ) -> None:
        """Requests without X-Session-ID should still use the legacy shared namespace."""
        client, token = auth_client

        response = client.post(
            "/api/workflows",
            json={
                "name": "legacy_workflow",
                "source": 'async def run() -> str:\n    return "ok"\n',
                "description": "Legacy workflow",
            },
            headers=auth_headers(token),
        )
        assert response.status_code == 200

        response = client.get("/api/workflows", headers=auth_headers(token))
        assert response.status_code == 200
        assert any(workflow["name"] == "legacy_workflow" for workflow in response.json())


@pytest.fixture
async def live_session_server_url(tmp_path, unused_tcp_port: int) -> str:
    """Start a real session server over HTTP and return its base URL."""
    from py_code_mode.execution.container.server import create_app

    config = SessionConfig(
        artifacts_path=tmp_path / "server-artifacts",
        workflows_path=tmp_path / "server-workflows",
        auth_disabled=True,
    )
    app = create_app(config)
    server_config = uvicorn.Config(app, host="127.0.0.1", port=unused_tcp_port, log_level="warning")
    server = uvicorn.Server(server_config)

    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.1)

    try:
        yield f"http://127.0.0.1:{unused_tcp_port}"
    finally:
        server.should_exit = True
        await task


@pytest.fixture
async def live_redis_session_server_url(
    remote_workspace_redis_url: str, unused_tcp_port: int
) -> str:
    """Start a real Redis-backed session server over HTTP and return its base URL."""
    from py_code_mode.execution.container.server import create_app

    config = SessionConfig(
        redis_url=remote_workspace_redis_url,
        storage_prefix=REMOTE_REDIS_STORAGE_PREFIX,
        auth_disabled=True,
    )
    app = create_app(config)
    server_config = uvicorn.Config(app, host="127.0.0.1", port=unused_tcp_port, log_level="warning")
    server = uvicorn.Server(server_config)

    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.1)

    try:
        yield f"http://127.0.0.1:{unused_tcp_port}"
    finally:
        server.should_exit = True
        await task


@pytest.fixture
def remote_workspace_redis_container(request: pytest.FixtureRequest):
    """Start a dedicated Redis container without triggering container image rebuild hooks."""
    pytest.importorskip("testcontainers.redis")
    from testcontainers.redis import RedisContainer

    if not _docker_daemon_is_available():
        if os.environ.get("CI"):
            pytest.fail("Docker daemon not available for remote Redis workspace journey tests")
        pytest.skip("Docker daemon not available for remote Redis workspace journey tests")

    container = RedisContainer(image="redis:7-alpine")
    container.start()
    try:
        yield container
    finally:
        if did_test_fail(request.node):
            emit_testcontainer_logs(
                container,
                source=f"testcontainers.RedisContainer ({request.node.nodeid})",
            )
        container.stop()


@pytest.fixture
def remote_workspace_redis_url(remote_workspace_redis_container) -> str:
    """Return a Redis URL for the dedicated workspace journey container."""
    host = remote_workspace_redis_container.get_container_host_ip()
    port = remote_workspace_redis_container.get_exposed_port(6379)
    return f"redis://{host}:{port}"


def create_remote_redis_session(
    redis_url: str,
    remote_url: str,
    workspace_id: str | None = None,
) -> Session:
    """Create a developer-style Session using RedisStorage and a remote container executor."""
    storage = RedisStorage(
        redis=redis.from_url(redis_url),
        prefix=REMOTE_REDIS_STORAGE_PREFIX,
        workspace_id=workspace_id,
    )
    executor = ContainerExecutor(
        ContainerConfig(
            remote_url=remote_url,
            timeout=30.0,
            auth_disabled=True,
        )
    )
    return Session(storage=storage, executor=executor)


class TestRemoteWorkspaceSessionE2E:
    """End-to-end tests through Session() against a live session server."""

    @pytest.mark.asyncio
    async def test_sessions_in_same_workspace_share_remote_state(
        self, tmp_path, live_session_server_url: str
    ) -> None:
        """Two Session() objects in the same workspace should share remote workflows/artifacts."""
        session_a = Session(
            storage=FileStorage(tmp_path / "client-storage-a", workspace_id="client_a"),
            executor=ContainerExecutor(
                ContainerConfig(
                    remote_url=live_session_server_url,
                    timeout=30.0,
                    auth_disabled=True,
                )
            ),
        )
        session_b = Session(
            storage=FileStorage(tmp_path / "client-storage-b", workspace_id="client_a"),
            executor=ContainerExecutor(
                ContainerConfig(
                    remote_url=live_session_server_url,
                    timeout=30.0,
                    auth_disabled=True,
                )
            ),
        )

        async with session_a, session_b:
            result = await session_a.run(
                "\n".join(
                    [
                        "workflows.create(",
                        "    'shared_remote',",
                        "    'async def run() -> str:\\n    return \"ok\"\\n',",
                        "    'Shared remote workflow',",
                        ")",
                        "artifacts.save('shared_remote.json', {'value': 1}, description='')",
                    ]
                )
            )
            assert result.error is None

            result = await session_b.run(
                "[workflows.get('shared_remote') is not None, "
                "artifacts.load('shared_remote.json')['value']]"
            )
            assert result.error is None
            assert result.value == [True, 1]

    @pytest.mark.asyncio
    async def test_sessions_in_different_workspaces_are_isolated(
        self, tmp_path, live_session_server_url: str
    ) -> None:
        """Two Session() objects in different workspaces should not share remote state."""
        session_a = Session(
            storage=FileStorage(tmp_path / "client-storage-a", workspace_id="client_a"),
            executor=ContainerExecutor(
                ContainerConfig(
                    remote_url=live_session_server_url,
                    timeout=30.0,
                    auth_disabled=True,
                )
            ),
        )
        session_b = Session(
            storage=FileStorage(tmp_path / "client-storage-b", workspace_id="client_b"),
            executor=ContainerExecutor(
                ContainerConfig(
                    remote_url=live_session_server_url,
                    timeout=30.0,
                    auth_disabled=True,
                )
            ),
        )

        async with session_a, session_b:
            result = await session_a.run(
                "\n".join(
                    [
                        "workflows.create(",
                        "    'isolated_remote',",
                        "    'async def run() -> str:\\n    return \"ok\"\\n',",
                        "    'Workspace A workflow',",
                        ")",
                        "artifacts.save('isolated_remote.json', {'value': 1}, description='')",
                    ]
                )
            )
            assert result.error is None

            workflow_result = await session_b.run("workflows.get('isolated_remote')")
            assert workflow_result.error is None
            assert workflow_result.value is None

            artifact_result = await session_b.run("artifacts.exists('isolated_remote.json')")
            assert artifact_result.error is None
            assert artifact_result.value is False

    @pytest.mark.asyncio
    async def test_sessions_without_workspace_id_use_shared_legacy_namespace(
        self, tmp_path, live_session_server_url: str
    ) -> None:
        """Omitting workspace_id should keep the legacy shared namespace behavior."""
        session_a = Session(
            storage=FileStorage(tmp_path / "client-storage-a"),
            executor=ContainerExecutor(
                ContainerConfig(
                    remote_url=live_session_server_url,
                    timeout=30.0,
                    auth_disabled=True,
                )
            ),
        )
        session_b = Session(
            storage=FileStorage(tmp_path / "client-storage-b"),
            executor=ContainerExecutor(
                ContainerConfig(
                    remote_url=live_session_server_url,
                    timeout=30.0,
                    auth_disabled=True,
                )
            ),
        )

        async with session_a, session_b:
            result = await session_a.run(
                "\n".join(
                    [
                        "workflows.create(",
                        "    'legacy_remote',",
                        "    'async def run() -> str:\\n    return \"ok\"\\n',",
                        "    'Legacy workflow',",
                        ")",
                    ]
                )
            )
            assert result.error is None

            result = await session_b.run("workflows.get('legacy_remote') is not None")
            assert result.error is None
            assert result.value is True

    @pytest.mark.asyncio
    async def test_workflow_search_is_isolated_across_session_workspaces(
        self, tmp_path, live_session_server_url: str
    ) -> None:
        """Agent-facing workflow search should respect workspace boundaries end-to-end."""
        session_a = Session(
            storage=FileStorage(tmp_path / "client-storage-a", workspace_id="client_a"),
            executor=ContainerExecutor(
                ContainerConfig(
                    remote_url=live_session_server_url,
                    timeout=30.0,
                    auth_disabled=True,
                )
            ),
        )
        session_b = Session(
            storage=FileStorage(tmp_path / "client-storage-b", workspace_id="client_b"),
            executor=ContainerExecutor(
                ContainerConfig(
                    remote_url=live_session_server_url,
                    timeout=30.0,
                    auth_disabled=True,
                )
            ),
        )

        async with session_a, session_b:
            result = await session_a.run(
                "\n".join(
                    [
                        "workflows.create(",
                        "    'summarize_remote_notes',",
                        "    'async def run() -> str:\\n    return \"ok\"\\n',",
                        "    'Summarize remote notes',",
                        ")",
                    ]
                )
            )
            assert result.error is None

            result = await session_b.run("workflows.search('summarize')")
            assert result.error is None
            assert result.value == []


@pytest.mark.xdist_group("remote-redis")
class TestRemoteWorkspaceRedisUserJourney:
    """Developer-facing remote Redis journeys for workspace scoping."""

    @pytest.mark.asyncio
    async def test_same_workspace_sessions_share_remote_redis_state(
        self, remote_workspace_redis_url: str, live_redis_session_server_url: str
    ) -> None:
        """Two sessions in one workspace should share workflows and artifacts through Redis."""
        session_a = create_remote_redis_session(
            remote_workspace_redis_url,
            live_redis_session_server_url,
            workspace_id="client_a",
        )
        session_b = create_remote_redis_session(
            remote_workspace_redis_url,
            live_redis_session_server_url,
            workspace_id="client_a",
        )

        async with session_a, session_b:
            result = await session_a.run(
                "\n".join(
                    [
                        "workflows.create(",
                        "    'shared_remote_redis',",
                        "    'async def run() -> str:\\n    return \"shared through redis\"\\n',",
                        "    'Shared remote Redis workflow',",
                        ")",
                        "artifacts.save(",
                        "    'shared_remote_redis.json',",
                        "    {'workspace': 'client_a'},",
                        "    description='shared',",
                        ")",
                    ]
                )
            )
            assert result.error is None

            workflow = await session_b.get_workflow("shared_remote_redis")
            assert workflow is not None

            artifact = await session_b.load_artifact("shared_remote_redis.json")
            assert artifact == {"workspace": "client_a"}

            result = await session_b.run(
                "[workflows.shared_remote_redis(), "
                "artifacts.load('shared_remote_redis.json')['workspace']]"
            )
            assert result.error is None
            assert result.value == ["shared through redis", "client_a"]

    @pytest.mark.asyncio
    async def test_different_workspaces_are_isolated_in_remote_redis(
        self, remote_workspace_redis_url: str, live_redis_session_server_url: str
    ) -> None:
        """Different workspace IDs should isolate Redis-backed remote state and search."""
        session_a = create_remote_redis_session(
            remote_workspace_redis_url,
            live_redis_session_server_url,
            workspace_id="client_a",
        )
        session_b = create_remote_redis_session(
            remote_workspace_redis_url,
            live_redis_session_server_url,
            workspace_id="client_b",
        )

        async with session_a, session_b:
            result = await session_a.run(
                "\n".join(
                    [
                        "workflows.create(",
                        "    'campaign_metrics',",
                        "    'async def run() -> str:\\n    return \"workspace a\"\\n',",
                        "    'Analyze campaign metrics and summarize ad performance',",
                        ")",
                        "artifacts.save(",
                        "    'campaign_metrics.json',",
                        "    {'workspace': 'client_a'},",
                        "    description='isolated',",
                        ")",
                    ]
                )
            )
            assert result.error is None

            assert await session_b.get_workflow("campaign_metrics") is None

            result = await session_b.run(
                "[workflows.get('campaign_metrics'), "
                "artifacts.exists('campaign_metrics.json'), "
                "workflows.search('campaign metrics ad performance')]"
            )
            assert result.error is None
            assert result.value == [None, False, []]

    @pytest.mark.asyncio
    async def test_fresh_session_rejoins_same_workspace_in_remote_redis(
        self, remote_workspace_redis_url: str, live_redis_session_server_url: str
    ) -> None:
        """A newly created session with the same workspace should rejoin shared Redis state."""
        async with create_remote_redis_session(
            remote_workspace_redis_url,
            live_redis_session_server_url,
            workspace_id="client_a",
        ) as writer:
            result = await writer.run(
                "\n".join(
                    [
                        "workflows.create(",
                        "    'rejoin_remote_redis',",
                        "    'async def run() -> str:\\n    return \"rejoined\"\\n',",
                        "    'Workflow for rejoin test',",
                        ")",
                        "artifacts.save(",
                        "    'rejoin_remote_redis.json',",
                        "    {'status': 'persisted'},",
                        "    description='persisted',",
                        ")",
                    ]
                )
            )
            assert result.error is None

        async with create_remote_redis_session(
            remote_workspace_redis_url,
            live_redis_session_server_url,
            workspace_id="client_a",
        ) as reader:
            workflow = await reader.get_workflow("rejoin_remote_redis")
            assert workflow is not None

            artifact = await reader.load_artifact("rejoin_remote_redis.json")
            assert artifact == {"status": "persisted"}

            result = await reader.run("workflows.rejoin_remote_redis()")
            assert result.error is None
            assert result.value == "rejoined"

    @pytest.mark.asyncio
    async def test_scoped_and_legacy_remote_redis_namespaces_are_isolated(
        self, remote_workspace_redis_url: str, live_redis_session_server_url: str
    ) -> None:
        """Scoped Redis workspaces should be isolated from the legacy default namespace."""
        legacy_session = create_remote_redis_session(
            remote_workspace_redis_url,
            live_redis_session_server_url,
        )
        scoped_session = create_remote_redis_session(
            remote_workspace_redis_url,
            live_redis_session_server_url,
            workspace_id="client_a",
        )

        async with legacy_session, scoped_session:
            result = await legacy_session.run(
                "\n".join(
                    [
                        "workflows.create(",
                        "    'legacy_remote_redis',",
                        "    'async def run() -> str:\\n    return \"legacy\"\\n',",
                        "    'Legacy default workflow',",
                        ")",
                        "artifacts.save(",
                        "    'legacy_remote_redis.json',",
                        "    {'namespace': 'legacy'},",
                        "    description='legacy',",
                        ")",
                    ]
                )
            )
            assert result.error is None

            result = await scoped_session.run(
                "[workflows.get('legacy_remote_redis'), "
                "artifacts.exists('legacy_remote_redis.json')]"
            )
            assert result.error is None
            assert result.value == [None, False]

            result = await scoped_session.run(
                "\n".join(
                    [
                        "workflows.create(",
                        "    'scoped_remote_redis',",
                        "    'async def run() -> str:\\n    return \"scoped\"\\n',",
                        "    'Scoped workflow',",
                        ")",
                        "artifacts.save(",
                        "    'scoped_remote_redis.json',",
                        "    {'namespace': 'scoped'},",
                        "    description='scoped',",
                        ")",
                    ]
                )
            )
            assert result.error is None

            result = await legacy_session.run(
                "[workflows.get('scoped_remote_redis'), "
                "artifacts.exists('scoped_remote_redis.json')]"
            )
            assert result.error is None
            assert result.value == [None, False]

    @pytest.mark.asyncio
    async def test_sessions_without_workspace_id_share_legacy_remote_redis_namespace(
        self, remote_workspace_redis_url: str, live_redis_session_server_url: str
    ) -> None:
        """Two unscoped sessions should share the legacy default Redis namespace."""
        session_a = create_remote_redis_session(
            remote_workspace_redis_url,
            live_redis_session_server_url,
        )
        session_b = create_remote_redis_session(
            remote_workspace_redis_url,
            live_redis_session_server_url,
        )

        async with session_a, session_b:
            result = await session_a.run(
                "\n".join(
                    [
                        "workflows.create(",
                        "    'legacy_shared_remote_redis',",
                        "    'async def run() -> str:\\n    return \"legacy shared\"\\n',",
                        "    'Legacy shared workflow',",
                        ")",
                        "artifacts.save(",
                        "    'legacy_shared_remote_redis.json',",
                        "    {'namespace': 'legacy'},",
                        "    description='legacy',",
                        ")",
                    ]
                )
            )
            assert result.error is None

            result = await session_b.run(
                "[workflows.legacy_shared_remote_redis(), "
                "artifacts.load('legacy_shared_remote_redis.json')['namespace']]"
            )
            assert result.error is None
            assert result.value == ["legacy shared", "legacy"]
