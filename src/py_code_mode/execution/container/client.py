"""HTTP client for session server.

This client connects to a running session server and provides
a Python API for code execution. Each client maintains its own
isolated session with separate Python namespace and artifacts.
The client lazily binds a server session on first session-scoped use.

Usage:
    async with SessionClient("http://localhost:8080") as client:
        result = await client.execute("x = 42")
        result = await client.execute("x * 2")  # Variables persist
        print(result.value)  # 84
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

try:
    import httpx

    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False
    httpx = None  # type: ignore


@dataclass
class ExecuteResult:
    """Result from code execution."""

    value: Any
    stdout: str
    error: str | None
    execution_time_ms: float
    session_id: str

    @property
    def is_ok(self) -> bool:
        """Check if execution succeeded."""
        return self.error is None


@dataclass
class HealthResult:
    """Health check result."""

    status: str
    uptime_seconds: float


@dataclass
class InfoResult:
    """Server info result."""

    tools: list[dict[str, str]]
    workflows: list[dict[str, str]]
    artifacts_path: str


@dataclass
class ResetResult:
    """Reset result."""

    status: str
    session_id: str | None


class SessionClient:
    """HTTP client for session server.

    Each client instance maintains its own isolated session with:
    - Separate Python namespace (variables don't leak between sessions)
    - Separate artifact directory

    Use the same client instance across requests to maintain state.
    The client lazily creates a bound remote session via POST /sessions and
    reuses that session ID for later session-scoped requests.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8080",
        timeout: float = 30.0,
        auth_token: str | None = None,
    ) -> None:
        """Initialize session client.

        Args:
            base_url: Base URL of session server.
            timeout: Default timeout for HTTP requests.
            auth_token: Optional Bearer token for API authentication.
                       If provided, sent as Authorization header.
        """
        if not HTTPX_AVAILABLE:
            raise ImportError("httpx required for SessionClient. Install with: pip install httpx")

        # Strip trailing slash
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session_id: str | None = None
        self.auth_token = auth_token
        self._client: httpx.AsyncClient | None = None
        self._workspace_id: str | None = None
        self._auto_init_session = True
        self._session_lock = asyncio.Lock()

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    def _auth_headers(self) -> dict[str, str]:
        """Get headers with optional auth token only."""
        headers: dict[str, str] = {}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        return headers

    def _headers(self) -> dict[str, str]:
        """Get headers with session ID and optional auth token."""
        headers = self._auth_headers()
        if self.session_id is not None:
            headers["X-Session-ID"] = self.session_id
        return headers

    async def _ensure_session_bound(self) -> None:
        """Ensure a previously initialized session is rebound after reset/expiry."""
        if self.session_id is None and self._auto_init_session:
            await self._create_session(self._workspace_id)

    def _is_invalid_session_response(self, response: httpx.Response) -> bool:
        """Check whether a response indicates a stale or missing bound session."""
        if response.status_code != 400:
            return False

        try:
            data = response.json()
        except ValueError:
            return False
        return data.get("detail") == "Invalid session ID"

    async def _create_session(self, workspace_id: str | None = None) -> str:
        """Create and bind a remote session without taking the session lock."""
        client = await self._get_client()
        payload: dict[str, str] = {}
        if workspace_id is not None:
            payload["workspace_id"] = workspace_id

        response = await client.post(
            f"{self.base_url}/sessions",
            json=payload,
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        data = response.json()

        self.session_id = data["session_id"]
        return self.session_id

    async def _rebind_if_current(self, failed_session_id: str) -> bool:
        """Rebind if the current client session still matches the failed session."""
        if not self._auto_init_session:
            return False
        if self.session_id is not None and self.session_id != failed_session_id:
            return False

        self.session_id = None
        await self._create_session(self._workspace_id)
        return True

    async def _send_session_request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """Send a session-scoped request, rebinding once if the server expired the session."""
        async with self._session_lock:
            await self._ensure_session_bound()
            client = await self._get_client()
            request_method = getattr(client, method.lower())
            request_session_id = self.session_id
            response = await request_method(
                f"{self.base_url}{path}",
                headers=self._headers(),
                **kwargs,
            )

            if request_session_id is not None and self._is_invalid_session_response(response):
                rebound = await self._rebind_if_current(request_session_id)
                if rebound:
                    response = await request_method(
                        f"{self.base_url}{path}",
                        headers=self._headers(),
                        **kwargs,
                    )

            return response

    async def init_session(self, workspace_id: str | None = None) -> str:
        """Create and bind an explicit remote session."""
        async with self._session_lock:
            self._workspace_id = workspace_id
            self._auto_init_session = True
            return await self._create_session(workspace_id)

    async def execute(
        self,
        code: str,
        timeout: float | None = None,
    ) -> ExecuteResult:
        """Execute code on session server.

        Args:
            code: Python code to execute.
            timeout: Optional execution timeout (sent to server).

        Returns:
            ExecuteResult with value, stdout, error.
        """
        payload = {"code": code}
        if timeout is not None:
            payload["timeout"] = timeout  # type: ignore

        response = await self._send_session_request(
            "POST",
            "/execute",
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

        return ExecuteResult(
            value=data["value"],
            stdout=data["stdout"],
            error=data["error"],
            execution_time_ms=data["execution_time_ms"],
            session_id=data["session_id"],
        )

    async def health(self) -> HealthResult:
        """Check server health.

        Returns:
            HealthResult with status and uptime.
        """
        client = await self._get_client()
        response = await client.get(f"{self.base_url}/health")
        response.raise_for_status()
        data = response.json()

        return HealthResult(
            status=data["status"],
            uptime_seconds=data["uptime_seconds"],
        )

    async def info(self) -> InfoResult:
        """Get server info.

        Returns:
            InfoResult with available tools and workflows.
        """
        response = await self._send_session_request("GET", "/info")
        response.raise_for_status()
        data = response.json()

        return InfoResult(
            tools=data["tools"],
            workflows=data["workflows"],
            artifacts_path=data["artifacts_path"],
        )

    async def reset(self) -> ResetResult:
        """Reset this session's state.

        Clears the Python namespace. Artifacts are preserved.

        Returns:
            ResetResult confirming reset.
        """
        async with self._session_lock:
            if self.session_id is None:
                return ResetResult(status="reset", session_id=None)

            client = await self._get_client()
            response = await client.post(
                f"{self.base_url}/reset",
                headers=self._headers(),
            )
            response.raise_for_status()
            data = response.json()
            self.session_id = None

            return ResetResult(
                status=data["status"],
                session_id=data.get("session_id"),
            )

    async def install_deps(self, packages: list[str]) -> dict[str, Any]:
        """Install packages in the container.

        Args:
            packages: List of package specifications (e.g., ["pandas>=2.0", "numpy"]).

        Returns:
            Dict with keys: installed, already_present, failed.

        Raises:
            RuntimeError: If installation fails.
        """
        client = await self._get_client()
        response = await client.post(
            f"{self.base_url}/install_deps",
            json={"packages": packages},
            headers=self._headers(),
            timeout=300.0,  # Long timeout for package installation
        )
        response.raise_for_status()
        return response.json()

    async def uninstall_deps(self, packages: list[str]) -> dict[str, Any]:
        """Uninstall packages from the container.

        Args:
            packages: List of package names to uninstall.

        Returns:
            Dict with keys: removed, not_found, failed.

        Raises:
            RuntimeError: If uninstallation fails.
        """
        client = await self._get_client()
        response = await client.post(
            f"{self.base_url}/uninstall_deps",
            json={"packages": packages},
            headers=self._headers(),
            timeout=120.0,  # Reasonable timeout for uninstall
        )
        response.raise_for_status()
        return response.json()

    # ==========================================================================
    # Tools API Methods
    # ==========================================================================

    async def list_tools(self) -> list[dict[str, Any]]:
        """List all registered tools.

        Returns:
            List of tool metadata dicts with name, description, tags.
        """
        client = await self._get_client()
        response = await client.get(
            f"{self.base_url}/api/tools",
            headers=self._headers(),
        )
        response.raise_for_status()
        return response.json()

    async def search_tools(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search tools by query.

        Args:
            query: Search query string.
            limit: Maximum number of results to return.

        Returns:
            List of matching tool metadata dicts.
        """
        client = await self._get_client()
        response = await client.get(
            f"{self.base_url}/api/tools/search",
            params={"query": query, "limit": limit},
            headers=self._headers(),
        )
        response.raise_for_status()
        return response.json()

    # ==========================================================================
    # Workflows API Methods
    # ==========================================================================

    async def list_workflows(self) -> list[dict[str, Any]]:
        """List all workflows."""
        response = await self._send_session_request("GET", "/api/workflows")
        response.raise_for_status()
        return response.json()

    async def search_workflows(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Search workflows."""
        response = await self._send_session_request(
            "GET",
            "/api/workflows/search",
            params={"query": query, "limit": limit},
        )
        response.raise_for_status()
        return response.json()

    async def get_workflow(self, name: str) -> dict[str, Any] | None:
        """Get workflow by name with full source."""
        response = await self._send_session_request("GET", f"/api/workflows/{name}")
        response.raise_for_status()
        return response.json()

    async def create_workflow(self, name: str, source: str, description: str) -> dict[str, Any]:
        """Create a new workflow."""
        response = await self._send_session_request(
            "POST",
            "/api/workflows",
            json={"name": name, "source": source, "description": description},
        )
        if response.status_code != 200:
            data = response.json()
            raise RuntimeError(data.get("detail", "Workflow creation failed"))
        return response.json()

    async def delete_workflow(self, name: str) -> bool:
        """Delete a workflow."""
        response = await self._send_session_request("DELETE", f"/api/workflows/{name}")
        response.raise_for_status()
        return response.json()

    # ==========================================================================
    # Artifacts API Methods
    # ==========================================================================

    async def list_artifacts(self) -> list[dict[str, Any]]:
        """List all artifacts with metadata.

        Returns:
            List of artifact metadata dicts.
        """
        response = await self._send_session_request("GET", "/api/artifacts")
        response.raise_for_status()
        return response.json()

    async def load_artifact(self, name: str) -> Any:
        """Load artifact data.

        Args:
            name: Artifact name.

        Returns:
            Artifact data (can be any JSON-serializable type).

        Raises:
            RuntimeError: If artifact not found.
        """
        response = await self._send_session_request("GET", f"/api/artifacts/{name}")
        if response.status_code == 404:
            raise RuntimeError(f"Artifact '{name}' not found")
        response.raise_for_status()
        return response.json()

    async def save_artifact(
        self,
        name: str,
        data: Any,
        description: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Save artifact.

        Args:
            name: Artifact name.
            data: Data to save (must be JSON-serializable).
            description: Optional description.
            metadata: Optional additional metadata.

        Returns:
            Artifact metadata dict.
        """
        response = await self._send_session_request(
            "POST",
            "/api/artifacts",
            json={
                "name": name,
                "data": data,
                "description": description,
                "metadata": metadata,
            },
        )
        response.raise_for_status()
        return response.json()

    async def delete_artifact(self, name: str) -> None:
        """Delete artifact.

        Args:
            name: Artifact name.

        Raises:
            RuntimeError: If artifact not found.
        """
        response = await self._send_session_request("DELETE", f"/api/artifacts/{name}")
        if response.status_code == 404:
            raise RuntimeError(f"Artifact '{name}' not found")
        response.raise_for_status()

    # ==========================================================================
    # Deps API Methods
    # ==========================================================================

    async def api_list_deps(self) -> list[str]:
        """List configured packages.

        Returns:
            List of package specifications.
        """
        client = await self._get_client()
        response = await client.get(
            f"{self.base_url}/api/deps",
            headers=self._headers(),
        )
        response.raise_for_status()
        return response.json()

    async def api_add_dep(self, package: str) -> dict[str, Any]:
        """Add and install a package.

        Args:
            package: Package specification (e.g., "pandas>=2.0").

        Returns:
            Dict with keys: installed, already_present, failed.

        Raises:
            RuntimeError: If installation fails or is disabled.
        """
        client = await self._get_client()
        response = await client.post(
            f"{self.base_url}/api/deps/add",
            json={"package": package},
            headers=self._headers(),
            timeout=300.0,  # Long timeout for package installation
        )
        response.raise_for_status()
        return response.json()

    async def api_remove_dep(self, package: str) -> dict[str, Any]:
        """Remove a package from configuration and uninstall it.

        Args:
            package: Package specification to remove.

        Returns:
            Dict with keys: removed, not_found, failed, removed_from_config.

        Raises:
            RuntimeError: If removal is disabled.
        """
        client = await self._get_client()
        response = await client.post(
            f"{self.base_url}/api/deps/remove",
            json={"package": package},
            headers=self._headers(),
        )
        response.raise_for_status()
        return response.json()

    async def api_sync_deps(self) -> dict[str, Any]:
        """Install all configured packages.

        Returns:
            Dict with keys: installed, already_present, failed.
        """
        client = await self._get_client()
        response = await client.post(
            f"{self.base_url}/api/deps/sync",
            headers=self._headers(),
            timeout=300.0,  # Long timeout for package installation
        )
        response.raise_for_status()
        return response.json()

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> SessionClient:
        """Async context manager entry."""
        return self

    async def __aexit__(self, *args: object) -> None:
        """Async context manager exit."""
        await self.close()
