"""Configuration for InProcessExecutor."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InProcessConfig:
    """Configuration for InProcessExecutor.

    Attributes:
        default_timeout: Default timeout for code execution in seconds.
        allow_runtime_deps: If True, deps.add() and deps.sync() are allowed.
                           If False, only deps.list() and deps.remove() work.
                           Default: True (backward compatible).
    """

    default_timeout: float = 30.0
    allow_runtime_deps: bool = True
