"""Execution backends for py-code-mode.

Available backends:
- in-process: Fast, no isolation, runs in same process
- container: Docker-based isolation with HTTP API
- microsandbox: microVM-based isolation (future)
"""

from py_code_mode.backend import register_backend

# Import backends to trigger registration
from py_code_mode.backends.in_process import InProcessExecutor

# Re-export for convenient imports
__all__ = ["InProcessExecutor"]
