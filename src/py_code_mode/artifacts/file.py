"""File-based artifact storage with metadata index."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from py_code_mode.artifacts.base import Artifact, ArtifactStoreProtocol
from py_code_mode.errors import ArtifactNotFoundError


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

    def _safe_path(self, name: str) -> Path:
        """Resolve path and verify it's contained within storage directory.

        Args:
            name: Artifact name (may include subdirectories like "scans/nmap.json").

        Returns:
            Resolved path within storage directory.

        Raises:
            ValueError: If path would escape storage directory.
        """
        resolved = (self._path / name).resolve()
        if not resolved.is_relative_to(self._path.resolve()):
            raise ValueError(f"Path traversal attempt detected: {name!r}")
        return resolved

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

    def _refresh_index(self) -> None:
        """Reload index from disk so external metadata changes are visible."""
        self._index = self._load_index()

    def _save_index(self) -> None:
        """Persist index to disk."""
        index_path = self._path / self.INDEX_FILE
        index_path.write_text(json.dumps(self._index, indent=2, default=str))

    def _drop_index_entries(self, names: list[str]) -> None:
        """Remove tracked artifacts from the index and persist the change."""
        removed = False
        for name in names:
            if name in self._index:
                del self._index[name]
                removed = True
        if removed:
            self._save_index()

    def _reconcile_index(self) -> None:
        """Prune stale or invalid tracked artifacts from the metadata index."""
        stale_names: list[str] = []
        for name in self._index:
            try:
                file_path = self._safe_path(name)
            except ValueError:
                stale_names.append(name)
                continue
            if not file_path.exists():
                stale_names.append(name)
        self._drop_index_entries(stale_names)

    def save(
        self,
        name: str,
        data: str | bytes | dict | list,
        description: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> Artifact:
        """Save data as an artifact.

        Args:
            name: Artifact name (can include subdirectories like "scans/nmap.json").
            data: Content to save. Dicts/lists are JSON serialized.
            description: Human-readable description for discovery (optional).
            metadata: Optional additional metadata.

        Returns:
            Artifact metadata object.

        Raises:
            ValueError: If name contains path traversal sequences.
        """
        file_path = self._safe_path(name)
        self._refresh_index()
        self._reconcile_index()

        # Create subdirectories if needed
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Write data and track type
        data_type = "bytes" if isinstance(data, bytes) else "text"
        if isinstance(data, bytes):
            file_path.write_bytes(data)
        elif isinstance(data, dict | list):
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
            ValueError: If name contains path traversal sequences.
        """
        file_path = self._safe_path(name)
        self._refresh_index()
        self._reconcile_index()

        if name not in self._index:
            raise ArtifactNotFoundError(name)

        # Check metadata for data type
        data_type = self._index[name].get("metadata", {}).get("_data_type")

        if not file_path.exists():
            self._drop_index_entries([name])
            raise ArtifactNotFoundError(name)

        # Load based on stored type
        try:
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
        except FileNotFoundError:
            self._drop_index_entries([name])
            raise ArtifactNotFoundError(name) from None

    def get(self, name: str) -> Artifact | None:
        """Get artifact metadata by name.

        Args:
            name: Artifact name.

        Returns:
            Artifact metadata or None if not found.

        Raises:
            ValueError: If name contains path traversal sequences.
        """
        # Validate path even for metadata lookups to prevent index poisoning
        file_path = self._safe_path(name)
        self._refresh_index()
        self._reconcile_index()

        if name not in self._index:
            return None

        if not file_path.exists():
            self._drop_index_entries([name])
            return None

        entry = self._index[name]
        return Artifact(
            name=name,
            path=str(file_path),
            description=entry["description"],
            metadata=entry.get("metadata", {}),
            created_at=datetime.fromisoformat(entry["created_at"]),
        )

    def list(self) -> list[Artifact]:
        """List all artifacts with metadata.

        Returns:
            List of Artifact objects.

        Note:
            Only returns artifacts with valid paths. Any index entries with
            path traversal attempts are silently skipped.
        """
        self._refresh_index()
        self._reconcile_index()

        artifacts = []
        for name, entry in self._index.items():
            file_path = self._safe_path(name)
            artifacts.append(
                Artifact(
                    name=name,
                    path=str(file_path),
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

        Raises:
            ValueError: If name contains path traversal sequences.
        """
        file_path = self._safe_path(name)
        self._refresh_index()
        self._reconcile_index()

        if name not in self._index:
            return False

        if not file_path.exists():
            self._drop_index_entries([name])
            return False

        return True

    def delete(self, name: str) -> None:
        """Delete artifact and its index entry.

        Args:
            name: Artifact name.

        Raises:
            ValueError: If name contains path traversal sequences.
        """
        file_path = self._safe_path(name)
        self._refresh_index()
        self._reconcile_index()

        if name not in self._index:
            return

        if file_path.exists():
            file_path.unlink()

        self._drop_index_entries([name])

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
            ValueError: If name contains path traversal sequences.
        """
        file_path = self._safe_path(name)
        self._refresh_index()
        self._reconcile_index()
        if not file_path.exists():
            raise ArtifactNotFoundError(name)

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


# Protocol compliance marker
_: ArtifactStoreProtocol = FileArtifactStore(Path("/tmp"))  # type: ignore[arg-type]
