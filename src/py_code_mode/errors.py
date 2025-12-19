"""Error types for py-code-mode.

All errors inherit from CodeModeError for easy catching at framework level.
"""

from typing import Any


class CodeModeError(Exception):
    """Base class for all py-code-mode errors."""

    pass


class ToolNotFoundError(CodeModeError):
    """Raised when a tool name is not found in the registry."""

    def __init__(
        self, tool_name: str, available_tools: list[str] | None = None
    ) -> None:
        self.tool_name = tool_name
        self.available_tools = available_tools or []
        msg = f"Tool '{tool_name}' not found"
        if self.available_tools:
            msg += f". Available: {', '.join(self.available_tools[:5])}"
            if len(self.available_tools) > 5:
                msg += f" (and {len(self.available_tools) - 5} more)"
        super().__init__(msg)


class ToolCallError(CodeModeError):
    """Raised when a tool call fails during execution."""

    def __init__(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        cause: Exception,
    ) -> None:
        self.tool_name = tool_name
        self.tool_args = (
            tool_args  # Named tool_args to avoid collision with Exception.args
        )
        self.cause = cause
        super().__init__(f"Tool '{tool_name}' failed: {cause}")


class ToolTimeoutError(CodeModeError):
    """Raised when a tool call exceeds its timeout."""

    def __init__(self, tool_name: str, timeout_seconds: float) -> None:
        self.tool_name = tool_name
        self.timeout_seconds = timeout_seconds
        super().__init__(f"Tool '{tool_name}' timed out after {timeout_seconds}s")


class ArtifactNotFoundError(CodeModeError):
    """Raised when trying to load a nonexistent artifact."""

    def __init__(self, artifact_name: str) -> None:
        self.artifact_name = artifact_name
        super().__init__(f"Artifact '{artifact_name}' not found")


class ArtifactWriteError(CodeModeError):
    """Raised when artifact save fails (disk full, permissions, path traversal)."""

    def __init__(self, artifact_name: str, reason: str) -> None:
        self.artifact_name = artifact_name
        self.reason = reason
        super().__init__(f"Cannot write artifact '{artifact_name}': {reason}")


class SkillNotFoundError(CodeModeError):
    """Raised when a skill name is not found."""

    def __init__(self, skill_name: str) -> None:
        self.skill_name = skill_name
        super().__init__(f"Skill '{skill_name}' not found")


class SkillValidationError(CodeModeError):
    """Raised when skill YAML is invalid."""

    def __init__(self, skill_name: str, reason: str) -> None:
        self.skill_name = skill_name
        self.reason = reason
        super().__init__(f"Invalid skill '{skill_name}': {reason}")


class SkillExecutionError(CodeModeError):
    """Raised when skill code execution fails."""

    def __init__(self, skill_name: str, cause: Exception) -> None:
        self.skill_name = skill_name
        self.cause = cause
        super().__init__(f"Skill '{skill_name}' execution failed: {cause}")


class DependencyError(CodeModeError):
    """Raised when a required package is unavailable."""

    def __init__(self, package: str, required_by: str | None = None) -> None:
        self.package = package
        self.required_by = required_by
        msg = f"Package '{package}' is not available"
        if required_by:
            msg += f" (required by {required_by})"
        super().__init__(msg)


class StorageError(CodeModeError):
    """Base exception for storage operations."""

    pass


class StorageReadError(StorageError):
    """Error reading from storage (corruption, permission, deserialization)."""

    def __init__(self, message: str, path: str | None = None) -> None:
        self.path = path
        super().__init__(message)


class StorageWriteError(StorageError):
    """Error writing to storage (permission, serialization)."""

    def __init__(self, message: str, path: str | None = None) -> None:
        self.path = path
        super().__init__(message)


class ConfigurationError(CodeModeError):
    """Error in configuration (missing deps, invalid config)."""

    pass
