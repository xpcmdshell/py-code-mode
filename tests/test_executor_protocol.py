"""Tests for Executor protocol changes - Step 5 of implementation plan.

These tests verify:
1. Executor protocol defines start() method
2. All executors accept StorageBackend | None (not StorageAccess)
3. StorageBackendAccess class is deleted
4. Each executor correctly handles StorageBackend

Written to FAIL initially (TDD RED phase).
"""

from pathlib import Path
from typing import get_type_hints
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# =============================================================================
# Protocol Compliance Tests
# =============================================================================


class TestExecutorProtocolDefinesStart:
    """Verify the Executor protocol includes start() method."""

    def test_protocol_has_start_method(self) -> None:
        """Executor protocol must define start() method."""
        from py_code_mode.execution.protocol import Executor

        # Protocol should have start method
        assert hasattr(Executor, "start"), "Executor protocol must define start() method"

    def test_protocol_start_accepts_storage_backend(self) -> None:
        """Executor.start() must accept StorageBackend | None parameter."""
        from py_code_mode.execution.protocol import Executor
        from py_code_mode.storage.backends import StorageBackend

        # Get type hints for start method, providing StorageBackend for forward reference
        hints = get_type_hints(Executor.start, globalns={"StorageBackend": StorageBackend})

        # Should have 'storage' parameter that accepts StorageBackend | None
        assert "storage" in hints, "start() must have 'storage' parameter"

        # Check the type annotation includes StorageBackend
        storage_type = hints["storage"]
        # Handle Union types (StorageBackend | None)
        storage_type_str = str(storage_type)
        assert "StorageBackend" in storage_type_str, (
            f"start() storage parameter must accept StorageBackend, got {storage_type_str}"
        )

    def test_protocol_start_is_async(self) -> None:
        """Executor.start() must be an async method."""
        import asyncio

        from py_code_mode.execution.protocol import Executor

        # start method should be a coroutine function
        assert asyncio.iscoroutinefunction(Executor.start), "Executor.start() must be async"


class TestStorageBackendAccessDeleted:
    """Verify StorageBackendAccess class is removed."""

    def test_storage_backend_access_not_in_protocol(self) -> None:
        """StorageBackendAccess should not exist in protocol module."""
        from py_code_mode.execution import protocol

        assert not hasattr(protocol, "StorageBackendAccess"), (
            "StorageBackendAccess should be deleted from protocol.py"
        )

    def test_storage_access_union_excludes_backend_access(self) -> None:
        """StorageAccess type should not include StorageBackendAccess."""
        from py_code_mode.execution.protocol import StorageAccess

        # StorageAccess should only be FileStorageAccess | RedisStorageAccess
        storage_access_str = str(StorageAccess)
        assert "StorageBackendAccess" not in storage_access_str, (
            f"StorageAccess should not include StorageBackendAccess: {storage_access_str}"
        )


# =============================================================================
# InProcessExecutor Tests
# =============================================================================


class TestInProcessExecutorAcceptsStorageBackend:
    """InProcessExecutor.start() must accept StorageBackend directly."""

    def test_start_accepts_storage_backend(self, tmp_path: Path) -> None:
        """InProcessExecutor.start() accepts StorageBackend parameter."""
        from py_code_mode.execution.in_process import InProcessExecutor
        from py_code_mode.storage.backends import FileStorage

        storage = FileStorage(tmp_path)
        executor = InProcessExecutor()

        # This should NOT raise - executor accepts StorageBackend
        # Type checker would fail if signature is still StorageAccess
        import asyncio

        asyncio.run(executor.start(storage=storage))

    def test_start_parameter_named_storage_not_storage_access(self) -> None:
        """InProcessExecutor.start() parameter must be named 'storage' not 'storage_access'."""
        import inspect

        from py_code_mode.execution.in_process import InProcessExecutor

        sig = inspect.signature(InProcessExecutor.start)
        param_names = list(sig.parameters.keys())

        assert "storage" in param_names, (
            f"start() must have 'storage' parameter, got: {param_names}"
        )
        assert "storage_access" not in param_names, (
            "start() should NOT have 'storage_access' parameter (old name)"
        )

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

        # Create storage (for skills/artifacts only)
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
    async def test_uses_storage_skills_via_get_skill_library(self, tmp_path: Path) -> None:
        """InProcessExecutor uses storage.get_skill_library() for skills."""
        from py_code_mode.execution.in_process import InProcessExecutor
        from py_code_mode.storage.backends import FileStorage

        storage = FileStorage(tmp_path)

        executor = InProcessExecutor()
        await executor.start(storage=storage)

        # Should have skills namespace
        result = await executor.run("'skills' in dir()")
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
            skills_path=tmp_path / "skills",
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
            skills_prefix="test:skills",
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

    def test_start_parameter_named_storage(self) -> None:
        """ContainerExecutor.start() parameter must be named 'storage'."""
        import inspect

        from py_code_mode.execution.container import ContainerExecutor

        sig = inspect.signature(ContainerExecutor.start)
        param_names = list(sig.parameters.keys())

        assert "storage" in param_names, (
            f"start() must have 'storage' parameter, got: {param_names}"
        )
        assert "storage_access" not in param_names, (
            "start() should NOT have 'storage_access' parameter (old name)"
        )

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
            skills_prefix="test:skills",
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
            skills_path=tmp_path / "skills",
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

    def test_start_parameter_named_storage(self) -> None:
        """SubprocessExecutor.start() parameter must be named 'storage'."""
        import inspect

        from py_code_mode.execution.subprocess import SubprocessExecutor

        sig = inspect.signature(SubprocessExecutor.start)
        param_names = list(sig.parameters.keys())

        assert "storage" in param_names, (
            f"start() must have 'storage' parameter, got: {param_names}"
        )
        assert "storage_access" not in param_names, (
            "start() should NOT have 'storage_access' parameter (old name)"
        )

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
            with patch(
                "py_code_mode.execution.subprocess.executor.KernelHost"
            ) as mock_host_class:
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
            skills_path=tmp_path / "skills",
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


class TestAllExecutorsHaveConsistentStartSignature:
    """All executors must have identical start() signatures."""

    def test_all_executors_have_storage_parameter(self) -> None:
        """All executor start() methods have 'storage' parameter."""
        import inspect

        from py_code_mode.execution.container import ContainerExecutor
        from py_code_mode.execution.in_process import InProcessExecutor
        from py_code_mode.execution.subprocess import SubprocessExecutor

        executors = [
            ("InProcessExecutor", InProcessExecutor),
            ("ContainerExecutor", ContainerExecutor),
            ("SubprocessExecutor", SubprocessExecutor),
        ]

        for name, executor_cls in executors:
            sig = inspect.signature(executor_cls.start)
            param_names = list(sig.parameters.keys())
            assert "storage" in param_names, (
                f"{name}.start() must have 'storage' parameter, got: {param_names}"
            )

    def test_all_executors_storage_defaults_to_none(self) -> None:
        """All executor start() methods have storage default to None."""
        import inspect

        from py_code_mode.execution.container import ContainerExecutor
        from py_code_mode.execution.in_process import InProcessExecutor
        from py_code_mode.execution.subprocess import SubprocessExecutor

        executors = [
            ("InProcessExecutor", InProcessExecutor),
            ("ContainerExecutor", ContainerExecutor),
            ("SubprocessExecutor", SubprocessExecutor),
        ]

        for name, executor_cls in executors:
            sig = inspect.signature(executor_cls.start)
            storage_param = sig.parameters.get("storage")
            assert storage_param is not None, f"{name}.start() missing storage parameter"
            assert storage_param.default is None, (
                f"{name}.start() storage must default to None, got: {storage_param.default}"
            )
