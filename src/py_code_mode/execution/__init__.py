"""py_code_mode.execution - Code execution backends."""

# Import to trigger registration
from py_code_mode.execution.in_process import InProcessExecutor
from py_code_mode.execution.protocol import (
    Capability,
    Executor,
    FileStorageAccess,
    RedisStorageAccess,
    StorageAccess,
)
from py_code_mode.execution.registry import (
    get_backend,
    list_backends,
    register_backend,
)

# Container is optional
try:
    from py_code_mode.execution.container import ContainerConfig, ContainerExecutor

    CONTAINER_AVAILABLE = True
except ImportError:
    CONTAINER_AVAILABLE = False
    ContainerConfig = None  # type: ignore
    ContainerExecutor = None  # type: ignore

__all__ = [
    "Capability",
    "Executor",
    "FileStorageAccess",
    "RedisStorageAccess",
    "StorageAccess",
    "get_backend",
    "list_backends",
    "register_backend",
    "InProcessExecutor",
    "ContainerExecutor",
    "ContainerConfig",
    "CONTAINER_AVAILABLE",
]
