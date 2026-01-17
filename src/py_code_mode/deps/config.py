"""Helpers for parsing deps configuration."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path


def collect_configured_deps(
    deps: Iterable[str] | None,
    deps_file: Path | None,
) -> list[str]:
    """Collect configured deps from config list and optional file.

    Args:
        deps: Iterable of deps from config (e.g. config.deps).
        deps_file: Optional requirements.txt-style file path.

    Returns:
        Combined list of dependency specifications.
    """
    configured = list(deps) if deps else []
    if deps_file and deps_file.exists():
        for line in deps_file.read_text().splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                configured.append(stripped)
    return configured
