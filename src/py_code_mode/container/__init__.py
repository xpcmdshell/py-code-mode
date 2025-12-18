"""Container isolation for py-code-mode.

Provides Docker-based execution environment with pre-packaged tools and skills.

Usage:
    from py_code_mode.container import ContainerExecutor, ContainerConfig

    config = ContainerConfig(
        image="py-code-mode-tools:latest",
        host_artifacts_path=Path("./artifacts"),
    )

    async with ContainerExecutor(config) as executor:
        result = await executor.run('tools.call("cli.nmap", {"target": "10.0.0.1"})')
"""

from py_code_mode.container.client import (
    ExecuteResult,
    HealthResult,
    InfoResult,
    ResetResult,
    SessionClient,
)
from py_code_mode.container.config import (
    CLIToolConfig,
    ContainerConfig,
    MCPServerConfig,
    SessionConfig,
)
from py_code_mode.container.executor import (
    ContainerExecutor,
    ExecutionResult,
)

__all__ = [
    # Config
    "CLIToolConfig",
    "ContainerConfig",
    "MCPServerConfig",
    "SessionConfig",
    # Client
    "ExecuteResult",
    "HealthResult",
    "InfoResult",
    "ResetResult",
    "SessionClient",
    # Executor
    "ContainerExecutor",
    "ExecutionResult",
]
