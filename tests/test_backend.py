"""Protocol compliance tests for execution backends.

These tests define what every Executor must do. Written FIRST (TDD).
All backends must pass these tests to be considered compliant.
"""

import pytest

# These imports will fail initially - that's expected (TDD red phase)
from py_code_mode.artifacts import FileArtifactStore
from py_code_mode.execution import Capability, Executor
from py_code_mode.execution.in_process import InProcessExecutor
from py_code_mode.types import ExecutionResult


class TestExecutorProtocol:
    """Tests that define the Executor protocol contract."""

    @pytest.fixture(params=["in-process"])  # Start with just in-process, add others as implemented
    async def executor(self, request, tmp_path) -> Executor:
        """Create executor for each backend type."""
        backend = request.param

        if backend == "in-process":
            artifacts_path = tmp_path / "artifacts"
            artifacts_path.mkdir(parents=True, exist_ok=True)
            artifact_store = FileArtifactStore(artifacts_path)
            executor = InProcessExecutor(artifact_store=artifact_store)
        elif backend == "container":
            pytest.skip("Container backend not yet migrated")
        elif backend == "microsandbox":
            pytest.skip("Microsandbox backend not yet implemented")
        else:
            pytest.fail(f"Unknown backend: {backend}")

        yield executor
        await executor.close()

    @pytest.mark.asyncio
    async def test_run_returns_execution_result(self, executor: Executor) -> None:
        """run() must return an ExecutionResult."""
        result = await executor.run("1 + 1")

        assert isinstance(result, ExecutionResult)
        assert result.is_ok
        assert result.value == 2

    @pytest.mark.asyncio
    async def test_run_captures_stdout(self, executor: Executor) -> None:
        """run() must capture print output in stdout field."""
        result = await executor.run("print('hello world')")

        assert result.is_ok
        assert "hello world" in result.stdout

    @pytest.mark.asyncio
    async def test_run_captures_errors(self, executor: Executor) -> None:
        """run() must capture exceptions in error field, not raise."""
        result = await executor.run("raise ValueError('boom')")

        assert not result.is_ok
        assert result.error is not None
        assert "ValueError" in result.error

    @pytest.mark.asyncio
    async def test_run_with_timeout(self, executor: Executor) -> None:
        """run() must respect timeout parameter."""
        result = await executor.run(
            "import time; time.sleep(10)",
            timeout=0.1,
        )

        assert not result.is_ok
        assert result.error is not None
        assert "timeout" in result.error.lower()

    @pytest.mark.asyncio
    async def test_supports_returns_bool(self, executor: Executor) -> None:
        """supports() must return a boolean."""
        result = executor.supports(Capability.TIMEOUT)

        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_supported_capabilities_returns_set(self, executor: Executor) -> None:
        """supported_capabilities() must return a set of strings."""
        caps = executor.supported_capabilities()

        assert isinstance(caps, set)
        # All backends must support timeout
        assert Capability.TIMEOUT in caps

    @pytest.mark.asyncio
    async def test_context_manager_support(self, tmp_path) -> None:
        """Executor must support async context manager."""
        artifacts_path = tmp_path / "artifacts"
        artifacts_path.mkdir(parents=True, exist_ok=True)
        artifact_store = FileArtifactStore(artifacts_path)
        async with InProcessExecutor(artifact_store=artifact_store) as executor:
            result = await executor.run("1 + 1")
            assert result.value == 2
        # After exit, resources should be released


class TestBackendRegistry:
    """Tests for backend registration and discovery."""

    def test_in_process_backend_registered(self) -> None:
        """in-process backend must be registered by default."""
        from py_code_mode.execution import get_backend, list_backends

        assert "in-process" in list_backends()
        assert get_backend("in-process") is not None

    def test_list_backends_returns_list(self) -> None:
        """list_backends() must return list of backend names."""
        from py_code_mode.execution import list_backends

        backends = list_backends()
        assert isinstance(backends, list)
        assert "in-process" in backends

    def test_get_unknown_backend_returns_none(self) -> None:
        """get_backend() returns None for unknown backends."""
        from py_code_mode.execution import get_backend

        result = get_backend("nonexistent-backend")
        assert result is None


class TestInProcessCapabilities:
    """Tests for in-process executor capabilities."""

    @pytest.fixture
    async def executor(self, tmp_path) -> Executor:
        """Create in-process executor."""
        artifacts_path = tmp_path / "artifacts"
        artifacts_path.mkdir(parents=True, exist_ok=True)
        artifact_store = FileArtifactStore(artifacts_path)
        executor = InProcessExecutor(artifact_store=artifact_store)
        yield executor
        await executor.close()

    def test_supports_timeout(self, executor: Executor) -> None:
        """In-process executor supports timeout."""
        assert executor.supports(Capability.TIMEOUT)

    def test_does_not_support_process_isolation(self, executor: Executor) -> None:
        """In-process executor does NOT support process isolation."""
        assert not executor.supports(Capability.PROCESS_ISOLATION)

    def test_does_not_support_network_isolation(self, executor: Executor) -> None:
        """In-process executor does NOT support network isolation."""
        assert not executor.supports(Capability.NETWORK_ISOLATION)

    def test_capabilities_set_contains_timeout(self, executor: Executor) -> None:
        """supported_capabilities() includes timeout and reset."""
        caps = executor.supported_capabilities()
        assert Capability.TIMEOUT in caps
        assert Capability.RESET in caps

    def test_capabilities_set_does_not_contain_isolation(self, executor: Executor) -> None:
        """supported_capabilities() does not include isolation capabilities."""
        caps = executor.supported_capabilities()
        assert Capability.PROCESS_ISOLATION not in caps
        assert Capability.NETWORK_ISOLATION not in caps


class TestContainerCapabilities:
    """Tests for container executor capabilities (requires Docker)."""

    @pytest.fixture
    def container_executor_class(self):
        """Get ContainerExecutor class, skip if docker not installed."""
        try:
            from py_code_mode.execution.container import ContainerExecutor

            return ContainerExecutor
        except ImportError:
            pytest.skip("Docker not installed")

    def test_supports_timeout(self, container_executor_class) -> None:
        """Container executor supports timeout."""
        from py_code_mode.execution.container import ContainerConfig

        config = ContainerConfig(auth_disabled=True)
        executor = container_executor_class(config)
        assert executor.supports(Capability.TIMEOUT)

    def test_supports_process_isolation(self, container_executor_class) -> None:
        """Container executor supports process isolation."""
        from py_code_mode.execution.container import ContainerConfig

        config = ContainerConfig(auth_disabled=True)
        executor = container_executor_class(config)
        assert executor.supports(Capability.PROCESS_ISOLATION)

    def test_supports_reset(self, container_executor_class) -> None:
        """Container executor supports reset capability."""
        from py_code_mode.execution.container import ContainerConfig

        config = ContainerConfig(auth_disabled=True)
        executor = container_executor_class(config)
        assert executor.supports(Capability.RESET)

    def test_does_not_support_network_isolation(self, container_executor_class) -> None:
        """Container executor does NOT support network isolation."""
        from py_code_mode.execution.container import ContainerConfig

        config = ContainerConfig(auth_disabled=True)
        executor = container_executor_class(config)
        assert not executor.supports(Capability.NETWORK_ISOLATION)

    def test_capabilities_set(self, container_executor_class) -> None:
        """supported_capabilities() returns correct set."""
        from py_code_mode.execution.container import ContainerConfig

        config = ContainerConfig(auth_disabled=True)
        executor = container_executor_class(config)
        caps = executor.supported_capabilities()

        assert Capability.TIMEOUT in caps
        assert Capability.PROCESS_ISOLATION in caps
        assert Capability.RESET in caps
        assert Capability.NETWORK_ISOLATION not in caps
