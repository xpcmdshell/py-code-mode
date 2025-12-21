"""Base types for artifact storage."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable


@dataclass
class Artifact:
    """Metadata for a stored artifact."""

    name: str
    path: str  # Location identifier (file path, redis key, s3 key, etc.)
    description: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@runtime_checkable
class ArtifactStoreProtocol(Protocol):
    """Protocol for artifact storage backends."""

    @property
    def path(self) -> str:
        """Base path/prefix for this store."""
        ...

    def save(
        self,
        name: str,
        data: str | bytes | dict | list,
        description: str,
        metadata: dict[str, Any] | None = None,
    ) -> Artifact:
        """Save data as an artifact."""
        ...

    def load(self, name: str) -> Any:
        """Load artifact content."""
        ...

    def get(self, name: str) -> Artifact | None:
        """Get artifact metadata by name."""
        ...

    def list(self) -> list[Artifact]:
        """List all artifacts with metadata."""
        ...

    def exists(self, name: str) -> bool:
        """Check if artifact exists."""
        ...

    def delete(self, name: str) -> None:
        """Delete artifact."""
        ...
