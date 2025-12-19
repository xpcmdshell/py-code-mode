"""Tests for Session/Executor API refactor.

These tests verify the new typed executor API where:
- Session accepts Executor instances (not strings)
- Session derives StorageAccess and passes to executor.start()
- String-based executor selection is rejected

TDD: These tests should FAIL initially, then pass as we implement.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from py_code_mode.session import Session
from py_code_mode.storage import FileStorage

if TYPE_CHECKING:
    pass


def _docker_available() -> bool:
    """Check if Docker is available."""
    return shutil.which("docker") is not None


# =============================================================================
# StorageAccess Type Tests
# =============================================================================


class TestStorageAccessTypes:
    """Tests for StorageAccess type definitions."""

    def test_file_storage_access_exists(self) -> None:
        """FileStorageAccess type is importable."""
        from py_code_mode.backend import FileStorageAccess

        assert FileStorageAccess is not None

    def test_redis_storage_access_exists(self) -> None:
        """RedisStorageAccess type is importable."""
        from py_code_mode.backend import RedisStorageAccess

        assert RedisStorageAccess is not None

    def test_file_storage_access_has_paths(self) -> None:
        """FileStorageAccess has tools_path, skills_path, artifacts_path."""
        from py_code_mode.backend import FileStorageAccess

        access = FileStorageAccess(
            tools_path=Path("/tmp/tools"),
            skills_path=Path("/tmp/skills"),
            artifacts_path=Path("/tmp/artifacts"),
        )
        assert access.tools_path == Path("/tmp/tools")
        assert access.skills_path == Path("/tmp/skills")
        assert access.artifacts_path == Path("/tmp/artifacts")

    def test_file_storage_access_paths_optional(self) -> None:
        """FileStorageAccess allows None for tools_path and skills_path."""
        from py_code_mode.backend import FileStorageAccess

        access = FileStorageAccess(
            tools_path=None,
            skills_path=None,
            artifacts_path=Path("/tmp/artifacts"),
        )
        assert access.tools_path is None
        assert access.skills_path is None

    def test_redis_storage_access_has_url_and_prefixes(self) -> None:
        """RedisStorageAccess has redis_url and prefix fields."""
        from py_code_mode.backend import RedisStorageAccess

        access = RedisStorageAccess(
            redis_url="redis://localhost:6379",
            tools_prefix="app:tools",
            skills_prefix="app:skills",
            artifacts_prefix="app:artifacts",
        )
        assert access.redis_url == "redis://localhost:6379"
        assert access.tools_prefix == "app:tools"
        assert access.skills_prefix == "app:skills"
        assert access.artifacts_prefix == "app:artifacts"


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
        from py_code_mode.backends.in_process import InProcessExecutor

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
        from py_code_mode.backends.in_process import InProcessExecutor

        session = Session(storage=storage)
        # After start, should have InProcessExecutor
        assert session._executor_spec is None or isinstance(
            session._executor_spec, InProcessExecutor
        )

    @pytest.mark.asyncio
    async def test_session_with_explicit_in_process_executor(self, storage: FileStorage) -> None:
        """Session works with explicitly passed InProcessExecutor."""
        from py_code_mode.backends.in_process import InProcessExecutor

        executor = InProcessExecutor()
        async with Session(storage=storage, executor=executor) as session:
            result = await session.run("2 + 2")
            assert result.is_ok
            assert result.value == 4

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _docker_available(), reason="Docker not available")
    async def test_session_with_container_executor(self, storage: FileStorage) -> None:
        """Session works with ContainerExecutor instance."""
        from py_code_mode.backends.container import ContainerConfig, ContainerExecutor

        config = ContainerConfig(timeout=30.0)
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

    @pytest.fixture
    def storage_with_tools(self, tmp_path: Path) -> FileStorage:
        """Create FileStorage with tools."""
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        (tools_dir / "echo.yaml").write_text(
            """
name: echo
type: cli
command: echo
args: "{text}"
description: Echo text
"""
        )
        return FileStorage(tmp_path)

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
    async def test_tools_namespace_available_with_typed_executor(
        self, storage_with_tools: FileStorage
    ) -> None:
        """tools namespace works when using typed executor."""
        from py_code_mode.backends.in_process import InProcessExecutor

        executor = InProcessExecutor()
        async with Session(storage=storage_with_tools, executor=executor) as session:
            result = await session.run("'tools' in dir()")
            assert result.is_ok
            assert result.value is True

    @pytest.mark.asyncio
    async def test_skills_namespace_available_with_typed_executor(
        self, storage_with_skills: FileStorage
    ) -> None:
        """skills namespace works when using typed executor."""
        from py_code_mode.backends.in_process import InProcessExecutor

        executor = InProcessExecutor()
        async with Session(storage=storage_with_skills, executor=executor) as session:
            result = await session.run("'skills' in dir()")
            assert result.is_ok
            assert result.value is True

    @pytest.mark.asyncio
    async def test_tools_are_loaded_from_storage(self, storage_with_tools: FileStorage) -> None:
        """tools from storage are available in executor."""
        from py_code_mode.backends.in_process import InProcessExecutor

        executor = InProcessExecutor()
        async with Session(storage=storage_with_tools, executor=executor) as session:
            result = await session.run("tools.list()")
            assert result.is_ok
            tool_names = [t["name"] for t in result.value]
            assert "echo" in tool_names

    @pytest.mark.asyncio
    async def test_skills_are_loaded_from_storage(self, storage_with_skills: FileStorage) -> None:
        """skills from storage are available in executor."""
        from py_code_mode.backends.in_process import InProcessExecutor

        executor = InProcessExecutor()
        async with Session(storage=storage_with_skills, executor=executor) as session:
            result = await session.run("skills.list()")
            assert result.is_ok
            skill_names = [s["name"] for s in result.value]
            assert "double" in skill_names


# =============================================================================
# ContainerExecutor Storage Access Tests
# =============================================================================


class TestContainerExecutorStorageAccess:
    """Tests for ContainerExecutor receiving storage access."""

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _docker_available(), reason="Docker not available")
    async def test_container_receives_file_storage_access(self, tmp_path: Path) -> None:
        """ContainerExecutor receives FileStorageAccess and sets up mounts."""
        from py_code_mode.backends.container import ContainerConfig, ContainerExecutor

        # Create storage with artifacts dir
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        storage = FileStorage(tmp_path)

        config = ContainerConfig(timeout=30.0)
        executor = ContainerExecutor(config)

        async with Session(storage=storage, executor=executor) as session:
            # Save artifact - should work via volume mount
            result = await session.run("artifacts.save('test.txt', b'data', 'test')")
            assert result.is_ok, f"artifacts.save failed: {result.error}"

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _docker_available(), reason="Docker not available")
    async def test_container_config_no_storage_fields(self) -> None:
        """ContainerConfig should NOT have storage-related fields."""
        from py_code_mode.backends.container import ContainerConfig

        # These fields should NOT exist on ContainerConfig
        config = ContainerConfig(timeout=30.0)

        assert not hasattr(config, "host_tools_path")
        assert not hasattr(config, "host_skills_path")
        assert not hasattr(config, "host_artifacts_path")
        assert not hasattr(config, "redis_url")
        assert not hasattr(config, "artifact_backend")


# =============================================================================
# Executor Protocol Compliance Tests
# =============================================================================


class TestExecutorStartSignature:
    """Tests for Executor.start() accepting StorageAccess."""

    @pytest.mark.asyncio
    async def test_in_process_executor_start_accepts_storage_access(self) -> None:
        """InProcessExecutor.start() accepts storage_access parameter."""
        from py_code_mode.backend import FileStorageAccess
        from py_code_mode.backends.in_process import InProcessExecutor

        executor = InProcessExecutor()
        access = FileStorageAccess(
            tools_path=None,
            skills_path=None,
            artifacts_path=Path("/tmp/artifacts"),
        )

        # Should not raise
        await executor.start(storage_access=access)
        await executor.close()

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _docker_available(), reason="Docker not available")
    async def test_container_executor_start_accepts_storage_access(self, tmp_path: Path) -> None:
        """ContainerExecutor.start() accepts storage_access parameter."""
        from py_code_mode.backend import FileStorageAccess
        from py_code_mode.backends.container import ContainerConfig, ContainerExecutor

        artifacts_path = tmp_path / "artifacts"
        artifacts_path.mkdir()

        config = ContainerConfig(timeout=30.0)
        executor = ContainerExecutor(config)

        access = FileStorageAccess(
            tools_path=None,
            skills_path=None,
            artifacts_path=artifacts_path,
        )

        # Should not raise
        await executor.start(storage_access=access)
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
        from py_code_mode.backend import Capability
        from py_code_mode.backends.in_process import InProcessExecutor

        executor = InProcessExecutor()
        async with Session(storage=storage, executor=executor) as session:
            assert session.supports(Capability.TIMEOUT)
            # InProcess doesn't support process isolation
            assert not session.supports(Capability.PROCESS_ISOLATION)

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _docker_available(), reason="Docker not available")
    async def test_container_capabilities_unchanged(self, storage: FileStorage) -> None:
        """ContainerExecutor capabilities unchanged with new API."""
        from py_code_mode.backend import Capability
        from py_code_mode.backends.container import ContainerConfig, ContainerExecutor

        config = ContainerConfig(timeout=30.0)
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
