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

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

# These imports will fail initially - that's expected (TDD red phase)
from py_code_mode.session import Session
from py_code_mode.storage import FileStorage

if TYPE_CHECKING:
    pass


def _docker_available() -> bool:
    """Check if Docker is available."""
    return shutil.which("docker") is not None


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
        from py_code_mode.execution.in_process import InProcessExecutor

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
    async def test_session_close_can_be_called_directly(self, storage: FileStorage) -> None:
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
    async def test_skills_list_callable(self, storage_with_skills: FileStorage) -> None:
        """skills.list() is callable and returns list."""
        async with Session(storage=storage_with_skills) as session:
            result = await session.run("skills.list()")

            assert result.is_ok, f"skills.list() failed: {result.error}"
            assert result.value is not None
            assert isinstance(result.value, list)

    @pytest.mark.asyncio
    async def test_skills_list_returns_skill_info(self, storage_with_skills: FileStorage) -> None:
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
    async def test_skills_search_callable(self, storage_with_skills: FileStorage) -> None:
        """skills.search(query) is callable and returns list."""
        async with Session(storage=storage_with_skills) as session:
            result = await session.run('skills.search("number")')

            assert result.is_ok
            assert isinstance(result.value, list)

    @pytest.mark.asyncio
    async def test_skills_create_callable(self, storage_with_skills: FileStorage) -> None:
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
    async def test_skill_direct_invocation(self, storage_with_skills: FileStorage) -> None:
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
        from py_code_mode.execution.in_process import InProcessExecutor

        executor = InProcessExecutor()
        async with Session(storage=storage, executor=executor) as session:
            result = await session.run("2 + 2")

            assert result.is_ok
            assert result.value == 4

    @pytest.mark.asyncio
    @pytest.mark.xdist_group("docker")
    async def test_session_with_container_executor(self, storage: FileStorage) -> None:
        """Session works with container executor."""
        import shutil

        if shutil.which("docker") is None:
            pytest.skip("Docker not available")

        from py_code_mode.execution.container import ContainerConfig, ContainerExecutor

        config = ContainerConfig(timeout=30.0, auth_disabled=True)
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


# =============================================================================
# StorageAccess Type Tests
# =============================================================================


class TestStorageAccessTypes:
    """Tests for StorageAccess type definitions."""

    def test_file_storage_access_exists(self) -> None:
        """FileStorageAccess type is importable."""
        from py_code_mode.execution.protocol import FileStorageAccess

        assert FileStorageAccess is not None

    def test_redis_storage_access_exists(self) -> None:
        """RedisStorageAccess type is importable."""
        from py_code_mode.execution.protocol import RedisStorageAccess

        assert RedisStorageAccess is not None

    def test_file_storage_access_has_paths(self) -> None:
        """FileStorageAccess has tools_path, skills_path, artifacts_path."""
        from py_code_mode.execution.protocol import FileStorageAccess

        access = FileStorageAccess(
            tools_path=Path("/tmp/tools"),
            skills_path=Path("/tmp/skills"),
            artifacts_path=Path("/tmp/artifacts"),
            deps_path=Path("/tmp/deps"),
        )
        assert access.tools_path == Path("/tmp/tools")
        assert access.skills_path == Path("/tmp/skills")
        assert access.artifacts_path == Path("/tmp/artifacts")
        assert access.deps_path == Path("/tmp/deps")

    def test_file_storage_access_paths_optional(self) -> None:
        """FileStorageAccess allows None for tools_path and skills_path."""
        from py_code_mode.execution.protocol import FileStorageAccess

        access = FileStorageAccess(
            tools_path=None,
            skills_path=None,
            artifacts_path=Path("/tmp/artifacts"),
            deps_path=None,
        )
        assert access.tools_path is None
        assert access.skills_path is None
        assert access.deps_path is None

    def test_redis_storage_access_has_url_and_prefixes(self) -> None:
        """RedisStorageAccess has redis_url and prefix fields."""
        from py_code_mode.execution.protocol import RedisStorageAccess

        access = RedisStorageAccess(
            redis_url="redis://localhost:6379",
            tools_prefix="app:tools",
            skills_prefix="app:skills",
            artifacts_prefix="app:artifacts",
            deps_prefix="app:deps",
        )
        assert access.redis_url == "redis://localhost:6379"
        assert access.tools_prefix == "app:tools"
        assert access.skills_prefix == "app:skills"
        assert access.artifacts_prefix == "app:artifacts"
        assert access.deps_prefix == "app:deps"


# =============================================================================
# Session Typed Executor API Tests
# =============================================================================


class TestSessionTypedExecutorAPI:
    """Tests for Session accepting typed Executor instances."""

    @pytest.fixture
    def storage(self, tmp_path: Path) -> FileStorage:
        """Create FileStorage for testing."""
        return FileStorage(tmp_path)

    def test_session_accepts_executor_instance(self, storage: FileStorage) -> None:
        """Session accepts an Executor instance."""
        from py_code_mode.execution.in_process import InProcessExecutor

        executor = InProcessExecutor()
        session = Session(storage=storage, executor=executor)
        assert session is not None

    def test_session_rejects_string_executor(self, storage: FileStorage) -> None:
        """Session rejects string-based executor specification."""
        with pytest.raises(TypeError) as exc_info:
            Session(storage=storage, executor="in-process")  # type: ignore

        assert "str" in str(exc_info.value).lower() or "executor" in str(exc_info.value).lower()

    def test_session_defaults_to_in_process_executor(self, storage: FileStorage) -> None:
        """Session defaults to InProcessExecutor when executor=None."""
        from py_code_mode.execution.in_process import InProcessExecutor

        session = Session(storage=storage)
        # After start, should have InProcessExecutor
        assert session._executor_spec is None or isinstance(
            session._executor_spec, InProcessExecutor
        )

    @pytest.mark.asyncio
    async def test_session_with_explicit_in_process_executor(self, storage: FileStorage) -> None:
        """Session works with explicitly passed InProcessExecutor."""
        from py_code_mode.execution.in_process import InProcessExecutor

        executor = InProcessExecutor()
        async with Session(storage=storage, executor=executor) as session:
            result = await session.run("2 + 2")
            assert result.is_ok
            assert result.value == 4

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _docker_available(), reason="Docker not available")
    @pytest.mark.xdist_group("docker")
    async def test_session_with_container_executor(self, storage: FileStorage) -> None:
        """Session works with ContainerExecutor instance."""
        from py_code_mode.execution.container import ContainerConfig, ContainerExecutor

        config = ContainerConfig(timeout=30.0, auth_disabled=True)
        executor = ContainerExecutor(config)

        async with Session(storage=storage, executor=executor) as session:
            result = await session.run("2 + 2")
            assert result.is_ok
            assert result.value == 4


# =============================================================================
# Storage Access Wiring Tests
# =============================================================================


class TestStorageAccessWiring:
    """Tests that Session correctly wires storage access to executors."""

    # storage_with_tools fixture removed - not compatible with unified interface

    @pytest.fixture
    def storage_with_skills(self, tmp_path: Path) -> FileStorage:
        """Create FileStorage with skills."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "double.py").write_text(
            '''"""Double a number."""

def run(n: int) -> int:
    return n * 2
'''
        )
        return FileStorage(tmp_path)

    @pytest.mark.asyncio
    async def test_skills_namespace_available_with_typed_executor(
        self, storage_with_skills: FileStorage
    ) -> None:
        """skills namespace works when using typed executor."""
        from py_code_mode.execution.in_process import InProcessExecutor

        executor = InProcessExecutor()
        async with Session(storage=storage_with_skills, executor=executor) as session:
            result = await session.run("'skills' in dir()")
            assert result.is_ok
            assert result.value is True

    @pytest.mark.asyncio
    async def test_skills_are_loaded_from_storage(self, storage_with_skills: FileStorage) -> None:
        """skills from storage are available in executor."""
        from py_code_mode.execution.in_process import InProcessExecutor

        executor = InProcessExecutor()
        async with Session(storage=storage_with_skills, executor=executor) as session:
            result = await session.run("skills.list()")
            assert result.is_ok
            skill_names = [s["name"] for s in result.value]
            assert "double" in skill_names


# =============================================================================
# ContainerExecutor Storage Access Tests
# =============================================================================


@pytest.mark.xdist_group("docker")
class TestContainerExecutorStorageAccess:
    """Tests for ContainerExecutor receiving storage access."""

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _docker_available(), reason="Docker not available")
    async def test_container_receives_file_storage_access(self, tmp_path: Path) -> None:
        """ContainerExecutor receives FileStorageAccess and sets up mounts."""
        from py_code_mode.execution.container import ContainerConfig, ContainerExecutor

        # Create storage with artifacts dir
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        storage = FileStorage(tmp_path)

        config = ContainerConfig(timeout=30.0, auth_disabled=True)
        executor = ContainerExecutor(config)

        async with Session(storage=storage, executor=executor) as session:
            # Save artifact - should work via volume mount
            result = await session.run("artifacts.save('test.txt', b'data', 'test')")
            assert result.is_ok, f"artifacts.save failed: {result.error}"

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _docker_available(), reason="Docker not available")
    async def test_container_config_no_storage_fields(self) -> None:
        """ContainerConfig should NOT have storage-related fields."""
        from py_code_mode.execution.container import ContainerConfig

        # These fields should NOT exist on ContainerConfig
        config = ContainerConfig(timeout=30.0, auth_disabled=True)

        assert not hasattr(config, "host_tools_path")
        assert not hasattr(config, "host_skills_path")
        assert not hasattr(config, "host_artifacts_path")
        assert not hasattr(config, "redis_url")
        assert not hasattr(config, "artifact_backend")


# =============================================================================
# Executor Protocol Compliance Tests
# =============================================================================


class TestExecutorStartSignature:
    """Tests for Executor.start() accepting StorageBackend."""

    @pytest.mark.asyncio
    async def test_in_process_executor_start_accepts_storage(self, tmp_path: Path) -> None:
        """InProcessExecutor.start() accepts storage parameter."""
        from py_code_mode.execution.in_process import InProcessExecutor

        storage = FileStorage(tmp_path)
        executor = InProcessExecutor()

        # Should not raise
        await executor.start(storage=storage)
        await executor.close()

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _docker_available(), reason="Docker not available")
    @pytest.mark.xdist_group("docker")
    async def test_container_executor_start_accepts_storage(self, tmp_path: Path) -> None:
        """ContainerExecutor.start() accepts storage parameter."""
        from py_code_mode.execution.container import ContainerConfig, ContainerExecutor

        storage = FileStorage(tmp_path)
        config = ContainerConfig(timeout=30.0, auth_disabled=True)
        executor = ContainerExecutor(config)

        # Should not raise
        await executor.start(storage=storage)
        await executor.close()


# =============================================================================
# Default Behavior Tests
# =============================================================================


class TestDefaultExecutorBehavior:
    """Tests for default executor creation."""

    @pytest.fixture
    def storage(self, tmp_path: Path) -> FileStorage:
        """Create FileStorage for testing."""
        return FileStorage(tmp_path)

    @pytest.mark.asyncio
    async def test_omitting_executor_creates_in_process(self, storage: FileStorage) -> None:
        """Omitting executor parameter creates InProcessExecutor."""
        async with Session(storage=storage) as session:
            result = await session.run("2 + 2")
            assert result.is_ok
            assert result.value == 4

    @pytest.mark.asyncio
    async def test_executor_none_creates_in_process(self, storage: FileStorage) -> None:
        """Passing executor=None explicitly creates InProcessExecutor."""
        async with Session(storage=storage, executor=None) as session:
            result = await session.run("2 + 2")
            assert result.is_ok
            assert result.value == 4


# =============================================================================
# Capability Preservation Tests
# =============================================================================


class TestCapabilityPreservation:
    """Tests that capability querying still works with new API."""

    @pytest.fixture
    def storage(self, tmp_path: Path) -> FileStorage:
        """Create FileStorage for testing."""
        return FileStorage(tmp_path)

    @pytest.mark.asyncio
    async def test_in_process_capabilities_unchanged(self, storage: FileStorage) -> None:
        """InProcessExecutor capabilities unchanged with new API."""
        from py_code_mode.execution.in_process import InProcessExecutor
        from py_code_mode.execution.protocol import Capability

        executor = InProcessExecutor()
        async with Session(storage=storage, executor=executor) as session:
            assert session.supports(Capability.TIMEOUT)
            # InProcess doesn't support process isolation
            assert not session.supports(Capability.PROCESS_ISOLATION)

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _docker_available(), reason="Docker not available")
    @pytest.mark.xdist_group("docker")
    async def test_container_capabilities_unchanged(self, storage: FileStorage) -> None:
        """ContainerExecutor capabilities unchanged with new API."""
        from py_code_mode.execution.container import ContainerConfig, ContainerExecutor
        from py_code_mode.execution.protocol import Capability

        config = ContainerConfig(timeout=30.0, auth_disabled=True)
        executor = ContainerExecutor(config)

        async with Session(storage=storage, executor=executor) as session:
            assert session.supports(Capability.TIMEOUT)
            assert session.supports(Capability.PROCESS_ISOLATION)
            assert session.supports(Capability.RESET)


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandling:
    """Tests for error cases in new API."""

    def test_none_storage_rejected(self) -> None:
        """Session rejects None storage."""
        with pytest.raises((TypeError, ValueError)):
            Session(storage=None)  # type: ignore

    def test_invalid_executor_type_rejected(self, tmp_path: Path) -> None:
        """Session rejects invalid executor types."""
        storage = FileStorage(tmp_path)

        with pytest.raises(TypeError):
            Session(storage=storage, executor=123)  # type: ignore

        with pytest.raises(TypeError):
            Session(storage=storage, executor=["in-process"])  # type: ignore


# =============================================================================
# Session + SubprocessExecutor Integration Tests
# =============================================================================


def _subprocess_executor_available() -> bool:
    """Check if SubprocessExecutor is available (requires uv)."""
    return shutil.which("uv") is not None


@pytest.mark.slow
@pytest.mark.xdist_group("subprocess")
class TestSessionWithSubprocessExecutor:
    """Integration tests for Session + SubprocessExecutor.

    These tests verify the architectural fix where SubprocessExecutor can be
    used through the unified Session API. SubprocessExecutor has PROCESS_ISOLATION
    capability, which means it calls storage.get_serializable_access() internally.

    Session is "dumb" - it just passes storage to executor.start(). The executor
    decides how to use it based on its capabilities.

    Tests are slow (~5-10s startup per test) due to venv creation.
    """

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _subprocess_executor_available(), reason="uv not available")
    async def test_session_with_subprocess_executor(self, tmp_path: Path) -> None:
        """Session works with SubprocessExecutor through unified API.

        User action: Create Session with SubprocessExecutor
        Verification: Code execution works, returns correct result
        Breaks when: SubprocessExecutor doesn't implement Executor protocol
        """
        from py_code_mode.execution.subprocess import SubprocessExecutor
        from py_code_mode.execution.subprocess.config import SubprocessConfig

        config = SubprocessConfig(
            python_version="3.12",
            venv_path=tmp_path / "venv",
            # py-code-mode required for namespace injection in subprocess
            base_deps=("ipykernel", "py-code-mode"),
        )
        executor = SubprocessExecutor(config=config)
        storage = FileStorage(tmp_path)

        async with Session(storage=storage, executor=executor) as session:
            result = await session.run("2 + 2")

            assert result.is_ok, f"Execution failed: {result.error}"
            assert result.value in (4, "4")

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _subprocess_executor_available(), reason="uv not available")
    async def test_subprocess_executor_gets_serializable_access(self, tmp_path: Path) -> None:
        """Verify get_serializable_access() is called for isolated executors.

        User action: Session.start() with SubprocessExecutor
        Verification: SubprocessExecutor receives storage and calls get_serializable_access()
        Breaks when: Session bypasses storage.get_serializable_access() for isolated executors
        """
        from unittest.mock import MagicMock, patch

        from py_code_mode.execution.subprocess import SubprocessExecutor
        from py_code_mode.execution.subprocess.config import SubprocessConfig

        storage = FileStorage(tmp_path)

        # Create a mock that tracks if get_serializable_access was called
        original_get_serializable_access = storage.get_serializable_access
        mock_access = MagicMock(wraps=original_get_serializable_access)

        config = SubprocessConfig(
            python_version="3.12",
            venv_path=tmp_path / "venv",
            # py-code-mode required for namespace injection in subprocess
            base_deps=("ipykernel", "py-code-mode"),
        )
        executor = SubprocessExecutor(config=config)

        with patch.object(storage, "get_serializable_access", mock_access):
            async with Session(storage=storage, executor=executor) as session:
                # Run a simple command to ensure full initialization
                await session.run("1")

        # SubprocessExecutor should have called get_serializable_access
        mock_access.assert_called()

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _subprocess_executor_available(), reason="uv not available")
    async def test_subprocess_namespaces_work_via_session(self, tmp_path: Path) -> None:
        """tools/skills/artifacts namespaces accessible via Session.

        User action: Access namespaces in code via Session.run()
        Setup: FileStorage with skills directory, py-code-mode in venv
        Verification: Namespaces exist and are callable
        Breaks when: Namespace injection fails in subprocess
        """
        from py_code_mode.execution.subprocess import SubprocessExecutor
        from py_code_mode.execution.subprocess.config import SubprocessConfig

        # Create skills directory with a test skill
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "add_numbers.py").write_text(
            '''"""Add two numbers together."""

def run(a: int, b: int) -> int:
    return a + b
'''
        )

        storage = FileStorage(tmp_path)

        config = SubprocessConfig(
            python_version="3.12",
            venv_path=tmp_path / "venv",
            # py-code-mode must be in the venv for namespaces to work
            base_deps=("ipykernel", "py-code-mode"),
        )
        executor = SubprocessExecutor(config=config)

        async with Session(storage=storage, executor=executor) as session:
            # Verify tools namespace exists
            result = await session.run("'tools' in dir()")
            assert result.is_ok, f"Failed to check tools: {result.error}"
            assert result.value in (True, "True"), "tools namespace not found"

            # Verify skills namespace exists
            result = await session.run("'skills' in dir()")
            assert result.is_ok, f"Failed to check skills: {result.error}"
            assert result.value in (True, "True"), "skills namespace not found"

            # Verify artifacts namespace exists
            result = await session.run("'artifacts' in dir()")
            assert result.is_ok, f"Failed to check artifacts: {result.error}"
            assert result.value in (True, "True"), "artifacts namespace not found"

            # Verify skills.list() works and contains our skill
            result = await session.run("skills.list()")
            assert result.is_ok, f"skills.list() failed: {result.error}"

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _subprocess_executor_available(), reason="uv not available")
    async def test_subprocess_capabilities_via_session(self, tmp_path: Path) -> None:
        """session.supports() reports correct capabilities for SubprocessExecutor.

        User action: Query session capabilities
        Verification: PROCESS_ISOLATION, TIMEOUT, RESET are supported
        Breaks when: Capability reporting broken in Session/Executor interface
        """
        from py_code_mode.execution.protocol import Capability
        from py_code_mode.execution.subprocess import SubprocessExecutor
        from py_code_mode.execution.subprocess.config import SubprocessConfig

        storage = FileStorage(tmp_path)

        config = SubprocessConfig(
            python_version="3.12",
            venv_path=tmp_path / "venv",
            # py-code-mode required for namespace injection in subprocess
            base_deps=("ipykernel", "py-code-mode"),
        )
        executor = SubprocessExecutor(config=config)

        async with Session(storage=storage, executor=executor) as session:
            # SubprocessExecutor advertises PROCESS_ISOLATION
            assert session.supports(Capability.PROCESS_ISOLATION), (
                "SubprocessExecutor should support PROCESS_ISOLATION"
            )

            # SubprocessExecutor supports TIMEOUT
            assert session.supports(Capability.TIMEOUT), "SubprocessExecutor should support TIMEOUT"

            # SubprocessExecutor supports RESET (via kernel restart)
            assert session.supports(Capability.RESET), "SubprocessExecutor should support RESET"

            # SubprocessExecutor does NOT support NETWORK_ISOLATION
            assert not session.supports(Capability.NETWORK_ISOLATION), (
                "SubprocessExecutor should NOT support NETWORK_ISOLATION"
            )

            # SubprocessExecutor does NOT support FILESYSTEM_ISOLATION
            assert not session.supports(Capability.FILESYSTEM_ISOLATION), (
                "SubprocessExecutor should NOT support FILESYSTEM_ISOLATION"
            )

            # supported_capabilities() returns the full set
            caps = session.supported_capabilities()
            assert Capability.PROCESS_ISOLATION in caps
            assert Capability.TIMEOUT in caps
            assert Capability.RESET in caps

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _subprocess_executor_available(), reason="uv not available")
    async def test_process_isolation_implies_serializable_access(self, tmp_path: Path) -> None:
        """Any executor with PROCESS_ISOLATION uses serializable access.

        User action: Use any executor with PROCESS_ISOLATION capability
        Verification: The executor calls get_serializable_access() not direct storage
        Breaks when: New isolated executor bypasses serialization

        This test documents the architectural invariant: executors that run code
        in a separate process (PROCESS_ISOLATION capability) cannot directly access
        Python objects from the main process. They must use get_serializable_access()
        to get file paths or connection URLs they can reconstruct from.
        """
        from py_code_mode.execution.protocol import Capability
        from py_code_mode.execution.subprocess import SubprocessExecutor
        from py_code_mode.execution.subprocess.config import SubprocessConfig

        storage = FileStorage(tmp_path)

        config = SubprocessConfig(
            python_version="3.12",
            venv_path=tmp_path / "venv",
            # py-code-mode required for namespace injection in subprocess
            base_deps=("ipykernel", "py-code-mode"),
        )
        executor = SubprocessExecutor(config=config)

        # Verify the invariant: PROCESS_ISOLATION capability exists
        assert executor.supports(Capability.PROCESS_ISOLATION), (
            "SubprocessExecutor must have PROCESS_ISOLATION capability"
        )

        # Start and verify it can access storage-based namespaces
        # (this implicitly verifies serializable access works)
        async with Session(storage=storage, executor=executor) as session:
            # If serializable access is broken, this will fail because
            # the subprocess won't be able to reconstruct the storage
            result = await session.run("'artifacts' in dir()")
            assert result.is_ok, f"Failed: {result.error}"
            assert result.value in (True, "True"), (
                "artifacts namespace not available - serializable access likely broken"
            )
