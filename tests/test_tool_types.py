"""Tests for unified tool type system."""

import pytest

from py_code_mode.tools import Tool, ToolCallable, ToolParameter


class TestToolParameter:
    """Tests for ToolParameter."""

    def test_required_parameter(self) -> None:
        param = ToolParameter(
            name="target",
            type="str",
            required=True,
            description="Target host",
        )
        assert param.name == "target"
        assert param.type == "str"
        assert param.required is True
        assert param.default is None

    def test_optional_parameter_with_default(self) -> None:
        param = ToolParameter(
            name="timeout",
            type="int",
            required=False,
            default="30",
            description="Timeout in seconds",
        )
        assert param.required is False
        assert param.default == "30"

    def test_signature_fragment_required(self) -> None:
        param = ToolParameter(name="target", type="str", required=True)
        assert param.signature_fragment() == "target: str"

    def test_signature_fragment_optional(self) -> None:
        param = ToolParameter(name="timeout", type="int", required=False, default="30")
        assert param.signature_fragment() == "timeout: int = 30"

    def test_signature_fragment_optional_no_default(self) -> None:
        param = ToolParameter(name="flags", type="str", required=False)
        assert param.signature_fragment() == "flags: str | None = None"

    def test_signature_fragment_bool(self) -> None:
        param = ToolParameter(name="verbose", type="bool", required=False, default="true")
        assert param.signature_fragment() == "verbose: bool = true"

    def test_signature_fragment_list(self) -> None:
        param = ToolParameter(name="ports", type="list[str]", required=False, default="[]")
        assert param.signature_fragment() == "ports: list[str] = []"


class TestToolCallable:
    """Tests for ToolCallable."""

    def test_callable_no_parameters(self) -> None:
        callable_def = ToolCallable(
            name="list_all",
            description="List all items",
            parameters=(),
        )
        assert callable_def.name == "list_all"
        assert len(callable_def.parameters) == 0

    def test_callable_with_parameters(self) -> None:
        params = (
            ToolParameter(name="target", type="str", required=True),
            ToolParameter(name="port", type="int", required=False, default="80"),
        )
        callable_def = ToolCallable(
            name="scan",
            description="Scan a target",
            parameters=params,
        )
        assert len(callable_def.parameters) == 2
        assert callable_def.parameters[0].name == "target"

    def test_signature_no_params(self) -> None:
        callable_def = ToolCallable(
            name="list_all",
            description="List all",
            parameters=(),
        )
        assert callable_def.signature() == "list_all()"

    def test_signature_with_params(self) -> None:
        params = (
            ToolParameter(name="target", type="str", required=True),
            ToolParameter(name="port", type="int", required=False, default="80"),
        )
        callable_def = ToolCallable(
            name="scan",
            description="Scan",
            parameters=params,
        )
        assert callable_def.signature() == "scan(target: str, port: int = 80)"

    def test_signature_required_before_optional(self) -> None:
        """Required parameters must come before optional ones in signature."""
        params = (
            ToolParameter(name="port", type="int", required=False, default="80"),
            ToolParameter(name="target", type="str", required=True),
            ToolParameter(name="verbose", type="bool", required=False),
        )
        callable_def = ToolCallable(
            name="scan",
            description="Scan",
            parameters=params,
        )
        # Should reorder: required first, then optional
        sig = callable_def.signature()
        assert sig.startswith("scan(target: str,")
        # Optional params after required
        assert "port: int" in sig
        assert "verbose: bool" in sig

    def test_signature_complex_types(self) -> None:
        params = (
            ToolParameter(name="ports", type="list[int]", required=True),
            ToolParameter(name="options", type="dict[str, str]", required=False),
        )
        callable_def = ToolCallable(
            name="multi_scan",
            description="Scan multiple",
            parameters=params,
        )
        sig = callable_def.signature()
        assert "ports: list[int]" in sig
        assert "options: dict[str, str]" in sig


class TestTool:
    """Tests for Tool."""

    def test_tool_single_callable(self) -> None:
        callable_def = ToolCallable(
            name="scan",
            description="Scan",
            parameters=(),
        )
        tool = Tool(
            name="nmap",
            description="Network scanner",
            callables=(callable_def,),
            tags=frozenset({"network", "recon"}),
        )
        assert tool.name == "nmap"
        assert len(tool.callables) == 1
        assert tool.tags == frozenset({"network", "recon"})

    def test_tool_multiple_callables(self) -> None:
        callables = (
            ToolCallable(name="syn_scan", description="SYN scan", parameters=()),
            ToolCallable(name="udp_scan", description="UDP scan", parameters=()),
            ToolCallable(name="quick", description="Quick scan", parameters=()),
        )
        tool = Tool(
            name="nmap",
            description="Network scanner",
            callables=callables,
        )
        assert len(tool.callables) == 3
        callable_names = {c.name for c in tool.callables}
        assert callable_names == {"syn_scan", "udp_scan", "quick"}

    def test_tool_signatures(self) -> None:
        callables = (
            ToolCallable(
                name="syn_scan",
                description="SYN scan",
                parameters=(ToolParameter(name="target", type="str", required=True),),
            ),
            ToolCallable(
                name="quick",
                description="Quick",
                parameters=(
                    ToolParameter(name="target", type="str", required=True),
                    ToolParameter(name="ports", type="str", required=False),
                ),
            ),
        )
        tool = Tool(
            name="nmap",
            description="Network scanner",
            callables=callables,
        )
        sigs = tool.signatures()
        assert len(sigs) == 2
        assert "syn_scan(target: str)" in sigs
        assert "quick(target: str" in sigs[1]  # Has optional ports param

    def test_tool_no_tags(self) -> None:
        callable_def = ToolCallable(name="run", description="Run", parameters=())
        tool = Tool(
            name="echo",
            description="Echo command",
            callables=(callable_def,),
        )
        assert tool.tags == frozenset()

    def test_tool_immutable(self) -> None:
        """Tool should be frozen (immutable)."""
        callable_def = ToolCallable(name="run", description="Run", parameters=())
        tool = Tool(
            name="echo",
            description="Echo",
            callables=(callable_def,),
        )
        with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
            tool.name = "changed"  # type: ignore
