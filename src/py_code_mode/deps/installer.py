"""PackageInstaller for synchronizing dependencies.

Handles installing packages via pip with hash-based caching.
"""

from __future__ import annotations

__all__ = [
    "PackageInstaller",
    "SyncResult",
    "clear_install_cache",
]

import logging
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from py_code_mode.deps.store import DepsStore


@dataclass
class SyncResult:
    """Result of a sync operation."""

    installed: set[str] = field(default_factory=set)
    already_present: set[str] = field(default_factory=set)
    failed: set[str] = field(default_factory=set)


# Global cache for tracking installed packages and the hash when they were installed
# Key: store hash -> set of packages that were synced at that hash
_INSTALLED_CACHE: dict[str, set[str]] = {}


class PackageInstaller:
    """Installs packages from a DepsStore using uv or pip.

    Uses hash-based caching to avoid redundant installations.
    """

    DEFAULT_TIMEOUT = 120  # 2 minutes default

    # Allowlist of safe extra arguments for pip/uv
    #
    # SECURITY: Only add flags that cannot be used to:
    # - Execute arbitrary code (--install-option, --global-option)
    # - Install from untrusted sources (--index-url, --extra-index-url, --find-links)
    # - Bypass security checks (--trusted-host, --no-verify)
    # - Modify files outside the venv (--target, --prefix, --root)
    # - Install editable packages (--editable, -e)
    # - Install from URLs or VCS (handled by package validation, but these flags help)
    #
    # Current allowlist rationale:
    # - --quiet/-q: Reduces output verbosity (safe)
    # - --no-cache-dir: Disables pip cache (safe, may slow installs)
    # - --upgrade/-U: Upgrades existing packages (safe)
    # - --no-deps: Skips dependency resolution (safe, may break packages)
    ALLOWED_EXTRA_ARGS = frozenset(
        {
            "--quiet",
            "-q",
            "--no-cache-dir",
            "--upgrade",
            "-U",
            "--no-deps",
        }
    )

    def __init__(
        self,
        timeout: int = DEFAULT_TIMEOUT,
        extra_args: list[str] | None = None,
    ) -> None:
        """Initialize installer.

        Args:
            timeout: Timeout in seconds for install operations.
            extra_args: Extra arguments to pass to pip/uv install.

        Raises:
            ValueError: If extra_args contains disallowed arguments.
        """
        self.timeout = timeout
        self.extra_args = extra_args or []
        self._validate_extra_args()

    def _validate_extra_args(self) -> None:
        """Validate that extra_args only contains allowed arguments.

        Raises:
            ValueError: If any argument is not in the allowlist.
        """
        for arg in self.extra_args:
            if arg not in self.ALLOWED_EXTRA_ARGS:
                raise ValueError(f"Disallowed extra argument: {arg}")

    def _get_installer_command(self) -> list[str]:
        """Get pip install command using the best available installer.

        Prefers uv if available (faster, doesn't require pip in venv), falls back
        to pip via current interpreter. Uses --python flag with uv to target
        the current interpreter's environment.
        """
        # Check if uv is available
        uv_path = shutil.which("uv")
        if uv_path is not None:
            # Use uv pip install with explicit --python to target current venv
            return [uv_path, "pip", "install", "--python", sys.executable]

        # Fall back to pip via current interpreter
        logger.warning("uv not found, falling back to pip")
        return [sys.executable, "-m", "pip", "install"]

    def _build_install_command(self, packages: list[str]) -> list[str]:
        """Build the full install command."""
        cmd = self._get_installer_command()
        cmd.extend(self.extra_args)
        cmd.extend(packages)
        return cmd

    def sync(self, store: DepsStore) -> SyncResult:
        """Synchronize packages from store to environment.

        Args:
            store: DepsStore containing packages to install.

        Returns:
            SyncResult with installed, already_present, and failed sets.
        """
        packages = store.list()

        if not packages:
            return SyncResult()

        current_hash = store.hash()
        packages_set = set(packages)

        # Check if we've already synced this exact configuration (same hash)
        if current_hash in _INSTALLED_CACHE:
            cached_packages = _INSTALLED_CACHE[current_hash]
            if packages_set == cached_packages:
                # Exact same configuration already synced
                return SyncResult(already_present=packages_set.copy())

        # Find what's new vs already installed
        # Merge all previously installed packages across all cached states
        all_previously_installed: set[str] = set()
        for cached_pkgs in _INSTALLED_CACHE.values():
            all_previously_installed.update(cached_pkgs)

        already_present = packages_set & all_previously_installed
        packages_to_install = packages_set - all_previously_installed

        if not packages_to_install:
            # All packages were previously installed
            _INSTALLED_CACHE[current_hash] = packages_set.copy()
            return SyncResult(already_present=packages_set.copy())

        # Run the installer for new packages
        result = self._run_install(list(packages_to_install))

        # Merge already_present from previous installs
        result.already_present.update(already_present)

        # Update cache: only cache the successfully installed + already present packages
        # Don't include failed packages in the cache
        successfully_synced = result.installed | result.already_present
        if successfully_synced:
            _INSTALLED_CACHE[current_hash] = successfully_synced.copy()

        return result

    def _run_install(self, packages: list[str]) -> SyncResult:
        """Run the install command for packages.

        Args:
            packages: List of packages to install.

        Returns:
            SyncResult with outcomes.
        """
        result = SyncResult()

        if not packages:
            return result

        cmd = self._build_install_command(packages)

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )

            if proc.returncode == 0:
                # Success - all packages installed
                result.installed = set(packages)
            else:
                # Failure - try individual packages to isolate failures
                result = self._install_individually(packages)

        except subprocess.TimeoutExpired:
            # Timeout - mark all as failed
            result.failed = set(packages)

        return result

    def _install_individually(self, packages: list[str]) -> SyncResult:
        """Install packages one by one to isolate failures.

        Args:
            packages: List of packages to install.

        Returns:
            SyncResult with per-package outcomes.
        """
        result = SyncResult()

        for package in packages:
            cmd = self._build_install_command([package])

            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                )

                if proc.returncode == 0:
                    result.installed.add(package)
                else:
                    result.failed.add(package)

            except subprocess.TimeoutExpired:
                result.failed.add(package)

        return result


def clear_install_cache() -> None:
    """Clear the installation cache.

    Primarily useful for testing to ensure test isolation.
    """
    _INSTALLED_CACHE.clear()
