"""Integration tests for CLI -> Registry -> Executor flow.

Tests the complete path: register CLI tools, inject into executor,
run code that calls tools through the tools.* namespace.
"""

from pathlib import Path
from textwrap import dedent

import pytest

from py_code_mode import CLIAdapter, CLIToolSpec, CodeExecutor, ToolRegistry
from py_code_mode.semantic import MockEmbedder, SkillLibrary
from py_code_mode.skill_store import FileSkillStore


class TestCLIToExecutorFlow:
    """Tests the full integration: CLI adapter -> Registry -> Executor."""

    @pytest.fixture
    async def registry_with_cli_tools(self) -> ToolRegistry:
        """Registry with real CLI tools."""
        adapter = CLIAdapter(
            [
                CLIToolSpec(
                    name="echo",
                    description="Echo a message",
                    command="echo",
                    args_template="{message}",
                ),
                CLIToolSpec(
                    name="pwd",
                    description="Print working directory",
                    command="pwd",
                ),
                CLIToolSpec(
                    name="date_iso",
                    description="Get current date in ISO format",
                    command="date",
                    args_template="+%Y-%m-%d",
                ),
            ]
        )

        registry = ToolRegistry()
        await registry.register_adapter(adapter)
        return registry

    @pytest.fixture
    async def executor(self, registry_with_cli_tools: ToolRegistry) -> CodeExecutor:
        """Executor with CLI tools injected."""
        return CodeExecutor(registry=registry_with_cli_tools)

    @pytest.mark.asyncio
    async def test_call_cli_tool_from_code(self, executor: CodeExecutor) -> None:
        """Code can call CLI tools through tools.call()."""
        result = await executor.run('tools.call("echo", {"message": "hello"})')

        assert result.is_ok, f"Execution failed: {result.error}"
        assert "hello" in result.value

    @pytest.mark.asyncio
    async def test_tool_result_usable_in_code(self, executor: CodeExecutor) -> None:
        """Tool results can be used in subsequent code."""
        result = await executor.run("""
pwd = tools.call("pwd", {})
pwd.strip()
""")

        assert result.is_ok, f"Execution failed: {result.error}"
        assert "/" in result.value  # Unix path

    @pytest.mark.asyncio
    async def test_tool_results_persist_in_state(self, executor: CodeExecutor) -> None:
        """Tool results stored in variables persist across executions."""
        # First execution: call tool and store result
        await executor.run('saved_pwd = tools.call("pwd", {})')

        # Second execution: use the saved result
        result = await executor.run("saved_pwd.strip()")

        assert result.is_ok, f"Execution failed: {result.error}"
        assert "/" in result.value

    @pytest.mark.asyncio
    async def test_tools_list_shows_cli_tools(self, executor: CodeExecutor) -> None:
        """tools.list() returns registered CLI tools."""
        result = await executor.run("len(tools.list())")

        assert result.is_ok, f"Execution failed: {result.error}"
        assert result.value == 3  # echo, pwd, date_iso

    @pytest.mark.asyncio
    async def test_tools_search_finds_cli_tools(self, executor: CodeExecutor) -> None:
        """tools.search() can find CLI tools by description."""
        result = await executor.run("""
matches = tools.search("echo")
[t["name"] for t in matches]
""")

        assert result.is_ok, f"Execution failed: {result.error}"
        assert any("echo" in name for name in result.value)

    @pytest.mark.asyncio
    async def test_tool_not_found_error(self, executor: CodeExecutor) -> None:
        """Calling nonexistent tool raises appropriate error."""
        result = await executor.run('tools.call("nonexistent", {})')

        # Error should be captured, not raised
        assert result.error is not None
        assert "not found" in result.error.lower() or "nonexistent" in result.error.lower()


class TestErrorPropagation:
    """Tests that errors propagate correctly through the stack."""

    @pytest.fixture
    async def executor_with_failing_tool(self) -> CodeExecutor:
        """Executor with a tool that will fail."""
        adapter = CLIAdapter(
            [
                CLIToolSpec(
                    name="fail",
                    description="A command that fails",
                    command="false",  # Unix command that always exits 1
                ),
            ]
        )

        registry = ToolRegistry()
        await registry.register_adapter(adapter)
        return CodeExecutor(registry=registry)

    @pytest.mark.asyncio
    async def test_cli_failure_captured_in_result(
        self, executor_with_failing_tool: CodeExecutor
    ) -> None:
        """CLI tool failure is captured in ExecutionResult."""
        result = await executor_with_failing_tool.run('tools.call("fail", {})')

        # The tool call itself may succeed but return error info,
        # or it may raise which gets captured
        # Either way, we should see some indication of failure
        assert result.error is not None or result.value == ""


class TestMultipleAdapters:
    """Tests registry with multiple adapters."""

    @pytest.mark.asyncio
    async def test_multiple_adapters_flat_namespace(self) -> None:
        """Tools from different adapters share flat namespace."""
        adapter1 = CLIAdapter(
            [
                CLIToolSpec(
                    name="echo1", description="Echo 1", command="echo", args_template="one"
                ),
            ]
        )
        adapter2 = CLIAdapter(
            [
                CLIToolSpec(
                    name="echo2", description="Echo 2", command="echo", args_template="two"
                ),
            ]
        )

        registry = ToolRegistry()
        await registry.register_adapter(adapter1)
        await registry.register_adapter(adapter2)

        executor = CodeExecutor(registry=registry)

        result1 = await executor.run('tools.call("echo1", {})')
        result2 = await executor.run('tools.call("echo2", {})')

        assert result1.is_ok and result2.is_ok
        assert "one" in result1.value
        assert "two" in result2.value

    @pytest.mark.asyncio
    async def test_duplicate_tool_name_rejected(self) -> None:
        """Duplicate tool names from different adapters are rejected."""
        adapter1 = CLIAdapter(
            [
                CLIToolSpec(name="echo", description="Echo 1", command="echo"),
            ]
        )
        adapter2 = CLIAdapter(
            [
                CLIToolSpec(name="echo", description="Echo 2", command="echo"),
            ]
        )

        registry = ToolRegistry()
        await registry.register_adapter(adapter1)

        with pytest.raises(ValueError, match="already registered"):
            await registry.register_adapter(adapter2)


class TestScopedExecution:
    """Tests that tool scoping works through executor."""

    @pytest.mark.asyncio
    async def test_scoped_registry_limits_tools(self) -> None:
        """Executor with scoped registry only sees allowed tools."""
        from py_code_mode import JsonSchema, ToolDefinition
        from tests.conftest import MockAdapter

        # Create tools with different tags
        adapter = MockAdapter(
            tools=[
                ToolDefinition(
                    name="safe",
                    description="Safe tool",
                    input_schema=JsonSchema(type="object"),
                    tags=frozenset({"safe"}),
                ),
                ToolDefinition(
                    name="dangerous",
                    description="Dangerous tool",
                    input_schema=JsonSchema(type="object"),
                    tags=frozenset({"dangerous"}),
                ),
            ],
            call_results={"safe": "ok", "dangerous": "boom"},
        )

        registry = ToolRegistry()
        await registry.register_adapter(adapter)

        # Create scoped view that only allows "safe" tag
        scoped = registry.scoped_view({"safe"})

        executor = CodeExecutor(registry=scoped)

        # Should see only 1 tool
        result = await executor.run("len(tools.list())")
        assert result.is_ok
        assert result.value == 1

        # Should be able to call safe tool
        result = await executor.run('tools.call("safe", {})')
        assert result.is_ok

        # Should NOT be able to call dangerous tool
        result = await executor.run('tools.call("dangerous", {})')
        assert result.error is not None


class TestSkillsIntegration:
    """Tests for skills system integration with executor."""

    @pytest.fixture
    def skills_dir(self, tmp_path: Path) -> Path:
        """Create a directory with sample Python skill files."""
        # Simple greeting skill
        (tmp_path / "greet.py").write_text(
            dedent('''
            """Greet someone by name."""

            def run(target_name: str, enthusiasm: int = 1) -> str:
                """Generate a greeting.

                Args:
                    target_name: Name to greet
                    enthusiasm: Exclamation marks
                """
                return f"Hello, {target_name}!" + "!" * (enthusiasm - 1)
        ''').strip()
        )

        # Math skill
        (tmp_path / "add_numbers.py").write_text(
            dedent('''
            """Add two numbers together."""

            def run(a: int, b: int) -> int:
                """Add two integers.

                Args:
                    a: First number
                    b: Second number
                """
                return a + b
        ''').strip()
        )

        return tmp_path

    @pytest.fixture
    def skill_library(self, skills_dir: Path) -> SkillLibrary:
        """Load skills from the test directory using new architecture."""
        store = FileSkillStore(skills_dir)
        # Use MockEmbedder to avoid GPU dependency in tests
        embedder = MockEmbedder(dimension=384)
        return SkillLibrary(embedder=embedder, store=store)

    @pytest.fixture
    def executor_with_skills(self, skill_library: SkillLibrary) -> CodeExecutor:
        """Executor with skills namespace injected."""
        return CodeExecutor(skill_library=skill_library)

    @pytest.mark.asyncio
    async def test_skills_namespace_available(self, executor_with_skills: CodeExecutor) -> None:
        """skills.* namespace is available in executor."""
        result = await executor_with_skills.run("'skills' in dir()")

        assert result.is_ok, f"Execution failed: {result.error}"
        assert result.value is True

    @pytest.mark.asyncio
    async def test_skills_search(self, executor_with_skills: CodeExecutor) -> None:
        """Can search for skills from code."""
        result = await executor_with_skills.run("""
matches = skills.search("greet")
[s["name"] for s in matches]
""")

        assert result.is_ok, f"Execution failed: {result.error}"
        assert "greet" in result.value

    @pytest.mark.asyncio
    async def test_skills_get(self, executor_with_skills: CodeExecutor) -> None:
        """Can get skill by name from code."""
        result = await executor_with_skills.run("""
skill = skills.get("greet")
skill.name
""")

        assert result.is_ok, f"Execution failed: {result.error}"
        assert result.value == "greet"

    @pytest.mark.asyncio
    async def test_skills_invoke(self, executor_with_skills: CodeExecutor) -> None:
        """Can invoke a skill with parameters."""
        result = await executor_with_skills.run("""
skills.invoke("greet", target_name="Alice")
""")

        assert result.is_ok, f"Execution failed: {result.error}"
        assert "Hello, Alice!" in result.value

    @pytest.mark.asyncio
    async def test_skills_invoke_with_defaults(self, executor_with_skills: CodeExecutor) -> None:
        """Skill invoke uses default parameter values."""
        result = await executor_with_skills.run("""
skills.invoke("greet", target_name="Bob", enthusiasm=3)
""")

        assert result.is_ok, f"Execution failed: {result.error}"
        assert "Hello, Bob!!!" in result.value

    @pytest.mark.asyncio
    async def test_skills_invoke_math(self, executor_with_skills: CodeExecutor) -> None:
        """Skill that does computation."""
        result = await executor_with_skills.run("""
skills.invoke("add_numbers", a=10, b=32)
""")

        assert result.is_ok, f"Execution failed: {result.error}"
        assert result.value == 42

    @pytest.mark.asyncio
    async def test_skills_list(self, executor_with_skills: CodeExecutor) -> None:
        """Can list all available skills."""
        result = await executor_with_skills.run("len(skills.list())")

        assert result.is_ok, f"Execution failed: {result.error}"
        assert result.value == 2  # greet and add_numbers
