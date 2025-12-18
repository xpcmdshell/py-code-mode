"""Execution backends for py-code-mode.

Available backends:
- in-process: Fast, no isolation, runs in same process
- container: Docker-based isolation with HTTP API
- microsandbox: microVM-based isolation (future)
"""

# Import backends to trigger registration
from py_code_mode.backends.in_process import InProcessExecutor

# Container backend is optional (requires docker)
try:
    from py_code_mode.backends.container import ContainerExecutor
except ImportError:
    ContainerExecutor = None  # type: ignore

# Re-export for convenient imports
__all__ = ["InProcessExecutor", "ContainerExecutor"]
