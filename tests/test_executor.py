"""Tests for code executor - written first to define interface."""

import pytest

from py_code_mode import CodeExecutor, ExecutionResult, ToolRegistry


class TestExecutorInterface:
    """Tests that define the executor interface."""

    @pytest.fixture
    def executor(self) -> CodeExecutor:
        """Basic executor without tools."""
        return CodeExecutor()

    @pytest.mark.asyncio
    async def test_execute_simple_expression(self, executor: CodeExecutor) -> None:
        """Executor returns result of expression."""
        result = await executor.execute("1 + 1")

        assert result.value == 2
        assert result.error is None

    @pytest.mark.asyncio
    async def test_execute_returns_last_expression(self, executor: CodeExecutor) -> None:
        """Multiple statements - returns last expression value."""
        result = await executor.execute("""
x = 10
y = 20
x + y
""")
        assert result.value == 30

    @pytest.mark.asyncio
    async def test_execute_captures_stdout(self, executor: CodeExecutor) -> None:
        """Print statements captured in output."""
        result = await executor.execute('print("hello world")')

        assert "hello world" in result.stdout
        assert result.value is None  # print returns None

    @pytest.mark.asyncio
    async def test_execute_error_captured(self, executor: CodeExecutor) -> None:
        """Errors captured, not raised."""
        result = await executor.execute("1 / 0")

        assert result.error is not None
        assert "ZeroDivisionError" in result.error
        assert result.value is None


class TestExecutorStatefulness:
    """Tests for kernel state persistence."""

    @pytest.fixture
    def executor(self) -> CodeExecutor:
        return CodeExecutor()

    @pytest.mark.asyncio
    async def test_variables_persist_across_executions(self, executor: CodeExecutor) -> None:
        """Variables defined in one execution available in next."""
        await executor.execute("x = 42")
        result = await executor.execute("x * 2")

        assert result.value == 84

    @pytest.mark.asyncio
    async def test_functions_persist(self, executor: CodeExecutor) -> None:
        """Functions defined persist across executions."""
        await executor.execute("""
def greet(name):
    return f"Hello, {name}!"
""")
        result = await executor.execute('greet("Alice")')

        assert result.value == "Hello, Alice!"

    @pytest.mark.asyncio
    async def test_imports_persist(self, executor: CodeExecutor) -> None:
        """Imported modules persist."""
        await executor.execute("import json")
        result = await executor.execute('json.dumps({"a": 1})')

        assert result.value == '{"a": 1}'

    @pytest.mark.asyncio
    async def test_state_isolated_between_executors(self) -> None:
        """Different executor instances have separate state."""
        exec1 = CodeExecutor()
        exec2 = CodeExecutor()

        await exec1.execute("shared_var = 'exec1'")
        await exec2.execute("shared_var = 'exec2'")

        result1 = await exec1.execute("shared_var")
        result2 = await exec2.execute("shared_var")

        assert result1.value == "exec1"
        assert result2.value == "exec2"


class TestExecutorToolInjection:
    """Tests for tools.* namespace injection."""

    @pytest.fixture
    async def executor_with_tools(self) -> CodeExecutor:
        """Executor with a mock tool registry."""
        from tests.conftest import MockAdapter

        registry = ToolRegistry()
        adapter = MockAdapter(
            tools=["echo", "add"],
            call_results={"echo": "echoed!", "add": 42},
        )
        await registry.register_adapter(adapter)

        return CodeExecutor(registry=registry)

    @pytest.mark.asyncio
    async def test_tools_namespace_available(self, executor_with_tools: CodeExecutor) -> None:
        """tools.* namespace injected into execution context."""
        result = await executor_with_tools.execute("'tools' in dir()")

        assert result.value is True

    @pytest.mark.asyncio
    async def test_call_tool_via_namespace(self, executor_with_tools: CodeExecutor) -> None:
        """Can call tools through namespace."""
        result = await executor_with_tools.execute('tools.call("echo", {})')

        assert result.value == "echoed!"

    @pytest.mark.asyncio
    async def test_tool_search_available(self, executor_with_tools: CodeExecutor) -> None:
        """tools.search() available in namespace."""
        result = await executor_with_tools.execute('len(tools.search("echo"))')

        assert result.value >= 1

    @pytest.mark.asyncio
    async def test_tool_list_available(self, executor_with_tools: CodeExecutor) -> None:
        """tools.list() available to enumerate tools."""
        result = await executor_with_tools.execute("len(tools.list())")

        assert result.value == 2  # echo and add


class TestExecutorTimeout:
    """Tests for execution timeout."""

    @pytest.fixture
    def executor(self) -> CodeExecutor:
        return CodeExecutor(default_timeout=0.5)

    @pytest.mark.asyncio
    async def test_timeout_stops_execution(self, executor: CodeExecutor) -> None:
        """Long-running code times out."""
        result = await executor.execute("""
import time
time.sleep(10)
""")
        assert result.error is not None
        assert "timeout" in result.error.lower()

    @pytest.mark.asyncio
    async def test_timeout_per_execution(self, executor: CodeExecutor) -> None:
        """Timeout can be overridden per execution."""
        # Default timeout is 0.5s, but we override to 0.1s
        result = await executor.execute(
            "import time; time.sleep(5)",
            timeout=0.1,
        )

        assert result.error is not None


class TestExecutorCleanup:
    """Tests for resource cleanup."""

    @pytest.mark.asyncio
    async def test_close_releases_resources(self) -> None:
        """Closing executor releases kernel resources."""
        executor = CodeExecutor()
        await executor.execute("x = 1")
        await executor.close()

        # After close, executor should not be usable
        # (implementation decides exact behavior - error or reinit)

    @pytest.mark.asyncio
    async def test_context_manager(self) -> None:
        """Executor can be used as async context manager."""
        async with CodeExecutor() as executor:
            result = await executor.execute("1 + 1")
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
    def executor_with_artifacts(self, tmp_path) -> CodeExecutor:
        """Executor with artifacts directory."""
        from py_code_mode.artifacts import FileArtifactStore

        store = FileArtifactStore(tmp_path)
        return CodeExecutor(artifact_store=store)

    @pytest.mark.asyncio
    async def test_artifacts_namespace_available(self, executor_with_artifacts) -> None:
        """artifacts.* namespace injected into execution context."""
        result = await executor_with_artifacts.execute("'artifacts' in dir()")

        assert result.value is True

    @pytest.mark.asyncio
    async def test_artifacts_save(self, executor_with_artifacts, tmp_path) -> None:
        """Can save artifacts from executed code."""
        result = await executor_with_artifacts.execute("""
artifacts.save("test.json", {"key": "value"}, description="Test data")
""")

        assert result.is_ok
        assert (tmp_path / "test.json").exists()

    @pytest.mark.asyncio
    async def test_artifacts_load(self, executor_with_artifacts) -> None:
        """Can load artifacts from executed code."""
        # First save
        await executor_with_artifacts.execute("""
artifacts.save("data.json", {"x": 42}, description="Data")
""")

        # Then load
        result = await executor_with_artifacts.execute("""
data = artifacts.load("data.json")
data["x"]
""")

        assert result.value == 42

    @pytest.mark.asyncio
    async def test_artifacts_list(self, executor_with_artifacts) -> None:
        """Can list artifacts from executed code."""
        await executor_with_artifacts.execute("""
artifacts.save("a.json", {}, description="First")
artifacts.save("b.json", {}, description="Second")
""")

        result = await executor_with_artifacts.execute("len(artifacts.list())")

        assert result.value == 2

    @pytest.mark.asyncio
    async def test_artifacts_path_for_raw_access(self, executor_with_artifacts) -> None:
        """artifacts.path available as string for raw file I/O."""
        result = await executor_with_artifacts.execute("""
isinstance(artifacts.path, str)
""")

        assert result.value is True

    @pytest.mark.asyncio
    async def test_artifacts_raw_file_io(self, executor_with_artifacts, tmp_path) -> None:
        """Can use standard file I/O with Path(artifacts.path)."""
        result = await executor_with_artifacts.execute("""
from pathlib import Path
p = Path(artifacts.path)
with open(p / "raw.txt", "w") as f:
    f.write("raw content")
(p / "raw.txt").read_text()
""")

        assert result.value == "raw content"
        assert (tmp_path / "raw.txt").exists()


class TestExecutorCreate:
    """Tests for CodeExecutor.create() factory method."""

    @pytest.mark.asyncio
    async def test_create_with_tools_directory(self, tmp_path) -> None:
        """create() loads tools from directory."""
        # Create tool YAML file
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        (tools_dir / "echo.yaml").write_text("""
name: echo
type: cli
command: echo
args: "{text}"
description: Echo text
""")

        executor = await CodeExecutor.create(tools=str(tools_dir))

        # Tool should be available
        result = await executor.run("tools.list()")
        assert result.value is not None
        assert any("echo" in str(t) for t in result.value)

    @pytest.mark.asyncio
    async def test_create_with_skills_directory(self, tmp_path) -> None:
        """create() loads skills from directory."""
        # Create skill file
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "greet.py").write_text('''
"""Greet someone."""

def run(name: str = "World") -> str:
    return f"Hello, {name}!"
''')

        executor = await CodeExecutor.create(skills=str(skills_dir))

        # Skill should be available
        result = await executor.run("skills.list()")
        assert result.value is not None
        assert any("greet" in str(s) for s in result.value)

    @pytest.mark.asyncio
    async def test_create_with_artifacts_directory(self, tmp_path) -> None:
        """create() sets up artifact storage."""
        artifacts_dir = tmp_path / "artifacts"

        executor = await CodeExecutor.create(artifacts=str(artifacts_dir))

        result = await executor.run("""
artifacts.save("test.txt", "hello", description="test")
artifacts.load("test.txt")
""")
        assert result.value == "hello"
        assert artifacts_dir.exists()

    @pytest.mark.asyncio
    async def test_create_with_all_options(self, tmp_path) -> None:
        """create() with tools, skills, and artifacts."""
        tools_dir = tmp_path / "tools"
        skills_dir = tmp_path / "skills"
        artifacts_dir = tmp_path / "artifacts"

        tools_dir.mkdir()
        skills_dir.mkdir()

        (tools_dir / "echo.yaml").write_text("""
name: echo
type: cli
command: echo
args: "{text}"
""")

        (skills_dir / "hello.py").write_text("""
def run() -> str:
    return "hello"
""")

        executor = await CodeExecutor.create(
            tools=str(tools_dir),
            skills=str(skills_dir),
            artifacts=str(artifacts_dir),
        )

        # All should work
        assert executor._registry is not None
        assert executor._skill_library is not None
        assert executor._artifact_store is not None

    @pytest.mark.asyncio
    async def test_create_with_nonexistent_directory(self) -> None:
        """create() handles missing directories gracefully."""
        executor = await CodeExecutor.create(
            tools="/nonexistent/tools",
            skills="/nonexistent/skills",
        )

        # Should still create executor, just with empty registries
        assert executor is not None


class TestSkillsNamespaceAttributeAccess:
    """Tests for skills.skill_name() attribute access syntax."""

    @pytest.mark.asyncio
    async def test_skill_callable_via_attribute(self, tmp_path) -> None:
        """skills.skill_name() works as alias for skills.invoke('skill_name')."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "greet.py").write_text('''
"""Greet someone."""

def run(person: str = "World") -> str:
    return f"Hello, {person}!"
''')

        executor = await CodeExecutor.create(skills=str(skills_dir))

        # Both styles should work
        result1 = await executor.run("skills.invoke('greet', person='Alice')")
        result2 = await executor.run("skills.greet(person='Bob')")

        assert result1.value == "Hello, Alice!"
        assert result2.value == "Hello, Bob!"

    @pytest.mark.asyncio
    async def test_skill_attribute_raises_for_missing(self, tmp_path) -> None:
        """skills.nonexistent raises AttributeError."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        # Need at least one skill so skills namespace is injected
        (skills_dir / "dummy.py").write_text('''
"""Dummy skill."""

def run() -> str:
    return "dummy"
''')

        executor = await CodeExecutor.create(skills=str(skills_dir))

        result = await executor.run("skills.nonexistent()")

        assert result.error is not None
        assert "AttributeError" in result.error or "not found" in result.error.lower()


class TestSkillsNamespaceCreate:
    """Tests for skills.create() - agent skill creation."""

    # --- Validation tests ---

    @pytest.mark.asyncio
    async def test_create_rejects_invalid_identifier(self, tmp_path) -> None:
        """Skill name must be valid Python identifier."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        executor = await CodeExecutor.create(skills=str(skills_dir))

        result = await executor.run("""
skills.create(
    name="my-skill",
    code="def run(): return 1"
)
""")

        assert result.error is not None
        assert "invalid" in result.error.lower() or "identifier" in result.error.lower()

    @pytest.mark.asyncio
    async def test_create_rejects_reserved_name(self, tmp_path) -> None:
        """Cannot create skill with reserved name."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        executor = await CodeExecutor.create(skills=str(skills_dir))

        result = await executor.run("""
skills.create(
    name="list",
    code="def run(): return 1"
)
""")

        assert result.error is not None
        assert "reserved" in result.error.lower()

    @pytest.mark.asyncio
    async def test_create_rejects_syntax_error(self, tmp_path) -> None:
        """Skill code must be valid Python."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        executor = await CodeExecutor.create(skills=str(skills_dir))

        result = await executor.run("""
skills.create(
    name="bad_syntax",
    code="def run( return 1"
)
""")

        assert result.error is not None
        assert "syntax" in result.error.lower()

    @pytest.mark.asyncio
    async def test_create_rejects_missing_run(self, tmp_path) -> None:
        """Skill must define run() function."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        executor = await CodeExecutor.create(skills=str(skills_dir))

        result = await executor.run("""
skills.create(
    name="no_run",
    code="def helper(): return 1"
)
""")

        assert result.error is not None
        assert "run" in result.error.lower()

    @pytest.mark.asyncio
    async def test_create_rejects_run_not_callable(self, tmp_path) -> None:
        """run must be a callable function."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        executor = await CodeExecutor.create(skills=str(skills_dir))

        result = await executor.run("""
skills.create(
    name="not_callable",
    code="run = 'not a function'"
)
""")

        assert result.error is not None
        assert "callable" in result.error.lower() or "function" in result.error.lower()

    # --- Happy path tests ---

    @pytest.mark.asyncio
    async def test_create_skill_from_code(self, tmp_path) -> None:
        """Can create skill from code string and invoke it."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        executor = await CodeExecutor.create(skills=str(skills_dir))

        # Create skill
        result = await executor.run('''
skills.create(
    name="greet",
    description="Greet someone",
    code="""
def run(name: str = "World") -> str:
    return f"Hello, {name}!"
"""
)
''')

        assert result.is_ok, f"Create failed: {result.error}"

        # Invoke via attribute
        result = await executor.run('skills.greet(name="Alice")')
        assert result.value == "Hello, Alice!"

    @pytest.mark.asyncio
    async def test_created_skill_has_metadata(self, tmp_path) -> None:
        """Created skill includes metadata."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        executor = await CodeExecutor.create(skills=str(skills_dir))

        result = await executor.run("""
info = skills.create(
    name="with_meta",
    code="def run(): return 1"
)
info
""")

        assert result.is_ok
        assert result.value is not None
        # Should return skill info dict
        assert "name" in result.value
        assert result.value["name"] == "with_meta"

    @pytest.mark.asyncio
    async def test_create_skill_persists_to_file(self, tmp_path) -> None:
        """Created skill is written to file system."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        executor = await CodeExecutor.create(skills=str(skills_dir))

        await executor.run("""
skills.create(
    name="persisted",
    code="def run(): return 42"
)
""")

        # File should exist
        skill_file = skills_dir / "persisted.py"
        assert skill_file.exists(), f"Skill file not created at {skill_file}"

        # Content should have run function
        content = skill_file.read_text()
        assert "def run()" in content


class TestSkillsNamespaceDelete:
    """Tests for skills.delete() - skill removal."""

    @pytest.mark.asyncio
    async def test_delete_skill(self, tmp_path) -> None:
        """Can delete a skill from registry."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        executor = await CodeExecutor.create(skills=str(skills_dir))

        # Create then delete
        await executor.run("""
skills.create(name="to_delete", code="def run(): return 1")
""")
        result = await executor.run('skills.delete("to_delete")')

        assert result.is_ok
        assert result.value is True

        # Should no longer be accessible
        result = await executor.run("skills.to_delete()")
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_delete_removes_file(self, tmp_path) -> None:
        """Delete removes the skill file."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        executor = await CodeExecutor.create(skills=str(skills_dir))

        await executor.run("""
skills.create(name="file_delete", code="def run(): return 1")
""")

        skill_file = skills_dir / "file_delete.py"
        assert skill_file.exists()

        await executor.run('skills.delete("file_delete")')
        assert not skill_file.exists()

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_false(self, tmp_path) -> None:
        """Deleting nonexistent skill returns False."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        executor = await CodeExecutor.create(skills=str(skills_dir))

        result = await executor.run('skills.delete("nonexistent")')

        assert result.is_ok
        assert result.value is False
