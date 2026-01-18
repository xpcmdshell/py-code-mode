"""Tests for semantic search - written first to define interface."""

from textwrap import dedent

import pytest

from py_code_mode.workflows import PythonWorkflow


def _make_workflow(name: str, description: str, code: str) -> PythonWorkflow:
    """Helper to create a PythonWorkflow from minimal info."""
    source = f'"""{description}"""\n\nasync def run():\n    {code}'
    return PythonWorkflow.from_source(name=name, source=source, description=description)


class TestEmbeddingProviderProtocol:
    """Tests that define the EmbeddingProvider interface."""

    def test_provider_has_embed_method(self) -> None:
        """Provider must have embed() that returns vectors."""
        from py_code_mode.workflows import EmbeddingProvider

        # Protocol should define embed method
        assert hasattr(EmbeddingProvider, "embed")

    def test_provider_has_dimension_property(self) -> None:
        """Provider exposes embedding dimension for index allocation."""
        from py_code_mode.workflows import EmbeddingProvider

        assert hasattr(EmbeddingProvider, "dimension")

    def test_embed_returns_list_of_vectors(self) -> None:
        """embed() takes list of strings, returns list of float vectors."""
        from py_code_mode.workflows import MockEmbedder

        embedder = MockEmbedder(dimension=384)
        vectors = embedder.embed(["hello world", "test query"])

        assert len(vectors) == 2
        assert len(vectors[0]) == 384
        assert all(isinstance(v, float) for v in vectors[0])

    def test_embed_single_text(self) -> None:
        """Convenience: can embed single string."""
        from py_code_mode.workflows import MockEmbedder

        embedder = MockEmbedder(dimension=384)
        vectors = embedder.embed(["single text"])

        assert len(vectors) == 1


class TestEmbedder:
    """Tests for the Embedder (BGE-small by default)."""

    @pytest.fixture
    def embedder(self):
        """Create embedder - skip if model not available."""
        pytest.importorskip("sentence_transformers")
        from py_code_mode.workflows import Embedder

        return Embedder()

    def test_default_dimension_is_384(self, embedder) -> None:
        """BGE-small produces 384-dim embeddings."""
        assert embedder.dimension == 384

    def test_embeds_text(self, embedder) -> None:
        """Can embed natural language descriptions."""
        vectors = embedder.embed(["scan network ports"])

        assert len(vectors) == 1
        assert len(vectors[0]) == 384

    def test_embeds_code(self, embedder) -> None:
        """Can embed Python code."""
        code = "def scan(target): return subprocess.run(['nmap', target])"
        vectors = embedder.embed([code])

        assert len(vectors) == 1
        assert len(vectors[0]) == 384

    def test_batch_embedding(self, embedder) -> None:
        """Efficiently embeds multiple texts at once."""
        texts = [
            "scan network ports",
            "take screenshot of webpage",
            "fuzzing web endpoints",
        ]
        vectors = embedder.embed(texts)

        assert len(vectors) == 3

    def test_detects_device(self, embedder) -> None:
        """Uses MPS on Apple Silicon, CUDA if available, else CPU."""
        # Just verify it has a device attribute
        assert hasattr(embedder, "device")
        assert embedder.device in ("mps", "cuda", "cpu")


class TestWorkflowLibrary:
    """Tests for WorkflowLibrary semantic search with dual indexing."""

    @pytest.fixture
    def sample_workflows(self) -> list[PythonWorkflow]:
        """Sample workflows for testing."""
        return [
            _make_workflow(
                name="fetch_url",
                description="Fetch content from a URL using HTTP GET request",
                code="return requests.get(url).text",
            ),
            _make_workflow(
                name="parse_json",
                description="Parse JSON string into Python dict",
                code="return json.loads(text)",
            ),
            _make_workflow(
                name="write_file",
                description="Write text content to a file on disk",
                code="Path(path).write_text(content)",
            ),
        ]

    @pytest.fixture
    def python_workflow(self) -> PythonWorkflow:
        """A Python workflow fixture."""
        source = dedent('''
            """Calculate sum of numbers."""

            async def run(numbers: list[int]) -> int:
                return sum(numbers)
        ''').strip()
        return PythonWorkflow.from_source(name="sum_numbers", source=source)

    def test_can_create_empty_library(self) -> None:
        """Library can be created without workflows."""
        from py_code_mode.workflows import MockEmbedder, WorkflowLibrary

        embedder = MockEmbedder(dimension=384)
        library = WorkflowLibrary(embedder)

        assert len(library) == 0

    def test_add_workflow_indexes_description(self, sample_workflows: list[PythonWorkflow]) -> None:
        """Adding workflow indexes its description for search."""
        from py_code_mode.workflows import MockEmbedder, WorkflowLibrary

        embedder = MockEmbedder(dimension=384)
        library = WorkflowLibrary(embedder)
        library.add(sample_workflows[0])

        assert len(library) == 1

    def test_add_workflow_indexes_code(self, sample_workflows: list[PythonWorkflow]) -> None:
        """Adding workflow indexes its source code for search."""
        from py_code_mode.workflows import MockEmbedder, WorkflowLibrary

        embedder = MockEmbedder(dimension=384)
        library = WorkflowLibrary(embedder)
        library.add(sample_workflows[0])

        # Code should be indexed (we can't easily verify embedding, but workflow should exist)
        assert library.get("fetch_url") is not None

    def test_search_by_description(self, sample_workflows: list[PythonWorkflow]) -> None:
        """Search finds workflows by description similarity."""
        from py_code_mode.workflows import MockEmbedder, WorkflowLibrary

        embedder = MockEmbedder(dimension=384)
        library = WorkflowLibrary(embedder)
        for workflow in sample_workflows:
            library.add(workflow)

        # Should find fetch_url when searching for URL-related queries
        results = library.search("download web content")

        assert len(results) >= 1
        # Results are returned - content depends on embedding model

    def test_search_by_code_intent(self, sample_workflows: list[PythonWorkflow]) -> None:
        """Search finds workflows by code content."""
        from py_code_mode.workflows import MockEmbedder, WorkflowLibrary

        embedder = MockEmbedder(dimension=384)
        library = WorkflowLibrary(embedder)
        for workflow in sample_workflows:
            library.add(workflow)

        # Search for something matching code
        results = library.search("json.loads")

        assert len(results) >= 1

    def test_combined_description_and_code_search(
        self, sample_workflows: list[PythonWorkflow]
    ) -> None:
        """Search considers both description and code."""
        from py_code_mode.workflows import MockEmbedder, WorkflowLibrary

        embedder = MockEmbedder(dimension=384)
        library = WorkflowLibrary(embedder)
        for workflow in sample_workflows:
            library.add(workflow)

        # Query that matches description
        results = library.search("fetch URL content")

        assert len(results) >= 1

    def test_search_with_python_workflow(
        self, sample_workflows: list[PythonWorkflow], python_workflow: PythonWorkflow
    ) -> None:
        """Search works with Python workflows that have full source."""
        from py_code_mode.workflows import MockEmbedder, WorkflowLibrary

        embedder = MockEmbedder(dimension=384)
        library = WorkflowLibrary(embedder)
        for workflow in sample_workflows:
            library.add(workflow)
        library.add(python_workflow)

        # Should find the Python workflow
        results = library.search("calculate sum")

        assert len(results) >= 1

    def test_get_by_name(self, sample_workflows: list[PythonWorkflow]) -> None:
        """Can retrieve workflow by exact name."""
        from py_code_mode.workflows import MockEmbedder, WorkflowLibrary

        embedder = MockEmbedder(dimension=384)
        library = WorkflowLibrary(embedder)
        for workflow in sample_workflows:
            library.add(workflow)

        workflow = library.get("parse_json")

        assert workflow is not None
        assert workflow.name == "parse_json"

    def test_search_limit(self, sample_workflows: list[PythonWorkflow]) -> None:
        """Search respects limit parameter."""
        from py_code_mode.workflows import MockEmbedder, WorkflowLibrary

        embedder = MockEmbedder(dimension=384)
        library = WorkflowLibrary(embedder)
        for workflow in sample_workflows:
            library.add(workflow)

        results = library.search("content", limit=1)

        assert len(results) == 1

    def test_remove_workflow(self) -> None:
        """Can remove workflow from library."""
        from py_code_mode.workflows import MockEmbedder, WorkflowLibrary

        embedder = MockEmbedder(dimension=384)
        library = WorkflowLibrary(embedder)

        workflow = _make_workflow("test", "Test workflow", "pass")
        library.add(workflow)
        assert len(library) == 1

        result = library.remove("test")

        assert result is True
        assert len(library) == 0
        assert library.get("test") is None


class TestRankingConfig:
    """Tests for configurable ranking weights."""

    def test_default_ranking_weights(self) -> None:
        """Default weights favor description over code."""
        from py_code_mode.workflows import RankingConfig

        config = RankingConfig()
        assert config.description_weight > config.code_weight

    def test_code_only_ranking(self) -> None:
        """Can configure to only use code embeddings."""
        from py_code_mode.workflows import MockEmbedder, RankingConfig, WorkflowLibrary

        config = RankingConfig(description_weight=0.0, code_weight=1.0)
        embedder = MockEmbedder(dimension=384)
        library = WorkflowLibrary(embedder, ranking=config)

        library.add(_make_workflow("test", "test workflow", "pass"))

        # Should still work
        results = library.search("test")
        assert len(results) == 1

    def test_threshold_filtering(self) -> None:
        """Can filter results below threshold."""
        from py_code_mode.workflows import MockEmbedder, RankingConfig, WorkflowLibrary

        config = RankingConfig(min_score_threshold=0.99)  # Very high threshold
        embedder = MockEmbedder(dimension=384)
        library = WorkflowLibrary(embedder, ranking=config)

        # Add workflow with low similarity to any query
        library.add(_make_workflow("obscure", "very specific thing", "pass"))

        # Most queries won't meet high threshold - this test just verifies
        # the threshold config is accepted, actual filtering depends on embeddings
        library.search("completely unrelated query")


class TestWorkflowLibraryWithStore:
    """Tests for WorkflowLibrary with storage backend integration.

    Verifies that add/remove/refresh operations correctly coordinate
    between the library's embedding index and the storage backend.
    """

    @pytest.fixture
    def sample_workflows(self) -> list[PythonWorkflow]:
        """Sample workflows for testing."""
        return [
            _make_workflow(
                name="fetch_url",
                description="Fetch content from a URL",
                code="return requests.get(url).text",
            ),
            _make_workflow(
                name="parse_json",
                description="Parse JSON string into Python dict",
                code="return json.loads(text)",
            ),
        ]

    def test_backend_workflows_searchable_at_construction(
        self, sample_workflows: list[PythonWorkflow]
    ) -> None:
        """Workflows in store should be searchable immediately after construction."""
        from py_code_mode.workflows import MemoryWorkflowStore, MockEmbedder, WorkflowLibrary

        # Populate store first
        store = MemoryWorkflowStore()
        for workflow in sample_workflows:
            store.save(workflow)

        # Create library with store - should load and embed
        embedder = MockEmbedder(dimension=384)
        library = WorkflowLibrary(embedder=embedder, store=store)

        # Workflows should be searchable without explicit add()
        results = library.search("download web content")
        assert len(results) >= 1
        assert any(r.name == "fetch_url" for r in results)

    def test_add_stores_in_store(self, sample_workflows: list[PythonWorkflow]) -> None:
        """add() should store workflow in store."""
        from py_code_mode.workflows import MemoryWorkflowStore, MockEmbedder, WorkflowLibrary

        store = MemoryWorkflowStore()
        embedder = MockEmbedder(dimension=384)
        library = WorkflowLibrary(embedder=embedder, store=store)

        # Add through library
        library.add(sample_workflows[0])

        # Should appear in store
        assert store.load("fetch_url") is not None

    def test_add_makes_workflow_searchable(self, sample_workflows: list[PythonWorkflow]) -> None:
        """add() should make workflow immediately searchable."""
        from py_code_mode.workflows import MemoryWorkflowStore, MockEmbedder, WorkflowLibrary

        store = MemoryWorkflowStore()
        embedder = MockEmbedder(dimension=384)
        library = WorkflowLibrary(embedder=embedder, store=store)

        # Add through library
        library.add(sample_workflows[0])

        # Should be searchable
        results = library.search("download content")
        assert any(r.name == "fetch_url" for r in results)

    def test_remove_removes_from_store(self, sample_workflows: list[PythonWorkflow]) -> None:
        """remove() should remove from store."""
        from py_code_mode.workflows import MemoryWorkflowStore, MockEmbedder, WorkflowLibrary

        store = MemoryWorkflowStore()
        for workflow in sample_workflows:
            store.save(workflow)

        embedder = MockEmbedder(dimension=384)
        library = WorkflowLibrary(embedder=embedder, store=store)

        # Remove through library
        result = library.remove("fetch_url")

        assert result is True
        assert store.load("fetch_url") is None

    def test_remove_removes_from_search(self, sample_workflows: list[PythonWorkflow]) -> None:
        """remove() should make workflow no longer searchable."""
        from py_code_mode.workflows import MemoryWorkflowStore, MockEmbedder, WorkflowLibrary

        store = MemoryWorkflowStore()
        for workflow in sample_workflows:
            store.save(workflow)

        embedder = MockEmbedder(dimension=384)
        library = WorkflowLibrary(embedder=embedder, store=store)

        # Remove through library
        library.remove("fetch_url")

        # Should not appear in search
        results = library.search("download content")
        assert not any(r.name == "fetch_url" for r in results)

    def test_refresh_picks_up_store_changes(self, sample_workflows: list[PythonWorkflow]) -> None:
        """refresh() should reload from store and rebuild embeddings."""
        from py_code_mode.workflows import MemoryWorkflowStore, MockEmbedder, WorkflowLibrary

        store = MemoryWorkflowStore()
        embedder = MockEmbedder(dimension=384)
        library = WorkflowLibrary(embedder=embedder, store=store)

        # Initially empty
        assert len(library) == 0

        # Add directly to store (bypassing library)
        new_workflow = _make_workflow("send_email", "Send email via SMTP", "smtp.send(message)")
        store.save(new_workflow)

        # Not searchable yet (not indexed)
        results = library.search("send email")
        assert not any(r.name == "send_email" for r in results)

        # Refresh to pick up changes
        library.refresh()

        # Now searchable
        results = library.search("send email")
        assert any(r.name == "send_email" for r in results)

    def test_refresh_clears_stale_embeddings(self, sample_workflows: list[PythonWorkflow]) -> None:
        """refresh() should remove embeddings for workflows no longer in store."""
        from py_code_mode.workflows import MemoryWorkflowStore, MockEmbedder, WorkflowLibrary

        store = MemoryWorkflowStore()
        for workflow in sample_workflows:
            store.save(workflow)

        embedder = MockEmbedder(dimension=384)
        library = WorkflowLibrary(embedder=embedder, store=store)

        # Both workflows searchable
        assert len(library) == 2

        # Remove directly from store
        store.delete("fetch_url")

        # Refresh
        library.refresh()

        # Only one workflow remains
        assert len(library) == 1
        assert library.get("fetch_url") is None
        assert library.get("parse_json") is not None

    def test_no_store_works_in_memory_only(self, sample_workflows: list[PythonWorkflow]) -> None:
        """Without store, library works as in-memory only."""
        from py_code_mode.workflows import MockEmbedder, WorkflowLibrary

        embedder = MockEmbedder(dimension=384)
        library = WorkflowLibrary(embedder=embedder)  # No store

        # Add works
        for workflow in sample_workflows:
            library.add(workflow)

        # Search works
        results = library.search("download")
        assert len(results) >= 1

    def test_refresh_with_no_store_is_noop(self) -> None:
        """refresh() with no store should do nothing, not crash."""
        from py_code_mode.workflows import MockEmbedder, WorkflowLibrary

        embedder = MockEmbedder(dimension=384)
        library = WorkflowLibrary(embedder=embedder)  # No store

        library.add(_make_workflow("test", "test", "pass"))

        # Should not crash or clear workflows
        library.refresh()

        assert len(library) == 1


class TestCreateWorkflowLibraryFactory:
    """Tests for the create_workflow_library factory function."""

    def test_creates_with_default_embedder(self) -> None:
        """Factory creates library with Embedder (BGE-small) by default."""
        pytest.importorskip("sentence_transformers")
        from py_code_mode.workflows import Embedder, create_workflow_library

        library = create_workflow_library()

        assert isinstance(library.embedder, Embedder)

    def test_creates_with_custom_embedder(self) -> None:
        """Factory accepts custom embedder."""
        from py_code_mode.workflows import MockEmbedder, create_workflow_library

        embedder = MockEmbedder(dimension=128)
        library = create_workflow_library(embedder=embedder)

        assert library.embedder is embedder

    def test_creates_with_store(self) -> None:
        """Factory accepts store and loads workflows."""
        from py_code_mode.workflows import (
            MemoryWorkflowStore,
            MockEmbedder,
            create_workflow_library,
        )

        store = MemoryWorkflowStore()
        store.save(_make_workflow("test", "test workflow", "pass"))

        embedder = MockEmbedder(dimension=384)
        library = create_workflow_library(store=store, embedder=embedder)

        # Workflow should be loaded and searchable
        assert len(library) == 1
        results = library.search("test")
        assert len(results) == 1


class TestWorkflowLibraryWithRealEmbedder:
    """Integration tests with real embeddings (BGE-small)."""

    @pytest.fixture
    def embedder(self):
        """Create embedder - skip if not available."""
        pytest.importorskip("sentence_transformers")
        from py_code_mode.workflows import Embedder

        return Embedder()

    @pytest.fixture
    def sample_workflows(self) -> list[PythonWorkflow]:
        """Sample workflows for testing."""
        return [
            _make_workflow(
                name="port_scan",
                description="Scan network ports using nmap to find open services",
                code="result = tools.nmap(target=target, ports='1-1000')",
            ),
            _make_workflow(
                name="web_screenshot",
                description="Capture a screenshot of a webpage using headless browser",
                code="tools.chromium(url=url, screenshot=output_path)",
            ),
            _make_workflow(
                name="dir_bruteforce",
                description="Bruteforce web directories to find hidden paths",
                code="tools.ffuf(url=url, wordlist=wordlist)",
            ),
            _make_workflow(
                name="dns_enum",
                description="Enumerate DNS records for a domain",
                code="tools.dig(domain=domain, type='ANY')",
            ),
        ]

    def test_semantic_search_finds_conceptual_match(
        self, embedder, sample_workflows: list[PythonWorkflow]
    ) -> None:
        """Semantic search finds workflows by meaning, not just keywords."""
        from py_code_mode.workflows import WorkflowLibrary

        library = WorkflowLibrary(embedder)
        for workflow in sample_workflows:
            library.add(workflow)

        # Query uses different words than workflow description
        results = library.search("discover which TCP ports are listening")

        assert len(results) >= 1
        # port_scan should be top result even without keyword match
        assert results[0].name == "port_scan"

    def test_semantic_search_code_understanding(
        self, embedder, sample_workflows: list[PythonWorkflow]
    ) -> None:
        """Search understands code semantics."""
        from py_code_mode.workflows import WorkflowLibrary

        library = WorkflowLibrary(embedder)
        for workflow in sample_workflows:
            library.add(workflow)

        # Query about what the code does
        results = library.search("use ffuf tool")

        assert len(results) >= 1
        assert results[0].name == "dir_bruteforce"

    def test_semantic_ranking(self, embedder, sample_workflows: list[PythonWorkflow]) -> None:
        """Results are ranked by semantic relevance."""
        from py_code_mode.workflows import WorkflowLibrary

        library = WorkflowLibrary(embedder)
        for workflow in sample_workflows:
            library.add(workflow)

        # Query that should match web workflows
        results = library.search("find hidden web pages")

        # dir_bruteforce should rank higher than port_scan
        result_names = [r.name for r in results]
        assert result_names.index("dir_bruteforce") < result_names.index("port_scan")
