"""Tests for CLI adapter."""

import pytest

from py_code_mode import CLIAdapter, CLIToolSpec, JsonSchema, ToolNotFoundError, ToolTimeoutError


class TestCLIToolSpec:
    """Tests for CLIToolSpec dataclass."""

    def test_basic_spec(self) -> None:
        spec = CLIToolSpec(
            name="echo",
            description="Echo text",
            command="echo",
            args_template="{text}",
        )

        assert spec.name == "echo"
        assert spec.command == "echo"
        assert spec.timeout_seconds == 60.0
        assert spec.parse_json is False

    def test_spec_with_schema(self) -> None:
        spec = CLIToolSpec(
            name="grep",
            description="Search",
            command="grep",
            args_template="-r {pattern} {path}",
            input_schema=JsonSchema(
                type="object",
                properties={
                    "pattern": JsonSchema(type="string"),
                    "path": JsonSchema(type="string"),
                },
                required=["pattern", "path"],
            ),
            tags=frozenset({"search", "text"}),
        )

        assert "search" in spec.tags
        assert spec.input_schema.required == ["pattern", "path"]


class TestCLIAdapter:
    """Tests for CLIAdapter."""

    @pytest.fixture
    def echo_adapter(self) -> CLIAdapter:
        """Adapter with echo tool."""
        return CLIAdapter(
            [
                CLIToolSpec(
                    name="echo",
                    description="Echo text to stdout",
                    command="echo",
                    args_template="{text}",
                    input_schema=JsonSchema(
                        type="object",
                        properties={"text": JsonSchema(type="string")},
                        required=["text"],
                    ),
                    tags=frozenset({"text", "output"}),
                ),
            ]
        )

    @pytest.fixture
    def multi_tool_adapter(self) -> CLIAdapter:
        """Adapter with multiple tools."""
        return CLIAdapter(
            [
                CLIToolSpec(
                    name="echo",
                    description="Echo text",
                    command="echo",
                    args_template="{text}",
                    input_schema=JsonSchema(
                        type="object",
                        properties={"text": JsonSchema(type="string")},
                        required=["text"],
                    ),
                ),
                CLIToolSpec(
                    name="pwd",
                    description="Print working directory",
                    command="pwd",
                ),
            ]
        )

    @pytest.mark.asyncio
    async def test_list_tools(self, echo_adapter: CLIAdapter) -> None:
        tools = await echo_adapter.list_tools()

        assert len(tools) == 1
        assert tools[0].name == "echo"
        assert tools[0].description == "Echo text to stdout"
        assert "text" in tools[0].tags

    @pytest.mark.asyncio
    async def test_call_echo(self, echo_adapter: CLIAdapter) -> None:
        result = await echo_adapter.call_tool("echo", {"text": "hello world"})

        assert "hello world" in result

    @pytest.mark.asyncio
    async def test_call_unknown_tool(self, echo_adapter: CLIAdapter) -> None:
        with pytest.raises(ToolNotFoundError) as exc_info:
            await echo_adapter.call_tool("nonexistent", {})

        assert "nonexistent" in str(exc_info.value)
        assert "echo" in exc_info.value.available_tools

    @pytest.mark.asyncio
    async def test_call_pwd(self, multi_tool_adapter: CLIAdapter) -> None:
        result = await multi_tool_adapter.call_tool("pwd", {})

        # Should return a path
        assert "/" in result or "\\" in result  # Unix or Windows path

    @pytest.mark.asyncio
    async def test_json_parsing(self) -> None:
        # Test JSON parsing with a command that outputs valid JSON
        # Using cat with a heredoc-style approach via sh -c
        import os
        import tempfile

        # Create a temp file with JSON content
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write('{"key": "value"}')
            temp_path = f.name

        try:
            adapter = CLIAdapter(
                [
                    CLIToolSpec(
                        name="cat_json",
                        description="Cat a JSON file",
                        command="cat",
                        args_template=temp_path,  # Hardcoded path for this test
                        parse_json=True,
                    ),
                ]
            )

            result = await adapter.call_tool("cat_json", {})

            assert isinstance(result, dict)
            assert result["key"] == "value"
        finally:
            os.unlink(temp_path)

    @pytest.mark.asyncio
    async def test_timeout(self) -> None:
        adapter = CLIAdapter(
            [
                CLIToolSpec(
                    name="slow",
                    description="Slow command",
                    command="sleep",
                    args_template="10",
                    timeout_seconds=0.1,  # Very short timeout
                ),
            ]
        )

        with pytest.raises(ToolTimeoutError) as exc_info:
            await adapter.call_tool("slow", {})

        assert exc_info.value.tool_name == "slow"
        assert exc_info.value.timeout_seconds == 0.1

    @pytest.mark.asyncio
    async def test_close_is_noop(self, echo_adapter: CLIAdapter) -> None:
        await echo_adapter.close()  # Should not raise


class TestCLIAdapterCommandBuilding:
    """Tests for command building logic."""

    @pytest.mark.asyncio
    async def test_template_substitution(self) -> None:
        adapter = CLIAdapter(
            [
                CLIToolSpec(
                    name="greet",
                    description="Greet",
                    command="echo",
                    args_template="Hello, {name}! You are {age} years old.",
                    input_schema=JsonSchema(
                        type="object",
                        properties={
                            "name": JsonSchema(type="string"),
                            "age": JsonSchema(type="integer"),
                        },
                    ),
                ),
            ]
        )

        result = await adapter.call_tool("greet", {"name": "Alice", "age": 30})

        assert "Hello, Alice!" in result
        assert "30 years old" in result

    @pytest.mark.asyncio
    async def test_command_with_complex_args(self) -> None:
        # Test ls with multiple flags
        adapter = CLIAdapter(
            [
                CLIToolSpec(
                    name="list",
                    description="List files",
                    command="ls",
                    args_template="-la {path}",
                    input_schema=JsonSchema(
                        type="object",
                        properties={"path": JsonSchema(type="string")},
                        required=["path"],
                    ),
                ),
            ]
        )

        result = await adapter.call_tool("list", {"path": "/tmp"})
        # Should succeed and return directory listing
        assert isinstance(result, str)


class TestCLIAdapterFromDir:
    """Tests for CLIAdapter.from_dir() factory method."""

    def test_from_dir_loads_yaml_files(self, tmp_path) -> None:
        """from_dir() loads tool specs from YAML files."""
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()

        (tools_dir / "echo.yaml").write_text("""
name: echo
command: echo
args: "{text}"
description: Echo text
tags: [util]
timeout: 30
""")

        (tools_dir / "cat.yaml").write_text("""
name: cat
args: "{file}"
""")

        adapter = CLIAdapter.from_dir(str(tools_dir))

        assert len(adapter._specs) == 2
        assert "echo" in adapter._specs
        assert "cat" in adapter._specs

    def test_from_dir_extracts_params_from_args(self, tmp_path) -> None:
        """from_dir() extracts parameters from args template."""
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()

        (tools_dir / "curl.yaml").write_text("""
name: curl
args: "-X {method} -H {header} {url}"
""")

        adapter = CLIAdapter.from_dir(str(tools_dir))

        spec = adapter._specs["curl"]
        # Should have extracted method, header, url as params
        props = spec.input_schema.properties or {}
        assert "method" in props
        assert "header" in props
        assert "url" in props

    def test_from_dir_command_defaults_to_name(self, tmp_path) -> None:
        """from_dir() defaults command to name if not specified."""
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()

        (tools_dir / "ls.yaml").write_text("""
name: ls
args: "-la {path}"
""")

        adapter = CLIAdapter.from_dir(str(tools_dir))

        assert adapter._specs["ls"].command == "ls"

    def test_from_dir_empty_directory(self, tmp_path) -> None:
        """from_dir() returns empty adapter for empty directory."""
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()

        adapter = CLIAdapter.from_dir(str(tools_dir))

        assert len(adapter._specs) == 0

    def test_from_dir_nonexistent_directory(self) -> None:
        """from_dir() returns empty adapter for nonexistent directory."""
        adapter = CLIAdapter.from_dir("/nonexistent/path")

        assert len(adapter._specs) == 0

    def test_from_dir_skips_files_without_name(self, tmp_path) -> None:
        """from_dir() skips YAML files without name field."""
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()

        (tools_dir / "valid.yaml").write_text("""
name: valid
args: "{x}"
""")

        (tools_dir / "invalid.yaml").write_text("""
args: "{x}"
""")

        adapter = CLIAdapter.from_dir(str(tools_dir))

        assert len(adapter._specs) == 1
        assert "valid" in adapter._specs

    def test_from_dir_skips_non_cli_tools(self, tmp_path) -> None:
        """from_dir() skips MCP and other non-CLI tools."""
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()

        # CLI tool (explicit type)
        (tools_dir / "curl.yaml").write_text("""
name: curl
type: cli
args: "-s {url}"
""")

        # CLI tool (implicit - no type field)
        (tools_dir / "jq.yaml").write_text("""
name: jq
args: "{filter}"
""")

        # MCP tool - should be skipped
        (tools_dir / "fetch.yaml").write_text("""
name: fetch
type: mcp
transport: stdio
command: uvx
args: ["mcp-server-fetch"]
""")

        # HTTP tool - should be skipped
        (tools_dir / "api.yaml").write_text("""
name: api
type: http
url: "https://api.example.com"
""")

        adapter = CLIAdapter.from_dir(str(tools_dir))

        assert len(adapter._specs) == 2
        assert "curl" in adapter._specs
        assert "jq" in adapter._specs
        assert "fetch" not in adapter._specs
        assert "api" not in adapter._specs
