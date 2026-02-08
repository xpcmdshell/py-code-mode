"""ArtifactsNamespace - agent-facing API for artifact storage."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from py_code_mode.artifacts.base import ArtifactStoreProtocol


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
        return self._store.save(name, data, description=description, metadata=metadata)

    def load(self, name: str) -> Any:
        return self._store.load(name)

    def list(self) -> Any:
        return self._store.list()

    def exists(self, name: str) -> Any:
        return bool(self._store.exists(name))

    def get(self, name: str) -> Any:
        return self._store.get(name)

    def delete(self, name: str) -> Any:
        self._store.delete(name)
        return None
