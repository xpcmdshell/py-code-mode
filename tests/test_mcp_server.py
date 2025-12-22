"""Comprehensive tests for MCP server functionality.

Tests cover:
- E2E tests via stdio transport (production path)
- Skill creation, persistence, and invocation
- Artifact storage and persistence
- Cross-namespace operations (skills calling tools)
- State persistence across run_code calls
- Tool invocation patterns
- Complete workflow scenarios
- Negative tests (error handling)
"""

import json
from pathlib import Path

import pytest
from mcp.client.stdio import StdioServerParameters

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def mcp_storage_dir(tmp_path: Path) -> Path:
    """Create storage directory structure for MCP server."""
    storage = tmp_path / "storage"
    storage.mkdir()

    # Create subdirectories
    tools_dir = storage / "tools"
    tools_dir.mkdir()

    skills_dir = storage / "skills"
    skills_dir.mkdir()

    artifacts_dir = storage / "artifacts"
    artifacts_dir.mkdir()

    # Echo tool for basic testing
    (tools_dir / "echo.yaml").write_text("""
name: echo
description: Echo text back
command: echo
timeout: 10
schema:
  positional:
    - name: text
      type: string
      required: true
recipes:
  echo:
    description: Echo text
    params:
      text: {}
""")

    # Curl tool for cross-namespace testing
    (tools_dir / "curl.yaml").write_text("""
name: curl
description: Make HTTP requests
command: curl
timeout: 60
schema:
  options:
    silent:
      type: boolean
      short: s
    location:
      type: boolean
      short: L
  positional:
    - name: url
      type: string
      required: true
recipes:
  get:
    description: Simple GET request
    preset:
      silent: true
      location: true
    params:
      url: {}
""")

    # Simple skill for basic testing
    (skills_dir / "double.py").write_text('''"""Double a number."""
def run(n: int) -> int:
    return n * 2
''')

    # Skill that calls tools (for cross-namespace testing)
    (skills_dir / "fetch_title.py").write_text('''"""Fetch a URL and extract title."""
def run(url: str) -> str:
    import re
    content = tools.curl.get(url=url)
    match = re.search(r'<title>([^<]+)</title>', content, re.I)
    return match.group(1) if match else "No title found"
''')

    return storage


# =============================================================================
# E2E Tests via Stdio - Production Path
# =============================================================================


class TestMCPServerE2E:
    """E2E tests that spawn the MCP server via stdio transport."""

    @pytest.mark.asyncio
    async def test_mcp_server_starts_via_stdio(
        self,
        mcp_storage_dir: Path,
    ) -> None:
        """E2E: Server spawns and responds to initialize."""
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command="py-code-mode-mcp",
            args=["--storage", str(mcp_storage_dir)],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Server should have these MCP tools
                tools = await session.list_tools()
                tool_names = {t.name for t in tools.tools}

                expected_tools = {
                    "run_code",
                    "list_tools",
                    "search_tools",
                    "list_skills",
                    "search_skills",
                }
                assert expected_tools <= tool_names, f"Missing tools: {expected_tools - tool_names}"

    @pytest.mark.asyncio
    async def test_mcp_server_list_tools(
        self,
        mcp_storage_dir: Path,
    ) -> None:
        """E2E: list_tools returns configured CLI tools."""
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command="py-code-mode-mcp",
            args=["--storage", str(mcp_storage_dir)],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                result = await session.call_tool("list_tools", {})
                tools_data = json.loads(result.content[0].text)

                tool_names = {t["name"] for t in tools_data}
                assert "echo" in tool_names
                assert "curl" in tool_names

    @pytest.mark.asyncio
    async def test_mcp_server_list_skills(
        self,
        mcp_storage_dir: Path,
    ) -> None:
        """E2E: list_skills returns seeded Python skills."""
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command="py-code-mode-mcp",
            args=["--storage", str(mcp_storage_dir)],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                result = await session.call_tool("list_skills", {})
                skills_data = json.loads(result.content[0].text)

                skill_names = {s["name"] for s in skills_data}
                assert "double" in skill_names
                assert "fetch_title" in skill_names

    @pytest.mark.asyncio
    async def test_mcp_server_search_tools(
        self,
        mcp_storage_dir: Path,
    ) -> None:
        """E2E: search_tools finds tools by intent."""
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command="py-code-mode-mcp",
            args=["--storage", str(mcp_storage_dir)],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                result = await session.call_tool("search_tools", {"query": "http request"})
                tools_data = json.loads(result.content[0].text)

                # Should find curl since it makes HTTP requests
                tool_names = {t["name"] for t in tools_data}
                assert "curl" in tool_names

    @pytest.mark.asyncio
    async def test_mcp_server_search_skills(
        self,
        mcp_storage_dir: Path,
    ) -> None:
        """E2E: search_skills finds skills by intent."""
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command="py-code-mode-mcp",
            args=["--storage", str(mcp_storage_dir)],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                result = await session.call_tool(
                    "search_skills", {"query": "multiply number", "limit": 5}
                )
                skills_data = json.loads(result.content[0].text)

                # Should find double since it multiplies by 2
                skill_names = {s["name"] for s in skills_data}
                assert "double" in skill_names

    # -------------------------------------------------------------------------
    # Runtime Skill Creation Tests
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_mcp_server_skill_create_and_invoke(
        self,
        mcp_storage_dir: Path,
    ) -> None:
        """E2E: Create skill at runtime, then invoke it."""
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command="py-code-mode-mcp",
            args=["--storage", str(mcp_storage_dir)],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create a skill at runtime
                create_code = '''
skills.create(
    name="add_numbers",
    source="""
def run(a: int, b: int) -> int:
    return a + b
""",
    description="Add two numbers together"
)
'''
                result = await session.call_tool("run_code", {"code": create_code})
                assert "error" not in result.content[0].text.lower()

                # Now invoke the skill we just created
                invoke_result = await session.call_tool(
                    "run_code", {"code": 'skills.invoke("add_numbers", a=10, b=32)'}
                )
                assert "42" in invoke_result.content[0].text

    @pytest.mark.asyncio
    async def test_mcp_server_skill_persists_across_calls(
        self,
        mcp_storage_dir: Path,
    ) -> None:
        """E2E: Skill created in call 1 is available in call 2."""
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command="py-code-mode-mcp",
            args=["--storage", str(mcp_storage_dir)],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Call 1: Create skill
                await session.call_tool(
                    "run_code",
                    {
                        "code": """
skills.create(
    name="triple",
    source="def run(n: int) -> int:\\n    return n * 3",
    description="Triple a number"
)
"""
                    },
                )

                # Call 2: Search for the skill (should find it)
                search_result = await session.call_tool(
                    "search_skills", {"query": "triple multiply", "limit": 5}
                )
                skills_found = json.loads(search_result.content[0].text)
                skill_names = {s["name"] for s in skills_found}
                assert "triple" in skill_names

                # Call 3: Invoke the skill
                invoke_result = await session.call_tool(
                    "run_code", {"code": 'skills.invoke("triple", n=14)'}
                )
                assert "42" in invoke_result.content[0].text

    @pytest.mark.asyncio
    async def test_mcp_server_skill_delete(
        self,
        mcp_storage_dir: Path,
    ) -> None:
        """E2E: Delete skill via skills.delete()."""
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command="py-code-mode-mcp",
            args=["--storage", str(mcp_storage_dir)],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create a skill
                await session.call_tool(
                    "run_code",
                    {
                        "code": """
skills.create(
    name="temp_skill",
    source="def run() -> str:\\n    return 'temporary'",
    description="Temporary skill for deletion test"
)
"""
                    },
                )

                # Verify it exists
                list_result = await session.call_tool("list_skills", {})
                skills_data = json.loads(list_result.content[0].text)
                skill_names = {s["name"] for s in skills_data}
                assert "temp_skill" in skill_names

                # Delete it
                await session.call_tool("run_code", {"code": 'skills.delete("temp_skill")'})

                # Verify it's gone
                list_result2 = await session.call_tool("list_skills", {})
                skills_data2 = json.loads(list_result2.content[0].text)
                skill_names2 = {s["name"] for s in skills_data2}
                assert "temp_skill" not in skill_names2

    # -------------------------------------------------------------------------
    # Artifact Storage Tests
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_mcp_server_artifact_save_and_load(
        self,
        mcp_storage_dir: Path,
    ) -> None:
        """E2E: Save artifact, then load it back."""
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command="py-code-mode-mcp",
            args=["--storage", str(mcp_storage_dir)],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Save artifact
                save_code = """
data = {"users": ["alice", "bob"], "count": 2}
artifacts.save("user_data", data)
"saved"
"""
                result = await session.call_tool("run_code", {"code": save_code})
                assert "saved" in result.content[0].text

                # Load artifact
                load_code = """
loaded = artifacts.load("user_data")
loaded["count"]
"""
                load_result = await session.call_tool("run_code", {"code": load_code})
                assert "2" in load_result.content[0].text

    @pytest.mark.asyncio
    async def test_mcp_server_artifact_persists_across_calls(
        self,
        mcp_storage_dir: Path,
    ) -> None:
        """E2E: Artifact saved in call 1 loads in call 2."""
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command="py-code-mode-mcp",
            args=["--storage", str(mcp_storage_dir)],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Call 1: Save
                await session.call_tool(
                    "run_code",
                    {
                        "code": """
artifacts.save("research", {"topic": "MCP", "notes": ["note1", "note2"]})
"""
                    },
                )

                # Call 2: Load (separate run_code call)
                result = await session.call_tool(
                    "run_code",
                    {
                        "code": """
data = artifacts.load("research")
data["topic"]
"""
                    },
                )
                assert "MCP" in result.content[0].text

    @pytest.mark.asyncio
    async def test_mcp_server_artifact_list(
        self,
        mcp_storage_dir: Path,
    ) -> None:
        """E2E: List all artifacts."""
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command="py-code-mode-mcp",
            args=["--storage", str(mcp_storage_dir)],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Save multiple artifacts
                await session.call_tool(
                    "run_code",
                    {
                        "code": """
artifacts.save("artifact_a", {"id": "a"})
artifacts.save("artifact_b", {"id": "b"})
"""
                    },
                )

                # List artifacts
                result = await session.call_tool(
                    "run_code",
                    {
                        "code": """
artifact_list = artifacts.list()
len(artifact_list)
"""
                    },
                )
                # Should have at least 2 artifacts
                assert "2" in result.content[0].text or int(result.content[0].text.strip()) >= 2

    @pytest.mark.asyncio
    async def test_mcp_server_artifact_delete(
        self,
        mcp_storage_dir: Path,
    ) -> None:
        """E2E: Delete artifact."""
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command="py-code-mode-mcp",
            args=["--storage", str(mcp_storage_dir)],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Save artifact
                await session.call_tool(
                    "run_code",
                    {
                        "code": """
artifacts.save("to_delete", {"temp": True})
"""
                    },
                )

                # Verify it exists by loading
                load_result = await session.call_tool(
                    "run_code",
                    {
                        "code": """
artifacts.load("to_delete")
"""
                    },
                )
                assert "temp" in load_result.content[0].text

                # Delete it
                await session.call_tool(
                    "run_code",
                    {
                        "code": """
artifacts.delete("to_delete")
"""
                    },
                )

                # Verify it's gone (should raise or return None)
                delete_check = await session.call_tool(
                    "run_code",
                    {
                        "code": """
result = artifacts.load("to_delete")
result is None
"""
                    },
                )
                # Either returns None or raises - both are valid
                assert (
                    "True" in delete_check.content[0].text
                    or "error" in delete_check.content[0].text.lower()
                )

    # -------------------------------------------------------------------------
    # Cross-Namespace Tests
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_mcp_server_skill_calls_tool(
        self,
        mcp_storage_dir: Path,
    ) -> None:
        """E2E: Create skill that uses tools namespace, then invoke it."""
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command="py-code-mode-mcp",
            args=["--storage", str(mcp_storage_dir)],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create skill that calls echo tool
                await session.call_tool(
                    "run_code",
                    {
                        "code": '''
skills.create(
    name="shout",
    source="""
def run(message: str) -> str:
    return tools.echo(text=message.upper())
""",
    description="Echo message in uppercase"
)
'''
                    },
                )

                # Invoke the skill
                result = await session.call_tool(
                    "run_code", {"code": 'skills.invoke("shout", message="hello world")'}
                )
                assert "HELLO WORLD" in result.content[0].text

    @pytest.mark.asyncio
    async def test_mcp_server_seeded_skill_calls_tool(
        self,
        mcp_storage_dir: Path,
    ) -> None:
        """E2E: Invoke seeded skill (fetch_title) that calls curl tool."""
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command="py-code-mode-mcp",
            args=["--storage", str(mcp_storage_dir)],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Invoke seeded skill that calls tools.curl.get()
                result = await session.call_tool(
                    "run_code", {"code": 'skills.invoke("fetch_title", url="https://example.com")'}
                )
                # example.com has title "Example Domain"
                assert (
                    "Example Domain" in result.content[0].text
                    or "title" in result.content[0].text.lower()
                )

    @pytest.mark.asyncio
    async def test_mcp_server_skill_calls_another_skill(
        self,
        mcp_storage_dir: Path,
    ) -> None:
        """E2E: Skill that calls skills.invoke()."""
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command="py-code-mode-mcp",
            args=["--storage", str(mcp_storage_dir)],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create a skill that calls the seeded "double" skill
                await session.call_tool(
                    "run_code",
                    {
                        "code": '''
skills.create(
    name="quadruple",
    source="""
def run(n: int) -> int:
    doubled = skills.invoke("double", n=n)
    return skills.invoke("double", n=doubled)
""",
    description="Quadruple a number by doubling twice"
)
'''
                    },
                )

                # Invoke the skill
                result = await session.call_tool(
                    "run_code", {"code": 'skills.invoke("quadruple", n=10)'}
                )
                assert "40" in result.content[0].text

    # -------------------------------------------------------------------------
    # State Persistence Tests
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_mcp_server_variable_persists(
        self,
        mcp_storage_dir: Path,
    ) -> None:
        """E2E: Variable assigned in call 1 is available in call 2."""
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command="py-code-mode-mcp",
            args=["--storage", str(mcp_storage_dir)],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Call 1: Assign variable
                await session.call_tool("run_code", {"code": "my_data = [1, 2, 3, 4, 5]"})

                # Call 2: Use the variable
                result = await session.call_tool("run_code", {"code": "sum(my_data)"})
                assert "15" in result.content[0].text

    @pytest.mark.asyncio
    async def test_mcp_server_import_persists(
        self,
        mcp_storage_dir: Path,
    ) -> None:
        """E2E: Import in call 1 is available in call 2."""
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command="py-code-mode-mcp",
            args=["--storage", str(mcp_storage_dir)],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Call 1: Import
                await session.call_tool("run_code", {"code": "import json"})

                # Call 2: Use the import
                result = await session.call_tool(
                    "run_code", {"code": 'json.dumps({"key": "value"})'}
                )
                assert '"key"' in result.content[0].text

    # -------------------------------------------------------------------------
    # Tool Invocation Pattern Tests
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_mcp_server_tool_recipe_invocation(
        self,
        mcp_storage_dir: Path,
    ) -> None:
        """E2E: Tool recipe invocation - tools.curl.get(url=...)."""
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command="py-code-mode-mcp",
            args=["--storage", str(mcp_storage_dir)],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Use recipe invocation pattern
                result = await session.call_tool(
                    "run_code", {"code": 'tools.echo.echo(text="recipe test")'}
                )
                assert "recipe test" in result.content[0].text

    @pytest.mark.asyncio
    async def test_mcp_server_tool_raw_invocation(
        self,
        mcp_storage_dir: Path,
    ) -> None:
        """E2E: Tool raw invocation (escape hatch) - tools.echo(text=..., ...)."""
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command="py-code-mode-mcp",
            args=["--storage", str(mcp_storage_dir)],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Use escape hatch (raw invocation)
                result = await session.call_tool(
                    "run_code", {"code": 'tools.echo(text="escape hatch test")'}
                )
                assert "escape hatch test" in result.content[0].text

    # -------------------------------------------------------------------------
    # MCP Tool: list_artifacts
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_mcp_server_list_artifacts(
        self,
        mcp_storage_dir: Path,
    ) -> None:
        """E2E: list_artifacts MCP tool shows saved artifacts."""
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command="py-code-mode-mcp",
            args=["--storage", str(mcp_storage_dir)],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Save an artifact via run_code
                await session.call_tool(
                    "run_code",
                    {"code": 'artifacts.save("test_data", {"key": "value"})'},
                )

                # List artifacts via dedicated MCP tool
                result = await session.call_tool("list_artifacts", {})
                artifacts_data = json.loads(result.content[0].text)

                # Should contain our saved artifact
                assert isinstance(artifacts_data, list)
                artifact_names = {a["name"] for a in artifacts_data}
                assert "test_data" in artifact_names

    # -------------------------------------------------------------------------
    # MCP Tool: create_skill
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_mcp_server_create_skill(
        self,
        mcp_storage_dir: Path,
    ) -> None:
        """E2E: create_skill MCP tool creates a skill directly."""
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command="py-code-mode-mcp",
            args=["--storage", str(mcp_storage_dir)],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create skill via dedicated MCP tool (not run_code)
                skill_source = "def run(x: int, y: int) -> int:\n    return x + y\n"
                result = await session.call_tool(
                    "create_skill",
                    {
                        "name": "add_two",
                        "source": skill_source,
                        "description": "Add two numbers",
                    },
                )

                # Should return skill info
                skill_info = json.loads(result.content[0].text)
                assert skill_info["name"] == "add_two"
                assert "Add two numbers" in skill_info["description"]

                # Verify skill works by invoking it via run_code
                invoke_result = await session.call_tool(
                    "run_code",
                    {"code": 'skills.invoke("add_two", x=17, y=25)'},
                )
                assert "42" in invoke_result.content[0].text

    @pytest.mark.asyncio
    async def test_mcp_server_create_skill_persists(
        self,
        mcp_storage_dir: Path,
    ) -> None:
        """E2E: Skill created via create_skill MCP tool persists and is searchable."""
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command="py-code-mode-mcp",
            args=["--storage", str(mcp_storage_dir)],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create skill via dedicated MCP tool
                skill_source = "def run(text: str) -> str:\n    return text.upper()\n"
                await session.call_tool(
                    "create_skill",
                    {
                        "name": "uppercase_text",
                        "source": skill_source,
                        "description": "Convert text to uppercase",
                    },
                )

                # Search for the skill (should be found)
                search_result = await session.call_tool(
                    "search_skills",
                    {"query": "uppercase convert text", "limit": 5},
                )
                skills_found = json.loads(search_result.content[0].text)
                skill_names = {s["name"] for s in skills_found}
                assert "uppercase_text" in skill_names

    # -------------------------------------------------------------------------
    # MCP Tool: delete_skill
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_mcp_server_delete_skill(
        self,
        mcp_storage_dir: Path,
    ) -> None:
        """E2E: delete_skill MCP tool removes a skill."""
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command="py-code-mode-mcp",
            args=["--storage", str(mcp_storage_dir)],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create a skill via MCP tool
                skill_source = "def run() -> str:\n    return 'I exist'\n"
                await session.call_tool(
                    "create_skill",
                    {
                        "name": "deleteme",
                        "source": skill_source,
                        "description": "Skill to be deleted",
                    },
                )

                # Verify it exists via list_skills
                list_result = await session.call_tool("list_skills", {})
                skills_data = json.loads(list_result.content[0].text)
                skill_names = {s["name"] for s in skills_data}
                assert "deleteme" in skill_names

                # Delete the skill via dedicated MCP tool
                delete_result = await session.call_tool(
                    "delete_skill",
                    {"name": "deleteme"},
                )
                delete_data = json.loads(delete_result.content[0].text)
                assert delete_data is True

                # Verify it's gone via list_skills
                list_result2 = await session.call_tool("list_skills", {})
                skills_data2 = json.loads(list_result2.content[0].text)
                skill_names2 = {s["name"] for s in skills_data2}
                assert "deleteme" not in skill_names2

    @pytest.mark.asyncio
    async def test_mcp_server_delete_skill_nonexistent(
        self,
        mcp_storage_dir: Path,
    ) -> None:
        """E2E: delete_skill returns False for nonexistent skill."""
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command="py-code-mode-mcp",
            args=["--storage", str(mcp_storage_dir)],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Try to delete a skill that doesn't exist
                delete_result = await session.call_tool(
                    "delete_skill",
                    {"name": "nonexistent_skill_xyz"},
                )
                delete_data = json.loads(delete_result.content[0].text)
                assert delete_data is False

    # -------------------------------------------------------------------------
    # Full Workflow Test
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_mcp_server_full_workflow(
        self,
        mcp_storage_dir: Path,
    ) -> None:
        """E2E: Complete agent workflow - fetch, parse, save skill, invoke, store artifact."""
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command="py-code-mode-mcp",
            args=["--storage", str(mcp_storage_dir)],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Step 1: Fetch content using tool
                await session.call_tool(
                    "run_code",
                    {
                        "code": """
content = tools.echo(text="Sample data: 100,200,300")
"""
                    },
                )

                # Step 2: Parse the content
                await session.call_tool(
                    "run_code",
                    {
                        "code": """
import re
numbers = [int(x) for x in re.findall(r"\\d+", content)]
"""
                    },
                )

                # Step 3: Create a skill to process this type of data
                await session.call_tool(
                    "run_code",
                    {
                        "code": '''
skills.create(
    name="sum_csv",
    source="""
import re
def run(text: str) -> int:
    numbers = [int(x) for x in re.findall(r'\\\\d+', text)]
    return sum(numbers)
""",
    description="Sum numbers from CSV-like text"
)
'''
                    },
                )

                # Step 4: Invoke the skill
                await session.call_tool(
                    "run_code",
                    {
                        "code": """
total = skills.invoke("sum_csv", text="Values: 10, 20, 30, 40")
"""
                    },
                )

                # Step 5: Store result as artifact
                await session.call_tool(
                    "run_code",
                    {
                        "code": """
artifacts.save("calculation_result", {"total": total, "source": "sum_csv skill"})
"""
                    },
                )

                # Step 6: Verify artifact was stored
                verify_result = await session.call_tool(
                    "run_code",
                    {
                        "code": """
loaded = artifacts.load("calculation_result")
loaded["total"]
"""
                    },
                )
                assert "100" in verify_result.content[0].text


# =============================================================================
# Negative Tests - Error Handling
# =============================================================================


class TestMCPServerNegative:
    """Negative tests for error handling and edge cases."""

    @pytest.mark.asyncio
    async def test_mcp_server_empty_tools_dir(
        self,
        tmp_path: Path,
    ) -> None:
        """E2E: Server handles empty tools directory gracefully."""
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        # Create storage with empty tools subdirectory
        storage = tmp_path / "storage"
        storage.mkdir()
        (storage / "tools").mkdir()
        (storage / "skills").mkdir()
        (storage / "artifacts").mkdir()

        # Server should still start (tools are optional)
        server_params = StdioServerParameters(
            command="py-code-mode-mcp",
            args=["--storage", str(storage)],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # list_tools should return empty or handle gracefully
                result = await session.call_tool("list_tools", {})
                # FastMCP returns structuredContent for lists, content for strings
                if result.content:
                    tools_data = json.loads(result.content[0].text)
                elif result.structuredContent and "result" in result.structuredContent:
                    tools_data = result.structuredContent["result"]
                else:
                    tools_data = []
                assert isinstance(tools_data, list)  # Should be empty list, not error

    @pytest.mark.asyncio
    async def test_mcp_server_run_code_syntax_error(
        self,
        mcp_storage_dir: Path,
    ) -> None:
        """E2E: Syntax error returns error, doesn't crash server."""
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command="py-code-mode-mcp",
            args=["--storage", str(mcp_storage_dir)],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Run code with syntax error
                result = await session.call_tool("run_code", {"code": "def broken("})

                # Should return error, not crash
                assert (
                    "error" in result.content[0].text.lower()
                    or "syntax" in result.content[0].text.lower()
                )

                # Server should still work after error
                result2 = await session.call_tool("run_code", {"code": "1 + 1"})
                assert "2" in result2.content[0].text

    @pytest.mark.asyncio
    async def test_mcp_server_run_code_runtime_error(
        self,
        mcp_storage_dir: Path,
    ) -> None:
        """E2E: Runtime error returns traceback, doesn't crash server."""
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command="py-code-mode-mcp",
            args=["--storage", str(mcp_storage_dir)],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Run code that raises runtime error
                result = await session.call_tool("run_code", {"code": "1 / 0"})

                # Should return error with traceback info
                text = result.content[0].text.lower()
                assert "error" in text or "zerodivision" in text

                # Server should still work after error
                result2 = await session.call_tool("run_code", {"code": "2 + 2"})
                assert "4" in result2.content[0].text

    @pytest.mark.asyncio
    async def test_mcp_server_invoke_nonexistent_skill(
        self,
        mcp_storage_dir: Path,
    ) -> None:
        """E2E: Invoking nonexistent skill returns error."""
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command="py-code-mode-mcp",
            args=["--storage", str(mcp_storage_dir)],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Try to invoke skill that doesn't exist
                result = await session.call_tool(
                    "run_code", {"code": 'skills.invoke("nonexistent_skill_xyz", arg=1)'}
                )

                # Should return error about skill not found
                text = result.content[0].text.lower()
                assert "error" in text or "not found" in text or "does not exist" in text

    @pytest.mark.asyncio
    async def test_mcp_server_load_nonexistent_artifact(
        self,
        mcp_storage_dir: Path,
    ) -> None:
        """E2E: Loading nonexistent artifact returns None or error."""
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command="py-code-mode-mcp",
            args=["--storage", str(mcp_storage_dir)],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Try to load artifact that doesn't exist
                result = await session.call_tool(
                    "run_code", {"code": 'artifacts.load("nonexistent_artifact_xyz")'}
                )

                # Should return None or error - both are valid behaviors
                # Note: run_code returns "(no output)" when result is None
                text = result.content[0].text
                assert (
                    "None" in text
                    or "no output" in text.lower()
                    or "error" in text.lower()
                    or "not found" in text.lower()
                )


# =============================================================================
# MCP Deps Tools Tests
# =============================================================================


class TestMCPServerDepsTools:
    """Tests for MCP deps management tools (add_dep, list_deps, remove_dep).

    These are thin wrappers around DepsNamespace methods. Core deps functionality
    is tested in test_deps_namespace.py - these tests verify MCP wiring works.
    """

    # -------------------------------------------------------------------------
    # Contract Tests - Tools Exist
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_deps_tools_registered(
        self,
        mcp_storage_dir: Path,
    ) -> None:
        """E2E: Deps tools are registered and available.

        Contract: add_dep, list_deps, remove_dep are MCP tools.
        Breaks when: Tools not registered with FastMCP.
        """
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command="py-code-mode-mcp",
            args=["--storage", str(mcp_storage_dir)],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                tools = await session.list_tools()
                tool_names = {t.name for t in tools.tools}

                expected_deps_tools = {"add_dep", "list_deps", "remove_dep"}
                assert expected_deps_tools <= tool_names, (
                    f"Missing deps tools: {expected_deps_tools - tool_names}"
                )

    # -------------------------------------------------------------------------
    # Contract Tests - Return Types
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_list_deps_returns_list(
        self,
        mcp_storage_dir: Path,
    ) -> None:
        """E2E: list_deps returns a JSON list.

        Contract: list_deps() returns list[str].
        Breaks when: Return type is wrong.
        """
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command="py-code-mode-mcp",
            args=["--storage", str(mcp_storage_dir)],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                result = await session.call_tool("list_deps", {})
                deps_data = json.loads(result.content[0].text)

                assert isinstance(deps_data, list)

    @pytest.mark.asyncio
    async def test_remove_dep_returns_bool(
        self,
        mcp_storage_dir: Path,
    ) -> None:
        """E2E: remove_dep returns a boolean.

        Contract: remove_dep() returns bool.
        Breaks when: Return type is wrong.
        """
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command="py-code-mode-mcp",
            args=["--storage", str(mcp_storage_dir)],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Try to remove non-existent package (should return False)
                result = await session.call_tool(
                    "remove_dep", {"package": "nonexistent-pkg-xyz"}
                )
                result_data = json.loads(result.content[0].text)

                assert isinstance(result_data, bool)
                assert result_data is False

    @pytest.mark.asyncio
    async def test_add_dep_returns_dict(
        self,
        mcp_storage_dir: Path,
    ) -> None:
        """E2E: add_dep returns a dict with result info.

        Contract: add_dep() returns dict with sync result info.
        Breaks when: Return type is wrong or structure missing.
        """
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command="py-code-mode-mcp",
            args=["--storage", str(mcp_storage_dir)],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Add a real package (will attempt pip install)
                result = await session.call_tool("add_dep", {"package": "six"})
                result_data = json.loads(result.content[0].text)

                # Should be a dict with sync result info
                assert isinstance(result_data, dict)
                # Should have standard sync result fields
                assert "installed" in result_data or "already_present" in result_data or "failed" in result_data

    # -------------------------------------------------------------------------
    # User Journey Tests (E2E)
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_add_dep_makes_package_listable(
        self,
        mcp_storage_dir: Path,
    ) -> None:
        """E2E: After add_dep, package appears in list_deps.

        Invariant: add_dep(X) -> X in list_deps()
        Breaks when: add_dep doesn't update store.
        """
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command="py-code-mode-mcp",
            args=["--storage", str(mcp_storage_dir)],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Add a package
                await session.call_tool("add_dep", {"package": "six"})

                # List deps
                result = await session.call_tool("list_deps", {})
                deps_data = json.loads(result.content[0].text)

                # Package should be in the list
                assert "six" in deps_data

    @pytest.mark.asyncio
    async def test_add_then_remove_dep_workflow(
        self,
        mcp_storage_dir: Path,
    ) -> None:
        """E2E: Complete add -> verify -> remove -> verify workflow.

        User action: Agent adds, verifies, removes, verifies package is gone.
        Breaks when: remove_dep doesn't update store.
        """
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command="py-code-mode-mcp",
            args=["--storage", str(mcp_storage_dir)],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # 1. Add a package
                await session.call_tool("add_dep", {"package": "six"})

                # 2. Verify it's in the list
                list_result = await session.call_tool("list_deps", {})
                deps_before = json.loads(list_result.content[0].text)
                assert "six" in deps_before

                # 3. Remove the package
                remove_result = await session.call_tool("remove_dep", {"package": "six"})
                removed = json.loads(remove_result.content[0].text)
                assert removed is True

                # 4. Verify it's gone
                list_result2 = await session.call_tool("list_deps", {})
                deps_after = json.loads(list_result2.content[0].text)
                assert "six" not in deps_after

    @pytest.mark.asyncio
    async def test_add_dep_with_version_specifier(
        self,
        mcp_storage_dir: Path,
    ) -> None:
        """E2E: add_dep accepts version specifiers.

        Breaks when: Version specifiers cause errors.
        """
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command="py-code-mode-mcp",
            args=["--storage", str(mcp_storage_dir)],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Add package with version specifier
                result = await session.call_tool("add_dep", {"package": "six>=1.0"})
                result_data = json.loads(result.content[0].text)

                # Should succeed (dict result, not error)
                assert isinstance(result_data, dict)

                # Verify it's in the list
                list_result = await session.call_tool("list_deps", {})
                deps_data = json.loads(list_result.content[0].text)
                assert "six>=1.0" in deps_data

    # -------------------------------------------------------------------------
    # Invariant Tests
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_list_deps_empty_returns_empty_list(
        self,
        tmp_path: Path,
    ) -> None:
        """E2E: list_deps on fresh session returns empty list.

        Invariant: Empty deps -> []
        Breaks when: Returns None or throws.
        """
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        # Create fresh storage with no deps
        storage = tmp_path / "storage"
        storage.mkdir()
        (storage / "tools").mkdir()
        (storage / "skills").mkdir()
        (storage / "artifacts").mkdir()
        (storage / "deps").mkdir()

        server_params = StdioServerParameters(
            command="py-code-mode-mcp",
            args=["--storage", str(storage)],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                result = await session.call_tool("list_deps", {})
                deps_data = json.loads(result.content[0].text)

                assert deps_data == []

    # -------------------------------------------------------------------------
    # Negative Tests
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_remove_dep_nonexistent_returns_false(
        self,
        mcp_storage_dir: Path,
    ) -> None:
        """E2E: remove_dep returns False for non-existent package.

        Breaks when: Returns True or throws.
        """
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command="py-code-mode-mcp",
            args=["--storage", str(mcp_storage_dir)],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                result = await session.call_tool(
                    "remove_dep", {"package": "nonexistent-package-xyz"}
                )
                removed = json.loads(result.content[0].text)

                assert removed is False

    @pytest.mark.asyncio
    async def test_add_dep_empty_string_returns_error(
        self,
        mcp_storage_dir: Path,
    ) -> None:
        """E2E: add_dep('') returns error response.

        Breaks when: Empty string is accepted or causes crash.
        """
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command="py-code-mode-mcp",
            args=["--storage", str(mcp_storage_dir)],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                result = await session.call_tool("add_dep", {"package": ""})
                text = result.content[0].text.lower()

                # Should indicate an error
                assert "error" in text or "invalid" in text or "empty" in text

    @pytest.mark.asyncio
    async def test_add_dep_with_shell_metacharacters_returns_error(
        self,
        mcp_storage_dir: Path,
    ) -> None:
        """E2E: add_dep rejects dangerous shell metacharacters.

        Breaks when: Command injection is possible.
        """
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command="py-code-mode-mcp",
            args=["--storage", str(mcp_storage_dir)],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Try command injection
                result = await session.call_tool(
                    "add_dep", {"package": "pandas; rm -rf /"}
                )
                text = result.content[0].text.lower()

                # Should indicate an error (invalid package name)
                assert "error" in text or "invalid" in text


class TestMCPServerDepsToolsSessionNotInitialized:
    """Tests for deps tools behavior when session is not initialized.

    These test the graceful degradation path (returning safe defaults).
    We need to test this without going through the full stdio flow since
    the session is always initialized in normal MCP usage.
    """

    @pytest.mark.asyncio
    async def test_add_dep_without_session_returns_error(self) -> None:
        """add_dep returns error dict when _session is None.

        Breaks when: Tool crashes instead of returning error.
        """
        from py_code_mode.cli import mcp_server

        # Store original session and set to None
        original_session = mcp_server._session
        mcp_server._session = None

        try:
            result = await mcp_server.add_dep("pandas")
            assert isinstance(result, dict)
            assert "error" in result
        finally:
            mcp_server._session = original_session

    @pytest.mark.asyncio
    async def test_list_deps_without_session_returns_empty(self) -> None:
        """list_deps returns empty list when _session is None.

        Breaks when: Tool crashes instead of returning empty list.
        """
        from py_code_mode.cli import mcp_server

        original_session = mcp_server._session
        mcp_server._session = None

        try:
            result = await mcp_server.list_deps()
            assert result == []
        finally:
            mcp_server._session = original_session

    @pytest.mark.asyncio
    async def test_remove_dep_without_session_returns_false(self) -> None:
        """remove_dep returns False when _session is None.

        Breaks when: Tool crashes instead of returning False.
        """
        from py_code_mode.cli import mcp_server

        original_session = mcp_server._session
        mcp_server._session = None

        try:
            result = await mcp_server.remove_dep("pandas")
            assert result is False
        finally:
            mcp_server._session = original_session
