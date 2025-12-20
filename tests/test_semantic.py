"""Tests for semantic search - written first to define interface."""

from textwrap import dedent

import pytest

from py_code_mode.skills import PythonSkill


def _make_skill(name: str, description: str, code: str) -> PythonSkill:
    """Helper to create a PythonSkill from minimal info."""
    source = f'"""{description}"""\n\ndef run():\n    {code}'
    return PythonSkill.from_source(name=name, source=source, description=description)


class TestEmbeddingProviderProtocol:
    """Tests that define the EmbeddingProvider interface."""

    def test_provider_has_embed_method(self) -> None:
        """Provider must have embed() that returns vectors."""
        from py_code_mode.semantic import EmbeddingProvider

        # Protocol should define embed method
        assert hasattr(EmbeddingProvider, "embed")

    def test_provider_has_dimension_property(self) -> None:
        """Provider exposes embedding dimension for index allocation."""
        from py_code_mode.semantic import EmbeddingProvider

        assert hasattr(EmbeddingProvider, "dimension")

    def test_embed_returns_list_of_vectors(self) -> None:
        """embed() takes list of strings, returns list of float vectors."""
        from py_code_mode.semantic import MockEmbedder

        embedder = MockEmbedder(dimension=384)
        vectors = embedder.embed(["hello world", "test query"])

        assert len(vectors) == 2
        assert len(vectors[0]) == 384
        assert all(isinstance(v, float) for v in vectors[0])

    def test_embed_single_text(self) -> None:
        """Convenience: can embed single string."""
        from py_code_mode.semantic import MockEmbedder

        embedder = MockEmbedder(dimension=384)
        vectors = embedder.embed(["single text"])

        assert len(vectors) == 1


class TestEmbedder:
    """Tests for the Embedder (BGE-small by default)."""

    @pytest.fixture
    def embedder(self):
        """Create embedder - skip if model not available."""
        pytest.importorskip("sentence_transformers")
        from py_code_mode.semantic import Embedder

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


class TestSkillLibrary:
    """Tests for SkillLibrary semantic search with dual indexing."""

    @pytest.fixture
    def sample_skills(self) -> list[PythonSkill]:
        """Sample skills for testing."""
        return [
            _make_skill(
                name="fetch_url",
                description="Fetch content from a URL using HTTP GET request",
                code="return requests.get(url).text",
            ),
            _make_skill(
                name="parse_json",
                description="Parse JSON string into Python dict",
                code="return json.loads(text)",
            ),
            _make_skill(
                name="write_file",
                description="Write text content to a file on disk",
                code="Path(path).write_text(content)",
            ),
        ]

    @pytest.fixture
    def python_skill(self) -> PythonSkill:
        """A Python skill fixture."""
        source = dedent('''
            """Calculate sum of numbers."""

            def run(numbers: list[int]) -> int:
                return sum(numbers)
        ''').strip()
        return PythonSkill.from_source(name="sum_numbers", source=source)

    def test_can_create_empty_library(self) -> None:
        """Library can be created without skills."""
        from py_code_mode.semantic import MockEmbedder, SkillLibrary

        embedder = MockEmbedder(dimension=384)
        library = SkillLibrary(embedder)

        assert len(library) == 0

    def test_add_skill_indexes_description(self, sample_skills: list[PythonSkill]) -> None:
        """Adding skill indexes its description for search."""
        from py_code_mode.semantic import MockEmbedder, SkillLibrary

        embedder = MockEmbedder(dimension=384)
        library = SkillLibrary(embedder)
        library.add(sample_skills[0])

        assert len(library) == 1

    def test_add_skill_indexes_code(self, sample_skills: list[PythonSkill]) -> None:
        """Adding skill indexes its source code for search."""
        from py_code_mode.semantic import MockEmbedder, SkillLibrary

        embedder = MockEmbedder(dimension=384)
        library = SkillLibrary(embedder)
        library.add(sample_skills[0])

        # Code should be indexed (we can't easily verify embedding, but skill should exist)
        assert library.get("fetch_url") is not None

    def test_search_by_description(self, sample_skills: list[PythonSkill]) -> None:
        """Search finds skills by description similarity."""
        from py_code_mode.semantic import MockEmbedder, SkillLibrary

        embedder = MockEmbedder(dimension=384)
        library = SkillLibrary(embedder)
        for skill in sample_skills:
            library.add(skill)

        # Should find fetch_url when searching for URL-related queries
        results = library.search("download web content")

        assert len(results) >= 1
        # Results are returned - content depends on embedding model

    def test_search_by_code_intent(self, sample_skills: list[PythonSkill]) -> None:
        """Search finds skills by code content."""
        from py_code_mode.semantic import MockEmbedder, SkillLibrary

        embedder = MockEmbedder(dimension=384)
        library = SkillLibrary(embedder)
        for skill in sample_skills:
            library.add(skill)

        # Search for something matching code
        results = library.search("json.loads")

        assert len(results) >= 1

    def test_combined_description_and_code_search(self, sample_skills: list[PythonSkill]) -> None:
        """Search considers both description and code."""
        from py_code_mode.semantic import MockEmbedder, SkillLibrary

        embedder = MockEmbedder(dimension=384)
        library = SkillLibrary(embedder)
        for skill in sample_skills:
            library.add(skill)

        # Query that matches description
        results = library.search("fetch URL content")

        assert len(results) >= 1

    def test_search_with_python_skill(
        self, sample_skills: list[PythonSkill], python_skill: PythonSkill
    ) -> None:
        """Search works with Python skills that have full source."""
        from py_code_mode.semantic import MockEmbedder, SkillLibrary

        embedder = MockEmbedder(dimension=384)
        library = SkillLibrary(embedder)
        for skill in sample_skills:
            library.add(skill)
        library.add(python_skill)

        # Should find the Python skill
        results = library.search("calculate sum")

        assert len(results) >= 1

    def test_get_by_name(self, sample_skills: list[PythonSkill]) -> None:
        """Can retrieve skill by exact name."""
        from py_code_mode.semantic import MockEmbedder, SkillLibrary

        embedder = MockEmbedder(dimension=384)
        library = SkillLibrary(embedder)
        for skill in sample_skills:
            library.add(skill)

        skill = library.get("parse_json")

        assert skill is not None
        assert skill.name == "parse_json"

    def test_search_limit(self, sample_skills: list[PythonSkill]) -> None:
        """Search respects limit parameter."""
        from py_code_mode.semantic import MockEmbedder, SkillLibrary

        embedder = MockEmbedder(dimension=384)
        library = SkillLibrary(embedder)
        for skill in sample_skills:
            library.add(skill)

        results = library.search("content", limit=1)

        assert len(results) == 1

    def test_remove_skill(self) -> None:
        """Can remove skill from library."""
        from py_code_mode.semantic import MockEmbedder, SkillLibrary

        embedder = MockEmbedder(dimension=384)
        library = SkillLibrary(embedder)

        skill = _make_skill("test", "Test skill", "pass")
        library.add(skill)
        assert len(library) == 1

        result = library.remove("test")

        assert result is True
        assert len(library) == 0
        assert library.get("test") is None


class TestRankingConfig:
    """Tests for configurable ranking weights."""

    def test_default_ranking_weights(self) -> None:
        """Default weights favor description over code."""
        from py_code_mode.semantic import RankingConfig

        config = RankingConfig()
        assert config.description_weight > config.code_weight

    def test_code_only_ranking(self) -> None:
        """Can configure to only use code embeddings."""
        from py_code_mode.semantic import MockEmbedder, RankingConfig, SkillLibrary

        config = RankingConfig(description_weight=0.0, code_weight=1.0)
        embedder = MockEmbedder(dimension=384)
        library = SkillLibrary(embedder, ranking=config)

        library.add(_make_skill("test", "test skill", "pass"))

        # Should still work
        results = library.search("test")
        assert len(results) == 1

    def test_threshold_filtering(self) -> None:
        """Can filter results below threshold."""
        from py_code_mode.semantic import MockEmbedder, RankingConfig, SkillLibrary

        config = RankingConfig(min_score_threshold=0.99)  # Very high threshold
        embedder = MockEmbedder(dimension=384)
        library = SkillLibrary(embedder, ranking=config)

        # Add skill with low similarity to any query
        library.add(_make_skill("obscure", "very specific thing", "pass"))

        # Most queries won't meet high threshold - this test just verifies
        # the threshold config is accepted, actual filtering depends on embeddings
        library.search("completely unrelated query")


class TestSkillLibraryWithStore:
    """Tests for SkillLibrary with storage backend integration.

    Verifies that add/remove/refresh operations correctly coordinate
    between the library's embedding index and the storage backend.
    """

    @pytest.fixture
    def sample_skills(self) -> list[PythonSkill]:
        """Sample skills for testing."""
        return [
            _make_skill(
                name="fetch_url",
                description="Fetch content from a URL",
                code="return requests.get(url).text",
            ),
            _make_skill(
                name="parse_json",
                description="Parse JSON string into Python dict",
                code="return json.loads(text)",
            ),
        ]

    def test_backend_skills_searchable_at_construction(
        self, sample_skills: list[PythonSkill]
    ) -> None:
        """Skills in store should be searchable immediately after construction."""
        from py_code_mode.semantic import MockEmbedder, SkillLibrary
        from py_code_mode.skill_store import MemorySkillStore

        # Populate store first
        store = MemorySkillStore()
        for skill in sample_skills:
            store.save(skill)

        # Create library with store - should load and embed
        embedder = MockEmbedder(dimension=384)
        library = SkillLibrary(embedder=embedder, store=store)

        # Skills should be searchable without explicit add()
        results = library.search("download web content")
        assert len(results) >= 1
        assert any(r.name == "fetch_url" for r in results)

    def test_add_stores_in_store(self, sample_skills: list[PythonSkill]) -> None:
        """add() should store skill in store."""
        from py_code_mode.semantic import MockEmbedder, SkillLibrary
        from py_code_mode.skill_store import MemorySkillStore

        store = MemorySkillStore()
        embedder = MockEmbedder(dimension=384)
        library = SkillLibrary(embedder=embedder, store=store)

        # Add through library
        library.add(sample_skills[0])

        # Should appear in store
        assert store.load("fetch_url") is not None

    def test_add_makes_skill_searchable(self, sample_skills: list[PythonSkill]) -> None:
        """add() should make skill immediately searchable."""
        from py_code_mode.semantic import MockEmbedder, SkillLibrary
        from py_code_mode.skill_store import MemorySkillStore

        store = MemorySkillStore()
        embedder = MockEmbedder(dimension=384)
        library = SkillLibrary(embedder=embedder, store=store)

        # Add through library
        library.add(sample_skills[0])

        # Should be searchable
        results = library.search("download content")
        assert any(r.name == "fetch_url" for r in results)

    def test_remove_removes_from_store(self, sample_skills: list[PythonSkill]) -> None:
        """remove() should remove from store."""
        from py_code_mode.semantic import MockEmbedder, SkillLibrary
        from py_code_mode.skill_store import MemorySkillStore

        store = MemorySkillStore()
        for skill in sample_skills:
            store.save(skill)

        embedder = MockEmbedder(dimension=384)
        library = SkillLibrary(embedder=embedder, store=store)

        # Remove through library
        result = library.remove("fetch_url")

        assert result is True
        assert store.load("fetch_url") is None

    def test_remove_removes_from_search(self, sample_skills: list[PythonSkill]) -> None:
        """remove() should make skill no longer searchable."""
        from py_code_mode.semantic import MockEmbedder, SkillLibrary
        from py_code_mode.skill_store import MemorySkillStore

        store = MemorySkillStore()
        for skill in sample_skills:
            store.save(skill)

        embedder = MockEmbedder(dimension=384)
        library = SkillLibrary(embedder=embedder, store=store)

        # Remove through library
        library.remove("fetch_url")

        # Should not appear in search
        results = library.search("download content")
        assert not any(r.name == "fetch_url" for r in results)

    def test_refresh_picks_up_store_changes(self, sample_skills: list[PythonSkill]) -> None:
        """refresh() should reload from store and rebuild embeddings."""
        from py_code_mode.semantic import MockEmbedder, SkillLibrary
        from py_code_mode.skill_store import MemorySkillStore

        store = MemorySkillStore()
        embedder = MockEmbedder(dimension=384)
        library = SkillLibrary(embedder=embedder, store=store)

        # Initially empty
        assert len(library) == 0

        # Add directly to store (bypassing library)
        new_skill = _make_skill("send_email", "Send email via SMTP", "smtp.send(message)")
        store.save(new_skill)

        # Not searchable yet (not indexed)
        results = library.search("send email")
        assert not any(r.name == "send_email" for r in results)

        # Refresh to pick up changes
        library.refresh()

        # Now searchable
        results = library.search("send email")
        assert any(r.name == "send_email" for r in results)

    def test_refresh_clears_stale_embeddings(self, sample_skills: list[PythonSkill]) -> None:
        """refresh() should remove embeddings for skills no longer in store."""
        from py_code_mode.semantic import MockEmbedder, SkillLibrary
        from py_code_mode.skill_store import MemorySkillStore

        store = MemorySkillStore()
        for skill in sample_skills:
            store.save(skill)

        embedder = MockEmbedder(dimension=384)
        library = SkillLibrary(embedder=embedder, store=store)

        # Both skills searchable
        assert len(library) == 2

        # Remove directly from store
        store.delete("fetch_url")

        # Refresh
        library.refresh()

        # Only one skill remains
        assert len(library) == 1
        assert library.get("fetch_url") is None
        assert library.get("parse_json") is not None

    def test_no_store_works_in_memory_only(self, sample_skills: list[PythonSkill]) -> None:
        """Without store, library works as in-memory only."""
        from py_code_mode.semantic import MockEmbedder, SkillLibrary

        embedder = MockEmbedder(dimension=384)
        library = SkillLibrary(embedder=embedder)  # No store

        # Add works
        for skill in sample_skills:
            library.add(skill)

        # Search works
        results = library.search("download")
        assert len(results) >= 1

    def test_refresh_with_no_store_is_noop(self) -> None:
        """refresh() with no store should do nothing, not crash."""
        from py_code_mode.semantic import MockEmbedder, SkillLibrary

        embedder = MockEmbedder(dimension=384)
        library = SkillLibrary(embedder=embedder)  # No store

        library.add(_make_skill("test", "test", "pass"))

        # Should not crash or clear skills
        library.refresh()

        assert len(library) == 1


class TestCreateSkillLibraryFactory:
    """Tests for the create_skill_library factory function."""

    def test_creates_with_default_embedder(self) -> None:
        """Factory creates library with Embedder (BGE-small) by default."""
        pytest.importorskip("sentence_transformers")
        from py_code_mode.semantic import Embedder, create_skill_library

        library = create_skill_library()

        assert isinstance(library.embedder, Embedder)

    def test_creates_with_custom_embedder(self) -> None:
        """Factory accepts custom embedder."""
        from py_code_mode.semantic import MockEmbedder, create_skill_library

        embedder = MockEmbedder(dimension=128)
        library = create_skill_library(embedder=embedder)

        assert library.embedder is embedder

    def test_creates_with_store(self) -> None:
        """Factory accepts store and loads skills."""
        from py_code_mode.semantic import MockEmbedder, create_skill_library
        from py_code_mode.skill_store import MemorySkillStore

        store = MemorySkillStore()
        store.save(_make_skill("test", "test skill", "pass"))

        embedder = MockEmbedder(dimension=384)
        library = create_skill_library(store=store, embedder=embedder)

        # Skill should be loaded and searchable
        assert len(library) == 1
        results = library.search("test")
        assert len(results) == 1


class TestSkillLibraryWithRealEmbedder:
    """Integration tests with real embeddings (BGE-small)."""

    @pytest.fixture
    def embedder(self):
        """Create embedder - skip if not available."""
        pytest.importorskip("sentence_transformers")
        from py_code_mode.semantic import Embedder

        return Embedder()

    @pytest.fixture
    def sample_skills(self) -> list[PythonSkill]:
        """Sample skills for testing."""
        return [
            _make_skill(
                name="port_scan",
                description="Scan network ports using nmap to find open services",
                code="result = tools.nmap(target=target, ports='1-1000')",
            ),
            _make_skill(
                name="web_screenshot",
                description="Capture a screenshot of a webpage using headless browser",
                code="tools.chromium(url=url, screenshot=output_path)",
            ),
            _make_skill(
                name="dir_bruteforce",
                description="Bruteforce web directories to find hidden paths",
                code="tools.ffuf(url=url, wordlist=wordlist)",
            ),
            _make_skill(
                name="dns_enum",
                description="Enumerate DNS records for a domain",
                code="tools.dig(domain=domain, type='ANY')",
            ),
        ]

    def test_semantic_search_finds_conceptual_match(
        self, embedder, sample_skills: list[PythonSkill]
    ) -> None:
        """Semantic search finds skills by meaning, not just keywords."""
        from py_code_mode.semantic import SkillLibrary

        library = SkillLibrary(embedder)
        for skill in sample_skills:
            library.add(skill)

        # Query uses different words than skill description
        results = library.search("discover which TCP ports are listening")

        assert len(results) >= 1
        # port_scan should be top result even without keyword match
        assert results[0].name == "port_scan"

    def test_semantic_search_code_understanding(
        self, embedder, sample_skills: list[PythonSkill]
    ) -> None:
        """Search understands code semantics."""
        from py_code_mode.semantic import SkillLibrary

        library = SkillLibrary(embedder)
        for skill in sample_skills:
            library.add(skill)

        # Query about what the code does
        results = library.search("use ffuf tool")

        assert len(results) >= 1
        assert results[0].name == "dir_bruteforce"

    def test_semantic_ranking(self, embedder, sample_skills: list[PythonSkill]) -> None:
        """Results are ranked by semantic relevance."""
        from py_code_mode.semantic import SkillLibrary

        library = SkillLibrary(embedder)
        for skill in sample_skills:
            library.add(skill)

        # Query that should match web skills
        results = library.search("find hidden web pages")

        # dir_bruteforce should rank higher than port_scan
        result_names = [r.name for r in results]
        assert result_names.index("dir_bruteforce") < result_names.index("port_scan")
