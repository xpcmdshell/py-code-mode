"""DepsNamespace - agent-facing API for dependency management.

Provides deps.add(), deps.list(), deps.remove(), deps.sync() in execution context.
"""

from __future__ import annotations

__all__ = [
    "DepsNamespace",
    "ControlledDepsNamespace",
    "RuntimeDepsDisabledError",
]

from typing import TYPE_CHECKING, Any

from py_code_mode.deps.installer import SyncResult

if TYPE_CHECKING:
    from py_code_mode.deps.installer import PackageInstaller
    from py_code_mode.deps.store import DepsStore


class RuntimeDepsDisabledError(Exception):
    """Raised when runtime dependency installation is disabled."""

    pass


class DepsNamespace:
    """Agent-facing namespace for dependency management.

    Provides a simple API for agents to add, remove, and sync dependencies.

    Usage in agent code:
        deps.add("pandas>=2.0")  # Adds and installs immediately
        deps.list()             # Returns list of configured packages
        deps.remove("pandas")   # Removes from config (doesn't uninstall)
        deps.sync()             # Ensures all configured packages are installed
    """

    def __init__(self, store: DepsStore, installer: PackageInstaller) -> None:
        """Initialize namespace.

        Args:
            store: DepsStore for package persistence.
            installer: PackageInstaller for installation.
        """
        self._store = store
        self._installer = installer

    def add(self, package: str) -> SyncResult:
        """Add a package and install it.

        Args:
            package: Package specification (e.g., "pandas>=2.0")

        Returns:
            SyncResult with installation outcome.

        Raises:
            ValueError: If package name is invalid.
        """
        # Add to store (store.add() validates the package name)
        self._store.add(package)

        # Sync to install
        return self._installer.sync(self._store)

    def list(self) -> list[str]:
        """Return list of configured packages."""
        return self._store.list()

    def remove(self, package: str) -> bool:
        """Remove a package from configuration.

        Note: This only removes from config, does not uninstall.

        Args:
            package: Package specification to remove.

        Returns:
            True if removed, False if not found.
        """
        return self._store.remove(package)

    def sync(self) -> SyncResult:
        """Ensure all configured packages are installed.

        Returns:
            SyncResult with installation outcomes.
        """
        return self._installer.sync(self._store)

    def __repr__(self) -> str:
        """Return helpful repr for agent discoverability."""
        packages = self._store.list()
        count = len(packages)
        return f"<DepsNamespace: {count} package(s) configured>"


class ControlledDepsNamespace:
    """Wrapper that controls runtime dependency operations.

    When allow_runtime=False, blocks add() and remove() but allows list() and sync().
    This makes the dependency configuration immutable at runtime - agents cannot
    add new deps or remove pre-configured ones, but can sync pre-configured deps.

    Security: Access to internal attributes (_wrapped, _allow_runtime) is blocked
    via __getattribute__ to prevent bypass attacks like deps._wrapped.add().

    Usage:
        # Wrap the real namespace
        controlled = ControlledDepsNamespace(deps_ns, allow_runtime=False)
    """

    # Attributes that are safe to access publicly
    _ALLOWED_ATTRS = frozenset(
        {
            "add",
            "list",
            "remove",
            "sync",
            "__repr__",
            "__class__",
            "__doc__",
        }
    )

    def __init__(self, wrapped: DepsNamespace, allow_runtime: bool = True) -> None:
        """Initialize controlled namespace.

        Args:
            wrapped: The underlying DepsNamespace to wrap.
            allow_runtime: If False, add() and remove() raise RuntimeDepsDisabledError.
                          sync() is always allowed since it only installs pre-configured deps.
        """
        # Use object.__setattr__ to bypass our potential future __setattr__
        object.__setattr__(self, "_wrapped", wrapped)
        object.__setattr__(self, "_allow_runtime", allow_runtime)

    def __getattribute__(self, name: str) -> Any:
        """Control access to attributes.

        Blocks access to internal attributes (_wrapped, _allow_runtime) to prevent
        bypass attacks where agent code accesses deps._wrapped.add() directly.

        Args:
            name: Attribute name being accessed.

        Returns:
            The attribute value for allowed attributes.

        Raises:
            AttributeError: For internal attributes (starting with _).
        """
        # Allow access to our whitelist of public methods
        allowed = object.__getattribute__(self, "_ALLOWED_ATTRS")
        if name in allowed:
            return object.__getattribute__(self, name)

        # Block access to internal attributes
        if name.startswith("_"):
            raise AttributeError(
                f"Cannot access internal attribute '{name}'. Runtime deps are disabled."
            )

        # For any other attribute, use default behavior
        return object.__getattribute__(self, name)

    def add(self, package: str) -> SyncResult:
        """Add a package and install it.

        Raises:
            RuntimeDepsDisabledError: If runtime deps are disabled.
        """
        allow_runtime = object.__getattribute__(self, "_allow_runtime")
        if not allow_runtime:
            raise RuntimeDepsDisabledError(
                "Runtime dependency installation is disabled. "
                "Dependencies must be pre-configured before session start."
            )
        wrapped = object.__getattribute__(self, "_wrapped")
        return wrapped.add(package)

    def list(self) -> list[str]:
        """Return list of configured packages."""
        wrapped = object.__getattribute__(self, "_wrapped")
        return wrapped.list()

    def remove(self, package: str) -> bool:
        """Remove a package from configuration.

        Raises:
            RuntimeDepsDisabledError: If runtime deps are disabled.
        """
        allow_runtime = object.__getattribute__(self, "_allow_runtime")
        if not allow_runtime:
            raise RuntimeDepsDisabledError(
                "Runtime dependency modification is disabled. "
                "Dependencies must be pre-configured before session start."
            )
        wrapped = object.__getattribute__(self, "_wrapped")
        return wrapped.remove(package)

    def sync(self) -> SyncResult:
        """Ensure all configured packages are installed.

        This is always allowed, even when allow_runtime=False, because sync()
        only installs packages that are already configured in the deps store.
        It does not add new dependencies.

        Returns:
            SyncResult with installation outcomes.
        """
        wrapped = object.__getattribute__(self, "_wrapped")
        return wrapped.sync()

    def __repr__(self) -> str:
        """Return helpful repr for agent discoverability."""
        allow_runtime = object.__getattribute__(self, "_allow_runtime")
        status = "enabled" if allow_runtime else "disabled"
        return f"<ControlledDepsNamespace: runtime={status}>"
