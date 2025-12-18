"""Redis-based artifact storage with metadata index."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from py_code_mode.artifacts import Artifact
from py_code_mode.errors import ArtifactNotFoundError

if TYPE_CHECKING:
    from redis import Redis


class RedisArtifactStore:
    """Redis-based artifact storage.

    Uses Redis keys for data storage and a hash for metadata index.
    Key format: {prefix}:{name}
    Index key: {prefix}:__index__
    """

    INDEX_SUFFIX = ":__index__"

    def __init__(self, redis: Redis, prefix: str = "artifacts") -> None:
        """Initialize store with Redis client.

        Args:
            redis: Redis client instance.
            prefix: Key prefix for all artifacts. Defaults to 'artifacts'.
        """
        self._redis = redis
        self._prefix = prefix

    @property
    def path(self) -> str:
        """Base prefix for this store (protocol compliance)."""
        return self._prefix

    def _data_key(self, name: str) -> str:
        """Build data key from artifact name."""
        return f"{self._prefix}:{name}"

    def _index_key(self) -> str:
        """Build index hash key."""
        return f"{self._prefix}{self.INDEX_SUFFIX}"

    def save(
        self,
        name: str,
        data: str | bytes | dict | list,
        description: str,
        metadata: dict[str, Any] | None = None,
    ) -> Artifact:
        """Save data as an artifact.

        Args:
            name: Artifact name (can include path separators like 'scans/nmap.json').
            data: Content to save. Dicts/lists are JSON serialized.
            description: Human-readable description for discovery.
            metadata: Optional additional metadata.

        Returns:
            Artifact metadata object.
        """
        data_key = self._data_key(name)

        # Serialize data
        if isinstance(data, bytes):
            self._redis.set(data_key, data)
        elif isinstance(data, (dict, list)):
            self._redis.set(data_key, json.dumps(data))
        else:
            self._redis.set(data_key, str(data))

        # Update index
        now = datetime.now(UTC)
        index_entry = {
            "description": description,
            "created_at": now.isoformat(),
            "metadata": metadata or {},
        }
        self._redis.hset(self._index_key(), name, json.dumps(index_entry))

        return Artifact(
            name=name,
            path=data_key,
            description=description,
            metadata=metadata or {},
            created_at=now,
        )

    def load(self, name: str) -> Any:
        """Load artifact content.

        Args:
            name: Artifact name.

        Returns:
            Stored content. JSON files are deserialized.

        Raises:
            ArtifactNotFoundError: If artifact doesn't exist.
        """
        data_key = self._data_key(name)
        content = self._redis.get(data_key)

        if content is None:
            raise ArtifactNotFoundError(f"Artifact not found: {name}")

        # Try JSON deserialization for .json files
        if name.endswith(".json"):
            try:
                return json.loads(content)
            except (json.JSONDecodeError, TypeError):
                pass

        return content

    def get(self, name: str) -> Artifact | None:
        """Get artifact metadata by name.

        Args:
            name: Artifact name.

        Returns:
            Artifact metadata or None if not found.
        """
        entry_json = self._redis.hget(self._index_key(), name)
        if entry_json is None:
            return None

        entry = json.loads(entry_json)
        return Artifact(
            name=name,
            path=self._data_key(name),
            description=entry["description"],
            metadata=entry.get("metadata", {}),
            created_at=datetime.fromisoformat(entry["created_at"]),
        )

    def list(self) -> list[Artifact]:
        """List all artifacts with metadata.

        Returns:
            List of Artifact objects.
        """
        index_data = self._redis.hgetall(self._index_key())
        if not index_data:
            return []

        artifacts = []
        for name, entry_json in index_data.items():
            entry = json.loads(entry_json)
            artifacts.append(
                Artifact(
                    name=name,
                    path=self._data_key(name),
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
        return self._redis.hexists(self._index_key(), name)

    def delete(self, name: str) -> None:
        """Delete artifact and its index entry.

        Args:
            name: Artifact name.
        """
        # Delete data
        self._redis.delete(self._data_key(name))
        # Remove from index
        self._redis.hdel(self._index_key(), name)
