"""Comprehensive feature matrix tests for py-code-mode.

This test module addresses a critical gap: existing tests pre-create directories,
masking bugs where features silently fail when directories don't exist.

The "from scratch" scenario is the most common real-world case:
    1. Developer creates new project
    2. Points py-code-mode at empty directory
    3. Expects skills.create(), artifacts.save() to work
    4. Expects created skills to persist across sessions

Test Matrix:
    - Storage: FileStorage, RedisStorage (mock)
    - Executor: InProcessExecutor, ContainerExecutor (if Docker)
    - Directory conditions: empty, partial, populated
    - Features: 12 (tools: 4, skills: 4, artifacts: 4)

Critical tests:
    - "From scratch" scenario - empty dir, all features work
    - Persistence across sessions - skills/artifacts survive close/reopen
    - Directory auto-creation - save() creates missing dirs
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from py_code_mode.session import Session
from py_code_mode.storage import FileStorage

if TYPE_CHECKING:
    from tests.conftest import MockRedisClient


# =============================================================================
# Directory Condition Fixtures
# =============================================================================


@pytest.fixture
def empty_base_dir(tmp_path: Path) -> Path:
    """Base directory exists but NO subdirs created.

    This is the critical "from scratch" scenario that was previously masked
    by fixtures that pre-create tools/, skills/, artifacts/ directories.
    """
    # tmp_path already exists (pytest creates it)
    # Explicitly verify no subdirs exist
    assert not (tmp_path / "tools").exists()
    assert not (tmp_path / "skills").exists()
    assert not (tmp_path / "artifacts").exists()
    return tmp_path


@pytest.fixture
def partial_dir_skills_only(tmp_path: Path) -> Path:
    """Only skills/ exists - tests tools and artifacts without their dirs."""
    (tmp_path / "skills").mkdir()
    return tmp_path


@pytest.fixture
def partial_dir_artifacts_only(tmp_path: Path) -> Path:
    """Only artifacts/ exists."""
    (tmp_path / "artifacts").mkdir()
    return tmp_path


@pytest.fixture
def populated_dir(tmp_path: Path) -> Path:
    """All directories exist with sample content.

    This matches the current test fixtures - included for comparison.
    """
    tools_dir = tmp_path / "tools"
    skills_dir = tmp_path / "skills"
    artifacts_dir = tmp_path / "artifacts"

    tools_dir.mkdir()
    skills_dir.mkdir()
    artifacts_dir.mkdir()

    # Sample tool
    (tools_dir / "echo.yaml").write_text("""
name: echo
type: cli
command: echo
args: "{text}"
description: Echo text back
""")

    # Sample skill
    (skills_dir / "double.py").write_text('''"""Double a number."""

def run(n: int) -> int:
    return n * 2
''')

    return tmp_path


# =============================================================================
# Helper Functions
# =============================================================================


def _docker_available() -> bool:
    """Check if Docker is available."""
    return shutil.which("docker") is not None


def _create_in_process_executor():
    """Create InProcessExecutor."""
    from py_code_mode.backends.in_process import InProcessExecutor

    return InProcessExecutor()


def _create_container_executor():
    """Create ContainerExecutor if Docker available."""
    if not _docker_available():
        pytest.skip("Docker not available")
    from py_code_mode.backends.container import ContainerConfig, ContainerExecutor

    return ContainerExecutor(ContainerConfig(timeout=30.0))


# =============================================================================
# "FROM SCRATCH" E2E TESTS - Most Critical
# =============================================================================


class TestFromScratchScenario:
    """Test the complete "from scratch" workflow.

    This is the most important test class. It verifies that a developer
    can start with an empty directory and use all features without
    needing to manually create subdirectories.

    Each test MUST start with NO pre-existing subdirectories.
    """

    @pytest.mark.asyncio
    async def test_complete_workflow_from_empty_directory(
        self, empty_base_dir: Path
    ) -> None:
        """Complete agent workflow starting from empty directory.

        User story: Developer creates new project, initializes py-code-mode,
        and uses all features without any setup.

        This test WILL FAIL if:
        - Directory auto-creation is broken
        - skills.list() crashes on missing skills/
        - artifacts.save() fails to create artifacts/
        - Persistence doesn't work
        """
        storage = FileStorage(empty_base_dir)

        async with Session(storage=storage) as session:
            # 1. Verify tools namespace exists (empty is fine)
            result = await session.run("tools.list()")
            assert result.is_ok, f"tools.list() failed on empty dir: {result.error}"
            assert result.value is not None, "tools.list() returned None"
            assert isinstance(result.value, list), (
                f"tools.list() returned {type(result.value)}"
            )
            # Empty list is expected - no tools defined yet

            # 2. Verify skills namespace exists (empty is fine)
            result = await session.run("skills.list()")
            assert result.is_ok, f"skills.list() failed on empty dir: {result.error}"
            assert result.value is not None, "skills.list() returned None"
            assert isinstance(result.value, list), (
                f"skills.list() returned {type(result.value)}"
            )

            # 3. Create a skill - this MUST create skills/ directory
            result = await session.run("""
skills.create(
    name="triple",
    description="Triple a number",
    source="def run(n: int) -> int:\\n    return n * 3"
)
""")
            assert result.is_ok, f"skills.create() failed: {result.error}"

            # 4. Verify skill appears in list
            result = await session.run("skills.list()")
            assert result.is_ok
            skill_names = [s["name"] for s in result.value]
            assert "triple" in skill_names, f"Created skill not in list: {skill_names}"

            # 5. Invoke the created skill
            result = await session.run("skills.triple(n=7)")
            assert result.is_ok, f"skills.triple() failed: {result.error}"
            assert result.value == 21, f"Expected 21, got {result.value}"

            # 6. Save an artifact - this MUST create artifacts/ directory
            result = await session.run(
                'artifacts.save("results.json", {"score": 100}, "Test results")'
            )
            assert result.is_ok, f"artifacts.save() failed: {result.error}"

            # 7. Load the artifact back
            result = await session.run('artifacts.load("results.json")')
            assert result.is_ok, f"artifacts.load() failed: {result.error}"
            assert result.value == {"score": 100}, f"Wrong data: {result.value}"

            # 8. Verify artifacts.list() works
            result = await session.run("list(artifacts.list())")
            assert result.is_ok, f"artifacts.list() failed: {result.error}"
            assert len(result.value) >= 1, "Artifact not in list"

        # Session closed. Verify files exist on disk.
        skills_dir = empty_base_dir / "skills"
        artifacts_dir = empty_base_dir / "artifacts"

        assert skills_dir.exists(), "skills/ directory was not created"
        assert (skills_dir / "triple.py").exists(), "Skill file was not persisted"
        assert artifacts_dir.exists(), "artifacts/ directory was not created"

    @pytest.mark.asyncio
    async def test_skills_persist_across_sessions(self, empty_base_dir: Path) -> None:
        """Skills created in one session are available in the next.

        This test WILL FAIL if:
        - Skills are only stored in memory
        - FileSkillStore doesn't save to disk
        - SkillLibrary doesn't reload from store on new session
        """
        storage = FileStorage(empty_base_dir)

        # Session 1: Create a skill
        async with Session(storage=storage) as session:
            result = await session.run("""
skills.create(
    name="quadruple",
    description="Multiply by 4",
    source="def run(n: int) -> int:\\n    return n * 4"
)
""")
            assert result.is_ok, f"skills.create() failed: {result.error}"

            # Verify it works in this session
            result = await session.run("skills.quadruple(n=5)")
            assert result.is_ok
            assert result.value == 20

        # Create a NEW session with SAME storage path
        # This is a completely fresh Session - no state carried over
        storage2 = FileStorage(empty_base_dir)

        async with Session(storage=storage2) as session:
            # Skill should be visible in list
            result = await session.run("skills.list()")
            assert result.is_ok
            skill_names = [s["name"] for s in result.value]
            assert "quadruple" in skill_names, (
                f"Skill not persisted across sessions. Found: {skill_names}"
            )

            # Skill should be callable
            result = await session.run("skills.quadruple(n=10)")
            assert result.is_ok, f"Persisted skill failed: {result.error}"
            assert result.value == 40

    @pytest.mark.asyncio
    async def test_artifacts_persist_across_sessions(
        self, empty_base_dir: Path
    ) -> None:
        """Artifacts saved in one session are loadable in the next.

        This test WILL FAIL if:
        - Artifacts are only in memory
        - FileArtifactStore doesn't persist correctly
        """
        storage = FileStorage(empty_base_dir)

        # Session 1: Save artifact
        async with Session(storage=storage) as session:
            result = await session.run(
                'artifacts.save("config.json", {"version": "1.0"}, "Configuration")'
            )
            assert result.is_ok, f"artifacts.save() failed: {result.error}"

        # Session 2: Load artifact
        storage2 = FileStorage(empty_base_dir)

        async with Session(storage=storage2) as session:
            result = await session.run('artifacts.load("config.json")')
            assert result.is_ok, f"Artifact not persisted: {result.error}"
            assert result.value == {"version": "1.0"}

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _docker_available(), reason="Docker not available")
    async def test_from_scratch_with_container_executor(
        self, empty_base_dir: Path
    ) -> None:
        """From scratch scenario works with container executor too.

        Verifies that the container receives proper storage access configuration:
        - skills_path is created and mounted read-write
        - artifacts_path is created and mounted read-write
        - Environment variables set for container's SessionConfig
        """
        from py_code_mode.backends.container import ContainerConfig, ContainerExecutor

        storage = FileStorage(empty_base_dir)
        config = ContainerConfig(timeout=30.0)
        executor = ContainerExecutor(config)

        async with Session(storage=storage, executor=executor) as session:
            # Skills should work
            result = await session.run("skills.list()")
            assert result.is_ok, f"skills.list() failed in container: {result.error}"

            # Artifacts should work
            result = await session.run(
                'artifacts.save("container_test.txt", b"hello", "test")'
            )
            assert result.is_ok, f"artifacts.save() failed in container: {result.error}"


# =============================================================================
# DIRECTORY AUTO-CREATION INVARIANT TESTS
# =============================================================================


class TestDirectoryAutoCreation:
    """Test that writing operations create missing directories.

    INVARIANT: Any write operation (save, create) MUST create the
    required directory if it doesn't exist. Users should never need
    to manually mkdir.
    """

    @pytest.mark.asyncio
    async def test_skills_create_creates_directory(self, empty_base_dir: Path) -> None:
        """skills.create() creates skills/ directory if missing."""
        storage = FileStorage(empty_base_dir)

        assert not (empty_base_dir / "skills").exists()

        async with Session(storage=storage) as session:
            result = await session.run("""
skills.create(
    name="test_skill",
    description="Test",
    source="def run() -> str:\\n    return 'ok'"
)
""")
            assert result.is_ok, f"Failed: {result.error}"

        # Directory should now exist
        assert (empty_base_dir / "skills").exists(), (
            "skills/ not created by skills.create()"
        )

    @pytest.mark.asyncio
    async def test_artifacts_save_creates_directory(self, empty_base_dir: Path) -> None:
        """artifacts.save() creates artifacts/ directory if missing."""
        storage = FileStorage(empty_base_dir)

        assert not (empty_base_dir / "artifacts").exists()

        async with Session(storage=storage) as session:
            result = await session.run(
                'artifacts.save("test.json", {"ok": True}, "Test")'
            )
            assert result.is_ok, f"Failed: {result.error}"

        # Directory should now exist
        assert (empty_base_dir / "artifacts").exists(), (
            "artifacts/ not created by artifacts.save()"
        )


# =============================================================================
# EMPTY DIRECTORY LISTING INVARIANT TESTS
# =============================================================================


class TestEmptyDirectoryListings:
    """Test that listing operations work on empty/missing directories.

    INVARIANT: list() operations MUST return empty list (not None, not error)
    when the underlying directory is empty or doesn't exist.
    """

    @pytest.mark.asyncio
    async def test_tools_list_on_missing_directory(self, empty_base_dir: Path) -> None:
        """tools.list() returns [] when tools/ doesn't exist."""
        storage = FileStorage(empty_base_dir)

        async with Session(storage=storage) as session:
            result = await session.run("tools.list()")

            assert result.is_ok, f"tools.list() crashed: {result.error}"
            assert result.value is not None, "tools.list() returned None"
            assert isinstance(result.value, list), f"Not a list: {type(result.value)}"
            assert result.value == [], f"Not empty: {result.value}"

    @pytest.mark.asyncio
    async def test_tools_list_on_empty_directory(self, empty_base_dir: Path) -> None:
        """tools.list() returns [] when tools/ exists but is empty."""
        (empty_base_dir / "tools").mkdir()
        storage = FileStorage(empty_base_dir)

        async with Session(storage=storage) as session:
            result = await session.run("tools.list()")

            assert result.is_ok
            assert result.value == []

    @pytest.mark.asyncio
    async def test_skills_list_on_missing_directory(self, empty_base_dir: Path) -> None:
        """skills.list() returns [] when skills/ doesn't exist."""
        storage = FileStorage(empty_base_dir)

        async with Session(storage=storage) as session:
            result = await session.run("skills.list()")

            assert result.is_ok, f"skills.list() crashed: {result.error}"
            assert result.value is not None, "skills.list() returned None"
            assert isinstance(result.value, list)
            assert result.value == []

    @pytest.mark.asyncio
    async def test_skills_list_on_empty_directory(self, empty_base_dir: Path) -> None:
        """skills.list() returns [] when skills/ exists but is empty."""
        (empty_base_dir / "skills").mkdir()
        storage = FileStorage(empty_base_dir)

        async with Session(storage=storage) as session:
            result = await session.run("skills.list()")

            assert result.is_ok
            assert result.value == []

    @pytest.mark.asyncio
    async def test_artifacts_list_on_missing_directory(
        self, empty_base_dir: Path
    ) -> None:
        """artifacts.list() returns empty on missing artifacts/."""
        storage = FileStorage(empty_base_dir)

        async with Session(storage=storage) as session:
            result = await session.run("list(artifacts.list())")

            assert result.is_ok, f"artifacts.list() crashed: {result.error}"
            assert result.value is not None
            assert isinstance(result.value, list)
            assert result.value == []

    @pytest.mark.asyncio
    async def test_artifacts_list_on_empty_directory(
        self, empty_base_dir: Path
    ) -> None:
        """artifacts.list() returns empty when artifacts/ exists but empty."""
        (empty_base_dir / "artifacts").mkdir()
        storage = FileStorage(empty_base_dir)

        async with Session(storage=storage) as session:
            result = await session.run("list(artifacts.list())")

            assert result.is_ok
            assert result.value == []


# =============================================================================
# NAMESPACE ALWAYS AVAILABLE INVARIANT TESTS
# =============================================================================


class TestNamespacesAlwaysAvailable:
    """Test that tools, skills, artifacts namespaces are ALWAYS available.

    INVARIANT: These namespaces must exist in every session, regardless
    of whether any tools/skills/artifacts are configured.
    """

    @pytest.mark.asyncio
    async def test_all_namespaces_exist_in_empty_session(
        self, empty_base_dir: Path
    ) -> None:
        """All three namespaces exist even with no content."""
        storage = FileStorage(empty_base_dir)

        async with Session(storage=storage) as session:
            result = await session.run("'tools' in dir()")
            assert result.is_ok
            assert result.value is True, "tools namespace missing"

            result = await session.run("'skills' in dir()")
            assert result.is_ok
            assert result.value is True, "skills namespace missing"

            result = await session.run("'artifacts' in dir()")
            assert result.is_ok
            assert result.value is True, "artifacts namespace missing"

    @pytest.mark.asyncio
    async def test_namespaces_have_expected_methods(self, empty_base_dir: Path) -> None:
        """Namespaces have their documented methods."""
        storage = FileStorage(empty_base_dir)

        async with Session(storage=storage) as session:
            # tools namespace
            result = await session.run("hasattr(tools, 'list')")
            assert result.is_ok and result.value is True
            result = await session.run("hasattr(tools, 'search')")
            assert result.is_ok and result.value is True
            result = await session.run("hasattr(tools, 'call')")
            assert result.is_ok and result.value is True

            # skills namespace
            result = await session.run("hasattr(skills, 'list')")
            assert result.is_ok and result.value is True
            result = await session.run("hasattr(skills, 'search')")
            assert result.is_ok and result.value is True
            result = await session.run("hasattr(skills, 'create')")
            assert result.is_ok and result.value is True

            # artifacts namespace
            result = await session.run("hasattr(artifacts, 'list')")
            assert result.is_ok and result.value is True
            result = await session.run("hasattr(artifacts, 'save')")
            assert result.is_ok and result.value is True
            result = await session.run("hasattr(artifacts, 'load')")
            assert result.is_ok and result.value is True


# =============================================================================
# NEGATIVE TESTS - Error Handling for Missing Resources
# =============================================================================


class TestMissingResourceErrors:
    """Test that missing resources produce clear errors, not crashes."""

    @pytest.mark.asyncio
    async def test_tool_not_found_gives_clear_error(self, empty_base_dir: Path) -> None:
        """Calling non-existent tool gives clear error."""
        storage = FileStorage(empty_base_dir)

        async with Session(storage=storage) as session:
            result = await session.run('tools.nonexistent_tool(arg="value")')

            assert not result.is_ok, "Expected error for missing tool"
            assert result.error is not None
            # Error should mention the tool name or "not found"
            error_lower = result.error.lower()
            assert any(
                x in error_lower for x in ["nonexistent", "not found", "attribute"]
            )

    @pytest.mark.asyncio
    async def test_skill_not_found_gives_clear_error(
        self, empty_base_dir: Path
    ) -> None:
        """Calling non-existent skill gives clear error."""
        storage = FileStorage(empty_base_dir)

        async with Session(storage=storage) as session:
            result = await session.run("skills.nonexistent_skill()")

            assert not result.is_ok, "Expected error for missing skill"
            assert result.error is not None
            error_lower = result.error.lower()
            assert any(
                x in error_lower for x in ["nonexistent", "not found", "attribute"]
            )

    @pytest.mark.asyncio
    async def test_artifact_load_missing_gives_error_or_none(
        self, empty_base_dir: Path
    ) -> None:
        """Loading non-existent artifact gives error or None."""
        storage = FileStorage(empty_base_dir)

        async with Session(storage=storage) as session:
            result = await session.run('artifacts.load("does_not_exist.json")')

            # Either fails with error or returns None - both acceptable
            if result.is_ok:
                assert result.value is None, (
                    f"Expected None for missing artifact, got {result.value}"
                )
            else:
                assert result.error is not None


# =============================================================================
# PARTIAL DIRECTORY TESTS
# =============================================================================


class TestPartialDirectoryConditions:
    """Test behavior when some directories exist but others don't."""

    @pytest.mark.asyncio
    async def test_skills_work_without_tools_directory(
        self, partial_dir_skills_only: Path
    ) -> None:
        """Skills work even when tools/ doesn't exist."""
        storage = FileStorage(partial_dir_skills_only)

        # Add a skill to the existing skills dir
        (partial_dir_skills_only / "skills" / "add.py").write_text('''
"""Add two numbers."""

def run(a: int, b: int) -> int:
    return a + b
''')

        async with Session(storage=storage) as session:
            # tools.list() should work (empty)
            result = await session.run("tools.list()")
            assert result.is_ok

            # skills should work
            result = await session.run("skills.add(a=1, b=2)")
            assert result.is_ok
            assert result.value == 3

    @pytest.mark.asyncio
    async def test_artifacts_work_without_skills_directory(
        self, partial_dir_artifacts_only: Path
    ) -> None:
        """Artifacts work even when skills/ doesn't exist."""
        storage = FileStorage(partial_dir_artifacts_only)

        async with Session(storage=storage) as session:
            # artifacts should work
            result = await session.run(
                'artifacts.save("test.json", {"ok": True}, "Test")'
            )
            assert result.is_ok

            # skills.list() should work (empty)
            result = await session.run("skills.list()")
            assert result.is_ok


# =============================================================================
# REDIS STORAGE TESTS (with mock)
# =============================================================================


class TestRedisStorageFromScratch:
    """Test "from scratch" scenario with Redis storage."""

    @pytest.fixture
    def redis_storage(self, mock_redis: MockRedisClient):
        """Create RedisStorage with mock client."""
        from py_code_mode.storage import RedisStorage

        return RedisStorage(mock_redis, prefix="test")

    @pytest.mark.asyncio
    async def test_skills_create_and_persist_in_redis(self, redis_storage) -> None:
        """Skills can be created and retrieved from Redis storage."""
        async with Session(storage=redis_storage) as session:
            # Create skill
            result = await session.run("""
skills.create(
    name="redis_skill",
    description="Test skill",
    source="def run() -> str:\\n    return 'from redis'"
)
""")
            assert result.is_ok, f"skills.create() failed: {result.error}"

            # Invoke skill
            result = await session.run("skills.redis_skill()")
            assert result.is_ok
            assert result.value == "from redis"

            # Verify in list
            result = await session.run("skills.list()")
            assert result.is_ok
            names = [s["name"] for s in result.value]
            assert "redis_skill" in names

    @pytest.mark.asyncio
    async def test_artifacts_save_and_load_in_redis(self, redis_storage) -> None:
        """Artifacts can be saved and loaded from Redis storage."""
        async with Session(storage=redis_storage) as session:
            result = await session.run(
                'artifacts.save("redis_data.json", {"source": "redis"}, "Test")'
            )
            assert result.is_ok, f"artifacts.save() failed: {result.error}"

            result = await session.run('artifacts.load("redis_data.json")')
            assert result.is_ok
            assert result.value == {"source": "redis"}


# =============================================================================
# EXECUTOR MATRIX TESTS
# =============================================================================


class TestExecutorMatrix:
    """Test features across different executors.

    Verifies that all features work correctly with both InProcessExecutor
    and ContainerExecutor. Container tests require Docker to be available.
    """

    @pytest.fixture(params=["in-process", "container"])
    def executor(self, request):
        """Parametrize over executor types."""
        if request.param == "in-process":
            return _create_in_process_executor()
        elif request.param == "container":
            return _create_container_executor()

    @pytest.mark.asyncio
    async def test_skills_list_works_with_executor(
        self, executor, empty_base_dir: Path
    ) -> None:
        """skills.list() works across executors."""
        storage = FileStorage(empty_base_dir)

        async with Session(storage=storage, executor=executor) as session:
            result = await session.run("skills.list()")
            assert result.is_ok, (
                f"skills.list() failed with {type(executor)}: {result.error}"
            )
            assert isinstance(result.value, list)

    @pytest.mark.asyncio
    async def test_artifacts_save_works_with_executor(
        self, executor, empty_base_dir: Path
    ) -> None:
        """artifacts.save() works across executors."""
        storage = FileStorage(empty_base_dir)

        async with Session(storage=storage, executor=executor) as session:
            result = await session.run(
                'artifacts.save("executor_test.json", {"ok": True}, "Test")'
            )
            assert result.is_ok, (
                f"artifacts.save() failed with {type(executor)}: {result.error}"
            )


# =============================================================================
# COMPLETE FEATURE MATRIX (Parametrized)
# =============================================================================


class TestCompleteFeatureMatrix:
    """Parametrized tests covering storage x executor x feature combinations.

    This runs the same tests across:
    - FileStorage (empty dir)
    - FileStorage (populated dir)

    And (if Docker available):
    - InProcessExecutor
    - ContainerExecutor
    """

    @pytest.fixture(params=["file_empty", "file_populated"])
    def storage(self, request, empty_base_dir: Path, populated_dir: Path):
        """Parametrize over storage conditions."""
        if request.param == "file_empty":
            return FileStorage(empty_base_dir)
        elif request.param == "file_populated":
            return FileStorage(populated_dir)

    @pytest.fixture(params=["in-process"])  # Add "container" when ready
    def executor(self, request):
        """Parametrize over executor types."""
        if request.param == "in-process":
            return _create_in_process_executor()
        # Container executor can be added when tests are stable

    @pytest.mark.asyncio
    async def test_tools_list_feature(self, storage, executor) -> None:
        """tools.list() works across all combinations."""
        async with Session(storage=storage, executor=executor) as session:
            result = await session.run("tools.list()")
            assert result.is_ok, f"tools.list() failed: {result.error}"
            assert isinstance(result.value, list)

    @pytest.mark.asyncio
    async def test_tools_search_feature(self, storage, executor) -> None:
        """tools.search() works across all combinations."""
        async with Session(storage=storage, executor=executor) as session:
            result = await session.run('tools.search("test")')
            assert result.is_ok, f"tools.search() failed: {result.error}"
            assert isinstance(result.value, list)

    @pytest.mark.asyncio
    async def test_skills_list_feature(self, storage, executor) -> None:
        """skills.list() works across all combinations."""
        async with Session(storage=storage, executor=executor) as session:
            result = await session.run("skills.list()")
            assert result.is_ok, f"skills.list() failed: {result.error}"
            assert isinstance(result.value, list)

    @pytest.mark.asyncio
    async def test_skills_search_feature(self, storage, executor) -> None:
        """skills.search() works across all combinations."""
        async with Session(storage=storage, executor=executor) as session:
            result = await session.run('skills.search("test")')
            assert result.is_ok, f"skills.search() failed: {result.error}"
            assert isinstance(result.value, list)

    @pytest.mark.asyncio
    async def test_skills_create_feature(self, storage, executor) -> None:
        """skills.create() works across all combinations."""
        async with Session(storage=storage, executor=executor) as session:
            result = await session.run("""
skills.create(
    name="matrix_test",
    description="Matrix test skill",
    source="def run() -> str:\\n    return 'matrix'"
)
""")
            assert result.is_ok, f"skills.create() failed: {result.error}"

            # Verify it's callable
            result = await session.run("skills.matrix_test()")
            assert result.is_ok
            assert result.value == "matrix"

    @pytest.mark.asyncio
    async def test_artifacts_list_feature(self, storage, executor) -> None:
        """artifacts.list() works across all combinations."""
        async with Session(storage=storage, executor=executor) as session:
            result = await session.run("list(artifacts.list())")
            assert result.is_ok, f"artifacts.list() failed: {result.error}"
            assert isinstance(result.value, list)

    @pytest.mark.asyncio
    async def test_artifacts_save_load_feature(self, storage, executor) -> None:
        """artifacts.save() and load() work across all combinations."""
        async with Session(storage=storage, executor=executor) as session:
            # Save
            result = await session.run(
                'artifacts.save("matrix.json", {"test": 123}, "Matrix test")'
            )
            assert result.is_ok, f"artifacts.save() failed: {result.error}"

            # Load
            result = await session.run('artifacts.load("matrix.json")')
            assert result.is_ok, f"artifacts.load() failed: {result.error}"
            assert result.value == {"test": 123}

    @pytest.mark.asyncio
    async def test_artifacts_delete_feature(self, storage, executor) -> None:
        """artifacts.delete() works across all combinations."""
        async with Session(storage=storage, executor=executor) as session:
            # Save first
            await session.run('artifacts.save("to_delete.json", {}, "Delete test")')

            # Delete
            result = await session.run('artifacts.delete("to_delete.json")')
            assert result.is_ok, f"artifacts.delete() failed: {result.error}"

            # Verify deleted
            result = await session.run('artifacts.exists("to_delete.json")')
            assert result.is_ok
            assert not result.value, "Artifact still exists after delete"
