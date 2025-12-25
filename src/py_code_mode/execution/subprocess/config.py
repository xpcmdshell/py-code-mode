"""Configuration for SubprocessExecutor."""

from __future__ import annotations

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
        venv_path: Path to virtual environment. None means auto-create in temp.
        base_deps: Dependencies to install in the venv. Defaults to
            ("ipykernel", "py-code-mode") for namespace injection support.
        startup_timeout: Timeout for kernel to become ready (seconds).
        default_timeout: Default timeout for code execution (seconds).
            None means no timeout (unlimited).
        allow_runtime_deps: Enable deps.add() for runtime dependency installation.
        cleanup_venv_on_close: Delete temp venv on close.
    """

    python_version: str | None = None
    venv_path: Path | None = None
    base_deps: tuple[str, ...] = ("ipykernel", "py-code-mode")
    startup_timeout: float = 30.0
    default_timeout: float | None = 60.0
    allow_runtime_deps: bool = True
    cleanup_venv_on_close: bool = True

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
