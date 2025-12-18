"""Tests for error types."""

import pytest

from py_code_mode import (
    ArtifactNotFoundError,
    ArtifactWriteError,
    CodeModeError,
    DependencyError,
    SkillExecutionError,
    SkillNotFoundError,
    SkillValidationError,
    ToolCallError,
    ToolNotFoundError,
    ToolTimeoutError,
)


class TestErrorHierarchy:
    """Test that all errors inherit from CodeModeError."""

    def test_tool_not_found_inheritance(self) -> None:
        err = ToolNotFoundError("test_tool")
        assert isinstance(err, CodeModeError)
        assert isinstance(err, Exception)

    def test_tool_call_error_inheritance(self) -> None:
        err = ToolCallError("test_tool", {"arg": "val"}, ValueError("inner"))
        assert isinstance(err, CodeModeError)

    def test_tool_timeout_error_inheritance(self) -> None:
        err = ToolTimeoutError("test_tool", 30.0)
        assert isinstance(err, CodeModeError)

    def test_artifact_errors_inheritance(self) -> None:
        assert isinstance(ArtifactNotFoundError("test"), CodeModeError)
        assert isinstance(ArtifactWriteError("test", "reason"), CodeModeError)

    def test_skill_errors_inheritance(self) -> None:
        assert isinstance(SkillNotFoundError("test"), CodeModeError)
        assert isinstance(SkillValidationError("test", "reason"), CodeModeError)
        assert isinstance(SkillExecutionError("test", ValueError("x")), CodeModeError)

    def test_dependency_error_inheritance(self) -> None:
        assert isinstance(DependencyError("numpy"), CodeModeError)


class TestToolNotFoundError:
    """Tests for ToolNotFoundError."""

    def test_basic_message(self) -> None:
        err = ToolNotFoundError("unknown_tool")
        assert "unknown_tool" in str(err)
        assert err.tool_name == "unknown_tool"
        assert err.available_tools == []

    def test_with_available_tools(self) -> None:
        err = ToolNotFoundError("unknown", ["tool1", "tool2", "tool3"])
        assert "unknown" in str(err)
        assert "tool1" in str(err)
        assert err.available_tools == ["tool1", "tool2", "tool3"]

    def test_truncates_long_list(self) -> None:
        tools = [f"tool{i}" for i in range(10)]
        err = ToolNotFoundError("unknown", tools)
        msg = str(err)
        assert "tool0" in msg
        assert "tool4" in msg
        assert "and 5 more" in msg


class TestToolCallError:
    """Tests for ToolCallError."""

    def test_attributes(self) -> None:
        cause = ValueError("bad input")
        err = ToolCallError("my_tool", {"x": 1, "y": 2}, cause)

        assert err.tool_name == "my_tool"
        assert err.tool_args == {"x": 1, "y": 2}
        assert err.cause is cause
        assert "my_tool" in str(err)
        assert "bad input" in str(err)


class TestToolTimeoutError:
    """Tests for ToolTimeoutError."""

    def test_attributes(self) -> None:
        err = ToolTimeoutError("slow_tool", 45.5)

        assert err.tool_name == "slow_tool"
        assert err.timeout_seconds == 45.5
        assert "slow_tool" in str(err)
        assert "45.5" in str(err)


class TestArtifactErrors:
    """Tests for artifact-related errors."""

    def test_not_found(self) -> None:
        err = ArtifactNotFoundError("data.json")
        assert err.artifact_name == "data.json"
        assert "data.json" in str(err)

    def test_write_error(self) -> None:
        err = ArtifactWriteError("output.csv", "disk full")
        assert err.artifact_name == "output.csv"
        assert err.reason == "disk full"
        assert "output.csv" in str(err)
        assert "disk full" in str(err)


class TestSkillErrors:
    """Tests for skill-related errors."""

    def test_not_found(self) -> None:
        err = SkillNotFoundError("web_enum")
        assert err.skill_name == "web_enum"
        assert "web_enum" in str(err)

    def test_validation_error(self) -> None:
        err = SkillValidationError("bad_skill", "missing required field 'code'")
        assert err.skill_name == "bad_skill"
        assert err.reason == "missing required field 'code'"
        assert "bad_skill" in str(err)

    def test_execution_error(self) -> None:
        cause = RuntimeError("division by zero")
        err = SkillExecutionError("buggy_skill", cause)
        assert err.skill_name == "buggy_skill"
        assert err.cause is cause
        assert "buggy_skill" in str(err)


class TestDependencyError:
    """Tests for DependencyError."""

    def test_basic(self) -> None:
        err = DependencyError("numpy")
        assert err.package == "numpy"
        assert err.required_by is None
        assert "numpy" in str(err)

    def test_with_required_by(self) -> None:
        err = DependencyError("python-nmap", required_by="nmap tool")
        assert err.package == "python-nmap"
        assert err.required_by == "nmap tool"
        assert "python-nmap" in str(err)
        assert "nmap tool" in str(err)


class TestCatchingAllErrors:
    """Test that CodeModeError catches all library errors."""

    def test_catch_all(self) -> None:
        errors = [
            ToolNotFoundError("x"),
            ToolCallError("x", {}, ValueError()),
            ToolTimeoutError("x", 1.0),
            ArtifactNotFoundError("x"),
            ArtifactWriteError("x", "y"),
            SkillNotFoundError("x"),
            SkillValidationError("x", "y"),
            SkillExecutionError("x", ValueError()),
            DependencyError("x"),
        ]

        for err in errors:
            try:
                raise err
            except CodeModeError:
                pass  # Expected
            except Exception:
                pytest.fail(f"{type(err).__name__} not caught by CodeModeError")
