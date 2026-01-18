"""Error types for py-code-mode.

All errors inherit from CodeModeError for easy catching at framework level.
"""

from typing import Any


class CodeModeError(Exception):
    """Base class for all py-code-mode errors."""

    pass


class ToolNotFoundError(CodeModeError):
    """Raised when a tool name is not found in the registry."""

    def __init__(self, tool_name: str, available_tools: list[str] | None = None) -> None:
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
        self.tool_args = tool_args  # Named tool_args to avoid collision with Exception.args
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


class WorkflowNotFoundError(CodeModeError):
    """Raised when a workflow name is not found."""

    def __init__(self, workflow_name: str) -> None:
        self.workflow_name = workflow_name
        super().__init__(f"Workflow '{workflow_name}' not found")


class WorkflowValidationError(CodeModeError):
    """Raised when workflow YAML is invalid."""

    def __init__(self, workflow_name: str, reason: str) -> None:
        self.workflow_name = workflow_name
        self.reason = reason
        super().__init__(f"Invalid workflow '{workflow_name}': {reason}")


class WorkflowExecutionError(CodeModeError):
    """Raised when workflow code execution fails."""

    def __init__(self, workflow_name: str, cause: Exception) -> None:
        self.workflow_name = workflow_name
        self.cause = cause
        super().__init__(f"Workflow '{workflow_name}' execution failed: {cause}")


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
        full_message = f"{message} (path: {path})" if path else message
        super().__init__(full_message)


class StorageWriteError(StorageError):
    """Error writing to storage (permission, serialization)."""

    def __init__(self, message: str, path: str | None = None) -> None:
        self.path = path
        full_message = f"{message} (path: {path})" if path else message
        super().__init__(full_message)


class ConfigurationError(CodeModeError):
    """Error in configuration (missing deps, invalid config)."""

    pass


# =============================================================================
# RPC Error Hierarchy
# =============================================================================

# WARNING: These error classes are duplicated in kernel_init.py for subprocess execution.
# If you modify any of these classes, you MUST update kernel_init.py to match.
# See: src/py_code_mode/execution/subprocess/kernel_init.py


class RPCError(CodeModeError):
    """Base for all RPC-related errors.

    Raised when RPC communication between host and kernel fails or when
    namespace operations fail via RPC.
    """

    pass


class RPCTransportError(RPCError):
    """RPC plumbing failed (JSON parse, timeout, channel broken).

    Raised for low-level transport issues, not application-level errors.
    """

    pass


class NamespaceError(RPCError):
    """Base for namespace operation failures.

    Provides structured context about which namespace, operation, and
    original exception type caused the failure.

    Attributes:
        namespace: The namespace where the error occurred (workflows, tools, artifacts, deps).
        operation: The operation that failed (e.g., invoke_workflow, call_tool).
        original_type: The original exception type name from the host.
    """

    def __init__(
        self,
        namespace: str,
        operation: str,
        message: str,
        original_type: str = "RuntimeError",
    ) -> None:
        self.namespace = namespace
        self.operation = operation
        self.original_type = original_type
        super().__init__(f"{namespace}.{operation}: [{original_type}] {message}")


class WorkflowError(NamespaceError):
    """Error in workflows namespace operation.

    Raised when workflow invocation, creation, search, or deletion fails.
    """

    def __init__(self, operation: str, message: str, original_type: str = "RuntimeError") -> None:
        super().__init__("workflows", operation, message, original_type)


class ToolError(NamespaceError):
    """Error in tools namespace operation.

    Raised when tool invocation, search, or listing fails.
    """

    def __init__(self, operation: str, message: str, original_type: str = "RuntimeError") -> None:
        super().__init__("tools", operation, message, original_type)


class ArtifactError(NamespaceError):
    """Error in artifacts namespace operation.

    Raised when artifact save, load, list, or delete fails.
    """

    def __init__(self, operation: str, message: str, original_type: str = "RuntimeError") -> None:
        super().__init__("artifacts", operation, message, original_type)


class DepsError(NamespaceError):
    """Error in deps namespace operation.

    Raised when dependency add, remove, list, or sync fails.
    """

    def __init__(self, operation: str, message: str, original_type: str = "RuntimeError") -> None:
        super().__init__("deps", operation, message, original_type)
