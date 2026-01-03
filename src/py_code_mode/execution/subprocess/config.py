"""Configuration for SubprocessExecutor."""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Pattern for valid python_version: major.minor only (e.g., "3.11", "3.12")
_PYTHON_VERSION_PATTERN = re.compile(r"^\d+\.\d+$")


def _get_current_python_version() -> str:
    """Get current Python version in major.minor format."""
    return f"{sys.version_info.major}.{sys.version_info.minor}"


@dataclass(frozen=True)
class SubprocessConfig:
    """Configuration for SubprocessExecutor.

    The SubprocessExecutor runs Python code in an isolated subprocess with its
    own virtual environment and IPython kernel.

    Attributes:
        python_version: Python version for venv creation (e.g., "3.11", "3.12").
            Must be in major.minor format. Defaults to current Python version.
        venv_path: Path to virtual environment. None means auto-create based on
            cache_venv setting (cached path or temp directory).
        base_deps: Dependencies to install in the venv. Defaults to
            ("ipykernel",) for RPC-based namespace access. pyzmq is included
            automatically as an ipykernel dependency.
        startup_timeout: Timeout for kernel to become ready (seconds).
        default_timeout: Default timeout for code execution (seconds).
            None means no timeout (unlimited).
        allow_runtime_deps: Enable deps.add() for runtime dependency installation.
        cleanup_venv_on_close: Delete venv on close. None means auto-detect:
            False if cache_venv=True, True if cache_venv=False.
        cache_venv: Enable persistent venv caching. When True and venv_path is None,
            uses canonical cache path (~/.cache/py-code-mode/venv-{version}).
            Default: True.
        tools_path: Path to directory with YAML tool definitions.
            None means no tools loaded from filesystem.
        deps: Tuple of user-configured package specs to pre-install
            (e.g., ("pandas>=2.0", "numpy")). Distinct from base_deps which
            are kernel dependencies. None means no pre-configured user deps.
        deps_file: Path to requirements.txt-style file for pre-configured deps.
            None means no deps file.
        ipc_timeout: Timeout for IPC queries (tool/skill/artifact) in seconds.
            None means unlimited (default).
    """

    python_version: str | None = None
    venv_path: Path | None = None
    base_deps: tuple[str, ...] = ("ipykernel",)
    startup_timeout: float = 30.0
    default_timeout: float | None = 60.0
    allow_runtime_deps: bool = True
    cleanup_venv_on_close: bool | None = None
    cache_venv: bool = True
    tools_path: Path | None = None
    deps: tuple[str, ...] | None = None
    deps_file: Path | None = None
    ipc_timeout: float | None = None

    def __post_init__(self) -> None:
        """Validate configuration values."""
        # Auto-detect python_version if None
        if self.python_version is None:
            object.__setattr__(self, "python_version", _get_current_python_version())

        # Validate python_version (now guaranteed to be str)
        version = self.python_version  # type: ignore[union-attr]
        stripped = version.strip()
        if not stripped:
            raise ValueError("python_version cannot be empty or whitespace-only")
        if not _PYTHON_VERSION_PATTERN.match(stripped):
            raise ValueError(
                f"python_version must be in major.minor format (e.g., '3.11'), got: {version!r}"
            )

        # Validate timeouts
        if self.startup_timeout <= 0.0:
            raise ValueError(f"startup_timeout must be positive, got: {self.startup_timeout}")
        if self.default_timeout is not None and self.default_timeout <= 0.0:
            msg = f"default_timeout must be positive or None, got: {self.default_timeout}"
            raise ValueError(msg)

    @staticmethod
    def get_canonical_venv_path(python_version: str) -> Path:
        """Get deterministic cache path for venv.

        Returns: ~/.cache/py-code-mode/venv-{python_version}
        Respects XDG_CACHE_HOME environment variable.

        Args:
            python_version: Python version string (e.g., "3.11", "3.12").

        Returns:
            Absolute path to the canonical venv location.
        """
        xdg_cache = os.environ.get("XDG_CACHE_HOME")
        if xdg_cache:
            cache_dir = Path(xdg_cache)
        else:
            cache_dir = Path.home() / ".cache"
        return cache_dir / "py-code-mode" / f"venv-{python_version}"

    def get_resolved_cleanup(self) -> bool:
        """Resolve cleanup_venv_on_close to a boolean.

        When None (auto):
        - cache_venv=True -> False (don't cleanup cached venv)
        - cache_venv=False -> True (cleanup temp venv)

        When explicit bool, return that value.

        Returns:
            True if venv should be cleaned up on close, False otherwise.
        """
        if self.cleanup_venv_on_close is not None:
            return self.cleanup_venv_on_close
        # Auto: opposite of cache_venv
        return not self.cache_venv
