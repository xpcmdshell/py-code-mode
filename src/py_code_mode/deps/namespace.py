"""DepsNamespace - agent-facing API for dependency management.

Provides deps.add(), deps.list(), deps.remove(), deps.sync() in execution context.
"""

from __future__ import annotations

__all__ = [
    "DepsNamespace",
]

from typing import TYPE_CHECKING

from py_code_mode.deps.installer import SyncResult

if TYPE_CHECKING:
    from py_code_mode.deps.installer import PackageInstaller
    from py_code_mode.deps.store import DepsStore


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
