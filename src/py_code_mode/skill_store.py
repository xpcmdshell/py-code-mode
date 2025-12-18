"""Skill persistence layer - stores and retrieves skills without search logic."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from py_code_mode.skills import PythonSkill, SkillMetadata

if TYPE_CHECKING:
    from redis import Redis

logger = logging.getLogger(__name__)


@runtime_checkable
class SkillStore(Protocol):
    """Protocol for skill persistence. No search logic - just storage."""

    def save(self, skill: PythonSkill) -> None:
        """Persist a skill."""
        ...

    def load(self, name: str) -> PythonSkill | None:
        """Load a skill by name. Returns None if not found."""
        ...

    def delete(self, name: str) -> bool:
        """Delete a skill. Returns True if deleted, False if not found."""
        ...

    def list_all(self) -> list[PythonSkill]:
        """List all persisted skills."""
        ...

    def exists(self, name: str) -> bool:
        """Check if a skill exists."""
        ...


class MemorySkillStore:
    """In-memory skill store for testing and ephemeral use."""

    def __init__(self) -> None:
        self._skills: dict[str, PythonSkill] = {}

    def save(self, skill: PythonSkill) -> None:
        """Store skill in memory."""
        self._skills[skill.name] = skill

    def load(self, name: str) -> PythonSkill | None:
        """Load skill from memory."""
        return self._skills.get(name)

    def delete(self, name: str) -> bool:
        """Remove skill from memory."""
        if name in self._skills:
            del self._skills[name]
            return True
        return False

    def list_all(self) -> list[PythonSkill]:
        """List all skills in memory."""
        return list(self._skills.values())

    def exists(self, name: str) -> bool:
        """Check if skill exists in memory."""
        return name in self._skills


class FileSkillStore:
    """File-based skill store. Reads/writes .py files to a directory."""

    def __init__(self, directory: Path) -> None:
        """Initialize file store.

        Args:
            directory: Directory to store skill files.
        """
        self._directory = directory
        # Ensure directory exists
        self._directory.mkdir(parents=True, exist_ok=True)

    def save(self, skill: PythonSkill) -> None:
        """Write skill source to .py file."""
        path = self._directory / f"{skill.name}.py"
        path.write_text(skill.source)

    def load(self, name: str) -> PythonSkill | None:
        """Load skill from .py file."""
        path = self._directory / f"{name}.py"
        if not path.exists():
            return None
        try:
            return PythonSkill.from_file(path)
        except Exception as e:
            logger.warning(f"Failed to load skill '{name}' from {path}: {type(e).__name__}: {e}")
            return None

    def delete(self, name: str) -> bool:
        """Delete skill .py file."""
        path = self._directory / f"{name}.py"
        if path.exists():
            path.unlink()
            return True
        return False

    def list_all(self) -> list[PythonSkill]:
        """Load all .py skill files from directory."""
        skills: list[PythonSkill] = []
        for path in self._directory.glob("*.py"):
            # Skip files starting with underscore
            if path.name.startswith("_"):
                continue
            try:
                skill = PythonSkill.from_file(path)
                skills.append(skill)
            except Exception as e:
                logger.warning(f"Failed to load skill from {path}: {type(e).__name__}: {e}")
                continue
        return skills

    def exists(self, name: str) -> bool:
        """Check if skill .py file exists."""
        path = self._directory / f"{name}.py"
        return path.exists()


class RedisSkillStore:
    """Redis-based skill store. Persists skills as JSON in a Redis hash."""

    # Suffix appended to prefix for Redis hash key: {prefix}:__skills__
    HASH_KEY = ":__skills__"

    def __init__(self, redis: Redis, prefix: str = "skills") -> None:
        """Initialize Redis store.

        Args:
            redis: Redis client instance.
            prefix: Key prefix for the skills hash.
        """
        self._redis = redis
        self._prefix = prefix

    def _hash_key(self) -> str:
        """Build the Redis hash key."""
        return f"{self._prefix}{self.HASH_KEY}"

    def save(self, skill: PythonSkill) -> None:
        """Serialize and store skill in Redis."""
        data = {
            "name": skill.name,
            "description": skill.description,
            "source": skill.source,
            "parameters": [asdict(p) for p in skill.parameters],
        }
        self._redis.hset(self._hash_key(), skill.name, json.dumps(data))

    def save_batch(self, skills: list[PythonSkill]) -> None:
        """Serialize and store multiple skills in Redis using a pipeline."""
        if not skills:
            return
        pipe = self._redis.pipeline()
        for skill in skills:
            data = {
                "name": skill.name,
                "description": skill.description,
                "source": skill.source,
                "parameters": [asdict(p) for p in skill.parameters],
            }
            pipe.hset(self._hash_key(), skill.name, json.dumps(data))
        pipe.execute()

    def _deserialize_skill(self, data: dict[str, Any]) -> PythonSkill:
        """Deserialize skill from stored JSON data."""
        required = ("name", "source", "description")
        missing = [k for k in required if k not in data]
        if missing:
            raise ValueError(f"Invalid skill data: missing keys {missing}")

        return PythonSkill.from_source(
            name=data["name"],
            source=data["source"],
            description=data["description"],
            metadata=SkillMetadata(
                created_at=datetime.now(UTC),
                created_by="unknown",
                source="redis",
            ),
        )

    def load(self, name: str) -> PythonSkill | None:
        """Load skill from Redis by name."""
        try:
            value = self._redis.hget(self._hash_key(), name)
            if value is None:
                return None

            if isinstance(value, bytes):
                value = value.decode()

            data = json.loads(value)
            return self._deserialize_skill(data)
        except Exception as e:
            logger.warning(f"Failed to load skill '{name}': {type(e).__name__}: {e}")
            return None

    def delete(self, name: str) -> bool:
        """Delete skill from Redis."""
        result = self._redis.hdel(self._hash_key(), name)
        return result > 0

    def list_all(self) -> list[PythonSkill]:
        """List all skills from Redis."""
        all_data = self._redis.hgetall(self._hash_key())
        if not all_data:
            return []

        skills = []
        for name, value in all_data.items():
            try:
                if isinstance(value, bytes):
                    value = value.decode()
                if isinstance(name, bytes):
                    name = name.decode()
                data = json.loads(value)
                skills.append(self._deserialize_skill(data))
            except Exception as e:
                logger.warning(f"Failed to deserialize skill '{name}': {type(e).__name__}: {e}")
                continue

        return skills

    def exists(self, name: str) -> bool:
        """Check if skill exists in Redis."""
        return self._redis.hexists(self._hash_key(), name)
