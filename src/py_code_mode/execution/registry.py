"""Backend registry for execution backends.

Provides functions to register, retrieve, and list available
execution backends at runtime.
"""

from __future__ import annotations

# Backend registry
_backends: dict[str, type] = {}


def register_backend(name: str, executor_class: type) -> None:
    """Register a backend executor class.

    Args:
        name: Backend name (e.g., "in-process", "container")
        executor_class: Class that implements the Executor protocol
    """
    _backends[name] = executor_class


def get_backend(name: str) -> type | None:
    """Get a registered backend by name.

    Args:
        name: Backend name

    Returns:
        Executor class or None if not found
    """
    return _backends.get(name)


def list_backends() -> list[str]:
    """List all registered backend names.

    Returns:
        List of registered backend names
    """
    return list(_backends.keys())
