"""py-code-mode: Code mode for LLM agents."""

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
from py_code_mode.session import Session

# Storage backends (commonly needed at top level)
from py_code_mode.storage import FileStorage, RedisStorage, StorageBackend

# Core types (foundational, used everywhere)
from py_code_mode.types import ExecutionResult, JsonSchema, ToolDefinition

__version__ = "0.1.0"

__all__ = [
    # Core
    "Session",
    # Types
    "ExecutionResult",
    "JsonSchema",
    "ToolDefinition",
    # Storage
    "StorageBackend",
    "FileStorage",
    "RedisStorage",
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
