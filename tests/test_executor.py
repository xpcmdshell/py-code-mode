"""Tests for code executor - written first to define interface."""

import pytest

from py_code_mode import ExecutionResult
from py_code_mode.execution.in_process import InProcessExecutor
from py_code_mode.tools.registry import ToolRegistry


class TestExecutorInterface:
    """Tests that define the executor interface."""

    @pytest.fixture
    def executor(self) -> InProcessExecutor:
        """Basic executor without tools."""
        return InProcessExecutor()

    @pytest.mark.asyncio
    async def test_execute_simple_expression(self, executor: InProcessExecutor) -> None:
        """Executor returns result of expression."""
        result = await executor.run("1 + 1")

        assert result.value == 2
        assert result.error is None

    @pytest.mark.asyncio
    async def test_execute_returns_last_expression(self, executor: InProcessExecutor) -> None:
        """Multiple statements - returns last expression value."""
        result = await executor.run("""
x = 10
y = 20
x + y
""")
        assert result.value == 30

    @pytest.mark.asyncio
    async def test_execute_captures_stdout(self, executor: InProcessExecutor) -> None:
        """Print statements captured in output."""
        result = await executor.run('print("hello world")')

        assert "hello world" in result.stdout
        assert result.value is None  # print returns None

    @pytest.mark.asyncio
    async def test_execute_error_captured(self, executor: InProcessExecutor) -> None:
        """Errors captured, not raised."""
        result = await executor.run("1 / 0")

        assert result.error is not None
        assert "ZeroDivisionError" in result.error
        assert result.value is None


class TestExecutorStatefulness:
    """Tests for kernel state persistence."""

    @pytest.fixture
    def executor(self) -> InProcessExecutor:
        return InProcessExecutor()

    @pytest.mark.asyncio
    async def test_variables_persist_across_executions(self, executor: InProcessExecutor) -> None:
        """Variables defined in one execution available in next."""
        await executor.run("x = 42")
        result = await executor.run("x * 2")

        assert result.value == 84

    @pytest.mark.asyncio
    async def test_functions_persist(self, executor: InProcessExecutor) -> None:
        """Functions defined persist across executions."""
        await executor.run("""
def greet(name):
    return f"Hello, {name}!"
""")
        result = await executor.run('greet("Alice")')

        assert result.value == "Hello, Alice!"

    @pytest.mark.asyncio
    async def test_imports_persist(self, executor: InProcessExecutor) -> None:
        """Imported modules persist."""
        await executor.run("import json")
        result = await executor.run('json.dumps({"a": 1})')

        assert result.value == '{"a": 1}'

    @pytest.mark.asyncio
    async def test_state_isolated_between_executors(self) -> None:
        """Different executor instances have separate state."""
        exec1 = InProcessExecutor()
        exec2 = InProcessExecutor()

        await exec1.run("shared_var = 'exec1'")
        await exec2.run("shared_var = 'exec2'")

        result1 = await exec1.run("shared_var")
        result2 = await exec2.run("shared_var")

        assert result1.value == "exec1"
        assert result2.value == "exec2"


class TestExecutorToolInjection:
    """Tests for tools.* namespace injection."""

    @pytest.fixture
    async def executor_with_tools(self) -> InProcessExecutor:
        """Executor with a mock tool registry."""
        from tests.conftest import MockAdapter

        registry = ToolRegistry()
        adapter = MockAdapter(
            tools=["echo", "add"],
            call_results={"echo": "echoed!", "add": 42},
        )
        registry.register_adapter(adapter)

        return InProcessExecutor(registry=registry)

    @pytest.mark.asyncio
    async def test_tools_namespace_available(self, executor_with_tools: InProcessExecutor) -> None:
        """tools.* namespace injected into execution context."""
        result = await executor_with_tools.run("'tools' in dir()")

        assert result.value is True

    @pytest.mark.asyncio
    async def test_call_tool_via_namespace(self, executor_with_tools: InProcessExecutor) -> None:
        """Can call tools through namespace escape hatch."""
        result = await executor_with_tools.run("tools.echo()")

        assert result.value == "echoed!"

    @pytest.mark.asyncio
    async def test_tool_search_available(self, executor_with_tools: InProcessExecutor) -> None:
        """tools.search() available in namespace."""
        result = await executor_with_tools.run('len(tools.search("echo"))')

        assert result.value >= 1

    @pytest.mark.asyncio
    async def test_tool_list_available(self, executor_with_tools: InProcessExecutor) -> None:
        """tools.list() available to enumerate tools."""
        result = await executor_with_tools.run("len(tools.list())")

        assert result.value == 2  # echo and add


class TestExecutorTimeout:
    """Tests for execution timeout."""

    @pytest.fixture
    def executor(self) -> InProcessExecutor:
        return InProcessExecutor(default_timeout=0.5)

    @pytest.mark.asyncio
    async def test_timeout_stops_execution(self, executor: InProcessExecutor) -> None:
        """Long-running code times out."""
        result = await executor.run("""
import time
time.sleep(10)
""")
        assert result.error is not None
        assert "timeout" in result.error.lower()

    @pytest.mark.asyncio
    async def test_timeout_per_execution(self, executor: InProcessExecutor) -> None:
        """Timeout can be overridden per execution."""
        # Default timeout is 0.5s, but we override to 0.1s
        result = await executor.run(
            "import time; time.sleep(5)",
            timeout=0.1,
        )

        assert result.error is not None


class TestExecutorCleanup:
    """Tests for resource cleanup."""

    @pytest.mark.asyncio
    async def test_close_releases_resources(self) -> None:
        """Closing executor releases kernel resources."""
        executor = InProcessExecutor()
        await executor.run("x = 1")
        await executor.close()

        # After close, executor should not be usable
        # (implementation decides exact behavior - error or reinit)

    @pytest.mark.asyncio
    async def test_context_manager(self) -> None:
        """Executor can be used as async context manager."""
        async with InProcessExecutor() as executor:
            result = await executor.run("1 + 1")
            assert result.value == 2
        # Resources released after context exit


class TestExecutionResult:
    """Tests for ExecutionResult dataclass."""

    def test_result_has_value(self) -> None:
        result = ExecutionResult(value=42, stdout="", error=None)
        assert result.value == 42

    def test_result_has_stdout(self) -> None:
        result = ExecutionResult(value=None, stdout="output", error=None)
        assert result.stdout == "output"

    def test_result_has_error(self) -> None:
        result = ExecutionResult(value=None, stdout="", error="Something broke")
        assert result.error == "Something broke"

    def test_result_is_ok(self) -> None:
        """Helper property for checking success."""
        success = ExecutionResult(value=42, stdout="", error=None)
        failure = ExecutionResult(value=None, stdout="", error="oops")

        assert success.is_ok is True
        assert failure.is_ok is False


class TestExecutorArtifacts:
    """Tests for artifacts namespace injection."""

    @pytest.fixture
    def executor_with_artifacts(self, tmp_path) -> InProcessExecutor:
        """Executor with artifacts directory."""
        from py_code_mode.artifacts import FileArtifactStore

        store = FileArtifactStore(tmp_path)
        return InProcessExecutor(artifact_store=store)

    @pytest.mark.asyncio
    async def test_artifacts_namespace_available(self, executor_with_artifacts) -> None:
        """artifacts.* namespace injected into execution context."""
        result = await executor_with_artifacts.run("'artifacts' in dir()")

        assert result.value is True

    @pytest.mark.asyncio
    async def test_artifacts_save(self, executor_with_artifacts, tmp_path) -> None:
        """Can save artifacts from executed code."""
        result = await executor_with_artifacts.run("""
artifacts.save("test.json", {"key": "value"}, description="Test data")
""")

        assert result.is_ok
        assert (tmp_path / "test.json").exists()

    @pytest.mark.asyncio
    async def test_artifacts_load(self, executor_with_artifacts) -> None:
        """Can load artifacts from executed code."""
        # First save
        await executor_with_artifacts.run("""
artifacts.save("data.json", {"x": 42}, description="Data")
""")

        # Then load
        result = await executor_with_artifacts.run("""
data = artifacts.load("data.json")
data["x"]
""")

        assert result.value == 42

    @pytest.mark.asyncio
    async def test_artifacts_list(self, executor_with_artifacts) -> None:
        """Can list artifacts from executed code."""
        await executor_with_artifacts.run("""
artifacts.save("a.json", {}, description="First")
artifacts.save("b.json", {}, description="Second")
""")

        result = await executor_with_artifacts.run("len(artifacts.list())")

        assert result.value == 2

    @pytest.mark.asyncio
    async def test_artifacts_path_for_raw_access(self, executor_with_artifacts) -> None:
        """artifacts.path available as string for raw file I/O."""
        result = await executor_with_artifacts.run("""
isinstance(artifacts.path, str)
""")

        assert result.value is True

    @pytest.mark.asyncio
    async def test_artifacts_raw_file_io(self, executor_with_artifacts, tmp_path) -> None:
        """Can use standard file I/O with Path(artifacts.path)."""
        result = await executor_with_artifacts.run("""
from pathlib import Path
p = Path(artifacts.path)
with open(p / "raw.txt", "w") as f:
    f.write("raw content")
(p / "raw.txt").read_text()
""")

        assert result.value == "raw content"
        assert (tmp_path / "raw.txt").exists()
