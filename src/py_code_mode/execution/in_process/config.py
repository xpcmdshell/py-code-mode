"""Configuration for InProcessExecutor."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class InProcessConfig:
    """Configuration for InProcessExecutor.

    Attributes:
        default_timeout: Default timeout for code execution in seconds.
                        None means no timeout (unlimited).
        allow_runtime_deps: If True, all deps methods are allowed.
                           If False, deps.add() and deps.remove() are blocked.
                           deps.list() and deps.sync() always work.
                           Default: True.
        tools_path: Path to directory with YAML tool definitions.
                   None means no tools loaded from filesystem.
        deps: Tuple of package specs to pre-install (e.g., ("pandas>=2.0", "numpy")).
             None means no pre-configured deps.
        deps_file: Path to requirements.txt-style file for pre-configured deps.
                  None means no deps file.
        ipc_timeout: Timeout for IPC queries (tool/skill/artifact) in seconds.
                    Default: 30.0.
    """

    default_timeout: float | None = 30.0
    allow_runtime_deps: bool = True
    tools_path: Path | None = None
    deps: tuple[str, ...] | None = None
    deps_file: Path | None = None
    ipc_timeout: float = 30.0
