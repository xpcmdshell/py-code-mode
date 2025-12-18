"""Protocol compliance tests for execution backends.

These tests define what every Executor must do. Written FIRST (TDD).
All backends must pass these tests to be considered compliant.
"""

import pytest

# These imports will fail initially - that's expected (TDD red phase)
from py_code_mode.backend import Capability, Executor, create_executor
from py_code_mode.types import ExecutionResult


class TestExecutorProtocol:
    """Tests that define the Executor protocol contract."""

    @pytest.fixture(params=["in-process"])  # Start with just in-process, add others as implemented
    async def executor(self, request, tmp_path) -> Executor:
        """Create executor for each backend type."""
        backend = request.param

        if backend == "in-process":
            executor = await create_executor(
                backend="in-process",
                artifacts=str(tmp_path / "artifacts"),
            )
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
        async with await create_executor(
            backend="in-process",
            artifacts=str(tmp_path / "artifacts"),
        ) as executor:
            result = await executor.run("1 + 1")
            assert result.value == 2
        # After exit, resources should be released


class TestCapabilityConstants:
    """Tests for Capability constants."""

    def test_timeout_capability_exists(self) -> None:
        """TIMEOUT capability must be defined."""
        assert hasattr(Capability, "TIMEOUT")
        assert Capability.TIMEOUT == "timeout"

    def test_process_isolation_capability_exists(self) -> None:
        """PROCESS_ISOLATION capability must be defined."""
        assert hasattr(Capability, "PROCESS_ISOLATION")
        assert Capability.PROCESS_ISOLATION == "process_isolation"

    def test_network_isolation_capability_exists(self) -> None:
        """NETWORK_ISOLATION capability must be defined."""
        assert hasattr(Capability, "NETWORK_ISOLATION")
        assert Capability.NETWORK_ISOLATION == "network_isolation"

    def test_network_filtering_capability_exists(self) -> None:
        """NETWORK_FILTERING capability must be defined."""
        assert hasattr(Capability, "NETWORK_FILTERING")
        assert Capability.NETWORK_FILTERING == "network_filtering"

    def test_filesystem_isolation_capability_exists(self) -> None:
        """FILESYSTEM_ISOLATION capability must be defined."""
        assert hasattr(Capability, "FILESYSTEM_ISOLATION")
        assert Capability.FILESYSTEM_ISOLATION == "filesystem_isolation"

    def test_memory_limit_capability_exists(self) -> None:
        """MEMORY_LIMIT capability must be defined."""
        assert hasattr(Capability, "MEMORY_LIMIT")
        assert Capability.MEMORY_LIMIT == "memory_limit"

    def test_cpu_limit_capability_exists(self) -> None:
        """CPU_LIMIT capability must be defined."""
        assert hasattr(Capability, "CPU_LIMIT")
        assert Capability.CPU_LIMIT == "cpu_limit"

    def test_reset_capability_exists(self) -> None:
        """RESET capability must be defined."""
        assert hasattr(Capability, "RESET")
        assert Capability.RESET == "reset"

    def test_all_returns_set_of_all_capabilities(self) -> None:
        """Capability.all() must return set of all defined capabilities."""
        all_caps = Capability.all()

        assert isinstance(all_caps, set)
        assert Capability.TIMEOUT in all_caps
        assert Capability.NETWORK_ISOLATION in all_caps
        assert len(all_caps) >= 8  # At least 8 capabilities defined


class TestExecutionResult:
    """Tests for the unified ExecutionResult type."""

    def test_result_has_value(self) -> None:
        """ExecutionResult must have value field."""
        result = ExecutionResult(value=42, stdout="", error=None)
        assert result.value == 42

    def test_result_has_stdout(self) -> None:
        """ExecutionResult must have stdout field."""
        result = ExecutionResult(value=None, stdout="output", error=None)
        assert result.stdout == "output"

    def test_result_has_error(self) -> None:
        """ExecutionResult must have error field."""
        result = ExecutionResult(value=None, stdout="", error="Something broke")
        assert result.error == "Something broke"

    def test_result_is_ok_property(self) -> None:
        """ExecutionResult must have is_ok property."""
        success = ExecutionResult(value=42, stdout="", error=None)
        failure = ExecutionResult(value=None, stdout="", error="oops")

        assert success.is_ok is True
        assert failure.is_ok is False

    def test_result_has_optional_execution_time(self) -> None:
        """ExecutionResult may have execution_time_ms field."""
        result = ExecutionResult(
            value=42,
            stdout="",
            error=None,
            execution_time_ms=123.45,
        )
        assert result.execution_time_ms == 123.45

    def test_result_has_optional_backend_info(self) -> None:
        """ExecutionResult may have backend_info dict."""
        result = ExecutionResult(
            value=42,
            stdout="",
            error=None,
            backend_info={"session_id": "abc123"},
        )
        assert result.backend_info["session_id"] == "abc123"


class TestBackendRegistry:
    """Tests for backend registration and discovery."""

    def test_in_process_backend_registered(self) -> None:
        """in-process backend must be registered by default."""
        from py_code_mode.backend import get_backend, list_backends

        assert "in-process" in list_backends()
        assert get_backend("in-process") is not None

    def test_list_backends_returns_list(self) -> None:
        """list_backends() must return list of backend names."""
        from py_code_mode.backend import list_backends

        backends = list_backends()
        assert isinstance(backends, list)
        assert "in-process" in backends

    def test_get_unknown_backend_returns_none(self) -> None:
        """get_backend() returns None for unknown backends."""
        from py_code_mode.backend import get_backend

        result = get_backend("nonexistent-backend")
        assert result is None


class TestCreateExecutorFactory:
    """Tests for the create_executor() factory function."""

    @pytest.mark.asyncio
    async def test_create_in_process_executor(self, tmp_path) -> None:
        """create_executor() can create in-process executor."""
        executor = await create_executor(
            backend="in-process",
            artifacts=str(tmp_path / "artifacts"),
        )

        result = await executor.run("1 + 1")
        assert result.value == 2

        await executor.close()

    @pytest.mark.asyncio
    async def test_create_with_tools_path(self, tmp_path) -> None:
        """create_executor() accepts tools path."""
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()

        executor = await create_executor(
            backend="in-process",
            tools=str(tools_dir),
        )

        # Should have tools namespace
        result = await executor.run("'tools' in dir()")
        assert result.value is True

        await executor.close()

    @pytest.mark.asyncio
    async def test_create_with_skills_path(self, tmp_path) -> None:
        """create_executor() accepts skills path."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        executor = await create_executor(
            backend="in-process",
            skills=str(skills_dir),
        )

        # Should have skills namespace
        result = await executor.run("'skills' in dir()")
        assert result.value is True

        await executor.close()

    @pytest.mark.asyncio
    async def test_create_unknown_backend_raises(self) -> None:
        """create_executor() raises ValueError for unknown backend."""
        with pytest.raises(ValueError, match="Unknown backend"):
            await create_executor(backend="nonexistent")

    @pytest.mark.asyncio
    async def test_create_passes_security_config(self, tmp_path) -> None:
        """create_executor() passes security config to backend."""
        # Security config is accepted even if backend ignores it
        executor = await create_executor(
            backend="in-process",
            network_policy="deny",
            allowed_hosts=["example.com"],
            filesystem_policy="readonly",
            memory_limit_mb=256,
        )

        # In-process doesn't enforce these, but should accept them
        result = await executor.run("1 + 1")
        assert result.value == 2

        await executor.close()


class TestInProcessCapabilities:
    """Tests for in-process executor capabilities."""

    @pytest.fixture
    async def executor(self, tmp_path) -> Executor:
        """Create in-process executor."""
        executor = await create_executor(
            backend="in-process",
            artifacts=str(tmp_path / "artifacts"),
        )
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
        """supported_capabilities() includes timeout."""
        caps = executor.supported_capabilities()
        assert Capability.TIMEOUT in caps

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
            from py_code_mode.backends.container import ContainerExecutor

            return ContainerExecutor
        except ImportError:
            pytest.skip("Docker not installed")

    def test_supports_timeout(self, container_executor_class) -> None:
        """Container executor supports timeout."""
        from py_code_mode.backends.container import ContainerConfig

        config = ContainerConfig()
        executor = container_executor_class(config)
        assert executor.supports(Capability.TIMEOUT)

    def test_supports_process_isolation(self, container_executor_class) -> None:
        """Container executor supports process isolation."""
        from py_code_mode.backends.container import ContainerConfig

        config = ContainerConfig()
        executor = container_executor_class(config)
        assert executor.supports(Capability.PROCESS_ISOLATION)

    def test_supports_reset(self, container_executor_class) -> None:
        """Container executor supports reset capability."""
        from py_code_mode.backends.container import ContainerConfig

        config = ContainerConfig()
        executor = container_executor_class(config)
        assert executor.supports(Capability.RESET)

    def test_does_not_support_network_isolation(self, container_executor_class) -> None:
        """Container executor does NOT support network isolation."""
        from py_code_mode.backends.container import ContainerConfig

        config = ContainerConfig()
        executor = container_executor_class(config)
        assert not executor.supports(Capability.NETWORK_ISOLATION)

    def test_capabilities_set(self, container_executor_class) -> None:
        """supported_capabilities() returns correct set."""
        from py_code_mode.backends.container import ContainerConfig

        config = ContainerConfig()
        executor = container_executor_class(config)
        caps = executor.supported_capabilities()

        assert Capability.TIMEOUT in caps
        assert Capability.PROCESS_ISOLATION in caps
        assert Capability.RESET in caps
        assert Capability.NETWORK_ISOLATION not in caps
