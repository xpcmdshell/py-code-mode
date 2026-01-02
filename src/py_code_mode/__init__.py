"""py-code-mode: Code mode for LLM agents."""

# Bootstrap (for subprocess namespace reconstruction)
from py_code_mode.bootstrap import NamespaceBundle, bootstrap_namespaces

# Core entry point
# All errors (foundational)
from py_code_mode.errors import (
    ArtifactNotFoundError,
    ArtifactWriteError,
    CodeModeError,
    ConfigurationError,
    DependencyError,
    SkillExecutionError,
    SkillNotFoundError,
    SkillValidationError,
    StorageError,
    StorageReadError,
    StorageWriteError,
    ToolCallError,
    ToolNotFoundError,
    ToolTimeoutError,
)

# Execution (commonly needed at top level)
from py_code_mode.execution import (
    CONTAINER_AVAILABLE,
    SUBPROCESS_AVAILABLE,
    Capability,
    Executor,
    InProcessConfig,
    InProcessExecutor,
)

# Conditionally import optional executors
if SUBPROCESS_AVAILABLE:
    from py_code_mode.execution import SubprocessConfig, SubprocessExecutor
else:
    SubprocessConfig = None  # type: ignore[assignment, misc]
    SubprocessExecutor = None  # type: ignore[assignment, misc]

if CONTAINER_AVAILABLE:
    from py_code_mode.execution import ContainerConfig, ContainerExecutor
else:
    ContainerConfig = None  # type: ignore[assignment, misc]
    ContainerExecutor = None  # type: ignore[assignment, misc]

from py_code_mode.session import Session

# Storage backends (commonly needed at top level)
from py_code_mode.storage import FileStorage, RedisStorage, StorageBackend

# Core types (foundational, used everywhere)
from py_code_mode.types import ExecutionResult, JsonSchema, ToolDefinition

__version__ = "0.1.0"

__all__ = [
    # Core
    "Session",
    # Bootstrap
    "bootstrap_namespaces",
    "NamespaceBundle",
    # Types
    "ExecutionResult",
    "JsonSchema",
    "ToolDefinition",
    # Storage
    "StorageBackend",
    "FileStorage",
    "RedisStorage",
    # Execution
    "Executor",
    "Capability",
    "InProcessExecutor",
    "InProcessConfig",
    "SubprocessExecutor",
    "SubprocessConfig",
    "ContainerExecutor",
    "ContainerConfig",
    "SUBPROCESS_AVAILABLE",
    "CONTAINER_AVAILABLE",
    # Errors
    "CodeModeError",
    "ToolNotFoundError",
    "ToolCallError",
    "ToolTimeoutError",
    "ArtifactNotFoundError",
    "ArtifactWriteError",
    "SkillNotFoundError",
    "SkillValidationError",
    "SkillExecutionError",
    "DependencyError",
    "StorageError",
    "StorageReadError",
    "StorageWriteError",
    "ConfigurationError",
]
