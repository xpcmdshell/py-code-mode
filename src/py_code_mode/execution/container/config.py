"""Configuration schemas for container execution."""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Default Docker image for container execution
DEFAULT_IMAGE = "py-code-mode-tools:latest"


@dataclass
class MCPServerConfig:
    """Configuration for an MCP server in the container."""

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class SessionConfig:
    """Configuration for the session server inside the container.

    Loaded from environment variables and/or YAML config files.
    """

    # Tools (MCP servers only - CLI tools loaded via TOOLS_PATH)
    mcp_servers: list[MCPServerConfig] = field(default_factory=list)

    # Python dependencies (auto-installed at startup)
    python_deps: list[str] = field(default_factory=list)

    # Skills
    skills_path: Path = field(default_factory=lambda: Path("/app/skills"))

    # Artifacts
    artifacts_path: Path = field(default_factory=lambda: Path("/workspace/artifacts"))
    artifact_backend: str = "file"  # "file" or "redis"
    redis_url: str | None = None

    # Execution
    default_timeout: float = 30.0
    max_execution_time: float = 300.0

    # Server
    host: str = "0.0.0.0"
    port: int = 8080

    # Deps configuration
    allow_runtime_deps: bool = True

    # Authentication
    auth_token: str | None = None  # Bearer token for API authentication
    auth_disabled: bool = False  # Explicit opt-out of authentication

    @classmethod
    def from_yaml(cls, path: Path) -> SessionConfig:
        """Load configuration from YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f) or {}

        return cls._from_dict(data)

    @classmethod
    def from_env(cls) -> SessionConfig:
        """Load configuration from environment variables.

        Raises:
            ValueError: If neither CONTAINER_AUTH_TOKEN nor CONTAINER_AUTH_DISABLED=true
                       is set. Server requires explicit auth configuration (fail-closed).
        """
        config = cls()

        # Load paths from env
        if skills_path := os.environ.get("SKILLS_PATH"):
            config.skills_path = Path(skills_path)
        if artifacts_path := os.environ.get("ARTIFACTS_PATH"):
            config.artifacts_path = Path(artifacts_path)

        # Artifact backend
        if backend := os.environ.get("ARTIFACT_BACKEND"):
            config.artifact_backend = backend
        if redis_url := os.environ.get("REDIS_URL"):
            config.redis_url = redis_url

        # Timeouts
        if timeout := os.environ.get("DEFAULT_TIMEOUT"):
            config.default_timeout = float(timeout)
        if max_time := os.environ.get("MAX_EXECUTION_TIME"):
            config.max_execution_time = float(max_time)

        # Server
        if host := os.environ.get("HOST"):
            config.host = host
        if port := os.environ.get("PORT"):
            config.port = int(port)

        # Deps configuration
        if allow_runtime_deps_str := os.environ.get("ALLOW_RUNTIME_DEPS"):
            config.allow_runtime_deps = allow_runtime_deps_str.lower() in ("true", "1", "yes")

        # Load tools config if specified
        if tools_config := os.environ.get("TOOLS_CONFIG"):
            tools_path = Path(tools_config)
            if tools_path.exists():
                with open(tools_path) as f:
                    tools_data = yaml.safe_load(f) or {}
                config.mcp_servers = cls._parse_mcp_servers(tools_data.get("mcp_servers", []))
                config.python_deps = tools_data.get("python_deps", [])

        # Authentication configuration (FAIL-CLOSED)
        # Server requires either an auth token OR explicit disable flag
        auth_token = os.environ.get("CONTAINER_AUTH_TOKEN")
        auth_disabled_str = os.environ.get("CONTAINER_AUTH_DISABLED", "").lower()
        auth_disabled = auth_disabled_str == "true"

        # Empty string token is not valid - treat as missing
        if auth_token is not None and auth_token.strip() == "":
            auth_token = None

        if auth_token is None and not auth_disabled:
            raise ValueError(
                "Server authentication requires CONTAINER_AUTH_TOKEN or "
                "CONTAINER_AUTH_DISABLED=true. Set one of these environment "
                "variables to start the server."
            )

        config.auth_token = auth_token
        config.auth_disabled = auth_disabled

        return config

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> SessionConfig:
        """Create config from dictionary."""
        return cls(
            mcp_servers=cls._parse_mcp_servers(data.get("mcp_servers", [])),
            python_deps=data.get("python_deps", []),
            skills_path=Path(data.get("skills_path", "/app/skills")),
            artifacts_path=Path(data.get("artifacts_path", "/workspace/artifacts")),
            artifact_backend=data.get("artifact_backend", "file"),
            redis_url=data.get("redis_url"),
            default_timeout=data.get("default_timeout", 30.0),
            max_execution_time=data.get("max_execution_time", 300.0),
            host=data.get("host", "0.0.0.0"),
            port=data.get("port", 8080),
            allow_runtime_deps=data.get("allow_runtime_deps", True),
        )

    @staticmethod
    def _parse_mcp_servers(servers_data: list[dict[str, Any]]) -> list[MCPServerConfig]:
        """Parse MCP server configurations."""
        return [
            MCPServerConfig(
                name=s["name"],
                command=s["command"],
                args=s.get("args", []),
                env=s.get("env", {}),
            )
            for s in servers_data
        ]


@dataclass
class ContainerConfig:
    """Configuration for ContainerExecutor on the host side.

    Controls how to start and connect to the container.
    This is RUNTIME configuration only - storage access is passed
    separately to executor.start().
    """

    # Image
    image: str = DEFAULT_IMAGE
    auto_build: bool = True  # Auto-build image if missing

    # Networking
    port: int = 0  # 0 = auto-assign
    host: str = "localhost"

    # Timeouts
    timeout: float = 30.0
    startup_timeout: float = 60.0
    health_check_interval: float = 0.5

    # Container settings
    environment: dict[str, str] = field(default_factory=dict)
    remove_on_exit: bool = True
    name: str | None = None  # Container name (auto-generated if None)

    # Deps configuration
    allow_runtime_deps: bool = True

    # Authentication (auth ENABLED by default, opt-out required)
    auth_token: str | None = None  # Bearer token for container API authentication
    auth_disabled: bool = False  # Explicit opt-out for local development only

    def to_docker_config(
        self,
        tools_path: Path | None = None,
        skills_path: Path | None = None,
        artifacts_path: Path | None = None,
        deps_path: Path | None = None,
        redis_url: str | None = None,
        tools_prefix: str | None = None,
        skills_prefix: str | None = None,
        artifacts_prefix: str | None = None,
        deps_prefix: str | None = None,
    ) -> dict[str, Any]:
        """Convert to Docker SDK configuration.

        Args:
            tools_path: Host path to tools directory (volume mount).
            skills_path: Host path to skills directory (volume mount).
            artifacts_path: Host path to artifacts directory (volume mount).
            deps_path: Host path to deps directory (volume mount).
            redis_url: Redis URL for Redis-based storage (sets env vars).
            tools_prefix: Redis key prefix for tools.
            skills_prefix: Redis key prefix for skills.
            artifacts_prefix: Redis key prefix for artifacts.
            deps_prefix: Redis key prefix for dependencies.

        Returns:
            Docker SDK run() configuration dict.
        """
        config: dict[str, Any] = {
            "image": self.image,
            "detach": True,
            "remove": self.remove_on_exit,
            "environment": {**self.environment},
        }

        # Add port binding
        if self.port > 0:
            config["ports"] = {"8080/tcp": self.port}
        else:
            config["ports"] = {"8080/tcp": None}  # Auto-assign

        # Add volumes from storage access
        volumes = {}
        if tools_path:
            volumes[str(tools_path.absolute())] = {
                "bind": "/app/tools",
                "mode": "ro",
            }
            config["environment"]["TOOLS_PATH"] = "/app/tools"
        if skills_path:
            volumes[str(skills_path.absolute())] = {
                "bind": "/app/skills",
                "mode": "rw",  # Agents create skills via skills.create()
            }
            config["environment"]["SKILLS_PATH"] = "/app/skills"
        if artifacts_path:
            volumes[str(artifacts_path.absolute())] = {
                "bind": "/workspace/artifacts",
                "mode": "rw",
            }
            config["environment"]["ARTIFACTS_PATH"] = "/workspace/artifacts"
        if deps_path:
            volumes[str(deps_path.absolute())] = {
                "bind": "/workspace/deps",
                "mode": "rw",  # Agents can add/remove deps at runtime
            }
            config["environment"]["DEPS_PATH"] = "/workspace/deps"
        if volumes:
            config["volumes"] = volumes

        # Add Redis config if provided
        if redis_url:
            config["environment"]["ARTIFACT_BACKEND"] = "redis"
            config["environment"]["REDIS_URL"] = redis_url
            # Pass prefixes so container uses consistent keys
            if tools_prefix:
                config["environment"]["REDIS_TOOLS_PREFIX"] = tools_prefix
            if skills_prefix:
                config["environment"]["REDIS_SKILLS_PREFIX"] = skills_prefix
            if artifacts_prefix:
                config["environment"]["REDIS_ARTIFACTS_PREFIX"] = artifacts_prefix
            if deps_prefix:
                config["environment"]["REDIS_DEPS_PREFIX"] = deps_prefix

        # Deps configuration
        config["environment"]["ALLOW_RUNTIME_DEPS"] = "true" if self.allow_runtime_deps else "false"

        # Authentication configuration (auth ENABLED by default, explicit opt-out)
        # - With token: auth enabled, server validates requests
        # - With auth_disabled=True: auth explicitly disabled (local dev only)
        # - Neither: server will fail-closed (refuses to start)
        if self.auth_token:
            config["environment"]["CONTAINER_AUTH_TOKEN"] = self.auth_token
        elif self.auth_disabled:
            config["environment"]["CONTAINER_AUTH_DISABLED"] = "true"
        # If neither set, server will fail-closed at startup (correct behavior)

        # Add host.docker.internal mapping for Linux
        # macOS/Windows Docker Desktop provides this natively, but Linux needs it
        if platform.system() == "Linux":
            config["extra_hosts"] = {"host.docker.internal": "host-gateway"}

        # Add container name
        if self.name:
            config["name"] = self.name

        return config
