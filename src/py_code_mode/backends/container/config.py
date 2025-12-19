"""Configuration schemas for container execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class CLIToolConfig:
    """Configuration for a CLI tool in the container.

    Defines how to invoke a CLI tool and expose it through the ToolRegistry.
    """

    name: str
    description: str = ""  # Auto-generated if empty
    command: str | None = None  # Defaults to name if not specified
    args_template: str = ""
    timeout_seconds: float = 60.0
    tags: list[str] = field(default_factory=list)
    working_dir: str | None = None
    env: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Apply defaults after initialization."""
        if self.command is None:
            object.__setattr__(self, "command", self.name)
        if not self.description:
            object.__setattr__(self, "description", f"Run {self.name} command")


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

    # Tools
    cli_tools: list[CLIToolConfig] = field(default_factory=list)
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

    @classmethod
    def from_yaml(cls, path: Path) -> SessionConfig:
        """Load configuration from YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f) or {}

        return cls._from_dict(data)

    @classmethod
    def from_env(cls) -> SessionConfig:
        """Load configuration from environment variables."""
        import os

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

        # Load tools config if specified
        if tools_config := os.environ.get("TOOLS_CONFIG"):
            tools_path = Path(tools_config)
            if tools_path.exists():
                with open(tools_path) as f:
                    tools_data = yaml.safe_load(f) or {}
                # Support both 'tools' (new) and 'cli_tools' (legacy) keys
                tools_list = tools_data.get("tools") or tools_data.get("cli_tools", [])
                config.cli_tools = cls._parse_cli_tools(tools_list)
                config.mcp_servers = cls._parse_mcp_servers(tools_data.get("mcp_servers", []))
                config.python_deps = tools_data.get("python_deps", [])

        return config

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> SessionConfig:
        """Create config from dictionary."""
        # Support both 'tools' (new) and 'cli_tools' (legacy) keys
        tools_list = data.get("tools") or data.get("cli_tools", [])
        return cls(
            cli_tools=cls._parse_cli_tools(tools_list),
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
        )

    @staticmethod
    def _parse_cli_tools(tools_data: list[dict[str, Any]]) -> list[CLIToolConfig]:
        """Parse CLI tool configurations.

        Supports both new and legacy field names:
        - 'args' (new) or 'args_template' (legacy)
        - 'timeout' (new) or 'timeout_seconds' (legacy)
        - 'command' is optional, defaults to 'name'
        """
        return [
            CLIToolConfig(
                name=t["name"],
                description=t.get("description", ""),
                command=t.get("command"),  # Defaults to name via __post_init__
                args_template=t.get("args") or t.get("args_template", ""),
                timeout_seconds=t.get("timeout") or t.get("timeout_seconds", 60.0),
                tags=t.get("tags", []),
                working_dir=t.get("working_dir"),
                env=t.get("env", {}),
            )
            for t in tools_data
        ]

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
    image: str = "py-code-mode-tools:latest"
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

    def to_docker_config(
        self,
        tools_path: Path | None = None,
        skills_path: Path | None = None,
        artifacts_path: Path | None = None,
        redis_url: str | None = None,
    ) -> dict[str, Any]:
        """Convert to Docker SDK configuration.

        Args:
            tools_path: Host path to tools directory (volume mount).
            skills_path: Host path to skills directory (volume mount).
            artifacts_path: Host path to artifacts directory (volume mount).
            redis_url: Redis URL for Redis-based storage (sets env vars).

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
        if volumes:
            config["volumes"] = volumes

        # Add Redis config if provided
        if redis_url:
            config["environment"]["ARTIFACT_BACKEND"] = "redis"
            config["environment"]["REDIS_URL"] = redis_url

        # Add container name
        if self.name:
            config["name"] = self.name

        return config
