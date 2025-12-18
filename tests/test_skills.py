"""Tests for skills system - Python skills only."""

import pytest
from pathlib import Path
from textwrap import dedent

from py_code_mode.skills import SkillParameter, PythonSkill


class TestSkillParameter:
    """Tests for SkillParameter dataclass."""

    def test_parameter_with_required(self) -> None:
        """Parameter can be marked required."""
        param = SkillParameter(
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
        param = SkillParameter(
            name="count",
            type="integer",
            description="Number of times",
            required=False,
            default=5,
        )

        assert param.default == 5
        assert param.required is False


class TestPythonSkill:
    """Tests for .py skill format - full Python files with run() entrypoint."""

    @pytest.fixture
    def skill_file(self, tmp_path: Path) -> Path:
        """Create a sample .py skill file."""
        skill_path = tmp_path / "greet.py"
        skill_path.write_text(dedent('''
            """Greet someone by name.

            A friendly greeting skill.
            """

            def run(target_name: str, enthusiasm: int = 1) -> str:
                """Generate a greeting.

                Args:
                    target_name: The person to greet
                    enthusiasm: Number of exclamation marks

                Returns:
                    A greeting string
                """
                return f"Hello, {target_name}!" + "!" * (enthusiasm - 1)
        ''').strip())
        return skill_path

    def test_load_from_file(self, skill_file: Path) -> None:
        """Load a Python skill from file."""
        skill = PythonSkill.from_file(skill_file)

        assert skill.name == "greet"
        assert "Greet someone" in skill.description

    def test_extracts_parameters_from_signature(self, skill_file: Path) -> None:
        """Parameters extracted from function signature."""
        skill = PythonSkill.from_file(skill_file)

        assert len(skill.parameters) == 2

        # First param: target_name (required, no default)
        assert skill.parameters[0].name == "target_name"
        assert skill.parameters[0].type == "string"
        assert skill.parameters[0].required is True

        # Second param: enthusiasm (optional, has default)
        assert skill.parameters[1].name == "enthusiasm"
        assert skill.parameters[1].type == "integer"
        assert skill.parameters[1].required is False
        assert skill.parameters[1].default == 1

    def test_has_source_property(self, skill_file: Path) -> None:
        """Skill exposes source code for agent inspection."""
        skill = PythonSkill.from_file(skill_file)

        assert skill.source is not None
        assert "def run(" in skill.source
        assert "Hello, {target_name}" in skill.source

    def test_invoke_calls_function(self, skill_file: Path) -> None:
        """Invoking skill calls the run() function."""
        skill = PythonSkill.from_file(skill_file)

        result = skill.invoke(target_name="Alice")

        assert result == "Hello, Alice!"

    def test_invoke_with_defaults(self, skill_file: Path) -> None:
        """Invoke uses default parameter values."""
        skill = PythonSkill.from_file(skill_file)

        result = skill.invoke(target_name="Bob", enthusiasm=3)

        assert result == "Hello, Bob!!!"

    def test_invoke_validates_required_params(self, skill_file: Path) -> None:
        """Invoke fails if required params missing."""
        skill = PythonSkill.from_file(skill_file)

        with pytest.raises(TypeError):
            skill.invoke()  # Missing target_name

    def test_skill_with_tools_access(self, tmp_path: Path) -> None:
        """Skill can reference tools in its code."""
        skill_path = tmp_path / "scan.py"
        skill_path.write_text(dedent('''
            """Scan a network target."""

            def run(target: str, tools) -> str:
                """Run a scan using tools.

                Args:
                    target: Target to scan
                    tools: Tools namespace (injected)
                """
                # In real use, would call tools.call(...)
                return f"Scanning {target}"
        ''').strip())

        skill = PythonSkill.from_file(skill_path)

        # tools parameter should be recognized as special, not a user param
        user_params = [p for p in skill.parameters if p.name != "tools"]
        assert len(user_params) == 1
        assert user_params[0].name == "target"


class TestPythonSkillFromSource:
    """Tests for creating Python skills from source code."""

    def test_from_source_basic(self) -> None:
        """Create skill from source string."""
        source = dedent('''
            """Add two numbers."""

            def run(a: int, b: int) -> int:
                return a + b
        ''').strip()

        skill = PythonSkill.from_source(name="add", source=source)

        assert skill.name == "add"
        assert skill.description == "Add two numbers."
        assert len(skill.parameters) == 2

    def test_from_source_with_description_override(self) -> None:
        """Description parameter overrides docstring."""
        source = dedent('''
            """Original description."""
            def run() -> str:
                return "hello"
        ''').strip()

        skill = PythonSkill.from_source(
            name="test",
            source=source,
            description="Custom description",
        )

        assert skill.description == "Custom description"

    def test_from_source_validates_syntax(self) -> None:
        """Invalid syntax raises SyntaxError."""
        with pytest.raises(SyntaxError):
            PythonSkill.from_source(name="bad", source="def run( broken")

    def test_from_source_requires_run_function(self) -> None:
        """Must have run() function."""
        source = dedent('''
            """No run function."""
            def other_func():
                pass
        ''').strip()

        with pytest.raises(ValueError, match="run"):
            PythonSkill.from_source(name="no_run", source=source)

    def test_from_source_validates_name(self) -> None:
        """Name must be valid Python identifier."""
        source = 'def run(): pass'

        with pytest.raises(ValueError, match="identifier"):
            PythonSkill.from_source(name="invalid-name", source=source)

    def test_invoke_from_source_skill(self) -> None:
        """Can invoke skill created from source."""
        source = dedent('''
            """Multiply numbers."""
            def run(x: int, y: int) -> int:
                return x * y
        ''').strip()

        skill = PythonSkill.from_source(name="multiply", source=source)
        result = skill.invoke(x=3, y=4)

        assert result == 12
