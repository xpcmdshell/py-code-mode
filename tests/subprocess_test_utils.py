"""Shared helpers for subprocess integration tests."""

from __future__ import annotations

import re
from pathlib import Path

import pytest


def worker_cached_subprocess_venv_path(
    tmp_path_factory: pytest.TempPathFactory, profile: str
) -> Path:
    """Return a worker-local cached venv path for subprocess tests.

    Using worker-local cache paths avoids repeated venv creation in slow integration
    tests while keeping xdist workers isolated from each other.
    """
    safe_profile = re.sub(r"[^A-Za-z0-9_.-]+", "-", profile).strip("-") or "default"
    cache_root = tmp_path_factory.getbasetemp() / "cached-subprocess-venvs"
    cache_root.mkdir(parents=True, exist_ok=True)
    return cache_root / safe_profile
