"""Execution backend protocol and types.

Defines the Executor protocol that all backends must implement,
capability constants for dynamic feature queries, and storage access
descriptors for wiring storage to executors.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from py_code_mode.types import ExecutionResult

if TYPE_CHECKING:
    from py_code_mode.storage.backends import StorageBackend

# =============================================================================
# Storage Access Descriptors
# =============================================================================


@dataclass(frozen=True)
class FileStorageAccess:
    """Access descriptor for file-based storage.

    Session derives this from FileStorage and passes to executor.start()
    so the executor knows where to find tools, skills, and artifacts.
    """

    tools_path: Path | None
    skills_path: Path | None
    artifacts_path: Path
    deps_path: Path | None


@dataclass(frozen=True)
class RedisStorageAccess:
    """Access descriptor for Redis storage.

    Session derives this from RedisStorage and passes to executor.start()
    so the executor knows the Redis connection and key prefixes.
    """

    redis_url: str
    tools_prefix: str
    skills_prefix: str
    artifacts_prefix: str
    deps_prefix: str


StorageAccess = FileStorageAccess | RedisStorageAccess


def validate_storage_not_access(storage: Any, executor_name: str) -> None:
    """Reject old StorageAccess types passed to executor.start().

    Args:
        storage: Value passed to executor.start()
        executor_name: Name of the executor for error message

    Raises:
        TypeError: If storage is a StorageAccess type (old API)
    """
    if isinstance(storage, (FileStorageAccess, RedisStorageAccess)):
        raise TypeError(
            f"{executor_name}.start() accepts StorageBackend, not {type(storage).__name__}. "
            "Pass the storage backend directly."
        )


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

    async def reset(self) -> None:
        """Reset session state if supported.

        Clears any persistent state from previous executions.
        Only available if executor.supports(Capability.RESET) is True.

        Raises:
            NotImplementedError: If backend doesn't support reset
        """
        ...

    async def start(self, storage: StorageBackend | None = None) -> None:
        """Initialize executor with storage backend.

        Args:
            storage: StorageBackend instance. Executor decides how to use it:
                    - InProcessExecutor: uses storage.tools/skills/artifacts directly
                    - ContainerExecutor: calls storage.get_serializable_access()
                    - SubprocessExecutor: calls storage.get_serializable_access()
        """
        ...
