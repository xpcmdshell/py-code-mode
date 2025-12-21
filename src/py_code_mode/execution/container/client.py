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
    active_sessions: int


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
    ) -> None:
        """Initialize session client.

        Args:
            base_url: Base URL of session server.
            timeout: Default timeout for HTTP requests.
            session_id: Optional session ID. If not provided, a new
                       unique session is created on first request.
        """
        if not HTTPX_AVAILABLE:
            raise ImportError("httpx required for SessionClient. Install with: pip install httpx")

        # Strip trailing slash
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session_id = session_id or str(uuid.uuid4())
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    def _headers(self) -> dict[str, str]:
        """Get headers with session ID."""
        return {"X-Session-ID": self.session_id}

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
            active_sessions=data.get("active_sessions", 0),
        )

    async def info(self) -> InfoResult:
        """Get server info.

        Returns:
            InfoResult with available tools and skills.
        """
        client = await self._get_client()
        response = await client.get(f"{self.base_url}/info")
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
