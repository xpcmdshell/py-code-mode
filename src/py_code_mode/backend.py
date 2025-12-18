"""Execution backend protocol and registry.

Defines the Executor protocol that all backends must implement,
capability constants for dynamic feature queries, and the
backend registry for runtime discovery.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from py_code_mode.types import ExecutionResult


class Capability:
    """Standard capability names for execution backends.

    Use these constants with executor.supports() to check
    if a backend provides specific features.
    """

    TIMEOUT = "timeout"
    PROCESS_ISOLATION = "process_isolation"
    NETWORK_ISOLATION = "network_isolation"
    NETWORK_FILTERING = "network_filtering"
    FILESYSTEM_ISOLATION = "filesystem_isolation"
    MEMORY_LIMIT = "memory_limit"
    CPU_LIMIT = "cpu_limit"
    RESET = "reset"

    @classmethod
    def all(cls) -> set[str]:
        """Return set of all defined capabilities."""
        return {
            cls.TIMEOUT,
            cls.PROCESS_ISOLATION,
            cls.NETWORK_ISOLATION,
            cls.NETWORK_FILTERING,
            cls.FILESYSTEM_ISOLATION,
            cls.MEMORY_LIMIT,
            cls.CPU_LIMIT,
            cls.RESET,
        }


@runtime_checkable
class Executor(Protocol):
    """Protocol for code execution backends.

    All backends must implement these methods to be usable
    with the py-code-mode framework.
    """

    async def run(
        self,
        code: str,
        timeout: float | None = None,
    ) -> ExecutionResult:
        """Execute Python code and return the result.

        Args:
            code: Python code to execute
            timeout: Optional timeout in seconds (overrides default)

        Returns:
            ExecutionResult with value, stdout, and error fields
        """
        ...

    async def close(self) -> None:
        """Release any resources held by the executor."""
        ...

    async def __aenter__(self) -> Executor:
        """Support async context manager."""
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Close on context exit."""
        ...

    def supports(self, capability: str) -> bool:
        """Check if this backend supports a capability.

        Args:
            capability: Capability name (use Capability constants)

        Returns:
            True if the backend supports this capability
        """
        ...

    def supported_capabilities(self) -> set[str]:
        """Return set of all capabilities this backend supports."""
        ...


# Backend registry
_backends: dict[str, type] = {}


def register_backend(name: str, executor_class: type) -> None:
    """Register a backend executor class.

    Args:
        name: Backend name (e.g., "in-process", "container")
        executor_class: Class that implements the Executor protocol
    """
    _backends[name] = executor_class


def get_backend(name: str) -> type | None:
    """Get a registered backend by name.

    Args:
        name: Backend name

    Returns:
        Executor class or None if not found
    """
    return _backends.get(name)


def list_backends() -> list[str]:
    """List all registered backend names.

    Returns:
        List of registered backend names
    """
    return list(_backends.keys())


async def create_executor(
    backend: str = "in-process",
    *,
    tools: str | None = None,
    skills: str | None = None,
    artifacts: str | None = None,
    # Security policies
    network_policy: str = "allow",
    allowed_hosts: list[str] | None = None,
    filesystem_policy: str = "allow",
    allowed_paths: list[str] | None = None,
    memory_limit_mb: int | None = None,
    cpu_limit: float | None = None,
    **kwargs: Any,
) -> Executor:
    """Create an executor for the specified backend.

    This is the primary factory function for creating executors.
    It handles backend lookup and passes configuration.

    Args:
        backend: Backend name ("in-process", "container", "microsandbox")
        tools: Path to tools directory
        skills: Path to skills directory
        artifacts: Path to artifacts directory
        network_policy: "allow", "deny", or "filtered"
        allowed_hosts: Hosts to allow when network_policy="filtered"
        filesystem_policy: "allow", "deny", or "readonly"
        allowed_paths: Paths to allow when filesystem_policy="readonly"
        memory_limit_mb: Memory limit in MB (if supported)
        cpu_limit: CPU limit (if supported)
        **kwargs: Additional backend-specific options

    Returns:
        An executor instance

    Raises:
        ValueError: If backend is not registered
    """
    executor_class = get_backend(backend)
    if executor_class is None:
        raise ValueError(f"Unknown backend: {backend}")

    # Build config kwargs
    config_kwargs = {
        "tools": tools,
        "skills": skills,
        "artifacts": artifacts,
        "network_policy": network_policy,
        "allowed_hosts": allowed_hosts or [],
        "filesystem_policy": filesystem_policy,
        "allowed_paths": allowed_paths or [],
        "memory_limit_mb": memory_limit_mb,
        "cpu_limit": cpu_limit,
        **kwargs,
    }

    # Remove None values for cleaner config
    config_kwargs = {k: v for k, v in config_kwargs.items() if v is not None}

    # Check if class has create() method or needs direct instantiation
    if hasattr(executor_class, "create"):
        return await executor_class.create(**config_kwargs)
    else:
        return executor_class(**config_kwargs)
