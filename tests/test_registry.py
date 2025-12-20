"""Tests for ToolRegistry with flat namespace."""

import pytest

from py_code_mode import ToolNotFoundError, ToolRegistry
from tests.conftest import ControllableEmbedder, MockAdapter


class TestToolRegistryBasics:
    """Basic registry operations."""

    @pytest.mark.asyncio
    async def test_register_adapter(
        self, network_adapter: MockAdapter, network_tools: list
    ) -> None:
        registry = ToolRegistry()
        registered = registry.register_adapter(network_adapter, tags={"cli"})

        assert len(registered) == 2
        # Flat namespace - no prefix
        assert {t.name for t in registered} == {"nmap", "ping"}

    @pytest.mark.asyncio
    async def test_list_all_tools(
        self, network_adapter: MockAdapter, web_adapter: MockAdapter
    ) -> None:
        registry = ToolRegistry()
        registry.register_adapter(network_adapter)
        registry.register_adapter(web_adapter)

        tools = registry.list_tools()
        assert len(tools) == 4  # 2 network + 2 web

    @pytest.mark.asyncio
    async def test_get_tool(self, network_adapter: MockAdapter) -> None:
        registry = ToolRegistry()
        registry.register_adapter(network_adapter)

        tool = registry.get_tool("nmap")
        assert tool.name == "nmap"
        assert "network" in tool.tags

    @pytest.mark.asyncio
    async def test_get_tool_not_found(self, network_adapter: MockAdapter) -> None:
        registry = ToolRegistry()
        registry.register_adapter(network_adapter)

        with pytest.raises(ToolNotFoundError) as exc_info:
            registry.get_tool("nonexistent")

        assert "nonexistent" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_duplicate_tool_name_rejected(self, network_adapter: MockAdapter) -> None:
        registry = ToolRegistry()
        registry.register_adapter(network_adapter)

        # Try to register another adapter with same tool names
        with pytest.raises(ValueError, match="already registered"):
            registry.register_adapter(network_adapter)


class TestToolRegistryScoping:
    """Tests for scoped tool access."""

    @pytest.mark.asyncio
    async def test_list_tools_with_scope(
        self, network_adapter: MockAdapter, web_adapter: MockAdapter
    ) -> None:
        registry = ToolRegistry()
        registry.register_adapter(network_adapter)
        registry.register_adapter(web_adapter)

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
        registry.register_adapter(network_adapter)
        registry.register_adapter(web_adapter)

        # Create scoped view for network tools only
        scoped = registry.scoped_view({"network"})

        assert len(scoped.list_tools()) == 2
        assert scoped.scope == {"network"}

    @pytest.mark.asyncio
    async def test_scoped_view_blocks_out_of_scope(
        self, network_adapter: MockAdapter, web_adapter: MockAdapter
    ) -> None:
        registry = ToolRegistry()
        registry.register_adapter(network_adapter)
        registry.register_adapter(web_adapter)

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
        registry.register_adapter(network_adapter)
        registry.register_adapter(web_adapter)

        scoped = registry.scoped_view({"network"})

        # Cannot call out-of-scope tools
        with pytest.raises(ToolNotFoundError):
            await scoped.call_tool("curl", None, {"url": "http://example.com"})

    @pytest.mark.asyncio
    async def test_empty_scope_blocks_all(self, network_adapter: MockAdapter) -> None:
        registry = ToolRegistry()
        registry.register_adapter(network_adapter)

        scoped = registry.scoped_view(set())
        assert len(scoped.list_tools()) == 0


class TestToolRegistryTagMerging:
    """Tests for tag merging during registration."""

    @pytest.mark.asyncio
    async def test_tags_merged(self, network_adapter: MockAdapter) -> None:
        registry = ToolRegistry()

        # Register with additional tags
        registered = registry.register_adapter(network_adapter, tags={"cli", "dangerous"})

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
        registry.register_adapter(network_adapter)
        registry.register_adapter(web_adapter)

        # Set responses
        network_adapter.set_response("nmap", {"hosts": ["192.168.1.1"]})
        web_adapter.set_response("curl", {"status": 200})

        # Call network tool
        result = await registry.call_tool("nmap", None, {"target": "192.168.1.0/24"})
        assert result == {"hosts": ["192.168.1.1"]}

        # Call web tool
        result = await registry.call_tool("curl", None, {"url": "http://example.com"})
        assert result == {"status": 200}

        # Verify routing
        assert network_adapter.call_log == [("nmap", {"target": "192.168.1.0/24"})]
        assert web_adapter.call_log == [("curl", {"url": "http://example.com"})]

    @pytest.mark.asyncio
    async def test_call_not_found(self, network_adapter: MockAdapter) -> None:
        registry = ToolRegistry()
        registry.register_adapter(network_adapter)

        with pytest.raises(ToolNotFoundError):
            await registry.call_tool("nonexistent", None, {})


class TestToolRegistrySearch:
    """Tests for tool search functionality."""

    @pytest.mark.asyncio
    async def test_search_by_name(
        self, network_adapter: MockAdapter, web_adapter: MockAdapter
    ) -> None:
        registry = ToolRegistry()
        registry.register_adapter(network_adapter)
        registry.register_adapter(web_adapter)

        results = registry.search("nmap")
        assert len(results) == 1
        assert results[0].name == "nmap"

    @pytest.mark.asyncio
    async def test_search_by_description(
        self, network_adapter: MockAdapter, web_adapter: MockAdapter
    ) -> None:
        registry = ToolRegistry()
        registry.register_adapter(network_adapter)
        registry.register_adapter(web_adapter)

        results = registry.search("scanner")
        assert len(results) == 1
        assert results[0].name == "nmap"  # Description is "Network scanner"

    @pytest.mark.asyncio
    async def test_search_limit(
        self, network_adapter: MockAdapter, web_adapter: MockAdapter
    ) -> None:
        registry = ToolRegistry()
        registry.register_adapter(network_adapter)
        registry.register_adapter(web_adapter)

        # Search for common term
        results = registry.search("e", limit=2)  # Many tools have 'e'
        assert len(results) <= 2

    @pytest.mark.asyncio
    async def test_scoped_search(
        self, network_adapter: MockAdapter, web_adapter: MockAdapter
    ) -> None:
        registry = ToolRegistry()
        registry.register_adapter(network_adapter)
        registry.register_adapter(web_adapter)

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
    async def test_close_all(self, network_adapter: MockAdapter, web_adapter: MockAdapter) -> None:
        registry = ToolRegistry()
        registry.register_adapter(network_adapter)
        registry.register_adapter(web_adapter)

        await registry.close()

        assert len(registry.list_tools()) == 0


# TestToolRegistryFromDir removed - use CLIAdapter(tools_path=...) for loading tools


class TestToolRegistrySemanticSearch:
    """Unit tests for semantic search mechanics."""

    # --- Low-level: Vector storage ---

    @pytest.mark.asyncio
    async def test_vectors_populated_on_register(
        self,
        controllable_embedder: ControllableEmbedder,
        web_adapter: MockAdapter,
    ) -> None:
        """_vectors dict populated when adapter registers tools."""
        # Setup: curl embeds to known vector
        controllable_embedder.set_response("curl: HTTP client", [1.0, 0.0, 0.0, 0.0])

        registry = ToolRegistry(embedder=controllable_embedder)
        registry.register_adapter(web_adapter)

        assert "curl" in registry._vectors
        assert len(registry._vectors["curl"]) == 4

    @pytest.mark.asyncio
    async def test_vectors_cleared_on_refresh(
        self,
        controllable_embedder: ControllableEmbedder,
        web_adapter: MockAdapter,
    ) -> None:
        """refresh() clears vectors before repopulating."""
        controllable_embedder.set_response("curl: HTTP client", [1.0, 0.0, 0.0, 0.0])

        registry = ToolRegistry(embedder=controllable_embedder)
        registry.register_adapter(web_adapter)

        # Store reference to check it gets cleared
        assert "curl" in registry._vectors
        await registry.refresh()

        # Without store, refresh clears but can't repopulate
        assert len(registry._vectors) == 0

    # --- Low-level: Search algorithm ---

    @pytest.mark.asyncio
    async def test_search_uses_cosine_similarity(
        self,
        controllable_embedder: ControllableEmbedder,
        web_adapter: MockAdapter,
        json_adapter: MockAdapter,
    ) -> None:
        """Search ranks by cosine similarity to query vector."""
        # curl is similar to query, jq is orthogonal
        controllable_embedder.set_response("curl: HTTP client", [1.0, 0.0, 0.0, 0.0])
        controllable_embedder.set_response("ffuf: Web fuzzer", [0.8, 0.2, 0.0, 0.0])
        controllable_embedder.set_response("jq: JSON processor", [0.0, 1.0, 0.0, 0.0])
        controllable_embedder.set_response("HTTP requests", [0.9, 0.1, 0.0, 0.0])

        registry = ToolRegistry(embedder=controllable_embedder)
        registry.register_adapter(web_adapter)
        registry.register_adapter(json_adapter)

        results = registry.search("HTTP requests")

        # curl vector [1,0,0,0] is most similar to query [0.9,0.1,0,0]
        assert len(results) >= 2
        assert results[0].name == "curl"

    @pytest.mark.asyncio
    async def test_fallback_to_substring_no_embedder(
        self,
        web_adapter: MockAdapter,
    ) -> None:
        """Without embedder, falls back to substring search."""
        registry = ToolRegistry(embedder=None)
        registry.register_adapter(web_adapter)

        # Substring "curl" matches
        results = registry.search("curl")
        assert len(results) == 1
        assert results[0].name == "curl"

        # Semantic query doesn't match anything
        results = registry.search("make HTTP requests")
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_fallback_to_substring_no_vectors(
        self,
        controllable_embedder: ControllableEmbedder,
    ) -> None:
        """With embedder but no tools, search returns empty."""
        registry = ToolRegistry(embedder=controllable_embedder)

        results = registry.search("anything")
        assert len(results) == 0

    # --- Low-level: Adapter lifecycle ---

    @pytest.mark.asyncio
    async def test_refresh_closes_existing_adapters(
        self,
        controllable_embedder: ControllableEmbedder,
        web_adapter: MockAdapter,
    ) -> None:
        """refresh() closes adapters before recreating."""
        registry = ToolRegistry(embedder=controllable_embedder)
        registry.register_adapter(web_adapter)

        assert not web_adapter.closed
        await registry.refresh()

        assert web_adapter.closed


class TestToolRegistrySemanticIntegration:
    """Integration tests for end-to-end semantic search behavior."""

    @pytest.mark.asyncio
    async def test_semantic_search_end_to_end(
        self,
        web_adapter: MockAdapter,
        json_adapter: MockAdapter,
    ) -> None:
        """End-to-end: semantic search finds tools by intent."""
        # Use real embedder for integration test
        from py_code_mode.semantic import Embedder

        registry = ToolRegistry(embedder=Embedder())
        registry.register_adapter(web_adapter)
        registry.register_adapter(json_adapter)

        # "process JSON data" should find jq
        results = registry.search("process JSON data")
        assert len(results) > 0
        # jq should be in results (may not be first with real embeddings)
        tool_names = [r.name for r in results]
        assert "jq" in tool_names

    @pytest.mark.asyncio
    async def test_scoped_semantic_search(
        self,
        controllable_embedder: ControllableEmbedder,
        web_adapter: MockAdapter,
        network_adapter: MockAdapter,
    ) -> None:
        """Scoped view respects scope for semantic search."""
        controllable_embedder.set_response("curl: HTTP client", [1.0, 0.0, 0.0, 0.0])
        controllable_embedder.set_response("ffuf: Web fuzzer", [0.8, 0.2, 0.0, 0.0])
        controllable_embedder.set_response("nmap: Network scanner", [0.0, 0.0, 1.0, 0.0])
        controllable_embedder.set_response("ping: ICMP ping", [0.0, 0.0, 0.8, 0.2])
        controllable_embedder.set_response("HTTP client", [0.95, 0.05, 0.0, 0.0])

        registry = ToolRegistry(embedder=controllable_embedder)
        registry.register_adapter(web_adapter)
        registry.register_adapter(network_adapter)

        # "HTTP client" would normally find curl (web) first
        # But if we search in network scope, curl shouldn't appear
        network_scoped = registry.scoped_view({"network"})
        results = network_scoped.search("HTTP client")

        # curl has tags web/http, not network, so shouldn't be in results
        tool_names = [r.name for r in results]
        assert "curl" not in tool_names
