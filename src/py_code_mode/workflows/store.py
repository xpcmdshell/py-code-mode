"""Workflow persistence layer - stores and retrieves workflows without search logic."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast, runtime_checkable

from py_code_mode.errors import StorageReadError
from py_code_mode.workflows.workflow import PythonWorkflow, WorkflowMetadata

# Valid workflow name pattern: Python identifier (letters, digits, underscores)
_VALID_WORKFLOW_NAME = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

if TYPE_CHECKING:
    from redis import Redis

logger = logging.getLogger(__name__)


@runtime_checkable
class WorkflowStore(Protocol):
    """Protocol for workflow persistence. No search logic - just storage."""

    def save(self, workflow: PythonWorkflow) -> None:
        """Persist a workflow."""
        ...

    def load(self, name: str) -> PythonWorkflow | None:
        """Load a workflow by name. Returns None if not found."""
        ...

    def delete(self, name: str) -> bool:
        """Delete a workflow. Returns True if deleted, False if not found."""
        ...

    def list_all(self) -> list[PythonWorkflow]:
        """List all persisted workflows."""
        ...

    def exists(self, name: str) -> bool:
        """Check if a workflow exists."""
        ...


class MemoryWorkflowStore:
    """In-memory workflow store for testing and ephemeral use."""

    def __init__(self) -> None:
        self._workflows: dict[str, PythonWorkflow] = {}

    def save(self, workflow: PythonWorkflow) -> None:
        """Store workflow in memory."""
        self._workflows[workflow.name] = workflow

    def load(self, name: str) -> PythonWorkflow | None:
        """Load workflow from memory."""
        return self._workflows.get(name)

    def delete(self, name: str) -> bool:
        """Remove workflow from memory."""
        if name in self._workflows:
            del self._workflows[name]
            return True
        return False

    def list_all(self) -> list[PythonWorkflow]:
        """List all workflows in memory."""
        return list(self._workflows.values())

    def exists(self, name: str) -> bool:
        """Check if workflow exists in memory."""
        return name in self._workflows


class FileWorkflowStore:
    """File-based workflow store. Reads/writes .py files to a directory."""

    def __init__(self, directory: Path) -> None:
        """Initialize file store.

        Args:
            directory: Directory to store workflow files.
        """
        self._directory = directory
        # Ensure directory exists
        self._directory.mkdir(parents=True, exist_ok=True)

    def _validate_workflow_name(self, name: str) -> None:
        """Validate workflow name is a valid Python identifier.

        Args:
            name: Workflow name to validate.

        Raises:
            ValueError: If name is not a valid Python identifier.
        """
        if not _VALID_WORKFLOW_NAME.match(name):
            raise ValueError(
                f"Invalid workflow name: {name!r}. "
                "Workflow names must be valid Python identifiers "
                "(letters, digits, underscores, cannot start with digit)."
            )

    def save(self, workflow: PythonWorkflow) -> None:
        """Write workflow source to .py file.

        Raises:
            ValueError: If workflow name is not a valid Python identifier.
        """
        self._validate_workflow_name(workflow.name)
        path = self._directory / f"{workflow.name}.py"
        path.write_text(workflow.source)

    def load(self, name: str) -> PythonWorkflow | None:
        """Load workflow from .py file.

        Raises:
            ValueError: If workflow name is not a valid Python identifier.
            StorageReadError: If workflow file exists but cannot be parsed.
        """
        self._validate_workflow_name(name)
        path = self._directory / f"{name}.py"
        if not path.exists():
            return None
        try:
            return PythonWorkflow.from_file(path)
        except FileNotFoundError:
            return None
        except (OSError, SyntaxError, ValueError) as e:
            logger.error(f"Failed to load workflow '{name}' from {path}: {type(e).__name__}: {e}")
            raise StorageReadError(f"Failed to load workflow '{name}' from {path}: {e}") from e

    def delete(self, name: str) -> bool:
        """Delete workflow .py file.

        Raises:
            ValueError: If workflow name is not a valid Python identifier.
        """
        self._validate_workflow_name(name)
        path = self._directory / f"{name}.py"
        if path.exists():
            path.unlink()
            return True
        return False

    def list_all(self) -> list[PythonWorkflow]:
        """Load all .py workflow files from directory."""
        workflows: list[PythonWorkflow] = []
        for path in self._directory.glob("*.py"):
            # Skip files starting with underscore
            if path.name.startswith("_"):
                continue
            try:
                workflow = PythonWorkflow.from_file(path)
                workflows.append(workflow)
            except (OSError, SyntaxError, ValueError) as e:
                logger.warning(f"Failed to load workflow from {path}: {type(e).__name__}: {e}")
                continue
        return workflows

    def exists(self, name: str) -> bool:
        """Check if workflow .py file exists.

        Raises:
            ValueError: If workflow name is not a valid Python identifier.
        """
        self._validate_workflow_name(name)
        path = self._directory / f"{name}.py"
        return path.exists()


class RedisWorkflowStore:
    """Redis-based workflow store. Persists workflows as JSON in a Redis hash."""

    # Suffix appended to prefix for Redis hash key: {prefix}:__workflows__
    HASH_KEY = ":__workflows__"

    def __init__(self, redis: Redis, prefix: str = "workflows") -> None:
        """Initialize Redis store.

        Args:
            redis: Redis client instance.
            prefix: Key prefix for the workflows hash.
        """
        self._redis = redis
        self._prefix = prefix

    def _hash_key(self) -> str:
        """Build the Redis hash key."""
        return f"{self._prefix}{self.HASH_KEY}"

    def save(self, workflow: PythonWorkflow) -> None:
        """Serialize and store workflow in Redis."""
        data = {
            "name": workflow.name,
            "description": workflow.description,
            "source": workflow.source,
            "parameters": [asdict(p) for p in workflow.parameters],
        }
        self._redis.hset(self._hash_key(), workflow.name, json.dumps(data))

    def save_batch(self, workflows: list[PythonWorkflow]) -> None:
        """Serialize and store multiple workflows in Redis using a pipeline."""
        if not workflows:
            return
        pipe = self._redis.pipeline()
        for workflow in workflows:
            data = {
                "name": workflow.name,
                "description": workflow.description,
                "source": workflow.source,
                "parameters": [asdict(p) for p in workflow.parameters],
            }
            pipe.hset(self._hash_key(), workflow.name, json.dumps(data))
        pipe.execute()

    def _deserialize_workflow(self, data: dict[str, Any]) -> PythonWorkflow:
        """Deserialize workflow from stored JSON data."""
        required = ("name", "source", "description")
        missing = [k for k in required if k not in data]
        if missing:
            raise ValueError(f"Invalid workflow data: missing keys {missing}")

        return PythonWorkflow.from_source(
            name=data["name"],
            source=data["source"],
            description=data["description"],
            metadata=WorkflowMetadata(
                created_at=datetime.now(UTC),
                created_by="unknown",
                source="redis",
            ),
        )

    def load(self, name: str) -> PythonWorkflow | None:
        """Load workflow from Redis by name."""
        value = cast(str | bytes | None, self._redis.hget(self._hash_key(), name))
        if value is None:
            return None

        try:
            if isinstance(value, bytes):
                value = value.decode()

            data = json.loads(value)
            return self._deserialize_workflow(data)
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Failed to load workflow '{name}': {type(e).__name__}: {e}")
            raise StorageReadError(f"Failed to load workflow '{name}': {e}") from e

    def delete(self, name: str) -> bool:
        """Delete workflow from Redis."""
        result = cast(int, self._redis.hdel(self._hash_key(), name))
        return result > 0

    def list_all(self) -> list[PythonWorkflow]:
        """List all workflows from Redis."""
        all_data = cast(dict[str | bytes, str | bytes], self._redis.hgetall(self._hash_key()))
        if not all_data:
            return []

        workflows = []
        for raw_name, raw_value in all_data.items():
            name = raw_name.decode() if isinstance(raw_name, bytes) else raw_name
            value = raw_value.decode() if isinstance(raw_value, bytes) else raw_value
            try:
                data = json.loads(value)
                workflows.append(self._deserialize_workflow(data))
            except (json.JSONDecodeError, ValueError, SyntaxError, KeyError) as e:
                logger.warning(f"Failed to deserialize workflow '{name}': {type(e).__name__}: {e}")
                continue

        return workflows

    def exists(self, name: str) -> bool:
        """Check if workflow exists in Redis."""
        return bool(self._redis.hexists(self._hash_key(), name))

    def __len__(self) -> int:
        """Return the number of workflows in the store."""
        return cast(int, self._redis.hlen(self._hash_key()))
