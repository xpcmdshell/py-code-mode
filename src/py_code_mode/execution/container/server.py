"""Session server for container-based code execution.

This FastAPI app runs inside the container and provides HTTP endpoints
for code execution with persistent state.

Supports multiple isolated sessions - each session_id gets its own
Python namespace and artifact directory.

Usage:
    uvicorn py_code_mode.execution.container.server:app --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

import dataclasses
import hmac
import importlib
import logging
import os
import subprocess
import sys
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Check for FastAPI at import time for cleaner error messages
try:
    from fastapi import Depends, FastAPI, Header, HTTPException
    from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
    from pydantic import BaseModel

    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False
    # Create dummy classes for type hints
    BaseModel = object  # type: ignore
    FastAPI = None  # type: ignore
    HTTPException = Exception  # type: ignore
    Header = None  # type: ignore
    Depends = None  # type: ignore
    HTTPBearer = None  # type: ignore
    HTTPAuthorizationCredentials = None  # type: ignore

from py_code_mode.artifacts import (  # noqa: E402
    ArtifactStoreProtocol,
    FileArtifactStore,
)
from py_code_mode.deps import (  # noqa: E402
    ControlledDepsNamespace,
    DepsNamespace,
    DepsStore,
    FileDepsStore,
    PackageInstaller,
    RedisDepsStore,
)
from py_code_mode.execution.container.config import SessionConfig  # noqa: E402
from py_code_mode.execution.in_process import (  # noqa: E402
    InProcessExecutor as CodeExecutor,
)
from py_code_mode.skills import FileSkillStore, SkillLibrary, create_skill_library  # noqa: E402
from py_code_mode.tools import ToolRegistry  # noqa: E402
from py_code_mode.tools.adapters.cli import CLIAdapter  # noqa: E402

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

    class InfoResponseModel(BaseModel):  # type: ignore
        """Server info response."""

        tools: list[dict[str, str]]
        skills: list[dict[str, str]]
        artifacts_path: str

    class ResetResponseModel(BaseModel):  # type: ignore
        """Reset response."""

        status: str
        session_id: str

    # NOTE: SessionInfoModel removed - /sessions endpoint was removed for security
    # (session enumeration attack vector)

    class DepsRequestModel(BaseModel):  # type: ignore
        """Request to install or uninstall packages."""

        packages: list[str]

    class DepsResponseModel(BaseModel):  # type: ignore
        """Response from package installation/uninstallation."""

        installed: list[str] = []
        already_present: list[str] = []
        removed: list[str] = []
        not_found: list[str] = []
        failed: list[str] = []


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
    deps_store: DepsStore | None = None
    deps_installer: PackageInstaller | None = None
    sessions: dict[str, Session] = field(default_factory=dict)
    start_time: float = 0.0
    redis_mode: bool = False


# Global state
_state = ServerState()


# Authentication helpers
# HTTPBearer with auto_error=False returns None instead of raising 401
# This lets us handle missing credentials ourselves for better error messages
BEARER_SCHEME = HTTPBearer(auto_error=False) if FASTAPI_AVAILABLE else None


def verify_auth_token(provided: str, expected: str) -> bool:
    """Verify auth token using timing-safe comparison.

    Args:
        provided: Token from Authorization header.
        expected: Expected token from config.

    Returns:
        True if tokens match, False otherwise.
    """
    return hmac.compare_digest(provided.encode(), expected.encode())


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

    # Create deps namespace if deps_store is available
    deps_namespace = None
    if _state.deps_store is not None and _state.deps_installer is not None:
        base_deps = DepsNamespace(_state.deps_store, _state.deps_installer)
        # Wrap if runtime deps disabled
        if not _state.config.allow_runtime_deps:
            deps_namespace = ControlledDepsNamespace(base_deps, allow_runtime=False)
        else:
            deps_namespace = base_deps

    # Create executor with shared registries but isolated namespace/artifacts
    executor = CodeExecutor(
        registry=_state.registry,
        skill_library=_state.skill_library,
        artifact_store=artifact_store,
        deps_namespace=deps_namespace,
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

        from py_code_mode.artifacts import RedisArtifactStore
        from py_code_mode.skills import RedisSkillStore
        from py_code_mode.storage import RedisToolStore, registry_from_redis

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

        # Deps from Redis
        # Derive deps prefix from tools prefix namespace (e.g., "myapp:tools" -> "myapp:deps")
        # If tools_prefix has no namespace separator, uses tools_prefix directly as base
        deps_prefix = os.environ.get("REDIS_DEPS_PREFIX", f"{tools_prefix.rsplit(':', 1)[0]}:deps")
        deps_store = RedisDepsStore(r, prefix=deps_prefix)
        deps_installer = PackageInstaller()
        logger.info("  Deps in Redis (%s): initialized", deps_prefix)

        _state = ServerState(
            config=config,
            registry=registry,
            skill_library=skill_library,
            artifact_store=artifact_store,
            deps_store=deps_store,
            deps_installer=deps_installer,
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
                registry.add_adapter(adapter=cli_adapter)

            # Also load MCP tools from the same directory
            mcp_registry = await ToolRegistry.from_dir(tools_path)
            for adapter in mcp_registry.get_adapters():
                registry.add_adapter(adapter=adapter)

            logger.info("  Tools in directory: %d", len(registry.list_tools()))
        else:
            # No TOOLS_PATH - no tools available
            logger.info("  TOOLS_PATH not set, no tools available")
            registry = ToolRegistry()

        skill_library = build_skill_library(config)

        # Create shared artifact store (same as Redis mode)
        config.artifacts_path.mkdir(parents=True, exist_ok=True)
        artifact_store = FileArtifactStore(config.artifacts_path)

        # Create deps store - use DEPS_PATH if mounted, otherwise derive from artifacts parent
        deps_path_env = os.environ.get("DEPS_PATH")
        if deps_path_env:
            # Deps directory is mounted directly at DEPS_PATH
            # FileDepsStore expects base_path where it creates deps/ subdirectory,
            # but if DEPS_PATH is set, the directory IS the deps directory
            deps_path = Path(deps_path_env)
            deps_path.mkdir(parents=True, exist_ok=True)
            # Create a store that uses deps_path directly (it's already the deps dir)
            # FileDepsStore expects {base_path}/deps, so we pass parent
            deps_store = FileDepsStore(deps_path.parent)
            logger.info("  Deps in file store (%s): initialized", deps_path)
        else:
            # No explicit DEPS_PATH, derive from artifacts parent
            deps_base = config.artifacts_path.parent
            deps_store = FileDepsStore(deps_base)
            logger.info("  Deps in file store (derived): initialized")
        deps_installer = PackageInstaller()

        _state = ServerState(
            config=config,
            registry=registry,
            skill_library=skill_library,
            artifact_store=artifact_store,
            deps_store=deps_store,
            deps_installer=deps_installer,
            sessions={},
            start_time=time.time(),
            redis_mode=False,
        )

    # Log authentication status (important for security awareness)
    if config.auth_disabled:
        logger.warning(
            "SECURITY: Authentication is DISABLED. "
            "This should only be used for local development. "
            "Set CONTAINER_AUTH_TOKEN for production deployments."
        )
    elif config.auth_token:
        logger.info("Authentication enabled with Bearer token")
    else:
        # This shouldn't happen (from_env validates), but log if it does
        logger.error("Authentication configuration missing - server may reject requests")


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

    # Authentication dependency - defined inside create_app to access config via closure
    async def require_auth(
        credentials: HTTPAuthorizationCredentials | None = Depends(BEARER_SCHEME),
    ) -> None:
        """Verify authentication for protected endpoints.

        Uses the config captured in closure to check auth settings.
        Fail-safe: any exception during auth check results in 500, not 200.
        """
        # Get config from state (set during lifespan startup)
        config = _state.config

        # Server not initialized - fail-safe with 500
        if config is None:
            raise HTTPException(status_code=500, detail="Server not initialized")

        # Auth explicitly disabled - allow all requests
        if config.auth_disabled:
            return

        # Auth enabled but no token configured - server misconfigured (fail-safe)
        if config.auth_token is None:
            raise HTTPException(status_code=500, detail="Server misconfigured")

        # No credentials provided - reject with 401
        if credentials is None:
            raise HTTPException(status_code=401, detail="Authorization required")

        # Verify scheme is exactly "Bearer" (case-sensitive for strict compliance)
        # HTTP allows case-insensitive schemes, but we enforce exact match for security
        if credentials.scheme != "Bearer":
            raise HTTPException(status_code=401, detail="Invalid authorization scheme")

        # Validate token provided is not empty/whitespace
        provided_token = credentials.credentials
        if not provided_token or not provided_token.strip():
            raise HTTPException(status_code=401, detail="Invalid token")

        # Verify token using timing-safe comparison (fail-safe wrapper)
        try:
            if not verify_auth_token(provided_token, config.auth_token):
                raise HTTPException(status_code=401, detail="Invalid token")
        except HTTPException:
            raise
        except Exception:
            # Any unexpected exception during verification - fail-safe with 500
            raise HTTPException(status_code=500, detail="Authentication error")

    @app.post("/execute", response_model=ExecuteResponseModel, dependencies=[Depends(require_auth)])
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
        """Health check endpoint.

        Does NOT require authentication - allows orchestrators (Kubernetes, Docker)
        to check container health without needing auth credentials.

        Does NOT expose active_sessions count (information leakage).
        """
        return HealthResponseModel(
            status="healthy",
            uptime_seconds=time.time() - _state.start_time,
        )

    @app.get("/info", response_model=InfoResponseModel, dependencies=[Depends(require_auth)])
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

    @app.post("/reset", response_model=ResetResponseModel, dependencies=[Depends(require_auth)])
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

    # NOTE: /sessions endpoint removed - session enumeration is an information disclosure risk

    @app.post(
        "/install_deps",
        response_model=DepsResponseModel,
        dependencies=[Depends(require_auth)],
    )
    async def install_deps(body: DepsRequestModel) -> DepsResponseModel:
        """Install packages in the container environment.

        This is a system-level API called by ContainerExecutor.install_deps().
        It installs pre-configured packages and is NOT affected by allow_runtime_deps.

        Agent-initiated installs via deps.add() are blocked by ControlledDepsNamespace
        when allow_runtime_deps=False.
        """
        # NOTE: This endpoint does NOT check allow_runtime_deps.
        # It's a system-level API for Session._sync_deps() to install pre-configured deps.
        # Agent-initiated installs are blocked at the namespace level by ControlledDepsNamespace.

        if _state.config is None:
            raise HTTPException(status_code=503, detail="Server not initialized")

        if _state.deps_store is None or _state.deps_installer is None:
            raise HTTPException(status_code=503, detail="Deps store not initialized")

        installed: list[str] = []
        failed: list[str] = []

        for pkg in body.packages:
            try:
                # Add to store and sync (DepsNamespace.add behavior)
                _state.deps_store.add(pkg)
                _state.deps_installer.sync(_state.deps_store)
                installed.append(pkg)
            except Exception as e:
                logger.warning("Failed to install %s: %s", pkg, e)
                failed.append(pkg)

        return DepsResponseModel(installed=installed, failed=failed)

    @app.post(
        "/uninstall_deps",
        response_model=DepsResponseModel,
        dependencies=[Depends(require_auth)],
    )
    async def uninstall_deps(body: DepsRequestModel) -> DepsResponseModel:
        """Uninstall packages from the container environment.

        This is a system-level API called by ContainerExecutor.uninstall_deps().
        It uninstalls packages and is NOT affected by allow_runtime_deps.

        Agent-initiated removals via deps.remove() are blocked by ControlledDepsNamespace
        when allow_runtime_deps=False.

        Note: This removes packages but does not modify the deps store.
        """
        # NOTE: This endpoint does NOT check allow_runtime_deps.
        # It's a system-level API for Session.remove_dep() to uninstall packages.
        # Agent-initiated removals are blocked at the namespace level by ControlledDepsNamespace.

        if _state.config is None:
            raise HTTPException(status_code=503, detail="Server not initialized")

        removed: list[str] = []
        failed: list[str] = []

        for pkg in body.packages:
            # Validate package name to prevent flag injection
            if pkg.startswith("-"):
                logger.warning("Invalid package name (starts with '-'): %s", pkg)
                failed.append(pkg)
                continue

            try:
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "uninstall", "-y", pkg],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if result.returncode == 0:
                    removed.append(pkg)
                else:
                    logger.warning("Failed to uninstall %s: %s", pkg, result.stderr)
                    failed.append(pkg)
            except Exception as e:
                logger.warning("Failed to uninstall %s: %s", pkg, e)
                failed.append(pkg)

        return DepsResponseModel(removed=removed, failed=failed)

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
