"""ArtifactsNamespace - agent-facing API for artifact storage.

This mirrors the sandbox ergonomics used by the Deno/Pyodide executor: a small,
high-level API exposed as `artifacts.*` inside executed code.

Design goal: allow both sync usage (`artifacts.load(...)`) and async usage
(`await artifacts.load(...)`) depending on execution context.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from py_code_mode.artifacts.base import ArtifactStoreProtocol


def _in_async_context() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


class ArtifactsNamespace:
    """Agent-facing namespace for artifacts.

    Provides:
    - artifacts.save(name, data, description="", metadata=None)
    - artifacts.load(name)
    - artifacts.list()
    - artifacts.exists(name)
    - artifacts.get(name)
    - artifacts.delete(name)

    This wrapper intentionally exposes a subset of the underlying store API to
    keep the sandbox surface stable.
    """

    def __init__(self, store: ArtifactStoreProtocol) -> None:
        self._store = store

    @property
    def path(self) -> Any:
        # Keep compatibility with FileArtifactStore.path.
        return getattr(self._store, "path", None)

    def save(
        self,
        name: str,
        data: Any,
        description: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        if _in_async_context():

            async def _coro() -> Any:
                return self._store.save(name, data, description=description, metadata=metadata)

            return _coro()
        return self._store.save(name, data, description=description, metadata=metadata)

    def load(self, name: str) -> Any:
        if _in_async_context():

            async def _coro() -> Any:
                return self._store.load(name)

            return _coro()
        return self._store.load(name)

    def list(self) -> Any:
        if _in_async_context():

            async def _coro() -> Any:
                return self._store.list()

            return _coro()
        return self._store.list()

    def exists(self, name: str) -> Any:
        if _in_async_context():

            async def _coro() -> bool:
                return bool(self._store.exists(name))

            return _coro()
        return bool(self._store.exists(name))

    def get(self, name: str) -> Any:
        if _in_async_context():

            async def _coro() -> Any:
                return self._store.get(name)

            return _coro()
        return self._store.get(name)

    def delete(self, name: str) -> Any:
        if _in_async_context():

            async def _coro() -> None:
                self._store.delete(name)

            return _coro()
        self._store.delete(name)
        return None
