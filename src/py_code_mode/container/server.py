"""Session server for container-based code execution.

This FastAPI app runs inside the container and provides HTTP endpoints
for code execution with persistent state.

Supports multiple isolated sessions - each session_id gets its own
Python namespace and artifact directory.

Usage:
    uvicorn py_code_mode.container.server:app --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

import importlib
import os
import subprocess
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Check for FastAPI at import time for cleaner error messages
try:
    from fastapi import FastAPI, HTTPException, Header
    from pydantic import BaseModel

    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False
    # Create dummy classes for type hints
    BaseModel = object  # type: ignore
    FastAPI = None  # type: ignore
    HTTPException = Exception  # type: ignore
    Header = None  # type: ignore

from py_code_mode.adapters import CLIAdapter, CLIToolSpec
from py_code_mode.artifacts import ArtifactStoreProtocol, FileArtifactStore
from py_code_mode.container.config import SessionConfig
from py_code_mode.executor import CodeExecutor
from py_code_mode.registry import ToolRegistry
from py_code_mode.semantic import SkillLibrary, create_skill_library
from py_code_mode.skill_store import FileSkillStore


# Session expiration (seconds)
SESSION_EXPIRY = 3600  # 1 hour


# Pydantic models for API (only if FastAPI available)
if FASTAPI_AVAILABLE:

    class ExecuteRequestModel(BaseModel):  # type: ignore
        """Request to execute code."""

        code: str
        timeout: float | None = None

    class ExecuteResponseModel(BaseModel):  # type: ignore
        """Response from code execution."""

        value: Any
        stdout: str
        error: str | None
        execution_time_ms: float
        session_id: str

    class HealthResponseModel(BaseModel):  # type: ignore
        """Health check response."""

        status: str
        uptime_seconds: float
        active_sessions: int

    class InfoResponseModel(BaseModel):  # type: ignore
        """Server info response."""

        tools: list[dict[str, str]]
        skills: list[dict[str, str]]
        artifacts_path: str

    class ResetResponseModel(BaseModel):  # type: ignore
        """Reset response."""

        status: str
        session_id: str

    class SessionInfoModel(BaseModel):  # type: ignore
        """Session information."""

        session_id: str
        execution_count: int
        created_at: float
        last_used: float


@dataclass
class Session:
    """Individual session state."""

    session_id: str
    executor: CodeExecutor
    artifact_store: ArtifactStoreProtocol
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    execution_count: int = 0


@dataclass
class ServerState:
    """Global server state."""

    config: SessionConfig | None = None
    registry: ToolRegistry | None = None
    skill_library: SkillLibrary | None = None
    artifact_store: ArtifactStoreProtocol | None = None  # Shared store for Redis mode
    sessions: dict[str, Session] = field(default_factory=dict)
    start_time: float = 0.0
    redis_mode: bool = False


# Global state
_state = ServerState()


async def build_tool_registry(config: SessionConfig) -> ToolRegistry:
    """Build tool registry from configuration.

    Tools are registered without namespace prefix - access as tools.nmap(), not tools.cli.nmap().
    """
    registry = ToolRegistry()

    if config.cli_tools:
        # Convert CLIToolConfig to CLIToolSpec
        specs = [
            CLIToolSpec(
                name=t.name,
                description=t.description,
                command=t.command,
                args_template=t.args_template,
                timeout_seconds=t.timeout_seconds,
                working_dir=t.working_dir,
                env=t.env,
            )
            for t in config.cli_tools
        ]

        adapter = CLIAdapter(specs)
        await registry.register_adapter(adapter)

    return registry


def build_skill_library(config: SessionConfig) -> SkillLibrary | None:
    """Build skill library from configuration with semantic search."""
    if not config.skills_path.exists():
        return None

    # Use file-based store wrapped in skill library
    store = FileSkillStore(config.skills_path)
    return create_skill_library(store=store)


def create_session(session_id: str) -> Session:
    """Create a new isolated session."""
    if _state.config is None:
        raise RuntimeError("Server not initialized")

    # Use shared Redis artifact store or create session-specific file store
    if _state.redis_mode and _state.artifact_store:
        artifact_store = _state.artifact_store
    else:
        session_artifacts_path = _state.config.artifacts_path / session_id
        session_artifacts_path.mkdir(parents=True, exist_ok=True)
        artifact_store = FileArtifactStore(session_artifacts_path)

    # Create executor with shared registries but isolated namespace/artifacts
    executor = CodeExecutor(
        registry=_state.registry,
        skill_library=_state.skill_library,
        artifact_store=artifact_store,
        default_timeout=_state.config.default_timeout,
    )

    return Session(
        session_id=session_id,
        executor=executor,
        artifact_store=artifact_store,
    )


def get_or_create_session(session_id: str | None) -> Session:
    """Get existing session or create a new one."""
    # Generate session_id if not provided
    if session_id is None:
        session_id = str(uuid.uuid4())

    # Return existing session
    if session_id in _state.sessions:
        session = _state.sessions[session_id]
        session.last_used = time.time()
        return session

    # Create new session
    session = create_session(session_id)
    _state.sessions[session_id] = session
    return session


def cleanup_expired_sessions() -> int:
    """Remove sessions that haven't been used recently."""
    now = time.time()
    expired = [
        sid for sid, session in _state.sessions.items()
        if now - session.last_used > SESSION_EXPIRY
    ]
    for sid in expired:
        del _state.sessions[sid]
    return len(expired)


def install_python_deps(deps: list[str]) -> None:
    """Install Python dependencies if not already installed.

    Uses pip to install packages. Skips packages that are already available.
    """
    for dep in deps:
        # Extract package name (handle version specifiers like "requests>=2.0")
        pkg_name = dep.split(">=")[0].split("<=")[0].split("==")[0].split("[")[0]
        # Normalize: some packages have different import names
        import_name = pkg_name.replace("-", "_").lower()

        try:
            importlib.import_module(import_name)
        except ImportError:
            print(f"Installing {dep}...")
            subprocess.run(
                ["pip", "install", "--quiet", dep],
                check=True,
                capture_output=True,
            )
            print(f"Installed {dep}")


async def initialize_server(config: SessionConfig) -> None:
    """Initialize the server with shared resources.

    When REDIS_URL is set, uses Redis for tools, skills, and artifacts.
    Otherwise falls back to file-based storage.
    """
    global _state

    # Install Python dependencies from config
    if config.python_deps:
        install_python_deps(config.python_deps)

    redis_url = os.environ.get("REDIS_URL")

    if redis_url:
        # Redis mode: load everything from Redis with semantic search
        import redis as redis_lib

        from py_code_mode.redis_artifacts import RedisArtifactStore
        from py_code_mode.redis_tools import RedisToolStore, registry_from_redis
        from py_code_mode.skill_store import RedisSkillStore

        print(f"Using Redis backend: {redis_url[:50]}...")
        r = redis_lib.from_url(redis_url)

        # Tools from Redis
        tool_store = RedisToolStore(r, prefix="agent-tools")
        registry = await registry_from_redis(tool_store)
        print(f"  Tools in Redis: {len(tool_store)}")

        # Skills from Redis with semantic search
        redis_store = RedisSkillStore(r, prefix="agent-skills")
        skill_library = create_skill_library(store=redis_store)
        print(f"  Skills in Redis: {len(redis_store)} (semantic search enabled)")

        # Artifacts in Redis (shared across sessions)
        artifact_store = RedisArtifactStore(r, prefix="agent-artifacts")

        _state = ServerState(
            config=config,
            registry=registry,
            skill_library=skill_library,
            artifact_store=artifact_store,
            sessions={},
            start_time=time.time(),
            redis_mode=True,
        )
    else:
        # File mode: load from config paths
        print("Using file-based backend (set REDIS_URL for Redis mode)")
        registry = await build_tool_registry(config)
        skill_library = build_skill_library(config)

        # Ensure base artifacts path exists
        config.artifacts_path.mkdir(parents=True, exist_ok=True)

        _state = ServerState(
            config=config,
            registry=registry,
            skill_library=skill_library,
            sessions={},
            start_time=time.time(),
            redis_mode=False,
        )


def create_app(config: SessionConfig | None = None) -> "FastAPI":
    """Create FastAPI application.

    Args:
        config: Optional session config. If not provided, loads from environment.
    """
    if not FASTAPI_AVAILABLE:
        raise ImportError(
            "FastAPI required for session server. "
            "Install with: pip install fastapi uvicorn"
        )

    # Store config for lifespan to use
    _app_config = config

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore
        """Application lifespan - initialize on startup."""
        cfg = _app_config if _app_config is not None else SessionConfig.from_env()
        await initialize_server(cfg)
        yield

    app = FastAPI(
        title="py-code-mode Session Server",
        description="Multi-session code execution environment",
        lifespan=lifespan,
    )

    @app.post("/execute", response_model=ExecuteResponseModel)
    async def execute(
        body: ExecuteRequestModel,
        x_session_id: str | None = Header(None, alias="X-Session-ID"),
    ) -> ExecuteResponseModel:
        """Execute code in an isolated session.

        Pass X-Session-ID header to use a specific session.
        Omit to create a new session (ID returned in response).
        """
        if _state.config is None:
            raise HTTPException(status_code=503, detail="Server not initialized")

        # Cleanup expired sessions periodically
        cleanup_expired_sessions()

        # Get or create session
        session = get_or_create_session(x_session_id)

        start = time.time()
        timeout = body.timeout or _state.config.default_timeout

        result = await session.executor.run(body.code, timeout=timeout)
        elapsed_ms = (time.time() - start) * 1000

        session.execution_count += 1
        session.last_used = time.time()

        # Serialize value for JSON response
        try:
            import json
            json.dumps(result.value)
            value = result.value
        except (TypeError, ValueError):
            value = str(result.value) if result.value is not None else None

        return ExecuteResponseModel(
            value=value,
            stdout=result.stdout,
            error=result.error,
            execution_time_ms=elapsed_ms,
            session_id=session.session_id,
        )

    @app.get("/health", response_model=HealthResponseModel)
    async def health() -> HealthResponseModel:
        """Health check endpoint."""
        return HealthResponseModel(
            status="healthy",
            uptime_seconds=time.time() - _state.start_time,
            active_sessions=len(_state.sessions),
        )

    @app.get("/info", response_model=InfoResponseModel)
    async def info() -> InfoResponseModel:
        """Get information about available tools and skills."""
        tools = []
        if _state.registry:
            for tool in _state.registry.list_tools():
                tools.append({"name": tool.name, "description": tool.description})

        skills = []
        if _state.skill_library:
            for skill in _state.skill_library.list():
                skills.append({"name": skill.name, "description": skill.description})

        artifacts_path = str(_state.config.artifacts_path) if _state.config else ""

        return InfoResponseModel(
            tools=tools,
            skills=skills,
            artifacts_path=artifacts_path,
        )

    @app.post("/reset", response_model=ResetResponseModel)
    async def reset(
        x_session_id: str | None = Header(None, alias="X-Session-ID"),
    ) -> ResetResponseModel:
        """Reset a session (clears namespace, keeps artifacts)."""
        if x_session_id and x_session_id in _state.sessions:
            del _state.sessions[x_session_id]

        return ResetResponseModel(
            status="reset",
            session_id=x_session_id or "",
        )

    @app.get("/sessions")
    async def list_sessions() -> list[SessionInfoModel]:
        """List all active sessions."""
        return [
            SessionInfoModel(
                session_id=s.session_id,
                execution_count=s.execution_count,
                created_at=s.created_at,
                last_used=s.last_used,
            )
            for s in _state.sessions.values()
        ]

    return app


# Create app instance for uvicorn
app = create_app()


def main() -> None:
    """Run the session server."""
    try:
        import uvicorn
    except ImportError as e:
        raise ImportError(
            "uvicorn required for session server. "
            "Install with: pip install uvicorn"
        ) from e

    config = SessionConfig.from_env()
    uvicorn.run(app, host=config.host, port=config.port)


if __name__ == "__main__":
    main()
