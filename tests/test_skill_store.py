"""Tests for WorkflowStore protocol and implementations."""

from pathlib import Path

import pytest

from py_code_mode.workflows import (
    FileWorkflowStore,
    MemoryWorkflowStore,
    PythonWorkflow,
    RedisWorkflowStore,
    WorkflowStore,
)

# --- Fixtures ---


@pytest.fixture
def sample_python_workflow() -> PythonWorkflow:
    """A simple Python workflow for testing."""
    return PythonWorkflow.from_source(
        name="greet",
        source='async def run(name: str) -> str:\n    return f"Hello, {name}!"',
        description="Greet someone",
    )


@pytest.fixture
def another_python_workflow() -> PythonWorkflow:
    """Another Python workflow for testing list operations."""
    return PythonWorkflow.from_source(
        name="farewell",
        source='async def run() -> str:\n    return "Goodbye!"',
        description="Say goodbye",
    )


@pytest.fixture
def memory_store() -> MemoryWorkflowStore:
    """Fresh in-memory store."""
    return MemoryWorkflowStore()


@pytest.fixture
def file_store(tmp_path: Path) -> FileWorkflowStore:
    """File store in temp directory."""
    return FileWorkflowStore(tmp_path)


# --- WorkflowStore Protocol Tests ---


class TestWorkflowStoreProtocol:
    """Verify implementations satisfy the WorkflowStore protocol."""

    def test_memory_store_is_workflow_store(self):
        """MemoryWorkflowStore should satisfy WorkflowStore protocol."""
        store = MemoryWorkflowStore()
        assert isinstance(store, WorkflowStore)

    def test_file_store_is_workflow_store(self, tmp_path: Path):
        """FileWorkflowStore should satisfy WorkflowStore protocol."""
        store = FileWorkflowStore(tmp_path)
        assert isinstance(store, WorkflowStore)


# --- MemoryWorkflowStore Tests ---


class TestMemoryWorkflowStore:
    """Tests for in-memory workflow store."""

    def test_save_and_load_python_workflow(
        self, memory_store: MemoryWorkflowStore, sample_python_workflow: PythonWorkflow
    ):
        """Should save and load a Python workflow."""
        memory_store.save(sample_python_workflow)
        loaded = memory_store.load("greet")

        assert loaded is not None
        assert loaded.name == "greet"
        assert loaded.description == "Greet someone"

    def test_load_nonexistent_returns_none(self, memory_store: MemoryWorkflowStore):
        """Should return None for nonexistent workflow."""
        assert memory_store.load("nonexistent") is None

    def test_delete_existing_workflow(
        self, memory_store: MemoryWorkflowStore, sample_python_workflow: PythonWorkflow
    ):
        """Should delete an existing workflow."""
        memory_store.save(sample_python_workflow)
        result = memory_store.delete("greet")

        assert result is True
        assert memory_store.load("greet") is None

    def test_delete_nonexistent_returns_false(self, memory_store: MemoryWorkflowStore):
        """Should return False when deleting nonexistent workflow."""
        result = memory_store.delete("nonexistent")
        assert result is False

    def test_list_all_empty(self, memory_store: MemoryWorkflowStore):
        """Should return empty list for empty store."""
        assert memory_store.list_all() == []

    def test_list_all_with_workflows(
        self,
        memory_store: MemoryWorkflowStore,
        sample_python_workflow: PythonWorkflow,
        another_python_workflow: PythonWorkflow,
    ):
        """Should list all saved workflows."""
        memory_store.save(sample_python_workflow)
        memory_store.save(another_python_workflow)

        workflows = memory_store.list_all()
        names = {s.name for s in workflows}

        assert len(workflows) == 2
        assert names == {"greet", "farewell"}

    def test_exists_true_for_saved_workflow(
        self, memory_store: MemoryWorkflowStore, sample_python_workflow: PythonWorkflow
    ):
        """Should return True for existing workflow."""
        memory_store.save(sample_python_workflow)
        assert memory_store.exists("greet") is True

    def test_exists_false_for_missing_workflow(self, memory_store: MemoryWorkflowStore):
        """Should return False for nonexistent workflow."""
        assert memory_store.exists("nonexistent") is False

    def test_save_overwrites_existing(
        self, memory_store: MemoryWorkflowStore, sample_python_workflow: PythonWorkflow
    ):
        """Saving with same name should overwrite."""
        memory_store.save(sample_python_workflow)

        updated = PythonWorkflow.from_source(
            name="greet",
            source='async def run(name: str) -> str:\n    return f"Hi, {name}!"',
            description="Updated greeting",
        )
        memory_store.save(updated)

        loaded = memory_store.load("greet")
        assert loaded is not None
        assert loaded.description == "Updated greeting"


# --- FileWorkflowStore Tests ---


class TestFileWorkflowStore:
    """Tests for file-based workflow store."""

    def test_save_creates_python_file(
        self, file_store: FileWorkflowStore, sample_python_workflow: PythonWorkflow, tmp_path: Path
    ):
        """Should write .py file to disk."""
        file_store.save(sample_python_workflow)

        expected_path = tmp_path / "greet.py"
        assert expected_path.exists()
        assert "def run" in expected_path.read_text()

    def test_load_reads_python_file(
        self, file_store: FileWorkflowStore, sample_python_workflow: PythonWorkflow
    ):
        """Should load workflow from .py file."""
        file_store.save(sample_python_workflow)
        loaded = file_store.load("greet")

        assert loaded is not None
        assert loaded.name == "greet"
        assert isinstance(loaded, PythonWorkflow)

    def test_load_nonexistent_returns_none(self, file_store: FileWorkflowStore):
        """Should return None for nonexistent file."""
        assert file_store.load("nonexistent") is None

    def test_delete_removes_file(
        self, file_store: FileWorkflowStore, sample_python_workflow: PythonWorkflow, tmp_path: Path
    ):
        """Should delete .py file from disk."""
        file_store.save(sample_python_workflow)
        result = file_store.delete("greet")

        assert result is True
        assert not (tmp_path / "greet.py").exists()

    def test_delete_nonexistent_returns_false(self, file_store: FileWorkflowStore):
        """Should return False when file doesn't exist."""
        result = file_store.delete("nonexistent")
        assert result is False

    def test_list_all_finds_py_files(
        self, file_store: FileWorkflowStore, sample_python_workflow: PythonWorkflow
    ):
        """Should list all .py files in directory."""
        file_store.save(sample_python_workflow)

        # Create another workflow
        another = PythonWorkflow.from_source(
            name="farewell",
            source='async def run() -> str:\n    return "Goodbye!"',
            description="Say goodbye",
        )
        file_store.save(another)

        workflows = file_store.list_all()
        names = {s.name for s in workflows}

        assert len(workflows) == 2
        assert names == {"greet", "farewell"}

    def test_list_all_ignores_underscore_files(self, file_store: FileWorkflowStore, tmp_path: Path):
        """Should skip files starting with underscore."""
        # Create __init__.py
        (tmp_path / "__init__.py").write_text("")
        (tmp_path / "_private.py").write_text("async def run(): pass")

        workflows = file_store.list_all()
        assert len(workflows) == 0

    def test_exists_checks_file(
        self, file_store: FileWorkflowStore, sample_python_workflow: PythonWorkflow
    ):
        """Should check if .py file exists."""
        assert file_store.exists("greet") is False

        file_store.save(sample_python_workflow)
        assert file_store.exists("greet") is True


# --- RedisWorkflowStore Tests (Mocked) ---


class TestRedisWorkflowStore:
    """Tests for Redis-based workflow store."""

    @pytest.fixture
    def mock_redis(self):
        """Mock Redis client."""

        class MockRedis:
            def __init__(self):
                self._data: dict[str, dict[str, str]] = {}

            def hset(self, key: str, field: str, value: str) -> int:
                if key not in self._data:
                    self._data[key] = {}
                self._data[key][field] = value
                return 1

            def hget(self, key: str, field: str) -> str | None:
                return self._data.get(key, {}).get(field)

            def hdel(self, key: str, field: str) -> int:
                if key in self._data and field in self._data[key]:
                    del self._data[key][field]
                    return 1
                return 0

            def hgetall(self, key: str) -> dict[str, str]:
                return self._data.get(key, {})

            def hexists(self, key: str, field: str) -> bool:
                return field in self._data.get(key, {})

        return MockRedis()

    @pytest.fixture
    def redis_store(self, mock_redis) -> RedisWorkflowStore:
        """Redis store with mock client."""
        return RedisWorkflowStore(mock_redis, prefix="test-workflows")

    def test_save_and_load_python_workflow(
        self, redis_store: RedisWorkflowStore, sample_python_workflow: PythonWorkflow
    ):
        """Should serialize and deserialize Python workflow."""
        redis_store.save(sample_python_workflow)
        loaded = redis_store.load("greet")

        assert loaded is not None
        assert loaded.name == "greet"
        assert loaded.description == "Greet someone"
        # Stored workflows have source and can invoke - duck typing
        assert hasattr(loaded, "source")
        assert hasattr(loaded, "invoke")

    def test_load_nonexistent_returns_none(self, redis_store: RedisWorkflowStore):
        """Should return None for nonexistent workflow."""
        assert redis_store.load("nonexistent") is None

    def test_delete_existing_workflow(
        self, redis_store: RedisWorkflowStore, sample_python_workflow: PythonWorkflow
    ):
        """Should delete workflow from Redis."""
        redis_store.save(sample_python_workflow)
        result = redis_store.delete("greet")

        assert result is True
        assert redis_store.load("greet") is None

    def test_delete_nonexistent_returns_false(self, redis_store: RedisWorkflowStore):
        """Should return False when workflow doesn't exist."""
        result = redis_store.delete("nonexistent")
        assert result is False

    def test_list_all(
        self, redis_store: RedisWorkflowStore, sample_python_workflow: PythonWorkflow
    ):
        """Should list all workflows from Redis."""
        redis_store.save(sample_python_workflow)

        another = PythonWorkflow.from_source(
            name="farewell",
            source='async def run() -> str:\n    return "Goodbye!"',
            description="Say goodbye",
        )
        redis_store.save(another)

        workflows = redis_store.list_all()
        names = {s.name for s in workflows}

        assert len(workflows) == 2
        assert names == {"greet", "farewell"}

    def test_exists(self, redis_store: RedisWorkflowStore, sample_python_workflow: PythonWorkflow):
        """Should check if workflow exists in Redis."""
        assert redis_store.exists("greet") is False

        redis_store.save(sample_python_workflow)
        assert redis_store.exists("greet") is True

    def test_uses_prefix_for_redis_key(self, mock_redis, sample_python_workflow: PythonWorkflow):
        """Should use configured prefix for Redis hash key."""
        store = RedisWorkflowStore(mock_redis, prefix="my-prefix")
        store.save(sample_python_workflow)

        # Check the key in mock redis
        assert "my-prefix:__workflows__" in mock_redis._data


# --- FileWorkflowStore Name Validation Tests ---


def _make_workflow_with_invalid_name(name: str) -> PythonWorkflow:
    """Create a PythonWorkflow with an arbitrary name, bypassing from_source validation.

    This is for testing the store-level validation, not workflow construction.
    In production, PythonWorkflow.from_source already validates names, but
    FileWorkflowStore should also validate as defense-in-depth.
    """
    # Create a valid workflow first
    valid_workflow = PythonWorkflow.from_source(
        name="temp_valid_name",
        source="async def run(): pass",
        description="test",
    )
    # Replace the name with the invalid one for testing
    # This simulates what could happen if someone constructs a PythonWorkflow directly
    return PythonWorkflow(
        name=name,
        description=valid_workflow.description,
        parameters=valid_workflow.parameters,
        source=valid_workflow.source,
        _func=valid_workflow._func,
        metadata=valid_workflow.metadata,
    )


class TestFileWorkflowStoreNameValidation:
    """Security tests for workflow name validation to prevent path traversal."""

    def test_invalid_workflow_name_rejected_dotdot_save(self, tmp_path: Path) -> None:
        """save() rejects path traversal names with ../"""
        store = FileWorkflowStore(tmp_path / "workflows")
        workflow = _make_workflow_with_invalid_name("../malicious")
        with pytest.raises(ValueError, match="Invalid workflow name"):
            store.save(workflow)

    def test_invalid_workflow_name_rejected_dotdot_load(self, tmp_path: Path) -> None:
        """load() rejects path traversal names with ../"""
        store = FileWorkflowStore(tmp_path / "workflows")
        with pytest.raises(ValueError, match="Invalid workflow name"):
            store.load("../malicious")

    def test_invalid_workflow_name_rejected_dotdot_delete(self, tmp_path: Path) -> None:
        """delete() rejects path traversal names with ../"""
        store = FileWorkflowStore(tmp_path / "workflows")
        with pytest.raises(ValueError, match="Invalid workflow name"):
            store.delete("../malicious")

    def test_invalid_workflow_name_rejected_dotdot_exists(self, tmp_path: Path) -> None:
        """exists() rejects path traversal names with ../"""
        store = FileWorkflowStore(tmp_path / "workflows")
        with pytest.raises(ValueError, match="Invalid workflow name"):
            store.exists("../malicious")

    def test_invalid_workflow_name_rejected_slash(self, tmp_path: Path) -> None:
        """save() rejects names with forward slashes."""
        store = FileWorkflowStore(tmp_path / "workflows")
        workflow = _make_workflow_with_invalid_name("foo/bar")
        with pytest.raises(ValueError, match="Invalid workflow name"):
            store.save(workflow)

    def test_invalid_workflow_name_rejected_backslash(self, tmp_path: Path) -> None:
        """save() rejects names with backslashes."""
        store = FileWorkflowStore(tmp_path / "workflows")
        workflow = _make_workflow_with_invalid_name("foo\\bar")
        with pytest.raises(ValueError, match="Invalid workflow name"):
            store.save(workflow)

    def test_invalid_workflow_name_rejected_starts_with_digit(self, tmp_path: Path) -> None:
        """save() rejects names starting with a digit (invalid Python identifier)."""
        store = FileWorkflowStore(tmp_path / "workflows")
        workflow = _make_workflow_with_invalid_name("123workflow")
        with pytest.raises(ValueError, match="Invalid workflow name"):
            store.save(workflow)

    def test_invalid_workflow_name_rejected_special_chars(self, tmp_path: Path) -> None:
        """save() rejects names with special characters."""
        store = FileWorkflowStore(tmp_path / "workflows")
        for name in ["workflow@name", "workflow-name", "workflow.name", "workflow name"]:
            workflow = _make_workflow_with_invalid_name(name)
            with pytest.raises(ValueError, match="Invalid workflow name"):
                store.save(workflow)

    def test_valid_workflow_names_accepted(self, tmp_path: Path) -> None:
        """Valid Python identifiers are accepted."""
        store = FileWorkflowStore(tmp_path / "workflows")
        for name in ["my_workflow", "workflow123", "_private", "CamelCase", "__dunder__"]:
            workflow = PythonWorkflow.from_source(
                name=name,
                source="async def run(): pass",
                description="test",
            )
            store.save(workflow)
            assert store.exists(name)
