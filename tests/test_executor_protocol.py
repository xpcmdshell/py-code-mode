"""Executor/storage integration tests.

These focus on behavior at the executor<->storage boundary, not protocol/shape
introspection (which is brittle and mostly redundant with behavioral tests).
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# =============================================================================
# InProcessExecutor Tests
# =============================================================================


class TestInProcessExecutorAcceptsStorageBackend:
    """InProcessExecutor.start() must accept StorageBackend directly."""

    @pytest.mark.asyncio
    async def test_uses_executor_config_for_tools(self, tmp_path: Path) -> None:
        """InProcessExecutor uses config.tools_path for tools.

        NOTE: Tools are now owned by executors (via config.tools_path), not storage.
        """
        from py_code_mode.execution.in_process import InProcessConfig, InProcessExecutor
        from py_code_mode.storage.backends import FileStorage

        # Create tools directory
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        (tools_dir / "test_tool.yaml").write_text("""
name: test_tool
description: A test tool
command: echo
schema:
  positional:
    - name: message
      type: string
recipes:
  say:
    description: Say something
    params:
      message: {}
""")

        # Create storage (for workflows/artifacts only)
        storage = FileStorage(tmp_path)

        # Configure executor with tools_path
        config = InProcessConfig(tools_path=tools_dir)
        executor = InProcessExecutor(config=config)
        await executor.start(storage=storage)

        # Should have tools namespace
        result = await executor.run("'tools' in dir()")
        assert result.value is True

        # Should find the test tool
        result = await executor.run("len(tools.list())")
        assert result.value >= 1

        await executor.close()

    @pytest.mark.asyncio
    async def test_uses_storage_workflows_via_get_workflow_library(self, tmp_path: Path) -> None:
        """InProcessExecutor uses storage.get_workflow_library() for workflows."""
        from py_code_mode.execution.in_process import InProcessExecutor
        from py_code_mode.storage.backends import FileStorage

        storage = FileStorage(tmp_path)

        executor = InProcessExecutor()
        await executor.start(storage=storage)

        # Should have workflows namespace
        result = await executor.run("'workflows' in dir()")
        assert result.value is True

        await executor.close()

    @pytest.mark.asyncio
    async def test_uses_storage_artifacts_via_get_artifact_store(self, tmp_path: Path) -> None:
        """InProcessExecutor uses storage.get_artifact_store() for artifacts."""
        from py_code_mode.execution.in_process import InProcessExecutor
        from py_code_mode.storage.backends import FileStorage

        storage = FileStorage(tmp_path)

        executor = InProcessExecutor()
        await executor.start(storage=storage)

        # Should have artifacts namespace
        result = await executor.run("'artifacts' in dir()")
        assert result.value is True

        await executor.close()

    @pytest.mark.asyncio
    async def test_start_with_none_uses_init_config(self) -> None:
        """InProcessExecutor.start(storage=None) uses __init__ configuration."""
        from py_code_mode.execution.in_process import InProcessExecutor

        executor = InProcessExecutor()
        await executor.start(storage=None)

        # Should work without storage
        result = await executor.run("1 + 1")
        assert result.value == 2

        await executor.close()


class TestInProcessExecutorRejectsOldTypes:
    """InProcessExecutor should NOT accept old StorageAccess types."""

    @pytest.mark.asyncio
    async def test_rejects_file_storage_access(self, tmp_path: Path) -> None:
        """InProcessExecutor.start() should reject FileStorageAccess.

        NOTE: tools_path and deps_path removed - tools/deps now owned by executors.
        """
        from py_code_mode.execution.in_process import InProcessExecutor
        from py_code_mode.execution.protocol import FileStorageAccess

        storage_access = FileStorageAccess(
            workflows_path=tmp_path / "workflows",
            artifacts_path=tmp_path / "artifacts",
        )

        executor = InProcessExecutor()

        # Should raise TypeError - wrong type
        with pytest.raises(TypeError):
            await executor.start(storage=storage_access)

    @pytest.mark.asyncio
    async def test_rejects_redis_storage_access(self) -> None:
        """InProcessExecutor.start() should reject RedisStorageAccess.

        NOTE: tools_prefix and deps_prefix removed - tools/deps now owned by executors.
        """
        from py_code_mode.execution.in_process import InProcessExecutor
        from py_code_mode.execution.protocol import RedisStorageAccess

        storage_access = RedisStorageAccess(
            redis_url="redis://localhost:6379",
            workflows_prefix="test:workflows",
            artifacts_prefix="test:artifacts",
        )

        executor = InProcessExecutor()

        # Should raise TypeError - wrong type
        with pytest.raises(TypeError):
            await executor.start(storage=storage_access)


# =============================================================================
# ContainerExecutor Tests
# =============================================================================


class TestContainerExecutorAcceptsStorageBackend:
    """ContainerExecutor.start() must accept StorageBackend directly."""

    @pytest.mark.asyncio
    async def test_calls_get_serializable_access_for_file_storage(self, tmp_path: Path) -> None:
        """ContainerExecutor calls storage.get_serializable_access() for FileStorage."""
        from py_code_mode.execution.container import ContainerExecutor
        from py_code_mode.execution.container.config import ContainerConfig
        from py_code_mode.storage.backends import FileStorage

        storage = FileStorage(tmp_path)

        # Mock get_serializable_access to verify it's called
        original_method = storage.get_serializable_access
        storage.get_serializable_access = MagicMock(return_value=original_method())

        config = ContainerConfig(image="py-code-mode:test", auth_disabled=True)
        executor = ContainerExecutor(config)

        # Mock Docker to avoid actually starting containers
        mock_container = MagicMock()
        mock_container.id = "test123"
        mock_container.status = "running"
        mock_container.attrs = {"NetworkSettings": {"Ports": {"8080/tcp": [{"HostPort": "32768"}]}}}
        mock_container.reload = MagicMock()

        mock_docker = MagicMock()
        mock_docker.containers.run.return_value = mock_container
        mock_docker.images.get.return_value = MagicMock()

        with patch("docker.from_env", return_value=mock_docker):
            with patch.object(executor, "_wait_for_healthy", new_callable=AsyncMock):
                try:
                    await executor.start(storage=storage)

                    # Verify get_serializable_access was called
                    storage.get_serializable_access.assert_called_once()
                finally:
                    await executor.close()

    @pytest.mark.asyncio
    async def test_calls_get_serializable_access_for_redis_storage(self) -> None:
        """ContainerExecutor calls storage.get_serializable_access() for RedisStorage."""
        pytest.importorskip("redis")
        from unittest.mock import MagicMock

        from py_code_mode.execution.container import ContainerExecutor
        from py_code_mode.execution.container.config import ContainerConfig
        from py_code_mode.execution.protocol import RedisStorageAccess
        from py_code_mode.storage.backends import RedisStorage

        # Create mock Redis client
        mock_redis = MagicMock()
        mock_redis.connection_pool.connection_kwargs = {
            "host": "localhost",
            "port": 6379,
            "db": 0,
        }

        storage = RedisStorage(redis=mock_redis, prefix="test")

        # Mock get_serializable_access to verify it's called
        # NOTE: tools_prefix and deps_prefix removed - tools/deps now owned by executors
        expected_access = RedisStorageAccess(
            redis_url="redis://localhost:6379/0",
            workflows_prefix="test:workflows",
            artifacts_prefix="test:artifacts",
        )
        storage.get_serializable_access = MagicMock(return_value=expected_access)

        config = ContainerConfig(image="py-code-mode:test", auth_disabled=True)
        executor = ContainerExecutor(config)

        # Mock Docker
        mock_container = MagicMock()
        mock_container.id = "test123"
        mock_container.status = "running"
        mock_container.attrs = {"NetworkSettings": {"Ports": {"8080/tcp": [{"HostPort": "32768"}]}}}
        mock_container.reload = MagicMock()

        mock_docker = MagicMock()
        mock_docker.containers.run.return_value = mock_container
        mock_docker.images.get.return_value = MagicMock()

        with patch("docker.from_env", return_value=mock_docker):
            with patch.object(executor, "_wait_for_healthy", new_callable=AsyncMock):
                try:
                    await executor.start(storage=storage)

                    # Verify get_serializable_access was called
                    storage.get_serializable_access.assert_called_once()
                finally:
                    await executor.close()


class TestContainerExecutorRejectsOldTypes:
    """ContainerExecutor should NOT accept old StorageAccess types directly."""

    @pytest.mark.asyncio
    async def test_rejects_file_storage_access(self, tmp_path: Path) -> None:
        """ContainerExecutor.start() should reject FileStorageAccess.

        NOTE: tools_path and deps_path removed - tools/deps now owned by executors.
        """
        from py_code_mode.execution.container import ContainerExecutor
        from py_code_mode.execution.container.config import ContainerConfig
        from py_code_mode.execution.protocol import FileStorageAccess

        storage_access = FileStorageAccess(
            workflows_path=tmp_path / "workflows",
            artifacts_path=tmp_path / "artifacts",
        )

        config = ContainerConfig(image="py-code-mode:test", auth_disabled=True)
        executor = ContainerExecutor(config)

        # Should raise TypeError - wrong type
        with pytest.raises(TypeError):
            await executor.start(storage=storage_access)


# =============================================================================
# SubprocessExecutor Tests
# =============================================================================


class TestSubprocessExecutorAcceptsStorageBackend:
    """SubprocessExecutor.start() must accept StorageBackend directly."""

    @pytest.mark.asyncio
    async def test_calls_get_serializable_access(self, tmp_path: Path) -> None:
        """SubprocessExecutor calls storage.get_serializable_access().

        This is a unit test that verifies the early part of start() without
        actually creating venvs or starting kernels.
        """
        from py_code_mode.execution.subprocess import SubprocessExecutor
        from py_code_mode.execution.subprocess.config import SubprocessConfig
        from py_code_mode.execution.subprocess.venv import KernelVenv
        from py_code_mode.storage.backends import FileStorage

        storage = FileStorage(tmp_path)

        # Mock get_serializable_access to verify it's called
        original_method = storage.get_serializable_access
        storage.get_serializable_access = MagicMock(return_value=original_method())

        config = SubprocessConfig(
            python_version="3.12",
            venv_path=tmp_path / "venv",
        )
        executor = SubprocessExecutor(config=config)

        # Create a mock venv
        mock_venv = KernelVenv(
            path=tmp_path / "venv",
            python_path=tmp_path / "venv" / "bin" / "python",
            kernel_spec_name="mock-kernel",
        )

        # Mock VenvManager to avoid creating actual venv
        with patch(
            "py_code_mode.execution.subprocess.executor.VenvManager"
        ) as mock_venv_manager_class:
            mock_manager = AsyncMock()
            mock_manager.create = AsyncMock(return_value=mock_venv)
            mock_venv_manager_class.return_value = mock_manager

            # Mock KernelHost to avoid starting actual kernel
            with patch("py_code_mode.execution.subprocess.executor.KernelHost") as mock_host_class:
                mock_host = AsyncMock()
                mock_host.start = AsyncMock()
                mock_host.execute = AsyncMock()
                mock_host_class.return_value = mock_host

                try:
                    # start() should call get_serializable_access early
                    await executor.start(storage=storage)

                    # Verify get_serializable_access was called
                    storage.get_serializable_access.assert_called_once()
                finally:
                    # Cleanup - executor may not have fully started
                    executor._host = None  # Reset to allow close without error


class TestSubprocessExecutorRejectsOldTypes:
    """SubprocessExecutor should NOT accept old StorageAccess types directly."""

    @pytest.mark.asyncio
    async def test_rejects_file_storage_access(self, tmp_path: Path) -> None:
        """SubprocessExecutor.start() should reject FileStorageAccess.

        NOTE: tools_path and deps_path removed - tools/deps now owned by executors.
        """
        from py_code_mode.execution.protocol import FileStorageAccess
        from py_code_mode.execution.subprocess import SubprocessExecutor
        from py_code_mode.execution.subprocess.config import SubprocessConfig

        storage_access = FileStorageAccess(
            workflows_path=tmp_path / "workflows",
            artifacts_path=tmp_path / "artifacts",
        )

        config = SubprocessConfig(
            python_version="3.12",
            venv_path=tmp_path / "venv",
        )
        executor = SubprocessExecutor(config=config)

        # Should raise TypeError - wrong type
        with pytest.raises(TypeError):
            await executor.start(storage=storage_access)


# =============================================================================
# Cross-Executor Consistency Tests
# =============================================================================
