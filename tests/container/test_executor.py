"""Tests for ContainerExecutor."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from py_code_mode.backends.container.config import ContainerConfig
from py_code_mode.backends.container.executor import ContainerExecutor


class TestContainerConfig:
    """Tests for ContainerConfig."""

    def test_default_values(self) -> None:
        """ContainerConfig has sensible defaults."""
        config = ContainerConfig()

        assert config.image == "py-code-mode-tools:latest"
        assert config.port == 0  # Auto-assign
        assert config.timeout == 30.0

    def test_custom_image(self) -> None:
        """Can set custom image."""
        config = ContainerConfig(image="my-tools:v1")
        assert config.image == "my-tools:v1"

    def test_custom_timeout(self) -> None:
        """Can set custom timeout."""
        config = ContainerConfig(timeout=60.0)
        assert config.timeout == 60.0


class TestContainerExecutor:
    """Tests for ContainerExecutor."""

    @pytest.fixture
    def config(self, tmp_path) -> ContainerConfig:
        """Create test config."""
        return ContainerConfig(
            image="py-code-mode-test:latest",
        )

    def _make_mock_container(self) -> MagicMock:
        """Create a mock Docker container with proper port bindings."""
        mock_container = MagicMock()
        mock_container.id = "abc123"
        mock_container.status = "running"
        mock_container.attrs = {
            "NetworkSettings": {
                "Ports": {"8080/tcp": [{"HostIp": "0.0.0.0", "HostPort": "32768"}]}
            }
        }
        mock_container.reload = MagicMock()
        return mock_container

    @pytest.mark.asyncio
    async def test_context_manager_starts_and_stops(self, config) -> None:
        """Executor starts container on enter, stops on exit."""
        executor = ContainerExecutor(config)

        mock_container = self._make_mock_container()
        mock_docker = MagicMock()
        mock_docker.containers.run.return_value = mock_container

        with patch("docker.from_env", return_value=mock_docker):
            with patch.object(executor, "_wait_for_healthy", new_callable=AsyncMock):
                async with executor:
                    assert executor._container is not None
                    mock_docker.containers.run.assert_called_once()

                # After exit, container should be stopped
                mock_container.stop.assert_called_once()
                mock_container.remove.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_delegates_to_client(self, config) -> None:
        """Run delegates to session client."""
        executor = ContainerExecutor(config)

        mock_container = self._make_mock_container()
        mock_docker = MagicMock()
        mock_docker.containers.run.return_value = mock_container

        from py_code_mode.backends.container.client import ExecuteResult

        mock_result = ExecuteResult(
            value=42,
            stdout="",
            error=None,
            execution_time_ms=5.0,
            session_id="test-session",
        )

        with patch("docker.from_env", return_value=mock_docker):
            with patch.object(executor, "_wait_for_healthy", new_callable=AsyncMock):
                async with executor:
                    executor._client.execute = AsyncMock(return_value=mock_result)

                    result = await executor.run("21 * 2")

                    assert result.value == 42
                    assert result.is_ok
                    executor._client.execute.assert_called_once_with(
                        "21 * 2", timeout=None
                    )

    @pytest.mark.asyncio
    async def test_run_with_timeout(self, config) -> None:
        """Run passes timeout to client."""
        executor = ContainerExecutor(config)

        mock_container = self._make_mock_container()
        mock_docker = MagicMock()
        mock_docker.containers.run.return_value = mock_container

        from py_code_mode.backends.container.client import ExecuteResult

        mock_result = ExecuteResult(
            value=None,
            stdout="",
            error=None,
            execution_time_ms=1000.0,
            session_id="test-session",
        )

        with patch("docker.from_env", return_value=mock_docker):
            with patch.object(executor, "_wait_for_healthy", new_callable=AsyncMock):
                async with executor:
                    executor._client.execute = AsyncMock(return_value=mock_result)

                    await executor.run("long_operation()", timeout=120.0)

                    executor._client.execute.assert_called_once_with(
                        "long_operation()", timeout=120.0
                    )

    @pytest.mark.asyncio
    async def test_run_converts_result_to_execution_result(self, config) -> None:
        """Run returns ExecutionResult compatible type."""
        executor = ContainerExecutor(config)

        mock_container = self._make_mock_container()
        mock_docker = MagicMock()
        mock_docker.containers.run.return_value = mock_container

        from py_code_mode.backends.container.client import ExecuteResult

        mock_result = ExecuteResult(
            value={"key": "value"},
            stdout="printed output",
            error=None,
            execution_time_ms=10.0,
            session_id="test-session",
        )

        with patch("docker.from_env", return_value=mock_docker):
            with patch.object(executor, "_wait_for_healthy", new_callable=AsyncMock):
                async with executor:
                    executor._client.execute = AsyncMock(return_value=mock_result)

                    result = await executor.run("code")

                    assert result.value == {"key": "value"}
                    assert result.stdout == "printed output"
                    assert result.error is None
                    assert result.is_ok

    @pytest.mark.asyncio
    async def test_run_with_error(self, config) -> None:
        """Run returns error from container."""
        executor = ContainerExecutor(config)

        mock_container = self._make_mock_container()
        mock_docker = MagicMock()
        mock_docker.containers.run.return_value = mock_container

        from py_code_mode.backends.container.client import ExecuteResult

        mock_result = ExecuteResult(
            value=None,
            stdout="",
            error="NameError: name 'x' is not defined",
            execution_time_ms=1.0,
            session_id="test-session",
        )

        with patch("docker.from_env", return_value=mock_docker):
            with patch.object(executor, "_wait_for_healthy", new_callable=AsyncMock):
                async with executor:
                    executor._client.execute = AsyncMock(return_value=mock_result)

                    result = await executor.run("x")

                    assert not result.is_ok
                    assert "NameError" in result.error


def _make_mock_container() -> MagicMock:
    """Create a mock Docker container with proper port bindings."""
    mock_container = MagicMock()
    mock_container.id = "abc123"
    mock_container.status = "running"
    mock_container.attrs = {
        "NetworkSettings": {
            "Ports": {"8080/tcp": [{"HostIp": "0.0.0.0", "HostPort": "32768"}]}
        }
    }
    mock_container.reload = MagicMock()
    return mock_container


class TestContainerExecutorVolumes:
    """Tests for volume mounting."""

    @pytest.mark.asyncio
    async def test_to_docker_config_with_volumes(self, tmp_path) -> None:
        """ContainerConfig.to_docker_config() adds volume mounts."""
        artifacts_path = tmp_path / "artifacts"
        artifacts_path.mkdir()

        config = ContainerConfig(image="py-code-mode:latest")

        docker_config = config.to_docker_config(artifacts_path=artifacts_path)

        # Check that volumes were added
        assert "volumes" in docker_config
        assert str(artifacts_path.absolute()) in docker_config["volumes"]
        assert (
            docker_config["volumes"][str(artifacts_path.absolute())]["bind"]
            == "/workspace/artifacts"
        )


class TestContainerExecutorEnvironment:
    """Tests for environment configuration."""

    @pytest.mark.asyncio
    async def test_passes_environment_variables(self, tmp_path) -> None:
        """Passes environment variables to container."""
        config = ContainerConfig(
            image="py-code-mode:latest",
            environment={"API_KEY": "secret123"},
        )
        executor = ContainerExecutor(config)

        mock_container = _make_mock_container()
        mock_docker = MagicMock()
        mock_docker.containers.run.return_value = mock_container

        with patch("docker.from_env", return_value=mock_docker):
            with patch.object(executor, "_wait_for_healthy", new_callable=AsyncMock):
                async with executor:
                    call_args = mock_docker.containers.run.call_args
                    env = call_args[1].get("environment", {})
                    assert "API_KEY" in env
                    assert env["API_KEY"] == "secret123"
