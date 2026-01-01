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
    so the executor knows where to find skills and artifacts.
    Tools and deps are owned by executors (via config), not storage.
    """

    skills_path: Path | None
    artifacts_path: Path
    vectors_path: Path | None = None


@dataclass(frozen=True)
class RedisStorageAccess:
    """Access descriptor for Redis storage.

    Session derives this from RedisStorage and passes to executor.start()
    so the executor knows the Redis connection and key prefixes for skills
    and artifacts. Tools and deps are owned by executors (via config).
    """

    redis_url: str
    skills_prefix: str
    artifacts_prefix: str
    vectors_prefix: str | None = None


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
    DEPS_INSTALL = "deps_install"  # Can install packages at runtime
    DEPS_UNINSTALL = "deps_uninstall"  # Can uninstall packages at runtime

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
            cls.DEPS_INSTALL,
            cls.DEPS_UNINSTALL,
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

    def get_configured_deps(self) -> list[str]:
        """Return list of pre-configured dependencies from executor config.

        These are deps specified via config.deps list and config.deps_file.
        Used by Session._sync_deps() to install deps on start.

        Returns:
            List of package specifications.
        """
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

    async def install_deps(self, packages: list[str]) -> dict[str, Any]:
        """Install packages in executor's environment.

        Each executor installs to its own environment:
        - InProcessExecutor: uses sys.executable (same process)
        - SubprocessExecutor: uses VenvManager (targets venv)
        - ContainerExecutor: calls HTTP endpoint (targets container)

        Args:
            packages: List of package specifications (e.g., ["pandas>=2.0", "numpy"])

        Returns:
            Dict with keys:
            - installed: List of successfully installed packages
            - already_present: List of packages that were already installed
            - failed: List of packages that failed to install

        Raises:
            RuntimeDepsDisabledError: If runtime deps are disabled via config
            RuntimeError: If executor not started or deps namespace unavailable
        """
        ...

    async def uninstall_deps(self, packages: list[str]) -> dict[str, Any]:
        """Uninstall packages from executor's environment.

        Args:
            packages: List of package names to uninstall

        Returns:
            Dict with keys:
            - removed: List of successfully uninstalled packages
            - not_found: List of packages that were not installed
            - failed: List of packages that failed to uninstall

        Raises:
            RuntimeDepsDisabledError: If runtime deps are disabled via config
            RuntimeError: If executor not started
        """
        ...

    async def add_dep(self, package: str) -> dict[str, Any]:
        """Add and install a single package.

        Adds the package to the deps store and installs it.
        This is the single-package equivalent of install_deps().

        Args:
            package: Package specification (e.g., "pandas>=2.0")

        Returns:
            Dict with keys:
            - installed: List of successfully installed packages
            - already_present: List of packages already installed
            - failed: List of packages that failed to install

        Raises:
            RuntimeDepsDisabledError: If runtime deps are disabled via config
            RuntimeError: If executor not started
        """
        ...

    async def remove_dep(self, package: str) -> dict[str, Any]:
        """Remove a package from configuration and uninstall it.

        Removes the package from deps store and uninstalls it.
        This is the single-package equivalent of uninstall_deps().

        Args:
            package: Package name to remove

        Returns:
            Dict with keys:
            - removed: List of successfully removed packages
            - not_found: List of packages that were not installed
            - failed: List of packages that failed to uninstall
            - removed_from_config: Boolean indicating if removed from config

        Raises:
            RuntimeDepsDisabledError: If runtime deps are disabled via config
            RuntimeError: If executor not started
        """
        ...

    async def list_deps(self) -> list[str]:
        """List all configured dependencies.

        Returns:
            List of package specifications.
        """
        ...

    async def sync_deps(self) -> dict[str, Any]:
        """Sync all configured dependencies.

        Installs all packages in the deps store that aren't already installed.
        This is always allowed even when allow_runtime_deps=False because
        it only installs pre-configured packages.

        Returns:
            Dict with keys:
            - installed: List of successfully installed packages
            - already_present: List of packages already installed
            - failed: List of packages that failed to install
        """
        ...

    async def list_tools(self) -> list[dict[str, Any]]:
        """List all available tools.

        Returns:
            List of tool info dicts with 'name', 'description', 'tags' keys.
        """
        ...

    async def search_tools(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search tools by name/description.

        Args:
            query: Search query string.
            limit: Maximum number of results.

        Returns:
            List of matching tool info dicts.
        """
        ...
