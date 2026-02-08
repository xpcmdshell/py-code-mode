"""Configuration for DenoPyodideExecutor."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DenoPyodideConfig:
    """Configuration for DenoPyodideExecutor.

    Notes:
    - This executor expects Pyodide runtime assets (WASM + stdlib files) to be
      present on disk and readable by the Deno subprocess.
    - Dependency installs are best-effort via Pyodide; many wheels will not work.
    """

    default_timeout: float | None = 60.0
    allow_runtime_deps: bool = True
    tools_path: Path | None = None
    deps: tuple[str, ...] | None = None
    deps_file: Path | None = None
    ipc_timeout: float = 30.0
    deps_timeout: float | None = 300.0

    deno_executable: str = "deno"
    # If None, the executor uses the packaged runner script adjacent to this module.
    runner_path: Path | None = None

    # Directory used for Deno's module/npm cache (DENO_DIR). If None, a default
    # per-user cache directory is used. This cache is prepared outside the
    # sandbox (host) via `deno cache`, then the sandbox runs with --cached-only.
    deno_dir: Path | None = None

    # Network profile:
    # - "none": deny all network access (no runtime dep installs)
    # - "deps-only": allow just enough for micropip / pyodide package fetches
    # - "full": allow all network access
    network_profile: str = "full"  # "none" | "deps-only" | "full"

    # Used when network_profile="deps-only".
    deps_net_allowlist: tuple[str, ...] = (
        "pypi.org",
        "files.pythonhosted.org",
        "cdn.jsdelivr.net",
    )
