"""Comprehensive feature matrix tests for py-code-mode.

This test module addresses a critical gap: existing tests pre-create directories,
masking bugs where features silently fail when directories don't exist.

The "from scratch" scenario is the most common real-world case:
    1. Developer creates new project
    2. Points py-code-mode at empty directory
    3. Expects workflows.create(), artifacts.save() to work
    4. Expects created workflows to persist across sessions

Test Matrix:
    - Storage: FileStorage, RedisStorage (mock)
    - Executor: InProcessExecutor, ContainerExecutor (if Docker)
    - Directory conditions: empty, partial, populated
    - Features: 12 (tools: 4, workflows: 4, artifacts: 4)

Critical tests:
    - "From scratch" scenario - empty dir, all features work
    - Persistence across sessions - workflows/artifacts survive close/reopen
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
    by fixtures that pre-create tools/, workflows/, artifacts/ directories.
    """
    # tmp_path already exists (pytest creates it)
    # Explicitly verify no subdirs exist
    assert not (tmp_path / "tools").exists()
    assert not (tmp_path / "workflows").exists()
    assert not (tmp_path / "artifacts").exists()
    return tmp_path


@pytest.fixture
def partial_dir_workflows_only(tmp_path: Path) -> Path:
    """Only workflows/ exists - tests tools and artifacts without their dirs."""
    (tmp_path / "workflows").mkdir()
    return tmp_path


@pytest.fixture
def partial_dir_artifacts_only(tmp_path: Path) -> Path:
    """Only artifacts/ exists."""
    (tmp_path / "artifacts").mkdir()
    return tmp_path


@pytest.fixture
def populated_dir(tmp_path: Path) -> tuple[Path, Path]:
    """All directories exist with sample content.

    This matches the current test fixtures - included for comparison.

    Returns:
        Tuple of (base_path, tools_path) for storage and executor config.
    """
    tools_dir = tmp_path / "tools"
    workflows_dir = tmp_path / "workflows"
    artifacts_dir = tmp_path / "artifacts"

    tools_dir.mkdir()
    workflows_dir.mkdir()
    artifacts_dir.mkdir()

    # Sample tool
    (tools_dir / "echo.yaml").write_text("""
name: echo
type: cli
command: echo
args: "{text}"
description: Echo text back
""")

    # Sample workflow
    (workflows_dir / "double.py").write_text('''"""Double a number."""

async def run(n: int) -> int:
    return n * 2
''')

    return tmp_path, tools_dir


# =============================================================================
# Helper Functions
# =============================================================================


def _docker_available() -> bool:
    """Check if Docker is available."""
    return shutil.which("docker") is not None


def _create_in_process_executor(tools_path: Path | None = None):
    """Create InProcessExecutor with optional tools path."""
    from py_code_mode.execution.in_process import InProcessConfig, InProcessExecutor

    config = InProcessConfig(tools_path=tools_path)
    return InProcessExecutor(config=config)


def _create_container_executor():
    """Create ContainerExecutor if Docker available."""
    if not _docker_available():
        pytest.skip("Docker not available")
    from py_code_mode.execution.container import ContainerConfig, ContainerExecutor

    return ContainerExecutor(ContainerConfig(timeout=30.0, auth_disabled=True))


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
    async def test_complete_workflow_from_empty_directory(self, empty_base_dir: Path) -> None:
        """Complete agent workflow starting from empty directory.

        User story: Developer creates new project, initializes py-code-mode,
        and uses all features without any setup.

        This test WILL FAIL if:
        - Directory auto-creation is broken
        - workflows.list() crashes on missing workflows/
        - artifacts.save() fails to create artifacts/
        - Persistence doesn't work
        """
        storage = FileStorage(empty_base_dir)

        async with Session(storage=storage) as session:
            # 1. Verify tools namespace exists (empty is fine)
            result = await session.run("tools.list()")
            assert result.is_ok, f"tools.list() failed on empty dir: {result.error}"
            assert result.value is not None, "tools.list() returned None"
            assert isinstance(result.value, list), f"tools.list() returned {type(result.value)}"
            # Empty list is expected - no tools defined yet

            # 2. Verify workflows namespace exists (empty is fine)
            result = await session.run("workflows.list()")
            assert result.is_ok, f"workflows.list() failed on empty dir: {result.error}"
            assert result.value is not None, "workflows.list() returned None"
            assert isinstance(result.value, list), f"workflows.list() returned {type(result.value)}"

            # 3. Create a workflow - this MUST create workflows/ directory
            result = await session.run("""
workflows.create(
    name="triple",
    description="Triple a number",
    source="async def run(n: int) -> int:\\n    return n * 3"
)
""")
            assert result.is_ok, f"workflows.create() failed: {result.error}"

            # 4. Verify workflow appears in list
            result = await session.run("workflows.list()")
            assert result.is_ok
            workflow_names = [s["name"] for s in result.value]
            assert "triple" in workflow_names, f"Created workflow not in list: {workflow_names}"

            # 5. Invoke the created workflow
            result = await session.run("workflows.triple(n=7)")
            assert result.is_ok, f"workflows.triple() failed: {result.error}"
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
        workflows_dir = empty_base_dir / "workflows"
        artifacts_dir = empty_base_dir / "artifacts"

        assert workflows_dir.exists(), "workflows/ directory was not created"
        assert (workflows_dir / "triple.py").exists(), "Workflow file was not persisted"
        assert artifacts_dir.exists(), "artifacts/ directory was not created"

    @pytest.mark.asyncio
    async def test_workflows_persist_across_sessions(self, empty_base_dir: Path) -> None:
        """Workflows created in one session are available in the next.

        This test WILL FAIL if:
        - Workflows are only stored in memory
        - FileWorkflowStore doesn't save to disk
        - WorkflowLibrary doesn't reload from store on new session
        """
        storage = FileStorage(empty_base_dir)

        # Session 1: Create a workflow
        async with Session(storage=storage) as session:
            result = await session.run("""
workflows.create(
    name="quadruple",
    description="Multiply by 4",
    source="async def run(n: int) -> int:\\n    return n * 4"
)
""")
            assert result.is_ok, f"workflows.create() failed: {result.error}"

            # Verify it works in this session
            result = await session.run("workflows.quadruple(n=5)")
            assert result.is_ok
            assert result.value == 20

        # Create a NEW session with SAME storage path
        # This is a completely fresh Session - no state carried over
        storage2 = FileStorage(empty_base_dir)

        async with Session(storage=storage2) as session:
            # Workflow should be visible in list
            result = await session.run("workflows.list()")
            assert result.is_ok
            workflow_names = [s["name"] for s in result.value]
            assert "quadruple" in workflow_names, (
                f"Workflow not persisted across sessions. Found: {workflow_names}"
            )

            # Workflow should be callable
            result = await session.run("workflows.quadruple(n=10)")
            assert result.is_ok, f"Persisted workflow failed: {result.error}"
            assert result.value == 40

    @pytest.mark.asyncio
    async def test_artifacts_persist_across_sessions(self, empty_base_dir: Path) -> None:
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
    @pytest.mark.xdist_group("docker")
    async def test_from_scratch_with_container_executor(self, empty_base_dir: Path) -> None:
        """From scratch scenario works with container executor too.

        Verifies that the container receives proper storage access configuration:
        - workflows_path is created and mounted read-write
        - artifacts_path is created and mounted read-write
        - Environment variables set for container's SessionConfig
        """
        from py_code_mode.execution.container import ContainerConfig, ContainerExecutor

        storage = FileStorage(empty_base_dir)
        config = ContainerConfig(timeout=30.0, auth_disabled=True)
        executor = ContainerExecutor(config)

        async with Session(storage=storage, executor=executor) as session:
            # Workflows should work
            result = await session.run("workflows.list()")
            assert result.is_ok, f"workflows.list() failed in container: {result.error}"

            # Artifacts should work
            result = await session.run('artifacts.save("container_test.txt", b"hello", "test")')
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
    async def test_workflows_create_creates_directory(self, empty_base_dir: Path) -> None:
        """workflows.create() creates workflows/ directory if missing."""
        storage = FileStorage(empty_base_dir)

        assert not (empty_base_dir / "workflows").exists()

        async with Session(storage=storage) as session:
            result = await session.run("""
workflows.create(
    name="test_workflow",
    description="Test",
    source="async def run() -> str:\\n    return 'ok'"
)
""")
            assert result.is_ok, f"Failed: {result.error}"

        # Directory should now exist
        assert (empty_base_dir / "workflows").exists(), (
            "workflows/ not created by workflows.create()"
        )

    @pytest.mark.asyncio
    async def test_artifacts_save_creates_directory(self, empty_base_dir: Path) -> None:
        """artifacts.save() creates artifacts/ directory if missing."""
        storage = FileStorage(empty_base_dir)

        assert not (empty_base_dir / "artifacts").exists()

        async with Session(storage=storage) as session:
            result = await session.run('artifacts.save("test.json", {"ok": True}, "Test")')
            assert result.is_ok, f"Failed: {result.error}"

        # Directory should now exist
        assert (empty_base_dir / "artifacts").exists(), "artifacts/ not created by artifacts.save()"


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
    async def test_workflows_list_on_missing_directory(self, empty_base_dir: Path) -> None:
        """workflows.list() returns [] when workflows/ doesn't exist."""
        storage = FileStorage(empty_base_dir)

        async with Session(storage=storage) as session:
            result = await session.run("workflows.list()")

            assert result.is_ok, f"workflows.list() crashed: {result.error}"
            assert result.value is not None, "workflows.list() returned None"
            assert isinstance(result.value, list)
            assert result.value == []

    @pytest.mark.asyncio
    async def test_workflows_list_on_empty_directory(self, empty_base_dir: Path) -> None:
        """workflows.list() returns [] when workflows/ exists but is empty."""
        (empty_base_dir / "workflows").mkdir()
        storage = FileStorage(empty_base_dir)

        async with Session(storage=storage) as session:
            result = await session.run("workflows.list()")

            assert result.is_ok
            assert result.value == []

    @pytest.mark.asyncio
    async def test_artifacts_list_on_missing_directory(self, empty_base_dir: Path) -> None:
        """artifacts.list() returns empty on missing artifacts/."""
        storage = FileStorage(empty_base_dir)

        async with Session(storage=storage) as session:
            result = await session.run("list(artifacts.list())")

            assert result.is_ok, f"artifacts.list() crashed: {result.error}"
            assert result.value is not None
            assert isinstance(result.value, list)
            assert result.value == []

    @pytest.mark.asyncio
    async def test_artifacts_list_on_empty_directory(self, empty_base_dir: Path) -> None:
        """artifacts.list() returns empty when artifacts/ exists but empty."""
        (empty_base_dir / "artifacts").mkdir()
        storage = FileStorage(empty_base_dir)

        async with Session(storage=storage) as session:
            result = await session.run("list(artifacts.list())")

            assert result.is_ok
            assert result.value == []


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
            assert any(x in error_lower for x in ["nonexistent", "not found", "attribute"])

    @pytest.mark.asyncio
    async def test_workflow_not_found_gives_clear_error(self, empty_base_dir: Path) -> None:
        """Calling non-existent workflow gives clear error."""
        storage = FileStorage(empty_base_dir)

        async with Session(storage=storage) as session:
            result = await session.run("workflows.nonexistent_workflow()")

            assert not result.is_ok, "Expected error for missing workflow"
            assert result.error is not None
            error_lower = result.error.lower()
            assert any(x in error_lower for x in ["nonexistent", "not found", "attribute"])

    @pytest.mark.asyncio
    async def test_artifact_load_missing_gives_error_or_none(self, empty_base_dir: Path) -> None:
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
    async def test_workflows_work_without_tools_directory(
        self, partial_dir_workflows_only: Path
    ) -> None:
        """Workflows work even when tools/ doesn't exist."""
        storage = FileStorage(partial_dir_workflows_only)

        # Add a workflow to the existing workflows dir
        (partial_dir_workflows_only / "workflows" / "add.py").write_text('''
"""Add two numbers."""

async def run(a: int, b: int) -> int:
    return a + b
''')

        async with Session(storage=storage) as session:
            # tools.list() should work (empty)
            result = await session.run("tools.list()")
            assert result.is_ok

            # workflows should work
            result = await session.run("workflows.add(a=1, b=2)")
            assert result.is_ok
            assert result.value == 3

    @pytest.mark.asyncio
    async def test_artifacts_work_without_workflows_directory(
        self, partial_dir_artifacts_only: Path
    ) -> None:
        """Artifacts work even when workflows/ doesn't exist."""
        storage = FileStorage(partial_dir_artifacts_only)

        async with Session(storage=storage) as session:
            # artifacts should work
            result = await session.run('artifacts.save("test.json", {"ok": True}, "Test")')
            assert result.is_ok

            # workflows.list() should work (empty)
            result = await session.run("workflows.list()")
            assert result.is_ok


# =============================================================================
# REDIS STORAGE TESTS (with mock)
# =============================================================================


@pytest.mark.skip(reason="Requires actual Redis - mock not intercepted at executor level")
class TestRedisStorageFromScratch:
    """Test "from scratch" scenario with Redis storage."""

    @pytest.fixture
    def redis_storage(self, mock_redis: MockRedisClient):
        """Create RedisStorage with mock client."""
        from py_code_mode.storage import RedisStorage

        return RedisStorage(redis=mock_redis, prefix="test")

    @pytest.mark.asyncio
    async def test_workflows_create_and_persist_in_redis(self, redis_storage) -> None:
        """Workflows can be created and retrieved from Redis storage."""
        async with Session(storage=redis_storage) as session:
            # Create workflow
            result = await session.run("""
workflows.create(
    name="redis_workflow",
    description="Test workflow",
    source="async def run() -> str:\\n    return 'from redis'"
)
""")
            assert result.is_ok, f"workflows.create() failed: {result.error}"

            # Invoke workflow
            result = await session.run("workflows.redis_workflow()")
            assert result.is_ok
            assert result.value == "from redis"

            # Verify in list
            result = await session.run("workflows.list()")
            assert result.is_ok
            names = [s["name"] for s in result.value]
            assert "redis_workflow" in names

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


@pytest.mark.xdist_group("docker")
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
    async def test_workflows_list_works_with_executor(self, executor, empty_base_dir: Path) -> None:
        """workflows.list() works across executors."""
        storage = FileStorage(empty_base_dir)

        async with Session(storage=storage, executor=executor) as session:
            result = await session.run("workflows.list()")
            assert result.is_ok, f"workflows.list() failed with {type(executor)}: {result.error}"
            assert isinstance(result.value, list)

    @pytest.mark.asyncio
    async def test_artifacts_save_works_with_executor(self, executor, empty_base_dir: Path) -> None:
        """artifacts.save() works across executors."""
        storage = FileStorage(empty_base_dir)

        async with Session(storage=storage, executor=executor) as session:
            result = await session.run('artifacts.save("executor_test.json", {"ok": True}, "Test")')
            assert result.is_ok, f"artifacts.save() failed with {type(executor)}: {result.error}"


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

    Note: Tools are now owned by executors (via config.tools_path), not storage.
    The storage_and_executor fixture returns both, with tools_path configured
    for populated directories.
    """

    @pytest.fixture(params=["file_empty", "file_populated"])
    def storage_and_executor(self, request, empty_base_dir: Path, populated_dir: tuple[Path, Path]):
        """Parametrize over storage conditions, returns (storage, executor)."""
        if request.param == "file_empty":
            storage = FileStorage(empty_base_dir)
            executor = _create_in_process_executor()  # No tools
            return storage, executor
        elif request.param == "file_populated":
            base_path, tools_path = populated_dir
            storage = FileStorage(base_path)
            executor = _create_in_process_executor(tools_path=tools_path)
            return storage, executor

    @pytest.mark.asyncio
    async def test_tools_list_feature(self, storage_and_executor) -> None:
        """tools.list() works across all combinations."""
        storage, executor = storage_and_executor
        async with Session(storage=storage, executor=executor) as session:
            result = await session.run("tools.list()")
            assert result.is_ok, f"tools.list() failed: {result.error}"
            assert isinstance(result.value, list)

    @pytest.mark.asyncio
    async def test_tools_search_feature(self, storage_and_executor) -> None:
        """tools.search() works across all combinations."""
        storage, executor = storage_and_executor
        async with Session(storage=storage, executor=executor) as session:
            result = await session.run('tools.search("test")')
            assert result.is_ok, f"tools.search() failed: {result.error}"
            assert isinstance(result.value, list)

    @pytest.mark.asyncio
    async def test_workflows_list_feature(self, storage_and_executor) -> None:
        """workflows.list() works across all combinations."""
        storage, executor = storage_and_executor
        async with Session(storage=storage, executor=executor) as session:
            result = await session.run("workflows.list()")
            assert result.is_ok, f"workflows.list() failed: {result.error}"
            assert isinstance(result.value, list)

    @pytest.mark.asyncio
    async def test_workflows_search_feature(self, storage_and_executor) -> None:
        """workflows.search() works across all combinations."""
        storage, executor = storage_and_executor
        async with Session(storage=storage, executor=executor) as session:
            result = await session.run('workflows.search("test")')
            assert result.is_ok, f"workflows.search() failed: {result.error}"
            assert isinstance(result.value, list)

    @pytest.mark.asyncio
    async def test_workflows_create_feature(self, storage_and_executor) -> None:
        """workflows.create() works across all combinations."""
        storage, executor = storage_and_executor
        async with Session(storage=storage, executor=executor) as session:
            result = await session.run("""
workflows.create(
    name="matrix_test",
    description="Matrix test workflow",
    source="async def run() -> str:\\n    return 'matrix'"
)
""")
            assert result.is_ok, f"workflows.create() failed: {result.error}"

            # Verify it's callable
            result = await session.run("workflows.matrix_test()")
            assert result.is_ok
            assert result.value == "matrix"

    @pytest.mark.asyncio
    async def test_artifacts_list_feature(self, storage_and_executor) -> None:
        """artifacts.list() works across all combinations."""
        storage, executor = storage_and_executor
        async with Session(storage=storage, executor=executor) as session:
            result = await session.run("list(artifacts.list())")
            assert result.is_ok, f"artifacts.list() failed: {result.error}"
            assert isinstance(result.value, list)

    @pytest.mark.asyncio
    async def test_artifacts_save_load_feature(self, storage_and_executor) -> None:
        """artifacts.save() and load() work across all combinations."""
        storage, executor = storage_and_executor
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
    async def test_artifacts_delete_feature(self, storage_and_executor) -> None:
        """artifacts.delete() works across all combinations."""
        storage, executor = storage_and_executor
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
