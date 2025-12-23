"""Configuration for InProcessExecutor."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InProcessConfig:
    """Configuration for InProcessExecutor.

    Attributes:
        default_timeout: Default timeout for code execution in seconds.
        allow_runtime_deps: If True, all deps methods are allowed.
                           If False, deps.add() and deps.remove() are blocked.
                           deps.list() and deps.sync() always work.
                           Default: True.
    """

    default_timeout: float = 30.0
    allow_runtime_deps: bool = True
