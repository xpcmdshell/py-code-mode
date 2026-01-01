"""py_code_mode.execution.subprocess - Subprocess-based code execution with RPC.

This executor runs Python code in an isolated subprocess (Jupyter kernel) with
bidirectional RPC for namespace operations. The kernel contains lightweight
proxy objects that forward all tools/skills/artifacts/deps calls to the host.
"""

from py_code_mode.execution.subprocess.config import SubprocessConfig
from py_code_mode.execution.subprocess.executor import (
    StorageResourceProvider,
    SubprocessExecutor,
)
from py_code_mode.execution.subprocess.host import (
    ExecutionResult,
    KernelHost,
    ResourceProvider,
)
from py_code_mode.execution.subprocess.kernel_init import (
    KERNEL_INIT_CODE,
    get_kernel_init_code,
)
from py_code_mode.execution.subprocess.rpc import RPCRequest, RPCResponse
from py_code_mode.execution.subprocess.venv import KernelVenv, VenvManager

__all__ = [
    # Core executor
    "SubprocessConfig",
    "SubprocessExecutor",
    "StorageResourceProvider",
    # Venv management
    "KernelVenv",
    "VenvManager",
    # RPC components
    "KernelHost",
    "ResourceProvider",
    "ExecutionResult",
    "RPCRequest",
    "RPCResponse",
    "KERNEL_INIT_CODE",
    "get_kernel_init_code",
]
