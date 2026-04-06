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
from py_code_mode.deps.store import _package_base_name  # noqa: E402
from py_code_mode.errors import ArtifactNotFoundError  # noqa: E402
from py_code_mode.execution.container.config import SessionConfig  # noqa: E402
from py_code_mode.execution.in_process import (  # noqa: E402
    InProcessExecutor as CodeExecutor,
)
from py_code_mode.storage.backends import _validate_workspace_id  # noqa: E402
from py_code_mode.tools import ToolRegistry  # noqa: E402
from py_code_mode.workflows import (  # noqa: E402
    FileWorkflowStore,
    WorkflowLibrary,
    create_workflow_library,
)

# Session expiration (seconds)
SESSION_EXPIRY = 3600  # 1 hour


def serialize_value(value: Any) -> Any:
    """Serialize a value for JSON response.

    Recursively converts dataclasses and frozensets to JSON-serializable types.
    """
    if value is None:
        return None
    if isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, dict):
        return {k: serialize_value(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
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
        workflows: list[dict[str, str]]
        artifacts_path: str

    class ResetResponseModel(BaseModel):  # type: ignore
        """Reset response."""

        status: str
        session_id: str

    class CreateSessionRequestModel(BaseModel):  # type: ignore
        """Request to create a bound remote session."""

        workspace_id: str | None = None

    class SessionResponseModel(BaseModel):  # type: ignore
        """Response containing a created session ID."""

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

    # ==========================================================================
    # API Endpoint Request/Response Models
    # ==========================================================================

    class CreateWorkflowRequest(BaseModel):  # type: ignore
        """Request to create a new workflow."""

        name: str
        source: str
        description: str

    class WorkflowResponse(BaseModel):  # type: ignore
        """Response for workflow information."""

        name: str
        description: str
        params: dict[str, str]
        source: str

    class SaveArtifactRequest(BaseModel):  # type: ignore
        """Request to save an artifact."""

        name: str
        data: Any
        description: str = ""
        metadata: dict[str, Any] | None = None

    class ArtifactResponse(BaseModel):  # type: ignore
        """Response for artifact information."""

        name: str
        path: str
        description: str
        metadata: dict[str, Any]
        created_at: str

    class AddDepRequest(BaseModel):  # type: ignore
        """Request to add a dependency."""

        package: str

    class RemoveDepRequest(BaseModel):  # type: ignore
        """Request to remove a dependency."""

        package: str

    class RemoveDepResponseModel(BaseModel):  # type: ignore
        """Response from removing a configured dependency."""

        removed: list[str] = []
        not_found: list[str] = []
        failed: list[str] = []
        removed_from_config: bool = False

    class DepsSyncResult(BaseModel):  # type: ignore
        """Response from deps sync operation."""

        installed: list[str] = []
        already_present: list[str] = []
        failed: list[str] = []


@dataclass
class WorkspaceBundle:
    """Shared workflow/artifact state for one workspace scope."""

    workspace_id: str | None
    workflow_library: WorkflowLibrary | None
    artifact_store: ArtifactStoreProtocol
    artifacts_path: str


@dataclass
class Session:
    """Individual session state with isolated Python state and bound storage."""

    session_id: str
    executor: CodeExecutor
    workflow_library: WorkflowLibrary | None
    artifact_store: ArtifactStoreProtocol
    workspace_id: str | None = None
    artifacts_path: str = ""
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    execution_count: int = 0


@dataclass
class ServerState:
    """Global server state."""

    config: SessionConfig | None = None
    registry: ToolRegistry | None = None
    workflow_library: WorkflowLibrary | None = None
    artifact_store: ArtifactStoreProtocol | None = None  # Shared store for Redis mode
    deps_store: DepsStore | None = None
    deps_installer: PackageInstaller | None = None
    sessions: dict[str, Session] = field(default_factory=dict)
    start_time: float = 0.0
    redis_mode: bool = False
    default_bundle: WorkspaceBundle | None = None
    workspace_bundles: dict[str, WorkspaceBundle] = field(default_factory=dict)
    redis_client: Any | None = None
    redis_workflows_prefix: str | None = None
    redis_artifacts_prefix: str | None = None


# Global state
_state = ServerState()


# Authentication helpers
# HTTPBearer with auto_error=False returns None instead of raising 401
# This lets us handle missing credentials ourselves for better error messages
if FASTAPI_AVAILABLE:
    BEARER_SCHEME = HTTPBearer(auto_error=False)
else:
    BEARER_SCHEME = None


def verify_auth_token(provided: str, expected: str) -> bool:
    """Verify auth token using timing-safe comparison.

    Args:
        provided: Token from Authorization header.
        expected: Expected token from config.

    Returns:
        True if tokens match, False otherwise.
    """
    return hmac.compare_digest(provided.encode(), expected.encode())


def build_workflow_library(config: SessionConfig) -> WorkflowLibrary | None:
    """Build workflow library from configuration."""
    try:
        config.workflows_path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.warning("Cannot create workflows directory at %s: %s", config.workflows_path, e)
        return None

    store = FileWorkflowStore(config.workflows_path)
    return create_workflow_library(store=store)


def build_workflow_library_for_path(workflows_path: Path) -> WorkflowLibrary | None:
    """Build a file-backed workflow library for the given path."""
    try:
        workflows_path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.warning("Cannot create workflows directory at %s: %s", workflows_path, e)
        return None

    store = FileWorkflowStore(workflows_path)
    return create_workflow_library(store=store)


def build_workflow_library_for_redis(redis_client: Any, prefix: str) -> WorkflowLibrary:
    """Build a Redis-backed workflow library for the given prefix."""
    from py_code_mode.workflows import RedisWorkflowStore

    store = RedisWorkflowStore(redis_client, prefix=prefix)
    return create_workflow_library(store=store)


def get_default_bundle() -> WorkspaceBundle:
    """Return the legacy unscoped bundle."""
    if _state.default_bundle is None:
        raise RuntimeError("Default workspace bundle not initialized")
    return _state.default_bundle


def _derive_redis_root_prefix(
    workflows_prefix: str | None,
    artifacts_prefix: str | None,
) -> str | None:
    """Derive a shared Redis root prefix from legacy workflow/artifact prefixes."""
    if workflows_prefix is None or artifacts_prefix is None:
        return None
    if not workflows_prefix.endswith(":workflows") or not artifacts_prefix.endswith(":artifacts"):
        return None

    workflows_root = workflows_prefix[: -len(":workflows")]
    artifacts_root = artifacts_prefix[: -len(":artifacts")]
    if workflows_root != artifacts_root:
        return None
    if ":ws:" in workflows_root:
        return None
    return workflows_root


def build_workspace_bundle(workspace_id: str) -> WorkspaceBundle:
    """Build a cached workflow/artifact bundle for one workspace."""
    workspace_id = _validate_workspace_id(workspace_id)
    config = _state.config
    if config is None:
        raise RuntimeError("Server not initialized")

    if _state.redis_mode:
        if _state.redis_client is None:
            raise RuntimeError("Redis client not initialized")

        storage_prefix = config.storage_prefix or _derive_redis_root_prefix(
            _state.redis_workflows_prefix,
            _state.redis_artifacts_prefix,
        )
        if storage_prefix is None:
            raise RuntimeError("Workspace-scoped Redis storage requires an explicit storage_prefix")

        workflow_prefix = f"{storage_prefix}:ws:{workspace_id}:workflows"
        artifact_prefix = f"{storage_prefix}:ws:{workspace_id}:artifacts"
        workflow_library = build_workflow_library_for_redis(_state.redis_client, workflow_prefix)

        from py_code_mode.artifacts import RedisArtifactStore

        artifact_store = RedisArtifactStore(_state.redis_client, prefix=artifact_prefix)
        return WorkspaceBundle(
            workspace_id=workspace_id,
            workflow_library=workflow_library,
            artifact_store=artifact_store,
            artifacts_path=artifact_prefix,
        )

    storage_base_path = config.storage_base_path
    if storage_base_path is not None:
        workspace_root = storage_base_path / "workspaces" / workspace_id
        workflows_path = workspace_root / "workflows"
        artifacts_path = workspace_root / "artifacts"
    else:
        workflows_path = (
            config.workflows_path.parent / "workspaces" / workspace_id / config.workflows_path.name
        )
        artifacts_path = (
            config.artifacts_path.parent / "workspaces" / workspace_id / config.artifacts_path.name
        )

    workflow_library = build_workflow_library_for_path(workflows_path)
    artifacts_path.mkdir(parents=True, exist_ok=True)
    artifact_store = FileArtifactStore(artifacts_path)
    return WorkspaceBundle(
        workspace_id=workspace_id,
        workflow_library=workflow_library,
        artifact_store=artifact_store,
        artifacts_path=str(artifacts_path),
    )


def get_workspace_bundle(workspace_id: str | None) -> WorkspaceBundle:
    """Return the default or scoped bundle for a request/session."""
    if workspace_id is None:
        return get_default_bundle()

    bundle = _state.workspace_bundles.get(workspace_id)
    if bundle is not None:
        return bundle

    bundle = build_workspace_bundle(workspace_id)
    _state.workspace_bundles[workspace_id] = bundle
    return bundle


def create_session(session_id: str, workspace_id: str | None = None) -> Session:
    """Create a new isolated Python session bound to a storage bundle."""
    config = _state.config
    if config is None:
        raise RuntimeError("Server not initialized")

    bundle = get_workspace_bundle(workspace_id)

    # Create deps namespace if deps_store is available
    deps_namespace = None
    if _state.deps_store is not None and _state.deps_installer is not None:
        base_deps = DepsNamespace(_state.deps_store, _state.deps_installer)
        # Wrap if runtime deps disabled
        if not config.allow_runtime_deps:
            deps_namespace = ControlledDepsNamespace(base_deps, allow_runtime=False)
        else:
            deps_namespace = base_deps

    # Create executor with shared registries but isolated namespace/artifacts
    executor = CodeExecutor(
        registry=_state.registry,
        workflow_library=bundle.workflow_library,
        artifact_store=bundle.artifact_store,
        deps_namespace=deps_namespace,
        default_timeout=config.default_timeout,
    )

    return Session(
        session_id=session_id,
        executor=executor,
        workflow_library=bundle.workflow_library,
        artifact_store=bundle.artifact_store,
        workspace_id=workspace_id,
        artifacts_path=bundle.artifacts_path,
    )


def create_new_session(workspace_id: str | None = None) -> Session:
    """Create a new isolated session with a server-issued ID."""
    session_id = str(uuid.uuid4())
    session = create_session(session_id, workspace_id=workspace_id)
    _state.sessions[session_id] = session
    return session


def get_existing_session(session_id: str) -> Session | None:
    """Get an existing session if present."""
    session = _state.sessions.get(session_id)
    if session is not None:
        session.last_used = time.time()
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


def get_bound_session(session_id: str | None) -> Session:
    """Resolve a request's bound session or raise 400."""
    cleanup_expired_sessions()
    if session_id is None:
        raise HTTPException(status_code=400, detail="Invalid session ID")

    session = get_existing_session(session_id)
    if session is None:
        raise HTTPException(status_code=400, detail="Invalid session ID")
    return session


def get_request_bundle(session_id: str | None) -> WorkspaceBundle:
    """Resolve the effective workflow/artifact bundle for a request."""
    session = get_bound_session(session_id)
    return WorkspaceBundle(
        workspace_id=session.workspace_id,
        workflow_library=session.workflow_library,
        artifact_store=session.artifact_store,
        artifacts_path=session.artifacts_path,
    )


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

    When REDIS_URL is set, uses Redis for tools, workflows, and artifacts.
    Otherwise falls back to file-based storage.
    """
    global _state

    # Install Python dependencies from config
    if config.python_deps:
        install_python_deps(config.python_deps)

    redis_url = config.redis_url or os.environ.get("REDIS_URL")

    if redis_url:
        # Redis mode: load everything from Redis with semantic search
        import redis as redis_lib

        from py_code_mode.artifacts import RedisArtifactStore
        from py_code_mode.storage import RedisToolStore, registry_from_redis
        from py_code_mode.workflows import RedisWorkflowStore

        logger.info("Using Redis backend: %s...", redis_url[:50])
        r = redis_lib.from_url(redis_url)

        # Get prefixes from environment (set by ContainerExecutor), with defaults
        tools_prefix = os.environ.get("REDIS_TOOLS_PREFIX", "tools")
        workflows_prefix = os.environ.get(
            "REDIS_WORKFLOWS_PREFIX",
            f"{config.storage_prefix}:workflows" if config.storage_prefix else "workflows",
        )
        artifacts_prefix = os.environ.get(
            "REDIS_ARTIFACTS_PREFIX",
            f"{config.storage_prefix}:artifacts" if config.storage_prefix else "artifacts",
        )

        # Tools from Redis
        tool_store = RedisToolStore(r, prefix=tools_prefix)
        registry = await registry_from_redis(tool_store)
        logger.info("  Tools in Redis (%s): %d", tools_prefix, len(tool_store))

        # Workflows from Redis
        redis_store = RedisWorkflowStore(r, prefix=workflows_prefix)
        workflow_library = create_workflow_library(store=redis_store)
        workflow_count = len(redis_store)
        logger.info("  Workflows in Redis (%s): %d (semantic)", workflows_prefix, workflow_count)

        # Artifacts in Redis (shared across sessions)
        artifact_store = RedisArtifactStore(r, prefix=artifacts_prefix)

        # Deps from Redis
        # Deps use the root Redis prefix. RedisDepsStore appends ":deps" internally.
        deps_prefix = os.environ.get("REDIS_DEPS_PREFIX", tools_prefix.rsplit(":", 1)[0])
        deps_store = RedisDepsStore(r, prefix=deps_prefix)
        deps_installer = PackageInstaller()
        logger.info("  Deps in Redis (%s): initialized", deps_prefix)

        # Pre-populate deps store with CONTAINER_DEPS if set
        container_deps = os.environ.get("CONTAINER_DEPS")
        if container_deps and deps_store is not None:
            for dep in container_deps.split(","):
                dep = dep.strip()
                if dep:
                    deps_store.add(dep)
            logger.info("  Pre-configured deps: %s", container_deps)

        default_bundle = WorkspaceBundle(
            workspace_id=None,
            workflow_library=workflow_library,
            artifact_store=artifact_store,
            artifacts_path=artifacts_prefix,
        )

        _state = ServerState(
            config=config,
            registry=registry,
            workflow_library=workflow_library,
            artifact_store=artifact_store,
            deps_store=deps_store,
            deps_installer=deps_installer,
            sessions={},
            start_time=time.time(),
            redis_mode=True,
            default_bundle=default_bundle,
            workspace_bundles={},
            redis_client=r,
            redis_workflows_prefix=workflows_prefix,
            redis_artifacts_prefix=artifacts_prefix,
        )
    else:
        # File mode: load from config paths
        logger.info("Using file-based backend (set REDIS_URL for Redis mode)")

        # Load tools from mounted directory if TOOLS_PATH is set
        tools_path = os.environ.get("TOOLS_PATH")
        if tools_path:
            logger.info("  Loading tools from directory: %s", tools_path)
            registry = await ToolRegistry.from_dir(tools_path)
            logger.info("  Tools in directory: %d", len(registry.list_tools()))
        else:
            # No TOOLS_PATH - no tools available
            logger.info("  TOOLS_PATH not set, no tools available")
            registry = ToolRegistry()

        workflow_library = build_workflow_library(config)

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

        # Pre-populate deps store with CONTAINER_DEPS if set
        container_deps = os.environ.get("CONTAINER_DEPS")
        if container_deps and deps_store is not None:
            for dep in container_deps.split(","):
                dep = dep.strip()
                if dep:
                    deps_store.add(dep)
            logger.info("  Pre-configured deps: %s", container_deps)

        default_bundle = WorkspaceBundle(
            workspace_id=None,
            workflow_library=workflow_library,
            artifact_store=artifact_store,
            artifacts_path=str(config.artifacts_path),
        )

        _state = ServerState(
            config=config,
            registry=registry,
            workflow_library=workflow_library,
            artifact_store=artifact_store,
            deps_store=deps_store,
            deps_installer=deps_installer,
            sessions={},
            start_time=time.time(),
            redis_mode=False,
            default_bundle=default_bundle,
            workspace_bundles={},
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

        Pass X-Session-ID header to use a specific bound session.
        """
        if _state.config is None:
            raise HTTPException(status_code=503, detail="Server not initialized")

        session = get_bound_session(x_session_id)

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

    @app.post(
        "/sessions",
        response_model=SessionResponseModel,
        dependencies=[Depends(require_auth)],
    )
    async def create_bound_session(body: CreateSessionRequestModel) -> SessionResponseModel:
        """Create a new session optionally bound to a workspace-scoped bundle."""
        try:
            workspace_id = (
                _validate_workspace_id(body.workspace_id) if body.workspace_id is not None else None
            )
            session = create_new_session(workspace_id=workspace_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e))

        return SessionResponseModel(session_id=session.session_id)

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
    async def info(
        x_session_id: str | None = Header(None, alias="X-Session-ID"),
    ) -> InfoResponseModel:
        """Get information about available tools and workflows."""
        bundle = get_request_bundle(x_session_id)
        tools = []
        if _state.registry:
            for tool in _state.registry.list_tools():
                tools.append({"name": tool.name, "description": tool.description})

        workflows = []
        if bundle.workflow_library is not None:
            bundle.workflow_library.refresh()
            for workflow in bundle.workflow_library.list():
                workflows.append({"name": workflow.name, "description": workflow.description})

        return InfoResponseModel(
            tools=tools,
            workflows=workflows,
            artifacts_path=bundle.artifacts_path,
        )

    @app.post("/reset", response_model=ResetResponseModel, dependencies=[Depends(require_auth)])
    async def reset(
        x_session_id: str | None = Header(None, alias="X-Session-ID"),
    ) -> ResetResponseModel:
        """Reset a session (clears namespace, keeps artifacts)."""
        if x_session_id is None or x_session_id not in _state.sessions:
            raise HTTPException(status_code=400, detail="Invalid session ID")

        del _state.sessions[x_session_id]

        return ResetResponseModel(
            status="reset",
            session_id=x_session_id,
        )

    # Only POST /sessions is exposed. Enumeration/listing endpoints remain unavailable.

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
        not_found: list[str] = []
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
                output = f"{result.stdout}\n{result.stderr}".lower()
                if "not installed" in output or "skipping" in output:
                    not_found.append(pkg)
                elif result.returncode == 0:
                    removed.append(pkg)
                else:
                    logger.warning("Failed to uninstall %s: %s", pkg, result.stderr)
                    failed.append(pkg)
            except Exception as e:
                logger.warning("Failed to uninstall %s: %s", pkg, e)
                failed.append(pkg)

        return DepsResponseModel(removed=removed, not_found=not_found, failed=failed)

    # ==========================================================================
    # Tools API Endpoints
    # ==========================================================================

    @app.get("/api/tools", dependencies=[Depends(require_auth)])
    async def api_list_tools() -> list[dict[str, Any]]:
        """Return all registered tools."""
        if _state.registry is None:
            return []

        return [tool.to_dict() for tool in _state.registry.get_all_tools()]

    @app.get("/api/tools/search", dependencies=[Depends(require_auth)])
    async def api_search_tools(query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search tools by query."""
        if _state.registry is None:
            return []

        from py_code_mode.tools.registry import substring_search

        tools = substring_search(
            query=query,
            items=_state.registry.get_all_tools(),
            get_name=lambda t: t.name,
            get_description=lambda t: t.description,
            limit=limit,
        )
        return [tool.to_dict() for tool in tools]

    # ==========================================================================
    # Workflows API Endpoints
    # ==========================================================================

    @app.get("/api/workflows", dependencies=[Depends(require_auth)])
    async def api_list_workflows(
        x_session_id: str | None = Header(None, alias="X-Session-ID"),
    ) -> list[dict[str, Any]]:
        """Return all workflows."""
        bundle = get_request_bundle(x_session_id)
        if bundle.workflow_library is None:
            raise HTTPException(status_code=503, detail="Workflow library not initialized")

        bundle.workflow_library.refresh()
        workflows = bundle.workflow_library.list()
        return [
            {
                "name": workflow.name,
                "description": workflow.description,
                "params": {p.name: p.description or p.type for p in workflow.parameters},
            }
            for workflow in workflows
        ]

    @app.get("/api/workflows/search", dependencies=[Depends(require_auth)])
    async def api_search_workflows(
        query: str,
        limit: int = 5,
        x_session_id: str | None = Header(None, alias="X-Session-ID"),
    ) -> list[dict[str, Any]]:
        """Search workflows."""
        bundle = get_request_bundle(x_session_id)
        if bundle.workflow_library is None:
            raise HTTPException(status_code=503, detail="Workflow library not initialized")

        bundle.workflow_library.refresh()
        workflows = bundle.workflow_library.search(query, limit=limit)
        return [
            {
                "name": workflow.name,
                "description": workflow.description,
                "params": {p.name: p.description or p.type for p in workflow.parameters},
            }
            for workflow in workflows
        ]

    @app.get("/api/workflows/{name}", dependencies=[Depends(require_auth)])
    async def api_get_workflow(
        name: str,
        x_session_id: str | None = Header(None, alias="X-Session-ID"),
    ) -> dict[str, Any] | None:
        """Get workflow by name with full source."""
        bundle = get_request_bundle(x_session_id)
        if bundle.workflow_library is None:
            raise HTTPException(status_code=503, detail="Workflow library not initialized")

        bundle.workflow_library.refresh()
        workflow = bundle.workflow_library.get(name)
        if workflow is None:
            return None

        return {
            "name": workflow.name,
            "description": workflow.description,
            "params": {p.name: p.description or p.type for p in workflow.parameters},
            "source": workflow.source,
        }

    @app.post("/api/workflows", dependencies=[Depends(require_auth)])
    async def api_create_workflow(
        body: CreateWorkflowRequest,
        x_session_id: str | None = Header(None, alias="X-Session-ID"),
    ) -> dict[str, Any]:
        """Create a new workflow."""
        bundle = get_request_bundle(x_session_id)
        if bundle.workflow_library is None:
            raise HTTPException(status_code=503, detail="Workflow library not initialized")

        from py_code_mode.workflows import PythonWorkflow

        try:
            workflow = PythonWorkflow.from_source(
                name=body.name,
                source=body.source,
                description=body.description,
            )
            bundle.workflow_library.add(workflow)
            return {
                "name": workflow.name,
                "description": workflow.description,
                "params": {p.name: p.description or p.type for p in workflow.parameters},
                "source": workflow.source,
            }
        except (ValueError, SyntaxError) as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.delete("/api/workflows/{name}", dependencies=[Depends(require_auth)])
    async def api_delete_workflow(
        name: str,
        x_session_id: str | None = Header(None, alias="X-Session-ID"),
    ) -> bool:
        """Delete a workflow."""
        bundle = get_request_bundle(x_session_id)
        if bundle.workflow_library is None:
            return False

        return bundle.workflow_library.remove(name)

    # ==========================================================================
    # Artifacts API Endpoints
    # ==========================================================================

    @app.get("/api/artifacts", dependencies=[Depends(require_auth)])
    async def api_list_artifacts(
        x_session_id: str | None = Header(None, alias="X-Session-ID"),
    ) -> list[dict[str, Any]]:
        """List all artifacts with metadata."""
        bundle = get_request_bundle(x_session_id)
        artifacts = bundle.artifact_store.list()
        return [
            {
                "name": artifact.name,
                "path": artifact.path,
                "description": artifact.description,
                "metadata": artifact.metadata,
                "created_at": artifact.created_at.isoformat(),
            }
            for artifact in artifacts
        ]

    @app.get("/api/artifacts/{name}", dependencies=[Depends(require_auth)])
    async def api_load_artifact(
        name: str,
        x_session_id: str | None = Header(None, alias="X-Session-ID"),
    ) -> Any:
        """Load artifact data."""
        bundle = get_request_bundle(x_session_id)

        try:
            return bundle.artifact_store.load(name)
        except ArtifactNotFoundError:
            raise HTTPException(status_code=404, detail=f"Artifact '{name}' not found")

    @app.post("/api/artifacts", dependencies=[Depends(require_auth)])
    async def api_save_artifact(
        body: SaveArtifactRequest,
        x_session_id: str | None = Header(None, alias="X-Session-ID"),
    ) -> dict[str, Any]:
        """Save artifact."""
        bundle = get_request_bundle(x_session_id)

        artifact = bundle.artifact_store.save(
            name=body.name,
            data=body.data,
            description=body.description,
            metadata=body.metadata,
        )
        return {
            "name": artifact.name,
            "path": artifact.path,
            "description": artifact.description,
            "metadata": artifact.metadata,
            "created_at": artifact.created_at.isoformat(),
        }

    @app.delete("/api/artifacts/{name}", dependencies=[Depends(require_auth)])
    async def api_delete_artifact(
        name: str,
        x_session_id: str | None = Header(None, alias="X-Session-ID"),
    ) -> None:
        """Delete artifact."""
        bundle = get_request_bundle(x_session_id)

        if not bundle.artifact_store.exists(name):
            raise HTTPException(status_code=404, detail=f"Artifact '{name}' not found")

        bundle.artifact_store.delete(name)

    # ==========================================================================
    # Deps API Endpoints
    # ==========================================================================

    @app.get("/api/deps", dependencies=[Depends(require_auth)])
    async def api_list_deps() -> list[str]:
        """List configured packages."""
        if _state.deps_store is None:
            return []

        return _state.deps_store.list()

    @app.post("/api/deps/add", dependencies=[Depends(require_auth)])
    async def api_add_dep(body: AddDepRequest) -> dict[str, Any]:
        """Add and install a package.

        This endpoint respects allow_runtime_deps configuration.
        """
        if _state.config is None:
            raise HTTPException(status_code=503, detail="Server not initialized")

        if _state.deps_store is None or _state.deps_installer is None:
            raise HTTPException(status_code=503, detail="Deps store not initialized")

        if not _state.config.allow_runtime_deps:
            raise HTTPException(
                status_code=403,
                detail="Runtime dependency installation is disabled",
            )

        try:
            _state.deps_store.add(body.package)
            result = _state.deps_installer.sync(_state.deps_store)
            return {
                "installed": list(result.installed),
                "already_present": list(result.already_present),
                "failed": list(result.failed),
            }
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post(
        "/api/deps/remove",
        response_model=RemoveDepResponseModel,
        dependencies=[Depends(require_auth)],
    )
    async def api_remove_dep(body: RemoveDepRequest) -> RemoveDepResponseModel:
        """Remove a package from configuration and uninstall it from the container.

        This endpoint respects allow_runtime_deps configuration.
        """
        if _state.config is None:
            raise HTTPException(status_code=503, detail="Server not initialized")

        if _state.deps_store is None:
            raise HTTPException(status_code=503, detail="Deps store not initialized")

        if not _state.config.allow_runtime_deps:
            raise HTTPException(
                status_code=403,
                detail="Runtime dependency modification is disabled",
            )

        package_name = _package_base_name(body.package)
        removed_from_config = _state.deps_store.remove(body.package)
        if not removed_from_config:
            return RemoveDepResponseModel(
                removed=[],
                not_found=[package_name],
                failed=[],
                removed_from_config=False,
            )

        uninstall_result = await uninstall_deps(DepsRequestModel(packages=[package_name]))
        return RemoveDepResponseModel(
            removed=list(uninstall_result.removed),
            not_found=list(uninstall_result.not_found),
            failed=list(uninstall_result.failed),
            removed_from_config=True,
        )

    @app.post("/api/deps/sync", dependencies=[Depends(require_auth)])
    async def api_sync_deps() -> dict[str, Any]:
        """Install all configured packages.

        This endpoint is always allowed, even when allow_runtime_deps=False,
        because it only installs pre-configured packages.
        """
        if _state.deps_store is None or _state.deps_installer is None:
            raise HTTPException(status_code=503, detail="Deps store not initialized")

        result = _state.deps_installer.sync(_state.deps_store)
        return {
            "installed": list(result.installed),
            "already_present": list(result.already_present),
            "failed": list(result.failed),
        }

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
