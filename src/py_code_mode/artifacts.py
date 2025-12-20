"""Artifacts system - pluggable storage with metadata for agent data sharing."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from py_code_mode.errors import ArtifactNotFoundError


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


class FileArtifactStore:
    """File-based artifact storage with metadata index.

    Artifacts are files on disk with an accompanying metadata index.
    Standard file I/O still works via the .path property.
    """

    INDEX_FILE = ".artifacts.json"

    def __init__(self, path: Path | str) -> None:
        """Initialize store at given directory.

        Args:
            path: Directory for artifact storage. Created if not exists.
        """
        self._path = Path(path) if isinstance(path, str) else path
        self._path.mkdir(parents=True, exist_ok=True)
        self._index: dict[str, dict[str, Any]] = self._load_index()

    @property
    def path(self) -> str:
        """Base path for raw file access."""
        return str(self._path)

    @property
    def path_obj(self) -> Path:
        """Base path as Path object for file operations."""
        return self._path

    def _load_index(self) -> dict[str, dict[str, Any]]:
        """Load index from disk."""
        index_path = self._path / self.INDEX_FILE
        if index_path.exists():
            return json.loads(index_path.read_text())
        return {}

    def _save_index(self) -> None:
        """Persist index to disk."""
        index_path = self._path / self.INDEX_FILE
        index_path.write_text(json.dumps(self._index, indent=2, default=str))

    def save(
        self,
        name: str,
        data: str | bytes | dict | list,
        description: str,
        metadata: dict[str, Any] | None = None,
    ) -> Artifact:
        """Save data as an artifact.

        Args:
            name: Artifact name (can include subdirectories like "scans/nmap.json").
            data: Content to save. Dicts/lists are JSON serialized.
            description: Human-readable description for discovery.
            metadata: Optional additional metadata.

        Returns:
            Artifact metadata object.
        """
        file_path = self._path / name

        # Create subdirectories if needed
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Write data and track type
        data_type = "bytes" if isinstance(data, bytes) else "text"
        if isinstance(data, bytes):
            file_path.write_bytes(data)
        elif isinstance(data, (dict, list)):
            file_path.write_text(json.dumps(data, indent=2))
            data_type = "json"
        else:
            file_path.write_text(str(data))

        # Update index
        now = datetime.now(UTC)
        index_metadata = metadata.copy() if metadata else {}
        index_metadata["_data_type"] = data_type
        self._index[name] = {
            "description": description,
            "created_at": now.isoformat(),
            "metadata": index_metadata,
        }
        self._save_index()

        return Artifact(
            name=name,
            path=str(file_path),
            description=description,
            metadata=metadata or {},
            created_at=now,
        )

    def load(self, name: str) -> Any:
        """Load artifact content.

        Args:
            name: Artifact name.

        Returns:
            File content. JSON files are deserialized.

        Raises:
            ArtifactNotFoundError: If artifact doesn't exist.
        """
        file_path = self._path / name

        if not file_path.exists():
            raise ArtifactNotFoundError(f"Artifact not found: {name}")

        # Check metadata for data type
        data_type = None
        if name in self._index:
            data_type = self._index[name].get("metadata", {}).get("_data_type")

        # Load based on stored type
        if data_type == "bytes":
            return file_path.read_bytes()
        elif data_type == "json" or name.endswith(".json"):
            content = file_path.read_text()
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                return content
        else:
            # For text or unknown, try text first, fall back to bytes
            try:
                return file_path.read_text()
            except UnicodeDecodeError:
                return file_path.read_bytes()

    def get(self, name: str) -> Artifact | None:
        """Get artifact metadata by name.

        Args:
            name: Artifact name.

        Returns:
            Artifact metadata or None if not found.
        """
        if name not in self._index:
            return None

        entry = self._index[name]
        return Artifact(
            name=name,
            path=str(self._path / name),
            description=entry["description"],
            metadata=entry.get("metadata", {}),
            created_at=datetime.fromisoformat(entry["created_at"]),
        )

    def list(self) -> list[Artifact]:
        """List all artifacts with metadata.

        Returns:
            List of Artifact objects.
        """
        artifacts = []
        for name, entry in self._index.items():
            artifacts.append(
                Artifact(
                    name=name,
                    path=str(self._path / name),
                    description=entry["description"],
                    metadata=entry.get("metadata", {}),
                    created_at=datetime.fromisoformat(entry["created_at"]),
                )
            )
        return artifacts

    def exists(self, name: str) -> bool:
        """Check if artifact exists.

        Args:
            name: Artifact name.

        Returns:
            True if artifact exists in index.
        """
        return name in self._index

    def delete(self, name: str) -> None:
        """Delete artifact and its index entry.

        Args:
            name: Artifact name.
        """
        file_path = self._path / name
        if file_path.exists():
            file_path.unlink()

        if name in self._index:
            del self._index[name]
            self._save_index()

    def register(
        self,
        name: str,
        description: str,
        metadata: dict[str, Any] | None = None,
    ) -> Artifact:
        """Register an externally created file in the index.

        Args:
            name: Artifact name (must already exist on disk).
            description: Human-readable description.
            metadata: Optional additional metadata.

        Returns:
            Artifact metadata object.

        Raises:
            ArtifactNotFoundError: If file doesn't exist.
        """
        file_path = self._path / name
        if not file_path.exists():
            raise ArtifactNotFoundError(f"File not found: {name}")

        now = datetime.now(UTC)
        self._index[name] = {
            "description": description,
            "created_at": now.isoformat(),
            "metadata": metadata or {},
        }
        self._save_index()

        return Artifact(
            name=name,
            path=str(file_path),
            description=description,
            metadata=metadata or {},
            created_at=now,
        )
