"""Session server for container-based code execution.

This FastAPI app runs inside the container and provides HTTP endpoints
for code execution with persistent state.

Supports multiple isolated sessions - each session_id gets its own
Python namespace and artifact directory.

Usage:
    uvicorn py_code_mode.backends.container.server:app --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

import dataclasses
import importlib
import logging
import os
import subprocess
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Check for FastAPI at import time for cleaner error messages
try:
    from fastapi import FastAPI, Header, HTTPException
    from pydantic import BaseModel

    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False
    # Create dummy classes for type hints
    BaseModel = object  # type: ignore
    FastAPI = None  # type: ignore
    HTTPException = Exception  # type: ignore
    Header = None  # type: ignore

from py_code_mode.adapters.cli import CLIAdapter  # noqa: E402
from py_code_mode.artifacts import (  # noqa: E402
    ArtifactStoreProtocol,
    FileArtifactStore,
)
from py_code_mode.backends.container.config import SessionConfig  # noqa: E402
from py_code_mode.backends.in_process import (  # noqa: E402
    InProcessExecutor as CodeExecutor,
)
from py_code_mode.registry import ToolRegistry  # noqa: E402
from py_code_mode.semantic import SkillLibrary, create_skill_library  # noqa: E402
from py_code_mode.skill_store import FileSkillStore  # noqa: E402

# Session expiration (seconds)
SESSION_EXPIRY = 3600  # 1 hour


def serialize_value(value: Any) -> Any:
    """Serialize a value for JSON response.

    Recursively converts dataclasses and frozensets to JSON-serializable types.
    """
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {k: serialize_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [serialize_value(v) for v in value]
    if isinstance(value, frozenset):
        return list(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {k: serialize_value(v) for k, v in dataclasses.asdict(value).items()}
    # Fallback to string representation
    return str(value)


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


def build_skill_library(config: SessionConfig) -> SkillLibrary | None:
    """Build skill library from configuration with semantic search."""
    # Create directory if it doesn't exist (same as artifacts behavior)
    try:
        config.skills_path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        # If we can't create the directory (e.g., read-only filesystem),
        # return None to signal no skill library is available
        logger.warning("Cannot create skills directory at %s: %s", config.skills_path, e)
        return None

    # Use file-based store wrapped in skill library
    store = FileSkillStore(config.skills_path)
    return create_skill_library(store=store)


def create_session(session_id: str) -> Session:
    """Create a new isolated session."""
    if _state.config is None:
        raise RuntimeError("Server not initialized")

    # Use shared artifact store (already initialized at startup for both modes)
    if _state.artifact_store is None:
        raise RuntimeError("Artifact store not initialized")
    artifact_store = _state.artifact_store

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
        sid for sid, session in _state.sessions.items() if now - session.last_used > SESSION_EXPIRY
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
            logger.info("Installing %s...", dep)
            subprocess.run(
                ["pip", "install", "--quiet", dep],
                check=True,
                capture_output=True,
            )
            logger.info("Installed %s", dep)


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

        logger.info("Using Redis backend: %s...", redis_url[:50])
        r = redis_lib.from_url(redis_url)

        # Get prefixes from environment (set by ContainerExecutor), with defaults
        tools_prefix = os.environ.get("REDIS_TOOLS_PREFIX", "tools")
        skills_prefix = os.environ.get("REDIS_SKILLS_PREFIX", "skills")
        artifacts_prefix = os.environ.get("REDIS_ARTIFACTS_PREFIX", "artifacts")

        # Tools from Redis
        tool_store = RedisToolStore(r, prefix=tools_prefix)
        registry = await registry_from_redis(tool_store)
        logger.info("  Tools in Redis (%s): %d", tools_prefix, len(tool_store))

        # Skills from Redis with semantic search
        redis_store = RedisSkillStore(r, prefix=skills_prefix)
        skill_library = create_skill_library(store=redis_store)
        skill_count = len(redis_store)
        logger.info("  Skills in Redis (%s): %d (semantic)", skills_prefix, skill_count)

        # Artifacts in Redis (shared across sessions)
        artifact_store = RedisArtifactStore(r, prefix=artifacts_prefix)

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
        logger.info("Using file-based backend (set REDIS_URL for Redis mode)")

        # Load tools from mounted directory if TOOLS_PATH is set
        tools_path = os.environ.get("TOOLS_PATH")
        if tools_path:
            logger.info("  Loading tools from directory: %s", tools_path)
            tools_dir = Path(tools_path)

            # Load CLI tools from YAML files
            cli_adapter = CLIAdapter(tools_path=tools_dir)
            registry = ToolRegistry()
            if cli_adapter.list_tools():
                registry.add_adapter(cli_adapter)

            # Also load MCP tools from the same directory
            mcp_registry = await ToolRegistry.from_dir(tools_path)
            for adapter in mcp_registry.get_adapters():
                registry.add_adapter(adapter)

            logger.info("  Tools in directory: %d", len(registry.list_tools()))
        else:
            # No TOOLS_PATH - no tools available
            logger.info("  TOOLS_PATH not set, no tools available")
            registry = ToolRegistry()

        skill_library = build_skill_library(config)

        # Create shared artifact store (same as Redis mode)
        config.artifacts_path.mkdir(parents=True, exist_ok=True)
        artifact_store = FileArtifactStore(config.artifacts_path)

        _state = ServerState(
            config=config,
            registry=registry,
            skill_library=skill_library,
            artifact_store=artifact_store,
            sessions={},
            start_time=time.time(),
            redis_mode=False,
        )


def create_app(config: SessionConfig | None = None) -> FastAPI:
    """Create FastAPI application.

    Args:
        config: Optional session config. If not provided, loads from environment.
    """
    if not FASTAPI_AVAILABLE:
        raise ImportError(
            "FastAPI required for session server. Install with: pip install fastapi uvicorn"
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

        # Serialize value for JSON response (handles dataclasses, frozensets, etc.)
        value = serialize_value(result.value)

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
            "uvicorn required for session server. Install with: pip install uvicorn"
        ) from e

    config = SessionConfig.from_env()
    uvicorn.run(app, host=config.host, port=config.port)


if __name__ == "__main__":
    main()
