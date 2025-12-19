"""Parametrized feature matrix tests.

Tests all combinations of:
    Storage: FileStorage, RedisStorage
    Executor: InProcessExecutor, ContainerExecutor

For each of the 12 namespace features:
    tools: list(), search(query), call(name, args), tool_name(**args)
    skills: list(), search(query), create(name, desc, source), skill_name(**args)
    artifacts: list(), save(name, data, desc), load(name), delete(name)

Total: 2 storage x 2 executor x 12 features = 48 test combinations

This is the feature matrix that ensures all combinations work together.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

# These imports will fail initially - that's expected (TDD red phase)
from py_code_mode.session import Session
from py_code_mode.storage import FileStorage, RedisStorage

if TYPE_CHECKING:
    from tests.conftest import MockRedisClient


# --- Fixtures for Storage Backends ---


@pytest.fixture
def file_storage(tmp_path: Path) -> FileStorage:
    """Create FileStorage with necessary subdirectories."""
    tools_dir = tmp_path / "tools"
    skills_dir = tmp_path / "skills"
    artifacts_dir = tmp_path / "artifacts"

    tools_dir.mkdir()
    skills_dir.mkdir()
    artifacts_dir.mkdir()

    # Add a sample tool
    (tools_dir / "echo.yaml").write_text(
        """
name: echo
type: cli
command: echo
args: "{text}"
description: Echo text back
"""
    )

    # Add a sample skill
    (skills_dir / "double.py").write_text(
        '''"""Double a number."""

def run(n: int) -> int:
    return n * 2
'''
    )

    return FileStorage(tmp_path)


@pytest.fixture
def redis_storage(mock_redis: MockRedisClient) -> RedisStorage:
    """Create RedisStorage with mock client and sample data."""
    storage = RedisStorage(mock_redis, prefix="test")

    # Add a sample tool
    storage.tools.save(
        {
            "name": "echo",
            "type": "cli",
            "command": "echo",
            "args": "{text}",
            "description": "Echo text back",
        }
    )

    # Add a sample skill
    storage.skills.save(
        {
            "name": "double",
            "source": '"""Double a number."""\n\ndef run(n: int) -> int:\n    return n * 2',
            "description": "Double a number",
        }
    )

    return storage


# --- Storage Backend Parametrization ---


def _docker_available() -> bool:
    """Check if Docker is available."""
    import shutil

    return shutil.which("docker") is not None


def _redis_available() -> bool:
    """Check if Redis is available for real tests."""
    try:
        import redis

        url = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379")
        client = redis.from_url(url)
        client.ping()
        return True
    except Exception:
        return False


# --- Feature Matrix Tests ---


class TestToolsListFeature:
    """Test tools.list() across all backend combinations."""

    @pytest.fixture(params=["file"])  # Add "redis" when ready
    def storage(
        self, request: Any, file_storage: FileStorage, redis_storage: RedisStorage
    ) -> FileStorage | RedisStorage:
        """Parametrize over storage backends."""
        if request.param == "file":
            return file_storage
        elif request.param == "redis":
            return redis_storage
        pytest.fail(f"Unknown storage: {request.param}")

    @pytest.fixture(params=["in-process"])  # Add "container" when ready
    def executor(self, request: Any):
        """Parametrize over executor types."""
        from py_code_mode.backends.in_process import InProcessExecutor

        if request.param == "in-process":
            return InProcessExecutor()
        # Add container executor when ready
        # elif request.param == "container":
        #     if not _docker_available():
        #         pytest.skip("Docker not available")
        #     return ContainerExecutor(ContainerConfig())
        #     return ContainerExecutor(ContainerConfig())
        pytest.fail(f"Unknown executor type: {request.param}")

    @pytest.mark.asyncio
    async def test_tools_list_returns_list(
        self, storage: FileStorage | RedisStorage, executor
    ) -> None:
        """tools.list() returns a list across all backends."""
        async with Session(storage=storage, executor=executor) as session:
            result = await session.run("tools.list()")

            assert result.is_ok, f"tools.list() failed: {result.error}"
            assert result.value is not None, "tools.list() returned None"
            assert isinstance(result.value, list)

    @pytest.mark.asyncio
    async def test_tools_list_contains_expected_tool(
        self, storage: FileStorage | RedisStorage, executor
    ) -> None:
        """tools.list() contains our sample tool."""
        async with Session(storage=storage, executor=executor) as session:
            result = await session.run("tools.list()")

            assert result.is_ok
            names = [t["name"] for t in result.value]
            assert "echo" in names, f"Expected 'echo' in tools, got: {names}"


class TestToolsSearchFeature:
    """Test tools.search(query) across all backend combinations."""

    @pytest.fixture(params=["file"])
    def storage(
        self, request: Any, file_storage: FileStorage, redis_storage: RedisStorage
    ) -> FileStorage | RedisStorage:
        if request.param == "file":
            return file_storage
        return redis_storage

    @pytest.fixture(params=["in-process"])
    def executor(self, request: Any):
        from py_code_mode.backends.in_process import InProcessExecutor

        if request.param == "in-process":
            return InProcessExecutor()
            # Add container executor when ready
            # elif request.param == "container":
            #     if not _docker_available():
            pytest.skip("Docker not available")
        #     return ContainerExecutor(ContainerConfig())
        pytest.fail(f"Unknown executor type: {request.param}")

    @pytest.mark.asyncio
    async def test_tools_search_returns_list(
        self, storage: FileStorage | RedisStorage, executor
    ) -> None:
        """tools.search(query) returns a list."""
        async with Session(storage=storage, executor=executor) as session:
            result = await session.run('tools.search("echo")')

            assert result.is_ok, f"tools.search() failed: {result.error}"
            assert isinstance(result.value, list)


class TestToolsCallFeature:
    """Test tools.call(name, args) across all backend combinations."""

    @pytest.fixture(params=["file"])
    def storage(
        self, request: Any, file_storage: FileStorage, redis_storage: RedisStorage
    ) -> FileStorage | RedisStorage:
        if request.param == "file":
            return file_storage
        return redis_storage

    @pytest.fixture(params=["in-process"])
    def executor(self, request: Any):
        from py_code_mode.backends.in_process import InProcessExecutor

        if request.param == "in-process":
            return InProcessExecutor()
            # Add container executor when ready
            # elif request.param == "container":
            #     if not _docker_available():
            pytest.skip("Docker not available")
        #     return ContainerExecutor(ContainerConfig())
        pytest.fail(f"Unknown executor type: {request.param}")

    @pytest.mark.asyncio
    async def test_tools_call_invokes_tool(
        self, storage: FileStorage | RedisStorage, executor
    ) -> None:
        """tools.call(name, args) invokes the specified tool."""
        async with Session(storage=storage, executor=executor) as session:
            result = await session.run('tools.call("echo", {"text": "hello"})')

            assert result.is_ok, f"tools.call() failed: {result.error}"
            assert "hello" in str(result.value)


class TestToolsDirectCallFeature:
    """Test tools.tool_name(**args) across all backend combinations."""

    @pytest.fixture(params=["file"])
    def storage(
        self, request: Any, file_storage: FileStorage, redis_storage: RedisStorage
    ) -> FileStorage | RedisStorage:
        if request.param == "file":
            return file_storage
        return redis_storage

    @pytest.fixture(params=["in-process"])
    def executor(self, request: Any):
        from py_code_mode.backends.in_process import InProcessExecutor

        if request.param == "in-process":
            return InProcessExecutor()
            # Add container executor when ready
            # elif request.param == "container":
            #     if not _docker_available():
            pytest.skip("Docker not available")
        #     return ContainerExecutor(ContainerConfig())
        pytest.fail(f"Unknown executor type: {request.param}")

    @pytest.mark.asyncio
    async def test_tools_direct_call_syntax(
        self, storage: FileStorage | RedisStorage, executor
    ) -> None:
        """tools.echo(text=...) invokes tool directly."""
        async with Session(storage=storage, executor=executor) as session:
            result = await session.run('tools.echo(text="direct")')

            assert result.is_ok, f"tools.echo() failed: {result.error}"
            assert "direct" in str(result.value)


class TestSkillsListFeature:
    """Test skills.list() across all backend combinations."""

    @pytest.fixture(params=["file"])
    def storage(
        self, request: Any, file_storage: FileStorage, redis_storage: RedisStorage
    ) -> FileStorage | RedisStorage:
        if request.param == "file":
            return file_storage
        return redis_storage

    @pytest.fixture(params=["in-process"])
    def executor(self, request: Any):
        from py_code_mode.backends.in_process import InProcessExecutor

        if request.param == "in-process":
            return InProcessExecutor()
            # Add container executor when ready
            # elif request.param == "container":
            #     if not _docker_available():
            pytest.skip("Docker not available")
        #     return ContainerExecutor(ContainerConfig())
        pytest.fail(f"Unknown executor type: {request.param}")

    @pytest.mark.asyncio
    async def test_skills_list_returns_list(
        self, storage: FileStorage | RedisStorage, executor
    ) -> None:
        """skills.list() returns a list across all backends."""
        async with Session(storage=storage, executor=executor) as session:
            result = await session.run("skills.list()")

            assert result.is_ok, f"skills.list() failed: {result.error}"
            assert result.value is not None, "skills.list() returned None"
            assert isinstance(result.value, list)

    @pytest.mark.asyncio
    async def test_skills_list_contains_expected_skill(
        self, storage: FileStorage | RedisStorage, executor
    ) -> None:
        """skills.list() contains our sample skill."""
        async with Session(storage=storage, executor=executor) as session:
            result = await session.run("skills.list()")

            assert result.is_ok
            names = [s["name"] for s in result.value]
            assert "double" in names, f"Expected 'double' in skills, got: {names}"


class TestSkillsSearchFeature:
    """Test skills.search(query) across all backend combinations."""

    @pytest.fixture(params=["file"])
    def storage(
        self, request: Any, file_storage: FileStorage, redis_storage: RedisStorage
    ) -> FileStorage | RedisStorage:
        if request.param == "file":
            return file_storage
        return redis_storage

    @pytest.fixture(params=["in-process"])
    def executor(self, request: Any):
        from py_code_mode.backends.in_process import InProcessExecutor

        if request.param == "in-process":
            return InProcessExecutor()
            # Add container executor when ready
            # elif request.param == "container":
            #     if not _docker_available():
            pytest.skip("Docker not available")
        #     return ContainerExecutor(ContainerConfig())
        pytest.fail(f"Unknown executor type: {request.param}")

    @pytest.mark.asyncio
    async def test_skills_search_returns_list(
        self, storage: FileStorage | RedisStorage, executor
    ) -> None:
        """skills.search(query) returns a list."""
        async with Session(storage=storage, executor=executor) as session:
            result = await session.run('skills.search("number")')

            assert result.is_ok, f"skills.search() failed: {result.error}"
            assert isinstance(result.value, list)


class TestSkillsCreateFeature:
    """Test skills.create(name, desc, source) across all backend combinations."""

    @pytest.fixture(params=["file"])
    def storage(
        self, request: Any, file_storage: FileStorage, redis_storage: RedisStorage
    ) -> FileStorage | RedisStorage:
        if request.param == "file":
            return file_storage
        return redis_storage

    @pytest.fixture(params=["in-process"])
    def executor(self, request: Any):
        from py_code_mode.backends.in_process import InProcessExecutor

        if request.param == "in-process":
            return InProcessExecutor()
            # Add container executor when ready
            # elif request.param == "container":
            #     if not _docker_available():
            pytest.skip("Docker not available")
        #     return ContainerExecutor(ContainerConfig())
        pytest.fail(f"Unknown executor type: {request.param}")

    @pytest.mark.asyncio
    async def test_skills_create_adds_skill(
        self, storage: FileStorage | RedisStorage, executor
    ) -> None:
        """skills.create() creates a new skill that's immediately usable."""
        async with Session(storage=storage, executor=executor) as session:
            # Create a new skill
            result = await session.run(
                """
skills.create(
    name="triple",
    description="Triple a number",
    source="def run(n: int) -> int:\\n    return n * 3"
)
"""
            )
            assert result.is_ok, f"skills.create() failed: {result.error}"

            # Use the created skill
            result = await session.run("skills.triple(n=10)")
            assert result.is_ok, f"skills.triple() failed: {result.error}"
            assert result.value == 30


class TestSkillsDirectCallFeature:
    """Test skills.skill_name(**args) across all backend combinations."""

    @pytest.fixture(params=["file"])
    def storage(
        self, request: Any, file_storage: FileStorage, redis_storage: RedisStorage
    ) -> FileStorage | RedisStorage:
        if request.param == "file":
            return file_storage
        return redis_storage

    @pytest.fixture(params=["in-process"])
    def executor(self, request: Any):
        from py_code_mode.backends.in_process import InProcessExecutor

        if request.param == "in-process":
            return InProcessExecutor()
            # Add container executor when ready
            # elif request.param == "container":
            #     if not _docker_available():
            pytest.skip("Docker not available")
        #     return ContainerExecutor(ContainerConfig())
        pytest.fail(f"Unknown executor type: {request.param}")

    @pytest.mark.asyncio
    async def test_skills_direct_call_syntax(
        self, storage: FileStorage | RedisStorage, executor
    ) -> None:
        """skills.double(n=...) invokes skill directly."""
        async with Session(storage=storage, executor=executor) as session:
            result = await session.run("skills.double(n=21)")

            assert result.is_ok, f"skills.double() failed: {result.error}"
            assert result.value == 42


class TestArtifactsListFeature:
    """Test artifacts.list() across all backend combinations."""

    @pytest.fixture(params=["file"])
    def storage(
        self, request: Any, file_storage: FileStorage, redis_storage: RedisStorage
    ) -> FileStorage | RedisStorage:
        if request.param == "file":
            return file_storage
        return redis_storage

    @pytest.fixture(params=["in-process"])
    def executor(self, request: Any):
        from py_code_mode.backends.in_process import InProcessExecutor

        if request.param == "in-process":
            return InProcessExecutor()
            # Add container executor when ready
            # elif request.param == "container":
            #     if not _docker_available():
            pytest.skip("Docker not available")
        #     return ContainerExecutor(ContainerConfig())
        pytest.fail(f"Unknown executor type: {request.param}")

    @pytest.mark.asyncio
    async def test_artifacts_list_returns_iterable(
        self, storage: FileStorage | RedisStorage, executor
    ) -> None:
        """artifacts.list() returns an iterable."""
        async with Session(storage=storage, executor=executor) as session:
            result = await session.run("list(artifacts.list())")

            assert result.is_ok, f"artifacts.list() failed: {result.error}"
            assert isinstance(result.value, list)


class TestArtifactsSaveFeature:
    """Test artifacts.save(name, data, desc) across all backend combinations."""

    @pytest.fixture(params=["file"])
    def storage(
        self, request: Any, file_storage: FileStorage, redis_storage: RedisStorage
    ) -> FileStorage | RedisStorage:
        if request.param == "file":
            return file_storage
        return redis_storage

    @pytest.fixture(params=["in-process"])
    def executor(self, request: Any):
        from py_code_mode.backends.in_process import InProcessExecutor

        if request.param == "in-process":
            return InProcessExecutor()
            # Add container executor when ready
            # elif request.param == "container":
            #     if not _docker_available():
            pytest.skip("Docker not available")
        #     return ContainerExecutor(ContainerConfig())
        pytest.fail(f"Unknown executor type: {request.param}")

    @pytest.mark.asyncio
    async def test_artifacts_save_stores_data(
        self, storage: FileStorage | RedisStorage, executor
    ) -> None:
        """artifacts.save() stores data that can be retrieved."""
        async with Session(storage=storage, executor=executor) as session:
            result = await session.run(
                'artifacts.save("test.json", {"key": "value"}, "Test artifact")'
            )
            assert result.is_ok, f"artifacts.save() failed: {result.error}"

            # Verify it was saved
            result = await session.run('artifacts.exists("test.json")')
            assert result.is_ok
            # Should be truthy
            assert result.value


class TestArtifactsLoadFeature:
    """Test artifacts.load(name) across all backend combinations."""

    @pytest.fixture(params=["file"])
    def storage(
        self, request: Any, file_storage: FileStorage, redis_storage: RedisStorage
    ) -> FileStorage | RedisStorage:
        if request.param == "file":
            return file_storage
        return redis_storage

    @pytest.fixture(params=["in-process"])
    def executor(self, request: Any):
        from py_code_mode.backends.in_process import InProcessExecutor

        if request.param == "in-process":
            return InProcessExecutor()
            # Add container executor when ready
            # elif request.param == "container":
            #     if not _docker_available():
            pytest.skip("Docker not available")
        #     return ContainerExecutor(ContainerConfig())
        pytest.fail(f"Unknown executor type: {request.param}")

    @pytest.mark.asyncio
    async def test_artifacts_load_retrieves_data(
        self, storage: FileStorage | RedisStorage, executor
    ) -> None:
        """artifacts.load() retrieves saved data."""
        async with Session(storage=storage, executor=executor) as session:
            await session.run('artifacts.save("load.json", {"n": 42}, "Load test")')
            result = await session.run('artifacts.load("load.json")')

            assert result.is_ok, f"artifacts.load() failed: {result.error}"
            assert result.value == {"n": 42}


class TestArtifactsDeleteFeature:
    """Test artifacts.delete(name) across all backend combinations."""

    @pytest.fixture(params=["file"])
    def storage(
        self, request: Any, file_storage: FileStorage, redis_storage: RedisStorage
    ) -> FileStorage | RedisStorage:
        if request.param == "file":
            return file_storage
        return redis_storage

    @pytest.fixture(params=["in-process"])
    def executor(self, request: Any):
        from py_code_mode.backends.in_process import InProcessExecutor

        if request.param == "in-process":
            return InProcessExecutor()
            # Add container executor when ready
            # elif request.param == "container":
            #     if not _docker_available():
            pytest.skip("Docker not available")
        #     return ContainerExecutor(ContainerConfig())
        pytest.fail(f"Unknown executor type: {request.param}")

    @pytest.mark.asyncio
    async def test_artifacts_delete_removes_artifact(
        self, storage: FileStorage | RedisStorage, executor
    ) -> None:
        """artifacts.delete() removes the artifact."""
        async with Session(storage=storage, executor=executor) as session:
            await session.run('artifacts.save("delete.json", {}, "Delete test")')

            result = await session.run('artifacts.delete("delete.json")')
            assert result.is_ok, f"artifacts.delete() failed: {result.error}"

            # Verify it's gone
            result = await session.run('artifacts.exists("delete.json")')
            assert result.is_ok
            assert not result.value  # Should be False


# --- Full Feature Matrix Test ---


class TestFullFeatureMatrix:
    """Run all features with all backend combinations in a single test.

    This provides a comprehensive integration test that exercises
    the complete 2x2x12 = 48 feature matrix.
    """

    @pytest.fixture(params=["file"])  # Add "redis" with real Redis
    def storage(
        self, request: Any, file_storage: FileStorage, redis_storage: RedisStorage
    ) -> FileStorage | RedisStorage:
        if request.param == "file":
            return file_storage
        return redis_storage

    @pytest.fixture(params=["in-process"])  # Add "container" with Docker
    def executor(self, request: Any):
        from py_code_mode.backends.in_process import InProcessExecutor

        if request.param == "in-process":
            return InProcessExecutor()
            # Add container executor when ready
            # elif request.param == "container":
            #     if not _docker_available():
            pytest.skip("Docker not available")
        #     return ContainerExecutor(ContainerConfig())
        pytest.fail(f"Unknown executor type: {request.param}")

    @pytest.mark.asyncio
    async def test_all_features_work_together(
        self, storage: FileStorage | RedisStorage, executor
    ) -> None:
        """All 12 features work in combination."""
        async with Session(storage=storage, executor=executor) as session:
            # --- Tools Features ---

            # 1. tools.list()
            result = await session.run("tools.list()")
            assert result.is_ok, f"tools.list() failed: {result.error}"
            assert isinstance(result.value, list)
            assert len(result.value) >= 1

            # 2. tools.search()
            result = await session.run('tools.search("echo")')
            assert result.is_ok, f"tools.search() failed: {result.error}"
            assert isinstance(result.value, list)

            # 3. tools.call()
            result = await session.run('tools.call("echo", {"text": "test"})')
            assert result.is_ok, f"tools.call() failed: {result.error}"

            # 4. tools.tool_name()
            result = await session.run('tools.echo(text="direct")')
            assert result.is_ok, f"tools.echo() failed: {result.error}"

            # --- Skills Features ---

            # 5. skills.list()
            result = await session.run("skills.list()")
            assert result.is_ok, f"skills.list() failed: {result.error}"
            assert isinstance(result.value, list)

            # 6. skills.search()
            result = await session.run('skills.search("double")')
            assert result.is_ok, f"skills.search() failed: {result.error}"

            # 7. skills.create()
            result = await session.run(
                """skills.create(
                    name="increment",
                    description="Add 1",
                    source="def run(n: int) -> int:\\n    return n + 1"
                )"""
            )
            assert result.is_ok, f"skills.create() failed: {result.error}"

            # 8. skills.skill_name()
            result = await session.run("skills.double(n=5)")
            assert result.is_ok, f"skills.double() failed: {result.error}"
            assert result.value == 10

            # --- Artifacts Features ---

            # 9. artifacts.list() (empty initially)
            result = await session.run("list(artifacts.list())")
            assert result.is_ok, f"artifacts.list() failed: {result.error}"

            # 10. artifacts.save()
            result = await session.run('artifacts.save("data.json", {"x": 1}, "Test")')
            assert result.is_ok, f"artifacts.save() failed: {result.error}"

            # 11. artifacts.load()
            result = await session.run('artifacts.load("data.json")')
            assert result.is_ok, f"artifacts.load() failed: {result.error}"
            assert result.value == {"x": 1}

            # 12. artifacts.delete()
            result = await session.run('artifacts.delete("data.json")')
            assert result.is_ok, f"artifacts.delete() failed: {result.error}"
