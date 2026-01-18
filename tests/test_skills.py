"""Tests for workflows system - Python workflows only."""

from pathlib import Path
from textwrap import dedent

import pytest

from py_code_mode.workflows import PythonWorkflow, WorkflowParameter


class TestWorkflowParameter:
    """Tests for WorkflowParameter dataclass."""

    def test_parameter_with_required(self) -> None:
        """Parameter can be marked required."""
        param = WorkflowParameter(
            name="target",
            type="string",
            description="Target to process",
            required=True,
        )

        assert param.name == "target"
        assert param.type == "string"
        assert param.required is True

    def test_parameter_with_default(self) -> None:
        """Parameters can have default values."""
        param = WorkflowParameter(
            name="count",
            type="integer",
            description="Number of times",
            required=False,
            default=5,
        )

        assert param.default == 5
        assert param.required is False


class TestPythonWorkflow:
    """Tests for .py workflow format - full Python files with run() entrypoint."""

    @pytest.fixture
    def workflow_file(self, tmp_path: Path) -> Path:
        """Create a sample .py workflow file."""
        workflow_path = tmp_path / "greet.py"
        workflow_path.write_text(
            dedent('''
            """Greet someone by name.

            A friendly greeting workflow.
            """

            async def run(target_name: str, enthusiasm: int = 1) -> str:
                """Generate a greeting.

                Args:
                    target_name: The person to greet
                    enthusiasm: Number of exclamation marks

                Returns:
                    A greeting string
                """
                return f"Hello, {target_name}!" + "!" * (enthusiasm - 1)
        ''').strip()
        )
        return workflow_path

    def test_load_from_file(self, workflow_file: Path) -> None:
        """Load a Python workflow from file."""
        workflow = PythonWorkflow.from_file(workflow_file)

        assert workflow.name == "greet"
        assert "Greet someone" in workflow.description

    def test_extracts_parameters_from_signature(self, workflow_file: Path) -> None:
        """Parameters extracted from function signature."""
        workflow = PythonWorkflow.from_file(workflow_file)

        assert len(workflow.parameters) == 2

        # First param: target_name (required, no default)
        assert workflow.parameters[0].name == "target_name"
        assert workflow.parameters[0].type == "string"
        assert workflow.parameters[0].required is True

        # Second param: enthusiasm (optional, has default)
        assert workflow.parameters[1].name == "enthusiasm"
        assert workflow.parameters[1].type == "integer"
        assert workflow.parameters[1].required is False
        assert workflow.parameters[1].default == 1

    def test_has_source_property(self, workflow_file: Path) -> None:
        """Workflow exposes source code for agent inspection."""
        workflow = PythonWorkflow.from_file(workflow_file)

        assert workflow.source is not None
        assert "async def run(" in workflow.source
        assert "Hello, {target_name}" in workflow.source

    @pytest.mark.asyncio
    async def test_invoke_calls_function(self, workflow_file: Path) -> None:
        """Invoking workflow calls the run() function."""
        workflow = PythonWorkflow.from_file(workflow_file)

        result = await workflow.invoke(target_name="Alice")

        assert result == "Hello, Alice!"

    @pytest.mark.asyncio
    async def test_invoke_with_defaults(self, workflow_file: Path) -> None:
        """Invoke uses default parameter values."""
        workflow = PythonWorkflow.from_file(workflow_file)

        result = await workflow.invoke(target_name="Bob", enthusiasm=3)

        assert result == "Hello, Bob!!!"

    @pytest.mark.asyncio
    async def test_invoke_validates_required_params(self, workflow_file: Path) -> None:
        """Invoke fails if required params missing."""
        workflow = PythonWorkflow.from_file(workflow_file)

        with pytest.raises(TypeError):
            await workflow.invoke()

    def test_workflow_with_tools_access(self, tmp_path: Path) -> None:
        """Workflow can reference tools in its code."""
        workflow_path = tmp_path / "scan.py"
        workflow_path.write_text(
            dedent('''
            """Scan a network target."""

            async def run(target: str) -> str:
                """Run a scan using tools."""
                # In real use, would call tools.call(...)
                _ = tools  # namespace is available as a global
                return f"Scanning {target}"
        ''').strip()
        )

        workflow = PythonWorkflow.from_file(workflow_path)

        assert [p.name for p in workflow.parameters] == ["target"]


class TestPythonWorkflowNamespaceParamValidation:
    def test_from_source_rejects_namespace_params(self) -> None:
        """run() must not accept tools/workflows/artifacts/deps as parameters."""
        source = dedent("""
            async def run(x: int, tools) -> int:
                return x
        """).strip()

        with pytest.raises(ValueError, match=r"must not declare parameter 'tools'"):
            PythonWorkflow.from_source(name="bad", source=source)


class TestPythonWorkflowFromSource:
    """Tests for creating Python workflows from source code."""

    def test_from_source_basic(self) -> None:
        """Create workflow from source string."""
        source = dedent('''
            """Add two numbers."""

            async def run(a: int, b: int) -> int:
                return a + b
        ''').strip()

        workflow = PythonWorkflow.from_source(name="add", source=source)

        assert workflow.name == "add"
        assert workflow.description == "Add two numbers."
        assert len(workflow.parameters) == 2

    def test_from_source_with_description_override(self) -> None:
        """Description parameter overrides docstring."""
        source = dedent('''
            """Original description."""
            async def run() -> str:
                return "hello"
        ''').strip()

        workflow = PythonWorkflow.from_source(
            name="test",
            source=source,
            description="Custom description",
        )

        assert workflow.description == "Custom description"

    def test_from_source_validates_syntax(self) -> None:
        """Invalid syntax raises SyntaxError."""
        with pytest.raises(SyntaxError):
            PythonWorkflow.from_source(name="bad", source="async def run( broken")

    def test_from_source_requires_run_function(self) -> None:
        """Must have run() function."""
        source = dedent('''
            """No run function."""
            def other_func():
                pass
        ''').strip()

        with pytest.raises(ValueError, match="run"):
            PythonWorkflow.from_source(name="no_run", source=source)

    def test_from_source_validates_name(self) -> None:
        """Name must be valid Python identifier."""
        source = "async def run(): pass"

        with pytest.raises(ValueError, match="identifier"):
            PythonWorkflow.from_source(name="invalid-name", source=source)

    @pytest.mark.asyncio
    async def test_invoke_from_source_workflow(self) -> None:
        """Can invoke workflow created from source."""
        source = dedent('''
            """Multiply numbers."""
            async def run(x: int, y: int) -> int:
                return x * y
        ''').strip()

        workflow = PythonWorkflow.from_source(name="multiply", source=source)
        result = await workflow.invoke(x=3, y=4)

        assert result == 12
