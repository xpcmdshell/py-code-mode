"""Tests for Session class.

Session wraps a StorageBackend and Executor, providing the unified
interface that agents use. It injects the tools, skills, and artifacts
namespaces into the executor's namespace.

Session lifecycle:
    1. Create with storage backend and executor
    2. Session injects namespaces into executor
    3. Run code via session.run()
    4. Close releases resources

The Session is the primary API for py-code-mode.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

# These imports will fail initially - that's expected (TDD red phase)
from py_code_mode.session import Session
from py_code_mode.storage import FileStorage

if TYPE_CHECKING:
    pass


class TestSessionConstruction:
    """Tests for Session initialization."""

    @pytest.fixture
    def storage(self, tmp_path: Path) -> FileStorage:
        """Create FileStorage for testing."""
        return FileStorage(tmp_path)

    def test_create_session_with_storage(self, storage: FileStorage) -> None:
        """Session can be created with a StorageBackend."""
        session = Session(storage=storage)
        assert session is not None

    def test_create_session_with_executor_type(self, storage: FileStorage) -> None:
        """Session can be created with executor instance."""
        from py_code_mode.backends.in_process import InProcessExecutor

        executor = InProcessExecutor()
        session = Session(storage=storage, executor=executor)
        assert session is not None

    def test_storage_property(self, storage: FileStorage) -> None:
        """Session exposes the storage backend."""
        session = Session(storage=storage)
        assert session.storage is storage


class TestSessionContextManager:
    """Tests for Session async context manager behavior."""

    @pytest.fixture
    def storage(self, tmp_path: Path) -> FileStorage:
        """Create FileStorage for testing."""
        return FileStorage(tmp_path)

    @pytest.mark.asyncio
    async def test_session_as_context_manager(self, storage: FileStorage) -> None:
        """Session works as async context manager."""
        async with Session(storage=storage) as session:
            result = await session.run("1 + 1")
            assert result.is_ok
            assert result.value == 2

    @pytest.mark.asyncio
    async def test_session_close_can_be_called_directly(
        self, storage: FileStorage
    ) -> None:
        """Session.close() can be called explicitly."""
        session = Session(storage=storage)
        await session.start()
        result = await session.run("1 + 1")
        assert result.is_ok

        await session.close()  # Should not raise


class TestSessionCodeExecution:
    """Tests for Session.run() - code execution."""

    @pytest.fixture
    def storage(self, tmp_path: Path) -> FileStorage:
        """Create FileStorage for testing."""
        return FileStorage(tmp_path)

    @pytest.mark.asyncio
    async def test_run_returns_execution_result(self, storage: FileStorage) -> None:
        """run() returns an ExecutionResult."""
        async with Session(storage=storage) as session:
            result = await session.run("42")

            assert hasattr(result, "is_ok")
            assert hasattr(result, "value")
            assert hasattr(result, "error")
            assert hasattr(result, "stdout")

    @pytest.mark.asyncio
    async def test_run_evaluates_expression(self, storage: FileStorage) -> None:
        """run() evaluates Python expressions and returns value."""
        async with Session(storage=storage) as session:
            result = await session.run("2 + 2")

            assert result.is_ok
            assert result.value == 4

    @pytest.mark.asyncio
    async def test_run_captures_print_output(self, storage: FileStorage) -> None:
        """run() captures stdout from print statements."""
        async with Session(storage=storage) as session:
            result = await session.run("print('hello session')")

            assert result.is_ok
            assert "hello session" in result.stdout

    @pytest.mark.asyncio
    async def test_run_captures_errors(self, storage: FileStorage) -> None:
        """run() captures exceptions in error field."""
        async with Session(storage=storage) as session:
            result = await session.run("raise ValueError('test error')")

            assert not result.is_ok
            assert result.error is not None
            assert "ValueError" in result.error

    @pytest.mark.asyncio
    async def test_run_with_timeout(self, storage: FileStorage) -> None:
        """run() respects timeout parameter."""
        async with Session(storage=storage) as session:
            result = await session.run(
                "import time; time.sleep(10)",
                timeout=0.1,
            )

            assert not result.is_ok
            assert "timeout" in result.error.lower()

    @pytest.mark.asyncio
    async def test_state_persists_within_session(self, storage: FileStorage) -> None:
        """Variables set in one run persist to subsequent runs."""
        async with Session(storage=storage) as session:
            await session.run("x = 42")
            result = await session.run("x * 2")

            assert result.is_ok
            assert result.value == 84


class TestSessionToolsNamespace:
    """Tests for Session tools namespace injection."""

    @pytest.fixture
    def storage_with_tools(self, tmp_path: Path) -> FileStorage:
        """Create FileStorage with tools."""
        storage = FileStorage(tmp_path)
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir(exist_ok=True)
        (tools_dir / "echo.yaml").write_text(
            """
name: echo
type: cli
command: echo
args: "{text}"
description: Echo text back
"""
        )
        return storage

    @pytest.mark.asyncio
    async def test_tools_namespace_available(
        self, storage_with_tools: FileStorage
    ) -> None:
        """tools namespace is available in session."""
        async with Session(storage=storage_with_tools) as session:
            result = await session.run("'tools' in dir()")

            assert result.is_ok
            assert result.value is True

    @pytest.mark.asyncio
    async def test_tools_list_callable(self, storage_with_tools: FileStorage) -> None:
        """tools.list() is callable and returns list."""
        async with Session(storage=storage_with_tools) as session:
            result = await session.run("tools.list()")

            assert result.is_ok, f"tools.list() failed: {result.error}"
            assert result.value is not None
            assert isinstance(result.value, list)

    @pytest.mark.asyncio
    async def test_tools_list_returns_tool_info(
        self, storage_with_tools: FileStorage
    ) -> None:
        """tools.list() returns tool info with name, description, params."""
        async with Session(storage=storage_with_tools) as session:
            result = await session.run("tools.list()")

            assert result.is_ok
            assert len(result.value) >= 1
            tool = result.value[0]
            assert "name" in tool
            assert "description" in tool
            assert "params" in tool

    @pytest.mark.asyncio
    async def test_tools_search_callable(self, storage_with_tools: FileStorage) -> None:
        """tools.search(query) is callable and returns list."""
        async with Session(storage=storage_with_tools) as session:
            result = await session.run('tools.search("echo")')

            assert result.is_ok
            assert isinstance(result.value, list)

    @pytest.mark.asyncio
    async def test_tools_call_invokes_tool(
        self, storage_with_tools: FileStorage
    ) -> None:
        """tools.call(name, args) invokes the tool."""
        async with Session(storage=storage_with_tools) as session:
            result = await session.run('tools.call("echo", {"text": "hello"})')

            assert result.is_ok
            assert "hello" in str(result.value)

    @pytest.mark.asyncio
    async def test_tool_direct_invocation(
        self, storage_with_tools: FileStorage
    ) -> None:
        """tools.tool_name(**kwargs) syntax works."""
        async with Session(storage=storage_with_tools) as session:
            result = await session.run('tools.echo(text="direct call")')

            assert result.is_ok
            assert "direct call" in str(result.value)


class TestSessionSkillsNamespace:
    """Tests for Session skills namespace injection."""

    @pytest.fixture
    def storage_with_skills(self, tmp_path: Path) -> FileStorage:
        """Create FileStorage with skills."""
        storage = FileStorage(tmp_path)
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir(exist_ok=True)
        (skills_dir / "double.py").write_text(
            '''"""Double a number."""

def run(n: int) -> int:
    return n * 2
'''
        )
        return storage

    @pytest.mark.asyncio
    async def test_skills_namespace_available(
        self, storage_with_skills: FileStorage
    ) -> None:
        """skills namespace is available in session."""
        async with Session(storage=storage_with_skills) as session:
            result = await session.run("'skills' in dir()")

            assert result.is_ok
            assert result.value is True

    @pytest.mark.asyncio
    async def test_skills_list_callable(self, storage_with_skills: FileStorage) -> None:
        """skills.list() is callable and returns list."""
        async with Session(storage=storage_with_skills) as session:
            result = await session.run("skills.list()")

            assert result.is_ok, f"skills.list() failed: {result.error}"
            assert result.value is not None
            assert isinstance(result.value, list)

    @pytest.mark.asyncio
    async def test_skills_list_returns_skill_info(
        self, storage_with_skills: FileStorage
    ) -> None:
        """skills.list() returns skill info with name, description, params."""
        async with Session(storage=storage_with_skills) as session:
            result = await session.run("skills.list()")

            assert result.is_ok
            assert len(result.value) >= 1
            skill = result.value[0]
            assert "name" in skill
            assert "description" in skill
            assert "params" in skill

    @pytest.mark.asyncio
    async def test_skills_search_callable(
        self, storage_with_skills: FileStorage
    ) -> None:
        """skills.search(query) is callable and returns list."""
        async with Session(storage=storage_with_skills) as session:
            result = await session.run('skills.search("number")')

            assert result.is_ok
            assert isinstance(result.value, list)

    @pytest.mark.asyncio
    async def test_skills_create_callable(
        self, storage_with_skills: FileStorage
    ) -> None:
        """skills.create(name, description, source) is callable."""
        async with Session(storage=storage_with_skills) as session:
            result = await session.run(
                """
skills.create(
    name="triple",
    description="Triple a number",
    source="def run(n: int) -> int:\\n    return n * 3"
)
"""
            )

            assert result.is_ok

            # Verify skill was created
            result = await session.run("skills.triple(n=10)")
            assert result.is_ok
            assert result.value == 30

    @pytest.mark.asyncio
    async def test_skill_direct_invocation(
        self, storage_with_skills: FileStorage
    ) -> None:
        """skills.skill_name(**kwargs) syntax works."""
        async with Session(storage=storage_with_skills) as session:
            result = await session.run("skills.double(n=21)")

            assert result.is_ok
            assert result.value == 42


class TestSessionArtifactsNamespace:
    """Tests for Session artifacts namespace injection."""

    @pytest.fixture
    def storage(self, tmp_path: Path) -> FileStorage:
        """Create FileStorage for testing."""
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir(exist_ok=True)
        return FileStorage(tmp_path)

    @pytest.mark.asyncio
    async def test_artifacts_namespace_available(self, storage: FileStorage) -> None:
        """artifacts namespace is available in session."""
        async with Session(storage=storage) as session:
            result = await session.run("'artifacts' in dir()")

            assert result.is_ok
            assert result.value is True

    @pytest.mark.asyncio
    async def test_artifacts_list_callable(self, storage: FileStorage) -> None:
        """artifacts.list() is callable."""
        async with Session(storage=storage) as session:
            result = await session.run("list(artifacts.list())")

            assert result.is_ok
            assert isinstance(result.value, list)

    @pytest.mark.asyncio
    async def test_artifacts_save_callable(self, storage: FileStorage) -> None:
        """artifacts.save(name, data, description) is callable."""
        async with Session(storage=storage) as session:
            result = await session.run(
                'artifacts.save("test.json", {"key": "value"}, "Test artifact")'
            )

            assert result.is_ok

    @pytest.mark.asyncio
    async def test_artifacts_load_callable(self, storage: FileStorage) -> None:
        """artifacts.load(name) is callable."""
        async with Session(storage=storage) as session:
            await session.run('artifacts.save("data.json", {"n": 42}, "Data")')
            result = await session.run('artifacts.load("data.json")')

            assert result.is_ok
            assert result.value == {"n": 42}

    @pytest.mark.asyncio
    async def test_artifacts_delete_callable(self, storage: FileStorage) -> None:
        """artifacts.delete(name) is callable."""
        async with Session(storage=storage) as session:
            await session.run('artifacts.save("temp.json", {}, "Temp")')
            result = await session.run('artifacts.delete("temp.json")')

            assert result.is_ok

            # Verify deleted
            result = await session.run('artifacts.exists("temp.json")')
            assert result.is_ok
            # Should be False or None
            assert not result.value


class TestSessionReset:
    """Tests for Session.reset() - clearing session state."""

    @pytest.fixture
    def storage(self, tmp_path: Path) -> FileStorage:
        """Create FileStorage for testing."""
        return FileStorage(tmp_path)

    @pytest.mark.asyncio
    async def test_reset_clears_variables(self, storage: FileStorage) -> None:
        """reset() clears Python namespace variables."""
        async with Session(storage=storage) as session:
            await session.run("x = 42")
            result = await session.run("x")
            assert result.is_ok
            assert result.value == 42

            await session.reset()

            result = await session.run("x")
            assert not result.is_ok
            assert "NameError" in str(result.error)

    @pytest.mark.asyncio
    async def test_reset_preserves_namespaces(self, storage: FileStorage) -> None:
        """reset() preserves tools, skills, artifacts namespaces."""
        async with Session(storage=storage) as session:
            await session.run("x = 42")
            await session.reset()

            # Namespaces should still be available
            result = await session.run("'tools' in dir()")
            assert result.is_ok
            assert result.value is True

            result = await session.run("'skills' in dir()")
            assert result.is_ok
            assert result.value is True

            result = await session.run("'artifacts' in dir()")
            assert result.is_ok
            assert result.value is True

    @pytest.mark.asyncio
    async def test_reset_preserves_artifacts(self, storage: FileStorage) -> None:
        """reset() does not delete stored artifacts."""
        async with Session(storage=storage) as session:
            await session.run('artifacts.save("persist.json", {"key": 1}, "Persist")')
            await session.reset()

            result = await session.run('artifacts.load("persist.json")')
            assert result.is_ok
            assert result.value == {"key": 1}


class TestSessionWithDifferentExecutors:
    """Tests for Session with different executor backends."""

    @pytest.fixture
    def storage(self, tmp_path: Path) -> FileStorage:
        """Create FileStorage for testing."""
        return FileStorage(tmp_path)

    @pytest.mark.asyncio
    async def test_session_with_in_process_executor(self, storage: FileStorage) -> None:
        """Session works with in-process executor."""
        from py_code_mode.backends.in_process import InProcessExecutor

        executor = InProcessExecutor()
        async with Session(storage=storage, executor=executor) as session:
            result = await session.run("2 + 2")

            assert result.is_ok
            assert result.value == 4

    @pytest.mark.asyncio
    async def test_session_with_container_executor(self, storage: FileStorage) -> None:
        """Session works with container executor."""
        import shutil

        if shutil.which("docker") is None:
            pytest.skip("Docker not available")

        from py_code_mode.backends.container import ContainerConfig, ContainerExecutor

        config = ContainerConfig(timeout=30.0)
        executor = ContainerExecutor(config)
        async with Session(storage=storage, executor=executor) as session:
            result = await session.run("2 + 2")

            assert result.is_ok
            assert result.value == 4


class TestSessionIsolation:
    """Tests for Session state isolation."""

    @pytest.fixture
    def storage(self, tmp_path: Path) -> FileStorage:
        """Create FileStorage for testing."""
        return FileStorage(tmp_path)

    @pytest.mark.asyncio
    async def test_different_sessions_isolated(self, storage: FileStorage) -> None:
        """Different Session instances have isolated state."""
        async with Session(storage=storage) as session1:
            await session1.run("session_var = 'session1'")

            async with Session(storage=storage) as session2:
                # session2 should not see session1's variable
                result = await session2.run("session_var")
                assert not result.is_ok
                assert "NameError" in str(result.error)

    @pytest.mark.asyncio
    async def test_sessions_share_storage(self, storage: FileStorage) -> None:
        """Different sessions using same storage see same artifacts."""
        async with Session(storage=storage) as session1:
            await session1.run('artifacts.save("shared.json", {"from": 1}, "Shared")')

        async with Session(storage=storage) as session2:
            result = await session2.run('artifacts.load("shared.json")')
            assert result.is_ok
            assert result.value == {"from": 1}


class TestSessionCapabilities:
    """Tests for Session capability querying."""

    @pytest.fixture
    def storage(self, tmp_path: Path) -> FileStorage:
        """Create FileStorage for testing."""
        return FileStorage(tmp_path)

    @pytest.mark.asyncio
    async def test_session_supports_method(self, storage: FileStorage) -> None:
        """Session has supports() method for capability queries."""
        async with Session(storage=storage) as session:
            # Should have this method
            assert hasattr(session, "supports")
            assert callable(session.supports)

    @pytest.mark.asyncio
    async def test_session_supported_capabilities(self, storage: FileStorage) -> None:
        """Session has supported_capabilities() method."""
        async with Session(storage=storage) as session:
            assert hasattr(session, "supported_capabilities")
            caps = session.supported_capabilities()
            assert isinstance(caps, set)
