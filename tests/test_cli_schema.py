"""Tests for CLI schema parsing and command building."""

from pathlib import Path

import pytest
import yaml

from py_code_mode.adapters.cli_schema import (
    CLICommandBuilder,
    CLIToolDefinition,
    parse_cli_tool_yaml,
)


class TestParseCliToolYaml:
    """Tests for parsing CLI tool YAML files."""

    def test_parse_simple_tool(self, simple_tool_yaml: Path) -> None:
        """Parse a simple tool without subcommands."""
        tool_def = parse_cli_tool_yaml(simple_tool_yaml)

        assert tool_def.name == "ping"
        assert tool_def.description == "ICMP ping"
        assert tool_def.command == "ping"
        assert tool_def.timeout == 10

    def test_parse_complex_tool_with_recipes(self, nmap_yaml: Path) -> None:
        """Parse a complex tool with multiple recipes."""
        tool_def = parse_cli_tool_yaml(nmap_yaml)

        assert tool_def.name == "nmap"
        assert tool_def.description == "Network scanner"
        assert tool_def.command == "nmap"
        assert tool_def.timeout == 300

        # Should have recipes
        assert "syn_scan" in tool_def.recipes
        assert "quick" in tool_def.recipes

    def test_parse_schema_options(self, nmap_yaml: Path) -> None:
        """Parse schema options correctly."""
        tool_def = parse_cli_tool_yaml(nmap_yaml)

        schema = tool_def.schema
        assert "sS" in schema["options"]
        assert schema["options"]["sS"]["type"] == "boolean"
        assert "p" in schema["options"]
        assert schema["options"]["p"]["type"] == "string"

    def test_parse_positional_params(self, nmap_yaml: Path) -> None:
        """Parse positional parameters correctly."""
        tool_def = parse_cli_tool_yaml(nmap_yaml)

        schema = tool_def.schema
        positional = schema["positional"]
        assert len(positional) == 1
        assert positional[0]["name"] == "target"
        assert positional[0]["type"] == "string"
        assert positional[0]["required"] is True

    def test_parse_recipe_preset(self, nmap_yaml: Path) -> None:
        """Parse recipe preset values."""
        tool_def = parse_cli_tool_yaml(nmap_yaml)

        syn_scan = tool_def.recipes["syn_scan"]
        assert syn_scan["preset"]["sS"] is True
        assert syn_scan["preset"]["Pn"] is True

    def test_parse_recipe_params(self, nmap_yaml: Path) -> None:
        """Parse recipe parameter definitions."""
        tool_def = parse_cli_tool_yaml(nmap_yaml)

        syn_scan = tool_def.recipes["syn_scan"]
        assert "target" in syn_scan["params"]
        assert "p" in syn_scan["params"]
        assert syn_scan["params"]["p"]["default"] == "-"


class TestCLICommandBuilder:
    """Tests for building command arrays from schema + args."""

    def test_build_simple_command(self, simple_tool_yaml: Path) -> None:
        """Build command for simple tool."""
        tool_def = parse_cli_tool_yaml(simple_tool_yaml)
        builder = CLICommandBuilder(tool_def)

        cmd = builder.build(args={"host": "example.com"})
        assert cmd == ["ping", "example.com"]

    def test_build_with_option(self, simple_tool_yaml: Path) -> None:
        """Build command with optional flag."""
        tool_def = parse_cli_tool_yaml(simple_tool_yaml)
        builder = CLICommandBuilder(tool_def)

        cmd = builder.build(args={"host": "example.com", "c": 5})
        assert "ping" in cmd
        assert "-c" in cmd
        assert "5" in cmd or 5 in cmd
        assert "example.com" in cmd

    def test_build_boolean_flag(self, nmap_yaml: Path) -> None:
        """Build command with boolean flags."""
        tool_def = parse_cli_tool_yaml(nmap_yaml)
        builder = CLICommandBuilder(tool_def)

        cmd = builder.build(args={"target": "10.0.0.1", "sS": True, "Pn": True})
        assert "nmap" in cmd
        assert "-sS" in cmd
        assert "-Pn" in cmd
        assert "10.0.0.1" in cmd

    def test_build_string_option(self, nmap_yaml: Path) -> None:
        """Build command with string option."""
        tool_def = parse_cli_tool_yaml(nmap_yaml)
        builder = CLICommandBuilder(tool_def)

        cmd = builder.build(args={"target": "10.0.0.1", "p": "22,80,443"})
        assert "nmap" in cmd
        assert "-p" in cmd
        assert "22,80,443" in cmd

    def test_build_recipe_with_preset(self, nmap_yaml: Path) -> None:
        """Build command from recipe with preset values."""
        tool_def = parse_cli_tool_yaml(nmap_yaml)
        builder = CLICommandBuilder(tool_def)

        # Recipe "syn_scan" has preset sS=true, Pn=true
        cmd = builder.build_recipe("syn_scan", args={"target": "10.0.0.1"})
        assert "nmap" in cmd
        assert "-sS" in cmd  # From preset
        assert "-Pn" in cmd  # From preset
        assert "10.0.0.1" in cmd

    def test_build_recipe_override_preset(self, nmap_yaml: Path) -> None:
        """User args override recipe preset values."""
        tool_def = parse_cli_tool_yaml(nmap_yaml)
        builder = CLICommandBuilder(tool_def)

        # Override the preset port range
        cmd = builder.build_recipe("syn_scan", args={"target": "10.0.0.1", "p": "1-1000"})
        assert "nmap" in cmd
        assert "-sS" in cmd  # From preset
        assert "-p" in cmd
        assert "1-1000" in cmd  # Overridden

    def test_build_recipe_apply_defaults(self, nmap_yaml: Path) -> None:
        """Apply recipe parameter defaults."""
        tool_def = parse_cli_tool_yaml(nmap_yaml)
        builder = CLICommandBuilder(tool_def)

        # syn_scan has default p="-" (all ports)
        cmd = builder.build_recipe("syn_scan", args={"target": "10.0.0.1"})
        assert "-p" in cmd
        # Default is "-" which means all ports

    def test_build_missing_required_param_raises(self, simple_tool_yaml: Path) -> None:
        """Missing required parameter raises error."""
        tool_def = parse_cli_tool_yaml(simple_tool_yaml)
        builder = CLICommandBuilder(tool_def)

        with pytest.raises(ValueError, match="required|missing"):
            builder.build(args={})  # Missing 'host'

    def test_build_boolean_false_omitted(self, nmap_yaml: Path) -> None:
        """Boolean flags set to False are omitted from command."""
        tool_def = parse_cli_tool_yaml(nmap_yaml)
        builder = CLICommandBuilder(tool_def)

        cmd = builder.build(args={"target": "10.0.0.1", "sS": False})
        assert "-sS" not in cmd

    def test_build_array_option(self) -> None:
        """Build command with array-type option."""
        # Create a tool with array option
        content = """
name: test
command: test
schema:
  options:
    exclude: {type: array, description: Exclude patterns}
  positional:
    - name: path
      type: string
      required: true
"""
        tool_def = CLIToolDefinition(
            name="test",
            command="test",
            schema=yaml.safe_load(content)["schema"],
            recipes={},
            timeout=60,
            description="Test",
        )
        builder = CLICommandBuilder(tool_def)

        cmd = builder.build(args={"path": "/tmp", "exclude": ["*.log", "*.tmp"]})
        assert "test" in cmd
        assert "--exclude" in cmd or "-exclude" in cmd
        # Array values should be expanded
        assert "*.log" in cmd
        assert "*.tmp" in cmd

    def test_positional_ordering(self, nmap_yaml: Path) -> None:
        """Positional arguments maintain order."""
        tool_def = parse_cli_tool_yaml(nmap_yaml)
        builder = CLICommandBuilder(tool_def)

        cmd = builder.build(args={"target": "10.0.0.1", "sS": True})
        # Target should come after options
        target_idx = cmd.index("10.0.0.1")
        option_indices = [i for i, x in enumerate(cmd) if x.startswith("-")]
        # All options should come before positionals
        assert all(i < target_idx for i in option_indices)

    def test_boolean_with_short_form(self) -> None:
        """Boolean option with short field uses short form."""
        content = """
name: test
command: test
schema:
  options:
    verbose:
      type: boolean
      short: v
      description: Verbose output
  positional:
    - name: arg
      type: string
      required: true
"""
        tool_def = CLIToolDefinition(
            name="test",
            command="test",
            schema=yaml.safe_load(content)["schema"],
            recipes={},
            timeout=60,
            description="Test",
        )
        builder = CLICommandBuilder(tool_def)

        cmd = builder.build(args={"arg": "value", "verbose": True})
        assert "test" in cmd
        assert "-v" in cmd
        assert "-verbose" not in cmd
        assert "--verbose" not in cmd

    def test_boolean_without_short_form(self) -> None:
        """Boolean option without short field uses long form."""
        content = """
name: test
command: test
schema:
  options:
    debug:
      type: boolean
      description: Debug mode
  positional:
    - name: arg
      type: string
      required: true
"""
        tool_def = CLIToolDefinition(
            name="test",
            command="test",
            schema=yaml.safe_load(content)["schema"],
            recipes={},
            timeout=60,
            description="Test",
        )
        builder = CLICommandBuilder(tool_def)

        cmd = builder.build(args={"arg": "value", "debug": True})
        assert "test" in cmd
        assert "--debug" in cmd
        assert "-debug" not in cmd

    def test_string_option_with_short_form(self) -> None:
        """String option with short field uses short form."""
        content = """
name: test
command: test
schema:
  options:
    output:
      type: string
      short: o
      description: Output file
  positional:
    - name: arg
      type: string
      required: true
"""
        tool_def = CLIToolDefinition(
            name="test",
            command="test",
            schema=yaml.safe_load(content)["schema"],
            recipes={},
            timeout=60,
            description="Test",
        )
        builder = CLICommandBuilder(tool_def)

        cmd = builder.build(args={"arg": "value", "output": "file.txt"})
        assert "test" in cmd
        assert "-o" in cmd
        assert "file.txt" in cmd
        assert "--output" not in cmd

    def test_string_option_without_short_form(self) -> None:
        """String option without short field uses long form."""
        content = """
name: test
command: test
schema:
  options:
    output:
      type: string
      description: Output file
  positional:
    - name: arg
      type: string
      required: true
"""
        tool_def = CLIToolDefinition(
            name="test",
            command="test",
            schema=yaml.safe_load(content)["schema"],
            recipes={},
            timeout=60,
            description="Test",
        )
        builder = CLICommandBuilder(tool_def)

        cmd = builder.build(args={"arg": "value", "output": "file.txt"})
        assert "test" in cmd
        assert "--output" in cmd
        assert "file.txt" in cmd
        assert "-output" not in cmd

    def test_array_option_with_short_form(self) -> None:
        """Array option with short field uses short form."""
        content = """
name: test
command: test
schema:
  options:
    exclude:
      type: array
      short: e
      description: Exclude patterns
  positional:
    - name: arg
      type: string
      required: true
"""
        tool_def = CLIToolDefinition(
            name="test",
            command="test",
            schema=yaml.safe_load(content)["schema"],
            recipes={},
            timeout=60,
            description="Test",
        )
        builder = CLICommandBuilder(tool_def)

        cmd = builder.build(args={"arg": "value", "exclude": ["*.log", "*.tmp"]})
        assert "test" in cmd
        assert "-e" in cmd
        assert "*.log" in cmd
        assert "*.tmp" in cmd
        assert "--exclude" not in cmd

    def test_integer_option_with_short_form(self) -> None:
        """Integer option with short field uses short form."""
        content = """
name: test
command: test
schema:
  options:
    count:
      type: integer
      short: n
      description: Number of iterations
  positional:
    - name: arg
      type: string
      required: true
"""
        tool_def = CLIToolDefinition(
            name="test",
            command="test",
            schema=yaml.safe_load(content)["schema"],
            recipes={},
            timeout=60,
            description="Test",
        )
        builder = CLICommandBuilder(tool_def)

        cmd = builder.build(args={"arg": "value", "count": 5})
        assert "test" in cmd
        assert "-n" in cmd
        assert "5" in cmd
        assert "--count" not in cmd
