"""Tests for CLIAdapter with unified Tool interface."""

from pathlib import Path

import pytest

from py_code_mode.adapters.cli import CLIAdapter
from py_code_mode.tool_types import Tool


class TestCLIAdapterUnified:
    """Tests for CLIAdapter returning Tool objects."""

    @pytest.mark.asyncio
    async def test_list_tools_returns_tool_objects(self, nmap_yaml: Path) -> None:
        """list_tools returns Tool objects with callables."""
        adapter = CLIAdapter(tools_path=nmap_yaml.parent)
        tools = adapter.list_tools()

        assert len(tools) > 0
        tool = tools[0]
        assert isinstance(tool, Tool)
        assert tool.name == "nmap"

    @pytest.mark.asyncio
    async def test_tool_has_recipes_as_callables(self, nmap_yaml: Path) -> None:
        """Tool callables include recipes."""
        adapter = CLIAdapter(tools_path=nmap_yaml.parent)
        tools = adapter.list_tools()

        nmap = next(t for t in tools if t.name == "nmap")
        callable_names = {c.name for c in nmap.callables}

        assert "syn_scan" in callable_names
        assert "quick" in callable_names

    @pytest.mark.asyncio
    async def test_call_tool_with_callable_name(self, nmap_yaml: Path) -> None:
        """call_tool dispatches to correct callable."""
        adapter = CLIAdapter(tools_path=nmap_yaml.parent)

        # Mock the subprocess call to avoid actually running nmap
        async def mock_run(cmd, timeout, cwd=None, env=None):
            return "Mock nmap output"

        adapter._run_subprocess = mock_run

        result = await adapter.call_tool("nmap", "syn_scan", {"target": "10.0.0.1"})
        assert result == "Mock nmap output"

    @pytest.mark.asyncio
    async def test_describe_callable(self, nmap_yaml: Path) -> None:
        """describe returns parameter descriptions for a callable."""
        adapter = CLIAdapter(tools_path=nmap_yaml.parent)

        descriptions = await adapter.describe("nmap", "syn_scan")
        assert "target" in descriptions
        assert isinstance(descriptions["target"], str)

    @pytest.mark.asyncio
    async def test_callable_has_parameters(self, nmap_yaml: Path) -> None:
        """ToolCallable.parameters is populated from recipe params."""
        adapter = CLIAdapter(tools_path=nmap_yaml.parent)
        tools = adapter.list_tools()

        nmap = next(t for t in tools if t.name == "nmap")
        syn_scan = next(c for c in nmap.callables if c.name == "syn_scan")

        # syn_scan recipe has target and p parameters
        assert len(syn_scan.parameters) > 0
        param_names = {p.name for p in syn_scan.parameters}
        assert "target" in param_names

    @pytest.mark.asyncio
    async def test_empty_recipe_params_inherit_from_schema(self, tmp_path: Path) -> None:
        """When recipe params is empty dict, inherit from schema."""
        # Create tool with schema params but empty recipe params
        tool_yaml = tmp_path / "test.yaml"
        tool_yaml.write_text("""
name: test
description: Test tool
command: test
timeout: 10

schema:
  positional:
    - name: target
      type: string
      required: true
      description: Target host
    - name: port
      type: integer
      required: false
      default: 80
      description: Port number

recipes:
  scan:
    description: Scan target
    params: {}
""")

        adapter = CLIAdapter(tools_path=tmp_path)
        tools = adapter.list_tools()

        test_tool = next((t for t in tools if t.name == "test"), None)
        assert test_tool is not None

        scan_callable = next((c for c in test_tool.callables if c.name == "scan"), None)
        assert scan_callable is not None

        # Should inherit both parameters from schema
        assert len(scan_callable.parameters) == 2
        param_dict = {p.name: p for p in scan_callable.parameters}

        assert "target" in param_dict
        assert param_dict["target"].type == "string"
        assert param_dict["target"].required is True

        assert "port" in param_dict
        assert param_dict["port"].type == "integer"
        assert param_dict["port"].required is False
        assert param_dict["port"].default == 80

    @pytest.mark.asyncio
    async def test_recipe_params_override_schema(self, tmp_path: Path) -> None:
        """When recipe specifies params, they override schema."""
        tool_yaml = tmp_path / "test.yaml"
        tool_yaml.write_text("""
name: test
description: Test tool
command: test
timeout: 10

schema:
  positional:
    - name: target
      type: string
      required: true
      description: Target host (from schema)

recipes:
  scan:
    description: Scan target
    params:
      target:
        type: str
        required: false
        default: "localhost"
        description: "Target (from recipe)"
""")

        adapter = CLIAdapter(tools_path=tmp_path)
        tools = adapter.list_tools()

        test_tool = next((t for t in tools if t.name == "test"), None)
        assert test_tool is not None

        scan_callable = next((c for c in test_tool.callables if c.name == "scan"), None)
        assert scan_callable is not None

        assert len(scan_callable.parameters) == 1
        target_param = scan_callable.parameters[0]

        # Recipe params should override schema
        assert target_param.name == "target"
        assert target_param.type == "str"  # from recipe
        assert target_param.required is False  # from recipe (schema says True)
        assert target_param.default == "localhost"  # from recipe
        assert target_param.description == "Target (from recipe)"  # from recipe

    @pytest.mark.asyncio
    async def test_empty_tools_path_creates_empty_adapter(self, tmp_path: Path) -> None:
        """Empty directory creates empty adapter."""
        adapter = CLIAdapter(tools_path=tmp_path)
        tools = adapter.list_tools()
        assert tools == []

    @pytest.mark.asyncio
    async def test_nonexistent_path_creates_empty_adapter(self) -> None:
        """Nonexistent path creates empty adapter."""
        adapter = CLIAdapter(tools_path="/nonexistent/path")
        tools = adapter.list_tools()
        assert tools == []

    @pytest.mark.asyncio
    async def test_no_tools_path_creates_empty_adapter(self) -> None:
        """No tools_path parameter creates empty adapter."""
        adapter = CLIAdapter()
        tools = adapter.list_tools()
        assert tools == []
