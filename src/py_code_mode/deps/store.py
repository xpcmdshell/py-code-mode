"""DepsStore protocol and implementations for dependency storage.

Provides file-based and Redis-based storage for Python package dependencies.
"""

from __future__ import annotations

__all__ = [
    "DepsStore",
    "FileDepsStore",
    "RedisDepsStore",
]

import hashlib
import re
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from redis import Redis


# Valid package name pattern based on PEP 508
# Allows: alphanumeric, hyphens, underscores, periods
# Followed by optional extras [extra1,extra2] and version specifiers
_VALID_PACKAGE_PATTERN = re.compile(
    r"^[a-zA-Z0-9]"  # Must start with alphanumeric
    r"[a-zA-Z0-9._-]*"  # Rest can have alphanumeric, dot, underscore, hyphen
    r"(?:\[[a-zA-Z0-9,._-]+\])?"  # Optional extras in brackets
    r"(?:[<>=!~].*)?$"  # Optional version specifiers
)

# Dangerous shell metacharacters to reject
_SHELL_METACHARACTERS = re.compile(r"[;|&`$()]")


def _validate_package_name(package: str) -> None:
    """Validate package name for security and correctness.

    Args:
        package: Package specification to validate.

    Raises:
        ValueError: If package name is invalid or contains dangerous characters.
    """
    if not package or not package.strip():
        raise ValueError("Invalid package: empty or whitespace-only")

    # Check for control characters (newlines, carriage returns, null bytes)
    if "\n" in package or "\r" in package or "\x00" in package:
        raise ValueError("Invalid package: contains control characters")

    # Length limit to prevent abuse
    if len(package) > 256:
        raise ValueError("Invalid package: name too long (max 256 characters)")

    # Check for shell metacharacters (command injection prevention)
    if _SHELL_METACHARACTERS.search(package):
        raise ValueError(f"Invalid package name: contains shell metacharacters: {package}")

    # Basic PEP 508 validation
    if not _VALID_PACKAGE_PATTERN.match(package):
        raise ValueError(f"Invalid package name: {package}")


def _normalize_package_name(package: str) -> str:
    """Normalize package name per PEP 503.

    - Lowercase the name part (before any extras or version specifiers)
    - Replace underscores with hyphens in the name part

    Args:
        package: Package specification (e.g., "My_Package>=2.0")

    Returns:
        Normalized package specification (e.g., "my-package>=2.0")
    """
    # Find where the name ends (at [ for extras or at version specifier)
    extras_match = re.search(r"\[", package)
    version_match = re.search(r"[<>=!~]", package)

    if extras_match:
        split_pos = extras_match.start()
    elif version_match:
        split_pos = version_match.start()
    else:
        split_pos = len(package)

    name_part = package[:split_pos]
    rest = package[split_pos:]

    # Normalize the name part
    normalized_name = name_part.lower().replace("_", "-")

    return normalized_name + rest


def _compute_hash(packages: list[str]) -> str:
    """Compute SHA256 hash of sorted package list.

    Args:
        packages: List of package specifications.

    Returns:
        Hex-encoded SHA256 hash.
    """
    # Sort for deterministic ordering
    sorted_packages = sorted(packages)
    content = "\n".join(sorted_packages)
    return hashlib.sha256(content.encode()).hexdigest()


@runtime_checkable
class DepsStore(Protocol):
    """Protocol for dependency storage. Manages list of required packages."""

    def list(self) -> list[str]:
        """Return list of all packages."""
        ...

    def add(self, package: str) -> None:
        """Add a package to the store.

        Args:
            package: Package specification (e.g., "pandas>=2.0")

        Raises:
            ValueError: If package name is invalid.
        """
        ...

    def remove(self, package: str) -> bool:
        """Remove a package from the store.

        Args:
            package: Package specification to remove.

        Returns:
            True if package was removed, False if not found.
        """
        ...

    def clear(self) -> None:
        """Remove all packages from the store."""
        ...

    def hash(self) -> str:
        """Compute hash of current package list for cache invalidation.

        Returns:
            Deterministic hash string based on package contents.
        """
        ...


class FileDepsStore:
    """File-based dependency store. Stores packages in requirements.txt format."""

    def __init__(self, base_path: Path) -> None:
        """Initialize file store.

        Args:
            base_path: Base directory. Will create deps/requirements.txt inside.
        """
        self._base_path = Path(base_path) if isinstance(base_path, str) else base_path
        self._deps_dir = self._base_path / "deps"
        self._requirements_file = self._deps_dir / "requirements.txt"
        self._packages: set[str] = set()
        self._load()

    def _load(self) -> None:
        """Load packages from requirements.txt if it exists."""
        if not self._requirements_file.exists():
            return

        content = self._requirements_file.read_text()
        for line in content.splitlines():
            line = line.strip()
            # Skip empty lines and comments
            if not line or line.startswith("#"):
                continue
            self._packages.add(line)

    def _save(self) -> None:
        """Save packages to requirements.txt."""
        self._deps_dir.mkdir(parents=True, exist_ok=True)
        # Sort for consistent output
        content = "\n".join(sorted(self._packages)) + "\n" if self._packages else ""
        self._requirements_file.write_text(content)

    def list(self) -> list[str]:
        """Return list of all packages."""
        return list(self._packages)

    def add(self, package: str) -> None:
        """Add a package to the store."""
        _validate_package_name(package)
        normalized = _normalize_package_name(package)

        # Check for duplicates with different formatting (e.g., my_package vs my-package)
        # Extract base name without version specifiers for comparison
        base_name = re.split(r"[\[<>=!~]", normalized)[0]

        # Remove existing entries with same base name
        to_remove = []
        for existing in self._packages:
            existing_base = re.split(r"[\[<>=!~]", existing)[0]
            if existing_base == base_name:
                to_remove.append(existing)

        for pkg in to_remove:
            self._packages.discard(pkg)

        self._packages.add(normalized)
        self._save()

    def remove(self, package: str) -> bool:
        """Remove a package from the store."""
        if not package or not package.strip():
            return False

        normalized = _normalize_package_name(package)

        if normalized in self._packages:
            self._packages.discard(normalized)
            self._save()
            return True
        return False

    def clear(self) -> None:
        """Remove all packages from the store."""
        self._packages.clear()
        self._save()

    def hash(self) -> str:
        """Compute hash of current package list."""
        return _compute_hash(list(self._packages))


class RedisDepsStore:
    """Redis-based dependency store. Uses a Redis set for packages."""

    def __init__(self, redis: Redis, prefix: str = "deps") -> None:
        """Initialize Redis store.

        Args:
            redis: Redis client instance.
            prefix: Key prefix. Packages stored at {prefix}:deps
        """
        self._redis = redis
        self._prefix = prefix
        self._key = f"{prefix}:deps"

    def list(self) -> list[str]:
        """Return list of all packages."""
        members = self._redis.smembers(self._key)
        if not members:
            return []
        # Decode bytes if needed
        result = []
        for m in members:
            if isinstance(m, bytes):
                result.append(m.decode())
            else:
                result.append(m)
        return result

    def add(self, package: str) -> None:
        """Add a package to the store."""
        _validate_package_name(package)
        normalized = _normalize_package_name(package)

        # Check for duplicates with different formatting
        base_name = re.split(r"[\[<>=!~]", normalized)[0]

        # Get all members and check for conflicts
        existing = self.list()
        for pkg in existing:
            existing_base = re.split(r"[\[<>=!~]", pkg)[0]
            if existing_base == base_name:
                self._redis.srem(self._key, pkg)

        self._redis.sadd(self._key, normalized)

    def remove(self, package: str) -> bool:
        """Remove a package from the store."""
        if not package or not package.strip():
            return False

        normalized = _normalize_package_name(package)

        result = self._redis.srem(self._key, normalized)
        return result > 0

    def clear(self) -> None:
        """Remove all packages from the store."""
        self._redis.delete(self._key)

    def hash(self) -> str:
        """Compute hash of current package list."""
        packages = self.list()
        return _compute_hash(packages)
