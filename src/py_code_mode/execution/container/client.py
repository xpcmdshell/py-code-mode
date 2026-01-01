"""HTTP client for session server.

This client connects to a running session server and provides
a Python API for code execution. Each client maintains its own
isolated session with separate Python namespace and artifacts.

Usage:
    async with SessionClient("http://localhost:8080") as client:
        result = await client.execute("x = 42")
        result = await client.execute("x * 2")  # Variables persist
        print(result.value)  # 84
"""

from __future__ import annotations

import uuid
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
    skills: list[dict[str, str]]
    artifacts_path: str


@dataclass
class ResetResult:
    """Reset result."""

    status: str
    session_id: str


class SessionClient:
    """HTTP client for session server.

    Each client instance maintains its own isolated session with:
    - Separate Python namespace (variables don't leak between sessions)
    - Separate artifact directory

    Use the same client instance across requests to maintain state,
    or create a new client for a fresh isolated session.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8080",
        timeout: float = 30.0,
        session_id: str | None = None,
        auth_token: str | None = None,
    ) -> None:
        """Initialize session client.

        Args:
            base_url: Base URL of session server.
            timeout: Default timeout for HTTP requests.
            session_id: Optional session ID. If not provided, a new
                       unique session is created on first request.
            auth_token: Optional Bearer token for API authentication.
                       If provided, sent as Authorization header.
        """
        if not HTTPX_AVAILABLE:
            raise ImportError("httpx required for SessionClient. Install with: pip install httpx")

        # Strip trailing slash
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session_id = session_id or str(uuid.uuid4())
        self.auth_token = auth_token
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    def _headers(self) -> dict[str, str]:
        """Get headers with session ID and optional auth token."""
        headers = {"X-Session-ID": self.session_id}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        return headers

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
        client = await self._get_client()
        payload = {"code": code}
        if timeout is not None:
            payload["timeout"] = timeout  # type: ignore

        response = await client.post(
            f"{self.base_url}/execute",
            json=payload,
            headers=self._headers(),
        )
        response.raise_for_status()
        data = response.json()

        # Update session_id if server assigned one
        if "session_id" in data:
            self.session_id = data["session_id"]

        return ExecuteResult(
            value=data["value"],
            stdout=data["stdout"],
            error=data["error"],
            execution_time_ms=data["execution_time_ms"],
            session_id=data.get("session_id", self.session_id),
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
            InfoResult with available tools and skills.
        """
        client = await self._get_client()
        response = await client.get(f"{self.base_url}/info", headers=self._headers())
        response.raise_for_status()
        data = response.json()

        return InfoResult(
            tools=data["tools"],
            skills=data["skills"],
            artifacts_path=data["artifacts_path"],
        )

    async def reset(self) -> ResetResult:
        """Reset this session's state.

        Clears the Python namespace. Artifacts are preserved.

        Returns:
            ResetResult confirming reset.
        """
        client = await self._get_client()
        response = await client.post(
            f"{self.base_url}/reset",
            headers=self._headers(),
        )
        response.raise_for_status()
        data = response.json()

        return ResetResult(
            status=data["status"],
            session_id=data.get("session_id", self.session_id),
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
        data = response.json()
        if response.status_code != 200:
            raise RuntimeError(data.get("error", "Install failed"))
        return data

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
        data = response.json()
        if response.status_code != 200:
            raise RuntimeError(data.get("error", "Uninstall failed"))
        return data

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
    # Skills API Methods
    # ==========================================================================

    async def list_skills(self) -> list[dict[str, Any]]:
        """List all skills.

        Returns:
            List of skill metadata dicts with name, description, parameters.
        """
        client = await self._get_client()
        response = await client.get(
            f"{self.base_url}/api/skills",
            headers=self._headers(),
        )
        response.raise_for_status()
        return response.json()

    async def search_skills(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Search skills semantically.

        Args:
            query: Natural language search query.
            limit: Maximum number of results to return.

        Returns:
            List of matching skill metadata dicts.
        """
        client = await self._get_client()
        response = await client.get(
            f"{self.base_url}/api/skills/search",
            params={"query": query, "limit": limit},
            headers=self._headers(),
        )
        response.raise_for_status()
        return response.json()

    async def get_skill(self, name: str) -> dict[str, Any] | None:
        """Get skill by name with full source.

        Args:
            name: Skill name.

        Returns:
            Skill dict with name, description, parameters, source.
            None if skill not found.
        """
        client = await self._get_client()
        response = await client.get(
            f"{self.base_url}/api/skills/{name}",
            headers=self._headers(),
        )
        response.raise_for_status()
        return response.json()

    async def create_skill(self, name: str, source: str, description: str) -> dict[str, Any]:
        """Create a new skill.

        Args:
            name: Skill name.
            source: Python source code with run() function.
            description: Skill description.

        Returns:
            Created skill metadata dict.

        Raises:
            RuntimeError: If skill creation fails.
        """
        client = await self._get_client()
        response = await client.post(
            f"{self.base_url}/api/skills",
            json={"name": name, "source": source, "description": description},
            headers=self._headers(),
        )
        if response.status_code != 200:
            data = response.json()
            raise RuntimeError(data.get("detail", "Skill creation failed"))
        return response.json()

    async def delete_skill(self, name: str) -> bool:
        """Delete a skill.

        Args:
            name: Skill name.

        Returns:
            True if skill was deleted, False if not found.
        """
        client = await self._get_client()
        response = await client.delete(
            f"{self.base_url}/api/skills/{name}",
            headers=self._headers(),
        )
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
        client = await self._get_client()
        response = await client.get(
            f"{self.base_url}/api/artifacts",
            headers=self._headers(),
        )
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
        client = await self._get_client()
        response = await client.get(
            f"{self.base_url}/api/artifacts/{name}",
            headers=self._headers(),
        )
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
        client = await self._get_client()
        response = await client.post(
            f"{self.base_url}/api/artifacts",
            json={
                "name": name,
                "data": data,
                "description": description,
                "metadata": metadata,
            },
            headers=self._headers(),
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
        client = await self._get_client()
        response = await client.delete(
            f"{self.base_url}/api/artifacts/{name}",
            headers=self._headers(),
        )
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
        if response.status_code != 200:
            data = response.json()
            raise RuntimeError(data.get("detail", "Add dep failed"))
        return response.json()

    async def api_remove_dep(self, package: str) -> dict[str, Any]:
        """Remove a package from configuration.

        Args:
            package: Package specification to remove.

        Returns:
            Dict with removal status.

        Raises:
            RuntimeError: If removal is disabled.
        """
        client = await self._get_client()
        response = await client.post(
            f"{self.base_url}/api/deps/remove",
            json={"package": package},
            headers=self._headers(),
        )
        if response.status_code != 200:
            data = response.json()
            raise RuntimeError(data.get("detail", "Remove dep failed"))
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
