"""Tests for SkillStore protocol and implementations."""

from pathlib import Path

import pytest

from py_code_mode.skills import (
    FileSkillStore,
    MemorySkillStore,
    PythonSkill,
    RedisSkillStore,
    SkillStore,
)

# --- Fixtures ---


@pytest.fixture
def sample_python_skill() -> PythonSkill:
    """A simple Python skill for testing."""
    return PythonSkill.from_source(
        name="greet",
        source='async def run(name: str) -> str:\n    return f"Hello, {name}!"',
        description="Greet someone",
    )


@pytest.fixture
def another_python_skill() -> PythonSkill:
    """Another Python skill for testing list operations."""
    return PythonSkill.from_source(
        name="farewell",
        source='async def run() -> str:\n    return "Goodbye!"',
        description="Say goodbye",
    )


@pytest.fixture
def memory_store() -> MemorySkillStore:
    """Fresh in-memory store."""
    return MemorySkillStore()


@pytest.fixture
def file_store(tmp_path: Path) -> FileSkillStore:
    """File store in temp directory."""
    return FileSkillStore(tmp_path)


# --- SkillStore Protocol Tests ---


class TestSkillStoreProtocol:
    """Verify implementations satisfy the SkillStore protocol."""

    def test_memory_store_is_skill_store(self):
        """MemorySkillStore should satisfy SkillStore protocol."""
        store = MemorySkillStore()
        assert isinstance(store, SkillStore)

    def test_file_store_is_skill_store(self, tmp_path: Path):
        """FileSkillStore should satisfy SkillStore protocol."""
        store = FileSkillStore(tmp_path)
        assert isinstance(store, SkillStore)


# --- MemorySkillStore Tests ---


class TestMemorySkillStore:
    """Tests for in-memory skill store."""

    def test_save_and_load_python_skill(
        self, memory_store: MemorySkillStore, sample_python_skill: PythonSkill
    ):
        """Should save and load a Python skill."""
        memory_store.save(sample_python_skill)
        loaded = memory_store.load("greet")

        assert loaded is not None
        assert loaded.name == "greet"
        assert loaded.description == "Greet someone"

    def test_load_nonexistent_returns_none(self, memory_store: MemorySkillStore):
        """Should return None for nonexistent skill."""
        assert memory_store.load("nonexistent") is None

    def test_delete_existing_skill(
        self, memory_store: MemorySkillStore, sample_python_skill: PythonSkill
    ):
        """Should delete an existing skill."""
        memory_store.save(sample_python_skill)
        result = memory_store.delete("greet")

        assert result is True
        assert memory_store.load("greet") is None

    def test_delete_nonexistent_returns_false(self, memory_store: MemorySkillStore):
        """Should return False when deleting nonexistent skill."""
        result = memory_store.delete("nonexistent")
        assert result is False

    def test_list_all_empty(self, memory_store: MemorySkillStore):
        """Should return empty list for empty store."""
        assert memory_store.list_all() == []

    def test_list_all_with_skills(
        self,
        memory_store: MemorySkillStore,
        sample_python_skill: PythonSkill,
        another_python_skill: PythonSkill,
    ):
        """Should list all saved skills."""
        memory_store.save(sample_python_skill)
        memory_store.save(another_python_skill)

        skills = memory_store.list_all()
        names = {s.name for s in skills}

        assert len(skills) == 2
        assert names == {"greet", "farewell"}

    def test_exists_true_for_saved_skill(
        self, memory_store: MemorySkillStore, sample_python_skill: PythonSkill
    ):
        """Should return True for existing skill."""
        memory_store.save(sample_python_skill)
        assert memory_store.exists("greet") is True

    def test_exists_false_for_missing_skill(self, memory_store: MemorySkillStore):
        """Should return False for nonexistent skill."""
        assert memory_store.exists("nonexistent") is False

    def test_save_overwrites_existing(
        self, memory_store: MemorySkillStore, sample_python_skill: PythonSkill
    ):
        """Saving with same name should overwrite."""
        memory_store.save(sample_python_skill)

        updated = PythonSkill.from_source(
            name="greet",
            source='async def run(name: str) -> str:\n    return f"Hi, {name}!"',
            description="Updated greeting",
        )
        memory_store.save(updated)

        loaded = memory_store.load("greet")
        assert loaded is not None
        assert loaded.description == "Updated greeting"


# --- FileSkillStore Tests ---


class TestFileSkillStore:
    """Tests for file-based skill store."""

    def test_save_creates_python_file(
        self, file_store: FileSkillStore, sample_python_skill: PythonSkill, tmp_path: Path
    ):
        """Should write .py file to disk."""
        file_store.save(sample_python_skill)

        expected_path = tmp_path / "greet.py"
        assert expected_path.exists()
        assert "def run" in expected_path.read_text()

    def test_load_reads_python_file(
        self, file_store: FileSkillStore, sample_python_skill: PythonSkill
    ):
        """Should load skill from .py file."""
        file_store.save(sample_python_skill)
        loaded = file_store.load("greet")

        assert loaded is not None
        assert loaded.name == "greet"
        assert isinstance(loaded, PythonSkill)

    def test_load_nonexistent_returns_none(self, file_store: FileSkillStore):
        """Should return None for nonexistent file."""
        assert file_store.load("nonexistent") is None

    def test_delete_removes_file(
        self, file_store: FileSkillStore, sample_python_skill: PythonSkill, tmp_path: Path
    ):
        """Should delete .py file from disk."""
        file_store.save(sample_python_skill)
        result = file_store.delete("greet")

        assert result is True
        assert not (tmp_path / "greet.py").exists()

    def test_delete_nonexistent_returns_false(self, file_store: FileSkillStore):
        """Should return False when file doesn't exist."""
        result = file_store.delete("nonexistent")
        assert result is False

    def test_list_all_finds_py_files(
        self, file_store: FileSkillStore, sample_python_skill: PythonSkill
    ):
        """Should list all .py files in directory."""
        file_store.save(sample_python_skill)

        # Create another skill
        another = PythonSkill.from_source(
            name="farewell",
            source='async def run() -> str:\n    return "Goodbye!"',
            description="Say goodbye",
        )
        file_store.save(another)

        skills = file_store.list_all()
        names = {s.name for s in skills}

        assert len(skills) == 2
        assert names == {"greet", "farewell"}

    def test_list_all_ignores_underscore_files(self, file_store: FileSkillStore, tmp_path: Path):
        """Should skip files starting with underscore."""
        # Create __init__.py
        (tmp_path / "__init__.py").write_text("")
        (tmp_path / "_private.py").write_text("async def run(): pass")

        skills = file_store.list_all()
        assert len(skills) == 0

    def test_exists_checks_file(self, file_store: FileSkillStore, sample_python_skill: PythonSkill):
        """Should check if .py file exists."""
        assert file_store.exists("greet") is False

        file_store.save(sample_python_skill)
        assert file_store.exists("greet") is True


# --- RedisSkillStore Tests (Mocked) ---


class TestRedisSkillStore:
    """Tests for Redis-based skill store."""

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
    def redis_store(self, mock_redis) -> RedisSkillStore:
        """Redis store with mock client."""
        return RedisSkillStore(mock_redis, prefix="test-skills")

    def test_save_and_load_python_skill(
        self, redis_store: RedisSkillStore, sample_python_skill: PythonSkill
    ):
        """Should serialize and deserialize Python skill."""
        redis_store.save(sample_python_skill)
        loaded = redis_store.load("greet")

        assert loaded is not None
        assert loaded.name == "greet"
        assert loaded.description == "Greet someone"
        # Stored skills have source and can invoke - duck typing
        assert hasattr(loaded, "source")
        assert hasattr(loaded, "invoke")

    def test_load_nonexistent_returns_none(self, redis_store: RedisSkillStore):
        """Should return None for nonexistent skill."""
        assert redis_store.load("nonexistent") is None

    def test_delete_existing_skill(
        self, redis_store: RedisSkillStore, sample_python_skill: PythonSkill
    ):
        """Should delete skill from Redis."""
        redis_store.save(sample_python_skill)
        result = redis_store.delete("greet")

        assert result is True
        assert redis_store.load("greet") is None

    def test_delete_nonexistent_returns_false(self, redis_store: RedisSkillStore):
        """Should return False when skill doesn't exist."""
        result = redis_store.delete("nonexistent")
        assert result is False

    def test_list_all(self, redis_store: RedisSkillStore, sample_python_skill: PythonSkill):
        """Should list all skills from Redis."""
        redis_store.save(sample_python_skill)

        another = PythonSkill.from_source(
            name="farewell",
            source='async def run() -> str:\n    return "Goodbye!"',
            description="Say goodbye",
        )
        redis_store.save(another)

        skills = redis_store.list_all()
        names = {s.name for s in skills}

        assert len(skills) == 2
        assert names == {"greet", "farewell"}

    def test_exists(self, redis_store: RedisSkillStore, sample_python_skill: PythonSkill):
        """Should check if skill exists in Redis."""
        assert redis_store.exists("greet") is False

        redis_store.save(sample_python_skill)
        assert redis_store.exists("greet") is True

    def test_uses_prefix_for_redis_key(self, mock_redis, sample_python_skill: PythonSkill):
        """Should use configured prefix for Redis hash key."""
        store = RedisSkillStore(mock_redis, prefix="my-prefix")
        store.save(sample_python_skill)

        # Check the key in mock redis
        assert "my-prefix:__skills__" in mock_redis._data


# --- FileSkillStore Name Validation Tests ---


def _make_skill_with_invalid_name(name: str) -> PythonSkill:
    """Create a PythonSkill with an arbitrary name, bypassing from_source validation.

    This is for testing the store-level validation, not skill construction.
    In production, PythonSkill.from_source already validates names, but
    FileSkillStore should also validate as defense-in-depth.
    """
    # Create a valid skill first
    valid_skill = PythonSkill.from_source(
        name="temp_valid_name",
        source="async def run(): pass",
        description="test",
    )
    # Replace the name with the invalid one for testing
    # This simulates what could happen if someone constructs a PythonSkill directly
    return PythonSkill(
        name=name,
        description=valid_skill.description,
        parameters=valid_skill.parameters,
        source=valid_skill.source,
        _func=valid_skill._func,
        metadata=valid_skill.metadata,
    )


class TestFileSkillStoreNameValidation:
    """Security tests for skill name validation to prevent path traversal."""

    def test_invalid_skill_name_rejected_dotdot_save(self, tmp_path: Path) -> None:
        """save() rejects path traversal names with ../"""
        store = FileSkillStore(tmp_path / "skills")
        skill = _make_skill_with_invalid_name("../malicious")
        with pytest.raises(ValueError, match="Invalid skill name"):
            store.save(skill)

    def test_invalid_skill_name_rejected_dotdot_load(self, tmp_path: Path) -> None:
        """load() rejects path traversal names with ../"""
        store = FileSkillStore(tmp_path / "skills")
        with pytest.raises(ValueError, match="Invalid skill name"):
            store.load("../malicious")

    def test_invalid_skill_name_rejected_dotdot_delete(self, tmp_path: Path) -> None:
        """delete() rejects path traversal names with ../"""
        store = FileSkillStore(tmp_path / "skills")
        with pytest.raises(ValueError, match="Invalid skill name"):
            store.delete("../malicious")

    def test_invalid_skill_name_rejected_dotdot_exists(self, tmp_path: Path) -> None:
        """exists() rejects path traversal names with ../"""
        store = FileSkillStore(tmp_path / "skills")
        with pytest.raises(ValueError, match="Invalid skill name"):
            store.exists("../malicious")

    def test_invalid_skill_name_rejected_slash(self, tmp_path: Path) -> None:
        """save() rejects names with forward slashes."""
        store = FileSkillStore(tmp_path / "skills")
        skill = _make_skill_with_invalid_name("foo/bar")
        with pytest.raises(ValueError, match="Invalid skill name"):
            store.save(skill)

    def test_invalid_skill_name_rejected_backslash(self, tmp_path: Path) -> None:
        """save() rejects names with backslashes."""
        store = FileSkillStore(tmp_path / "skills")
        skill = _make_skill_with_invalid_name("foo\\bar")
        with pytest.raises(ValueError, match="Invalid skill name"):
            store.save(skill)

    def test_invalid_skill_name_rejected_starts_with_digit(self, tmp_path: Path) -> None:
        """save() rejects names starting with a digit (invalid Python identifier)."""
        store = FileSkillStore(tmp_path / "skills")
        skill = _make_skill_with_invalid_name("123skill")
        with pytest.raises(ValueError, match="Invalid skill name"):
            store.save(skill)

    def test_invalid_skill_name_rejected_special_chars(self, tmp_path: Path) -> None:
        """save() rejects names with special characters."""
        store = FileSkillStore(tmp_path / "skills")
        for name in ["skill@name", "skill-name", "skill.name", "skill name"]:
            skill = _make_skill_with_invalid_name(name)
            with pytest.raises(ValueError, match="Invalid skill name"):
                store.save(skill)

    def test_valid_skill_names_accepted(self, tmp_path: Path) -> None:
        """Valid Python identifiers are accepted."""
        store = FileSkillStore(tmp_path / "skills")
        for name in ["my_skill", "skill123", "_private", "CamelCase", "__dunder__"]:
            skill = PythonSkill.from_source(
                name=name,
                source="async def run(): pass",
                description="test",
            )
            store.save(skill)
            assert store.exists(name)
