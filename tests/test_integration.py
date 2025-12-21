"""Integration tests for CLI -> Registry -> Executor flow.

Tests the complete path: register CLI tools, inject into executor,
run code that calls tools through the tools.* namespace.
"""

from pathlib import Path

import pytest

from py_code_mode.execution.in_process import InProcessExecutor
from py_code_mode.skills import FileSkillStore, MockEmbedder, SkillLibrary
from py_code_mode.tools.adapters.base import ToolAdapter
from py_code_mode.tools.adapters.cli import CLIAdapter
from py_code_mode.tools.registry import ToolRegistry


class TestCLIToExecutorFlow:
    """Tests the full integration: CLI adapter -> Registry -> Executor."""

    @pytest.fixture
    def tools_dir(self, tmp_path: Path) -> Path:
        """Create temp directory with CLI tool YAMLs."""
        tools_path = tmp_path / "tools"
        tools_path.mkdir()

        # echo tool
        (tools_path / "echo.yaml").write_text("""
name: echo
command: echo
description: Echo a message

schema:
  positional:
    - name: message
      type: string
      required: true

recipes:
  say:
    description: Echo a message
    params:
      message: {}
""")

        # pwd tool
        (tools_path / "pwd.yaml").write_text("""
name: pwd
command: pwd
description: Print working directory

schema: {}

recipes:
  run:
    description: Get current directory
    params: {}
""")

        # date tool
        (tools_path / "date_iso.yaml").write_text("""
name: date_iso
command: date
description: Get current date in ISO format

schema:
  positional:
    - name: format
      type: string
      required: false

recipes:
  iso:
    description: Get ISO date
    preset:
      format: "+%Y-%m-%d"
    params: {}
""")
        return tools_path

    @pytest.fixture
    def registry_with_cli_tools(self, tools_dir: Path) -> ToolRegistry:
        """Registry with real CLI tools."""
        adapter = CLIAdapter(tools_path=tools_dir)
        registry = ToolRegistry()
        registry._adapters.append(adapter)
        return registry

    @pytest.fixture
    def executor(self, registry_with_cli_tools: ToolRegistry) -> InProcessExecutor:
        """Executor with CLI tools injected."""
        return InProcessExecutor(registry=registry_with_cli_tools)

    @pytest.mark.asyncio
    async def test_call_cli_tool_from_code(self, executor: InProcessExecutor) -> None:
        """Code can call CLI tools through escape hatch."""
        result = await executor.run('tools.echo(message="hello")')

        assert result.is_ok, f"Execution failed: {result.error}"
        assert "hello" in result.value

    @pytest.mark.asyncio
    async def test_tool_result_usable_in_code(self, executor: InProcessExecutor) -> None:
        """Tool results can be used in subsequent code."""
        result = await executor.run("""
pwd = tools.pwd()
pwd.strip()
""")

        assert result.is_ok, f"Execution failed: {result.error}"
        assert "/" in result.value  # Unix path

    @pytest.mark.asyncio
    async def test_tool_results_persist_in_state(self, executor: InProcessExecutor) -> None:
        """Tool results stored in variables persist across executions."""
        # First execution: call tool and store result
        await executor.run("saved_pwd = tools.pwd()")

        # Second execution: use the saved result
        result = await executor.run("saved_pwd.strip()")

        assert result.is_ok, f"Execution failed: {result.error}"
        assert "/" in result.value

    @pytest.mark.asyncio
    async def test_tools_list_shows_cli_tools(self, executor: InProcessExecutor) -> None:
        """tools.list() returns registered CLI tools."""
        result = await executor.run("len(tools.list())")

        assert result.is_ok, f"Execution failed: {result.error}"
        assert result.value == 3  # echo, pwd, date_iso

    @pytest.mark.asyncio
    async def test_tools_search_finds_cli_tools(self, executor: InProcessExecutor) -> None:
        """tools.search() can find CLI tools by description."""
        result = await executor.run("""
matches = tools.search("echo")
[t.name for t in matches]
""")

        assert result.is_ok, f"Execution failed: {result.error}"
        assert any("echo" in name for name in result.value)

    @pytest.mark.asyncio
    async def test_tool_not_found_error(self, executor: InProcessExecutor) -> None:
        """Calling nonexistent tool raises appropriate error."""
        result = await executor.run("tools.nonexistent()")

        # Error should be captured, not raised
        assert result.error is not None
        assert "unknown tool" in result.error.lower() or "nonexistent" in result.error.lower()


class TestErrorPropagation:
    """Tests that errors propagate correctly through the stack."""

    @pytest.fixture
    def tools_dir(self, tmp_path: Path) -> Path:
        """Create temp directory with failing CLI tool."""
        tools_path = tmp_path / "tools"
        tools_path.mkdir()

        (tools_path / "fail.yaml").write_text("""
name: fail
command: "false"
description: A command that fails

schema: {}

recipes:
  run:
    description: Run failing command
    params: {}
""")
        return tools_path

    @pytest.fixture
    def executor_with_failing_tool(self, tools_dir: Path) -> InProcessExecutor:
        """Executor with a tool that will fail."""
        adapter = CLIAdapter(tools_path=tools_dir)
        registry = ToolRegistry()
        registry._adapters.append(adapter)
        return InProcessExecutor(registry=registry)

    @pytest.mark.asyncio
    async def test_cli_failure_captured_in_result(
        self, executor_with_failing_tool: InProcessExecutor
    ) -> None:
        """CLI tool failure is captured in ExecutionResult."""
        result = await executor_with_failing_tool.run("tools.fail()")

        # The tool call itself may succeed but return error info,
        # or it may raise which gets captured
        # Either way, we should see some indication of failure
        assert result.error is not None or result.value == ""


class TestMultipleAdapters:
    """Tests registry with multiple adapters."""

    @pytest.fixture
    def tools_dir1(self, tmp_path: Path) -> Path:
        """Create temp directory with first adapter tools."""
        tools_path = tmp_path / "tools1"
        tools_path.mkdir()

        (tools_path / "echo1.yaml").write_text("""
name: echo1
command: echo
description: Echo 1

schema:
  positional:
    - name: text
      type: string
      required: false

recipes:
  run:
    description: Run echo
    preset:
      text: "one"
    params: {}
""")
        return tools_path

    @pytest.fixture
    def tools_dir2(self, tmp_path: Path) -> Path:
        """Create temp directory with second adapter tools."""
        tools_path = tmp_path / "tools2"
        tools_path.mkdir()

        (tools_path / "echo2.yaml").write_text("""
name: echo2
command: echo
description: Echo 2

schema:
  positional:
    - name: text
      type: string
      required: false

recipes:
  run:
    description: Run echo
    preset:
      text: "two"
    params: {}
""")
        return tools_path

    @pytest.mark.asyncio
    async def test_multiple_adapters_flat_namespace(
        self, tools_dir1: Path, tools_dir2: Path
    ) -> None:
        """Tools from different adapters share flat namespace."""
        adapter1 = CLIAdapter(tools_path=tools_dir1)
        adapter2 = CLIAdapter(tools_path=tools_dir2)

        registry = ToolRegistry()
        registry._adapters.append(adapter1)
        registry._adapters.append(adapter2)

        executor = InProcessExecutor(registry=registry)

        result1 = await executor.run("tools.echo1.run()")
        result2 = await executor.run("tools.echo2.run()")

        assert result1.is_ok and result2.is_ok
        assert "one" in result1.value
        assert "two" in result2.value

    @pytest.fixture
    def duplicate_tools_dir1(self, tmp_path: Path) -> Path:
        """Create temp directory with duplicate tool name."""
        tools_path = tmp_path / "dup1"
        tools_path.mkdir()

        (tools_path / "echo.yaml").write_text("""
name: echo
command: echo
description: Echo 1

schema: {}

recipes:
  run:
    description: Run echo
    params: {}
""")
        return tools_path

    @pytest.fixture
    def duplicate_tools_dir2(self, tmp_path: Path) -> Path:
        """Create temp directory with duplicate tool name."""
        tools_path = tmp_path / "dup2"
        tools_path.mkdir()

        (tools_path / "echo.yaml").write_text("""
name: echo
command: echo
description: Echo 2

schema: {}

recipes:
  run:
    description: Run echo
    params: {}
""")
        return tools_path

    @pytest.mark.asyncio
    async def test_duplicate_tool_name_in_adapters(
        self, duplicate_tools_dir1: Path, duplicate_tools_dir2: Path
    ) -> None:
        """Duplicate tool names from different adapters coexist (last wins)."""
        # Note: With the new unified interface, we don't use register_adapter
        # so there's no duplicate check. The second adapter's tools would shadow.
        adapter1 = CLIAdapter(tools_path=duplicate_tools_dir1)
        adapter2 = CLIAdapter(tools_path=duplicate_tools_dir2)

        registry = ToolRegistry()
        registry._adapters.append(adapter1)
        registry._adapters.append(adapter2)

        # Both adapters are in the list, first match wins during lookup
        tools = []
        for adapter in registry._adapters:
            if isinstance(adapter, ToolAdapter):
                tools.extend(adapter.list_tools())

        echo_tools = [t for t in tools if t.name == "echo"]
        assert len(echo_tools) == 2  # Both exist, first wins on call


class TestScopedExecution:
    """Tests that tool scoping works through executor."""

    @pytest.mark.asyncio
    async def test_scoped_registry_limits_tools(self) -> None:
        """Executor with scoped registry only sees allowed tools."""
        from py_code_mode import JsonSchema, ToolDefinition
        from tests.conftest import MockAdapter

        # Create tools with different tags
        network_tool = ToolDefinition(
            name="scan",
            description="Network scanner",
            input_schema=JsonSchema(type="object"),
            tags=frozenset({"network"}),
        )
        web_tool = ToolDefinition(
            name="curl",
            description="HTTP client",
            input_schema=JsonSchema(type="object"),
            tags=frozenset({"web"}),
        )

        adapter = MockAdapter([network_tool, web_tool])
        registry = ToolRegistry()
        registry.register_adapter(adapter)

        # Create scoped view that only allows network tools
        scoped = registry.scoped_view({"network"})

        tools = scoped.list_tools()
        assert len(tools) == 1
        assert tools[0].name == "scan"


class TestSkillsIntegration:
    """Tests skills integration with executor."""

    @pytest.fixture
    def skill_library(self, tmp_path: Path) -> SkillLibrary:
        """Create skill library with test skills."""
        skills_path = tmp_path / "skills"
        skills_path.mkdir()

        # Create a simple skill
        (skills_path / "double.py").write_text('''"""Double a number."""

def run(n: int) -> int:
    return n * 2
''')

        store = FileSkillStore(skills_path)
        return SkillLibrary(embedder=MockEmbedder(), store=store)

    @pytest.fixture
    def executor_with_skills(self, skill_library: SkillLibrary) -> InProcessExecutor:
        """Executor with skill library."""
        return InProcessExecutor(skill_library=skill_library)

    @pytest.mark.asyncio
    async def test_skills_list_shows_skills(self, executor_with_skills: InProcessExecutor) -> None:
        """skills.list() returns available skills."""
        result = await executor_with_skills.run("len(skills.list())")

        assert result.is_ok, f"Execution failed: {result.error}"
        assert result.value == 1

    @pytest.mark.asyncio
    async def test_skill_invocation(self, executor_with_skills: InProcessExecutor) -> None:
        """Can invoke skill from executed code."""
        result = await executor_with_skills.run("skills.double(n=21)")

        assert result.is_ok, f"Execution failed: {result.error}"
        assert result.value == 42

    @pytest.mark.asyncio
    async def test_skills_search(self, executor_with_skills: InProcessExecutor) -> None:
        """skills.search() can find skills."""
        result = await executor_with_skills.run("""
matches = skills.search("double")
[s["name"] for s in matches]
""")

        assert result.is_ok, f"Execution failed: {result.error}"
        assert "double" in result.value
