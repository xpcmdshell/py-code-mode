"""Tests for ToolRegistry with flat namespace."""

import pytest

from py_code_mode import ToolNotFoundError, ToolRegistry
from tests.conftest import MockAdapter


class TestToolRegistryBasics:
    """Basic registry operations."""

    @pytest.mark.asyncio
    async def test_register_adapter(
        self, network_adapter: MockAdapter, network_tools: list
    ) -> None:
        registry = ToolRegistry()
        registered = await registry.register_adapter(network_adapter, tags={"cli"})

        assert len(registered) == 2
        # Flat namespace - no prefix
        assert {t.name for t in registered} == {"nmap", "ping"}

    @pytest.mark.asyncio
    async def test_list_all_tools(
        self, network_adapter: MockAdapter, web_adapter: MockAdapter
    ) -> None:
        registry = ToolRegistry()
        await registry.register_adapter(network_adapter)
        await registry.register_adapter(web_adapter)

        tools = registry.list_tools()
        assert len(tools) == 4  # 2 network + 2 web

    @pytest.mark.asyncio
    async def test_get_tool(self, network_adapter: MockAdapter) -> None:
        registry = ToolRegistry()
        await registry.register_adapter(network_adapter)

        tool = registry.get_tool("nmap")
        assert tool.name == "nmap"
        assert "network" in tool.tags

    @pytest.mark.asyncio
    async def test_get_tool_not_found(self, network_adapter: MockAdapter) -> None:
        registry = ToolRegistry()
        await registry.register_adapter(network_adapter)

        with pytest.raises(ToolNotFoundError) as exc_info:
            registry.get_tool("nonexistent")

        assert "nonexistent" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_duplicate_tool_name_rejected(
        self, network_adapter: MockAdapter
    ) -> None:
        registry = ToolRegistry()
        await registry.register_adapter(network_adapter)

        # Try to register another adapter with same tool names
        with pytest.raises(ValueError, match="already registered"):
            await registry.register_adapter(network_adapter)


class TestToolRegistryScoping:
    """Tests for scoped tool access."""

    @pytest.mark.asyncio
    async def test_list_tools_with_scope(
        self, network_adapter: MockAdapter, web_adapter: MockAdapter
    ) -> None:
        registry = ToolRegistry()
        await registry.register_adapter(network_adapter)
        await registry.register_adapter(web_adapter)

        # Only network tools
        network_tools = registry.list_tools(scope={"network"})
        assert len(network_tools) == 2
        assert all("network" in t.tags for t in network_tools)

        # Only recon tools (spans both adapters)
        recon_tools = registry.list_tools(scope={"recon"})
        assert len(recon_tools) == 2
        assert {t.name for t in recon_tools} == {"nmap", "ffuf"}

    @pytest.mark.asyncio
    async def test_scoped_view(
        self, network_adapter: MockAdapter, web_adapter: MockAdapter
    ) -> None:
        registry = ToolRegistry()
        await registry.register_adapter(network_adapter)
        await registry.register_adapter(web_adapter)

        # Create scoped view for network tools only
        scoped = registry.scoped_view({"network"})

        assert len(scoped.list_tools()) == 2
        assert scoped.scope == {"network"}

    @pytest.mark.asyncio
    async def test_scoped_view_blocks_out_of_scope(
        self, network_adapter: MockAdapter, web_adapter: MockAdapter
    ) -> None:
        registry = ToolRegistry()
        await registry.register_adapter(network_adapter)
        await registry.register_adapter(web_adapter)

        # Scoped to network only
        scoped = registry.scoped_view({"network"})

        # Can access network tools
        tool = scoped.get_tool("nmap")
        assert tool is not None

        # Cannot access web-only tools
        with pytest.raises(ToolNotFoundError):
            scoped.get_tool("curl")  # curl has tags {"web", "http"}, not "network"

    @pytest.mark.asyncio
    async def test_scoped_view_call_blocked(
        self, network_adapter: MockAdapter, web_adapter: MockAdapter
    ) -> None:
        registry = ToolRegistry()
        await registry.register_adapter(network_adapter)
        await registry.register_adapter(web_adapter)

        scoped = registry.scoped_view({"network"})

        # Cannot call out-of-scope tools
        with pytest.raises(ToolNotFoundError):
            await scoped.call_tool("curl", {"url": "http://example.com"})

    @pytest.mark.asyncio
    async def test_empty_scope_blocks_all(
        self, network_adapter: MockAdapter
    ) -> None:
        registry = ToolRegistry()
        await registry.register_adapter(network_adapter)

        scoped = registry.scoped_view(set())
        assert len(scoped.list_tools()) == 0


class TestToolRegistryTagMerging:
    """Tests for tag merging during registration."""

    @pytest.mark.asyncio
    async def test_tags_merged(self, network_adapter: MockAdapter) -> None:
        registry = ToolRegistry()

        # Register with additional tags
        registered = await registry.register_adapter(
            network_adapter, tags={"cli", "dangerous"}
        )

        # Original tags + new tags
        nmap = next(t for t in registered if t.name == "nmap")
        assert "network" in nmap.tags  # Original
        assert "recon" in nmap.tags  # Original
        assert "cli" in nmap.tags  # Added
        assert "dangerous" in nmap.tags  # Added


class TestToolRegistryCallRouting:
    """Tests for routing tool calls to adapters."""

    @pytest.mark.asyncio
    async def test_call_routed_to_correct_adapter(
        self, network_adapter: MockAdapter, web_adapter: MockAdapter
    ) -> None:
        registry = ToolRegistry()
        await registry.register_adapter(network_adapter)
        await registry.register_adapter(web_adapter)

        # Set responses
        network_adapter.set_response("nmap", {"hosts": ["192.168.1.1"]})
        web_adapter.set_response("curl", {"status": 200})

        # Call network tool
        result = await registry.call_tool("nmap", {"target": "192.168.1.0/24"})
        assert result == {"hosts": ["192.168.1.1"]}

        # Call web tool
        result = await registry.call_tool("curl", {"url": "http://example.com"})
        assert result == {"status": 200}

        # Verify routing
        assert network_adapter.call_log == [("nmap", {"target": "192.168.1.0/24"})]
        assert web_adapter.call_log == [("curl", {"url": "http://example.com"})]

    @pytest.mark.asyncio
    async def test_call_not_found(self, network_adapter: MockAdapter) -> None:
        registry = ToolRegistry()
        await registry.register_adapter(network_adapter)

        with pytest.raises(ToolNotFoundError):
            await registry.call_tool("nonexistent", {})


class TestToolRegistrySearch:
    """Tests for tool search functionality."""

    @pytest.mark.asyncio
    async def test_search_by_name(
        self, network_adapter: MockAdapter, web_adapter: MockAdapter
    ) -> None:
        registry = ToolRegistry()
        await registry.register_adapter(network_adapter)
        await registry.register_adapter(web_adapter)

        results = registry.search("nmap")
        assert len(results) == 1
        assert results[0].name == "nmap"

    @pytest.mark.asyncio
    async def test_search_by_description(
        self, network_adapter: MockAdapter, web_adapter: MockAdapter
    ) -> None:
        registry = ToolRegistry()
        await registry.register_adapter(network_adapter)
        await registry.register_adapter(web_adapter)

        results = registry.search("scanner")
        assert len(results) == 1
        assert results[0].name == "nmap"  # Description is "Network scanner"

    @pytest.mark.asyncio
    async def test_search_limit(
        self, network_adapter: MockAdapter, web_adapter: MockAdapter
    ) -> None:
        registry = ToolRegistry()
        await registry.register_adapter(network_adapter)
        await registry.register_adapter(web_adapter)

        # Search for common term
        results = registry.search("e", limit=2)  # Many tools have 'e'
        assert len(results) <= 2

    @pytest.mark.asyncio
    async def test_scoped_search(
        self, network_adapter: MockAdapter, web_adapter: MockAdapter
    ) -> None:
        registry = ToolRegistry()
        await registry.register_adapter(network_adapter)
        await registry.register_adapter(web_adapter)

        scoped = registry.scoped_view({"network"})

        # Search within scope
        results = scoped.search("ping")
        assert len(results) == 1
        assert results[0].name == "ping"

        # Search for out-of-scope tool returns nothing
        results = scoped.search("curl")
        assert len(results) == 0


class TestToolRegistryCleanup:
    """Tests for cleanup operations."""

    @pytest.mark.asyncio
    async def test_close_all(
        self, network_adapter: MockAdapter, web_adapter: MockAdapter
    ) -> None:
        registry = ToolRegistry()
        await registry.register_adapter(network_adapter)
        await registry.register_adapter(web_adapter)

        await registry.close()

        assert len(registry.list_tools()) == 0


class TestToolRegistryFromDir:
    """Tests for ToolRegistry.from_dir() factory method."""

    @pytest.mark.asyncio
    async def test_from_dir_loads_cli_tools(self, tmp_path) -> None:
        """from_dir() loads CLI tools from YAML files."""
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()

        (tools_dir / "echo.yaml").write_text("""
name: echo
type: cli
command: echo
args: "{text}"
description: Echo text back
""")

        (tools_dir / "cat.yaml").write_text("""
name: cat
type: cli
args: "{file}"
""")

        registry = await ToolRegistry.from_dir(str(tools_dir))

        tools = registry.list_tools()
        names = {t.name for t in tools}
        assert "echo" in names
        assert "cat" in names

    @pytest.mark.asyncio
    async def test_from_dir_empty_directory(self, tmp_path) -> None:
        """from_dir() handles empty directory."""
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()

        registry = await ToolRegistry.from_dir(str(tools_dir))

        assert len(registry.list_tools()) == 0

    @pytest.mark.asyncio
    async def test_from_dir_nonexistent_directory(self) -> None:
        """from_dir() handles nonexistent directory."""
        registry = await ToolRegistry.from_dir("/nonexistent/path")

        assert len(registry.list_tools()) == 0

    @pytest.mark.asyncio
    async def test_from_dir_skips_invalid_yaml(self, tmp_path) -> None:
        """from_dir() skips YAML files without name field."""
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()

        # Valid tool
        (tools_dir / "valid.yaml").write_text("""
name: valid
type: cli
args: "{x}"
""")

        # Invalid - no name
        (tools_dir / "invalid.yaml").write_text("""
type: cli
args: "{x}"
""")

        registry = await ToolRegistry.from_dir(str(tools_dir))

        tools = registry.list_tools()
        assert len(tools) == 1
        assert tools[0].name == "valid"


