"""Test for escape hatch parameter passing (regression test for parameter bug)."""

import tempfile
from pathlib import Path

import pytest

from py_code_mode.adapters.cli import CLIAdapter


class TestEscapeHatchParameterPassing:
    """Test that escape hatch (tools.X(...)) properly passes parameters to commands."""

    @pytest.mark.asyncio
    async def test_escape_hatch_with_schema_format(self) -> None:
        """Schema + recipes format works with escape hatch."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tool_path = Path(tmpdir)
            echo_yaml = tool_path / "echo.yaml"

            # Schema + recipes format
            echo_yaml.write_text("""
name: echo
description: Echo text
command: echo
timeout: 5

schema:
  positional:
    - name: text
      type: string
      required: true
      description: Text to echo

recipes:
  echo:
    description: Echo text to stdout
    params:
      text:
        type: string
        required: true
        description: Text to echo
""")

            adapter = CLIAdapter(tools_path=tool_path)

            # Mock subprocess
            captured_cmd = None

            async def mock_run(cmd, timeout, cwd=None, env=None):
                nonlocal captured_cmd
                captured_cmd = cmd
                return "hello world"

            adapter._run_subprocess = mock_run

            # Escape hatch call (callable_name=None)
            result = await adapter.call_tool("echo", None, {"text": "hello world"})

            assert captured_cmd == ["echo", "hello world"]
            assert result == "hello world"

    @pytest.mark.asyncio
    async def test_escape_hatch_with_schema_and_options(self) -> None:
        """Schema with options and positionals works correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tool_path = Path(tmpdir)
            tool_yaml = tool_path / "grep.yaml"

            tool_yaml.write_text("""
name: grep
description: Search for patterns
command: grep
timeout: 5

schema:
  options:
    i: {type: boolean, short: i, description: Case insensitive}
    n: {type: boolean, short: n, description: Line numbers}
  positional:
    - name: pattern
      type: string
      required: true
    - name: file
      type: string
      required: true

recipes:
  grep:
    description: Search files
    params:
      pattern: {type: string, required: true}
      file: {type: string, required: true}
      i: {type: boolean, required: false}
      n: {type: boolean, required: false}
""")

            adapter = CLIAdapter(tools_path=tool_path)

            captured_cmd = None

            async def mock_run(cmd, timeout, cwd=None, env=None):
                nonlocal captured_cmd
                captured_cmd = cmd
                return "match"

            adapter._run_subprocess = mock_run

            await adapter.call_tool(
                "grep", None, {"pattern": "error", "file": "log.txt", "i": True}
            )

            # Options come before positionals
            assert "grep" in captured_cmd
            assert "-i" in captured_cmd
            assert "error" in captured_cmd
            assert "log.txt" in captured_cmd
            # Verify positionals come after options
            assert captured_cmd.index("error") > captured_cmd.index("-i")

    @pytest.mark.asyncio
    async def test_escape_hatch_with_multiple_positional_args(self) -> None:
        """Multiple positional arguments are passed in correct order."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tool_path = Path(tmpdir)
            tool_yaml = tool_path / "cp.yaml"

            # New format with multiple positionals
            tool_yaml.write_text("""
name: cp
description: Copy files
command: cp
timeout: 5

schema:
  positional:
    - name: source
      type: string
      required: true
      description: Source file
    - name: dest
      type: string
      required: true
      description: Destination file
    - name: extra
      type: string
      required: false
      description: Extra argument

recipes:
  copy:
    description: Copy a file
    params:
      source: {type: string, required: true}
      dest: {type: string, required: true}
""")

            adapter = CLIAdapter(tools_path=tool_path)

            captured_cmd = None

            async def mock_run(cmd, timeout, cwd=None, env=None):
                nonlocal captured_cmd
                captured_cmd = cmd
                return "ok"

            adapter._run_subprocess = mock_run

            await adapter.call_tool("cp", None, {"source": "a.txt", "dest": "b.txt"})

            assert captured_cmd == ["cp", "a.txt", "b.txt"]
