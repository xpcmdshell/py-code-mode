"""Async-capable wrapper for deps namespace.

The base DepsNamespace API is synchronous (it may run pip). For sandbox
consistency with async executors, this wrapper allows:
  - deps.add(...)  (sync)
  - await deps.add(...) (async)

The async variants simply run the synchronous operations in-process.
"""

from __future__ import annotations

import asyncio
from typing import Any

from py_code_mode.deps.namespace import DepsNamespace


def _in_async_context() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


class AsyncDepsNamespace:
    """Wrapper around DepsNamespace providing optional await support."""

    def __init__(self, wrapped: DepsNamespace) -> None:
        self._wrapped = wrapped

    def add(self, package: str) -> Any:
        if _in_async_context():

            async def _coro() -> Any:
                return self._wrapped.add(package)

            return _coro()
        return self._wrapped.add(package)

    def list(self) -> Any:
        if _in_async_context():

            async def _coro() -> list[str]:
                return self._wrapped.list()

            return _coro()
        return self._wrapped.list()

    def remove(self, package: str) -> Any:
        if _in_async_context():

            async def _coro() -> bool:
                return self._wrapped.remove(package)

            return _coro()
        return self._wrapped.remove(package)

    def sync(self) -> Any:
        if _in_async_context():

            async def _coro() -> Any:
                return self._wrapped.sync()

            return _coro()
        return self._wrapped.sync()

    def __repr__(self) -> str:
        return repr(self._wrapped)
