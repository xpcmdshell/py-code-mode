"""Tests for SkillLibrary VectorStore integration - TDD RED phase.

These tests define the new behavior we want:
- SkillLibrary accepts vector_store parameter
- Search delegates to VectorStore when provided
- Content hash change detection skips re-embedding when unchanged
- Fallback to in-memory when vector_store=None
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from py_code_mode.skills import PythonSkill
from py_code_mode.skills.vector_store import ModelInfo, SearchResult, VectorStore


def _make_skill(name: str, description: str, code: str) -> PythonSkill:
    """Helper to create a PythonSkill from minimal info."""
    source = f'"""{description}"""\n\ndef run():\n    {code}'
    return PythonSkill.from_source(name=name, source=source, description=description)


@dataclass
class MockVectorStore:
    """Mock VectorStore that records calls for verification."""

    # Record what was called
    add_calls: list[tuple[str, str, str, str]]
    remove_calls: list[str]
    search_calls: list[tuple[str, int, float, float]]
    get_content_hash_calls: list[str]

    # State
    _store: dict[str, dict[str, Any]]  # id -> {hash, description, source}
    _model_info: ModelInfo

    def __init__(self, model_info: ModelInfo | None = None):
        self.add_calls = []
        self.remove_calls = []
        self.search_calls = []
        self.get_content_hash_calls = []
        self._store = {}
        self._model_info = model_info or ModelInfo(
            model_name="mock-model", dimension=384, version="1"
        )

    def add(self, id: str, description: str, source: str, content_hash: str) -> None:
        """Record add call and update store."""
        self.add_calls.append((id, description, source, content_hash))
        self._store[id] = {
            "hash": content_hash,
            "description": description,
            "source": source,
        }

    def remove(self, id: str) -> bool:
        """Record remove call."""
        self.remove_calls.append(id)
        if id in self._store:
            del self._store[id]
            return True
        return False

    def search(
        self,
        query: str,
        limit: int = 10,
        desc_weight: float = 0.7,
        code_weight: float = 0.3,
    ) -> list[SearchResult]:
        """Record search call and return mock results."""
        self.search_calls.append((query, limit, desc_weight, code_weight))

        # Return all stored skills as results (mock similarity)
        results = []
        for skill_id, data in self._store.items():
            # Mock score based on presence of query term in description
            score = 0.8 if query.lower() in data["description"].lower() else 0.5
            results.append(SearchResult(id=skill_id, score=score, metadata={"mock": True}))

        # Sort by score descending
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    def get_content_hash(self, id: str) -> str | None:
        """Record get_content_hash call and return stored hash."""
        self.get_content_hash_calls.append(id)
        data = self._store.get(id)
        return data["hash"] if data else None

    def get_model_info(self) -> ModelInfo:
        """Return model info."""
        return self._model_info

    def clear(self) -> None:
        """Clear all embeddings."""
        self._store.clear()

    def count(self) -> int:
        """Return count of stored skills."""
        return len(self._store)


class TestSkillLibraryParameterAcceptance:
    """Test that SkillLibrary accepts vector_store parameter."""

    def test_accepts_vector_store_parameter(self) -> None:
        """SkillLibrary constructor should accept vector_store parameter.

        This test will FAIL because SkillLibrary doesn't accept vector_store yet.
        """
        from py_code_mode.skills import MockEmbedder, SkillLibrary

        embedder = MockEmbedder(dimension=384)
        vector_store = MockVectorStore()

        # This should work but will fail - parameter doesn't exist yet
        library = SkillLibrary(embedder=embedder, vector_store=vector_store)

        assert library.vector_store is vector_store

    def test_works_with_vector_store_none(self) -> None:
        """SkillLibrary should work with vector_store=None (current behavior).

        This ensures backward compatibility.
        """
        from py_code_mode.skills import MockEmbedder, SkillLibrary

        embedder = MockEmbedder(dimension=384)

        # This should work - None is default
        library = SkillLibrary(embedder=embedder, vector_store=None)

        assert library.vector_store is None

    def test_works_with_vector_store_instance(self) -> None:
        """SkillLibrary should work with a VectorStore instance."""
        from py_code_mode.skills import MockEmbedder, SkillLibrary

        embedder = MockEmbedder(dimension=384)
        vector_store = MockVectorStore()

        library = SkillLibrary(embedder=embedder, vector_store=vector_store)

        # Should store the vector_store
        assert isinstance(library.vector_store, VectorStore)


class TestSearchDelegation:
    """Test that search() delegates to VectorStore when provided."""

    def test_search_delegates_to_vector_store(self) -> None:
        """When vector_store provided, search() should delegate to vector_store.search().

        This test will FAIL because delegation logic doesn't exist yet.
        """
        from py_code_mode.skills import MockEmbedder, SkillLibrary

        embedder = MockEmbedder(dimension=384)
        vector_store = MockVectorStore()

        library = SkillLibrary(embedder=embedder, vector_store=vector_store)

        # Add a skill (so search has something to find)
        skill = _make_skill("test", "test skill", "pass")
        library.add(skill)

        # Search should delegate to vector_store
        library.search("test")

        # Verify delegation occurred
        assert len(vector_store.search_calls) == 1
        query, limit, desc_weight, code_weight = vector_store.search_calls[0]
        assert query == "test"
        assert limit == 10  # default

    def test_search_returns_python_skill_objects(self) -> None:
        """search() should return PythonSkill objects, not SearchResult.

        VectorStore.search() returns SearchResult, but SkillLibrary.search()
        should map those back to PythonSkill objects.
        """
        from py_code_mode.skills import MockEmbedder, SkillLibrary

        embedder = MockEmbedder(dimension=384)
        vector_store = MockVectorStore()

        library = SkillLibrary(embedder=embedder, vector_store=vector_store)

        skill = _make_skill(
            "fetch_url", "Fetch content from a URL", "return requests.get(url).text"
        )
        library.add(skill)

        results = library.search("download")

        # Should return PythonSkill objects
        assert len(results) >= 1
        assert all(isinstance(r, PythonSkill) for r in results)
        assert results[0].name == "fetch_url"

    def test_search_respects_limit_parameter(self) -> None:
        """search(limit=N) should pass limit to vector_store.search()."""
        from py_code_mode.skills import MockEmbedder, SkillLibrary

        embedder = MockEmbedder(dimension=384)
        vector_store = MockVectorStore()

        library = SkillLibrary(embedder=embedder, vector_store=vector_store)

        # Add multiple skills
        for i in range(5):
            library.add(_make_skill(f"skill_{i}", f"skill {i}", "pass"))

        # Search with custom limit
        results = library.search("skill", limit=3)

        # Verify limit was passed through
        assert len(vector_store.search_calls) == 1
        _, limit, _, _ = vector_store.search_calls[0]
        assert limit == 3

        # Results should respect limit
        assert len(results) <= 3

    def test_search_passes_ranking_config_weights(self) -> None:
        """search() should pass RankingConfig weights to vector_store.search()."""
        from py_code_mode.skills import MockEmbedder, RankingConfig, SkillLibrary

        embedder = MockEmbedder(dimension=384)
        vector_store = MockVectorStore()

        # Custom ranking config
        ranking = RankingConfig(description_weight=0.8, code_weight=0.2)

        library = SkillLibrary(
            embedder=embedder,
            vector_store=vector_store,
            ranking=ranking,
        )

        skill = _make_skill("test", "test", "pass")
        library.add(skill)

        library.search("test")

        # Verify weights were passed
        assert len(vector_store.search_calls) == 1
        _, _, desc_weight, code_weight = vector_store.search_calls[0]
        assert desc_weight == 0.8
        assert code_weight == 0.2

    def test_search_filters_missing_skills(self) -> None:
        """search() should filter out SearchResults whose IDs aren't in _skills.

        VectorStore might return stale results for deleted skills.
        SkillLibrary should filter those out.
        """
        from py_code_mode.skills import MockEmbedder, SkillLibrary

        embedder = MockEmbedder(dimension=384)
        vector_store = MockVectorStore()

        library = SkillLibrary(embedder=embedder, vector_store=vector_store)

        # Add skill to vector_store directly (bypassing library)
        vector_store.add("stale_skill", "stale", "pass", "hash123")

        # Search - should not crash, should filter out the stale result
        results = library.search("stale")

        # Should be empty (skill not in library._skills)
        assert len(results) == 0


class TestContentHashChangeDetection:
    """Test content hash change detection to skip re-embedding."""

    def test_index_skill_computes_content_hash(self) -> None:
        """_index_skill should compute content hash for the skill.

        This test will FAIL because hash computation doesn't exist yet.
        """
        from py_code_mode.skills import MockEmbedder, SkillLibrary
        from py_code_mode.skills.vector_store import compute_content_hash

        embedder = MockEmbedder(dimension=384)
        vector_store = MockVectorStore()

        library = SkillLibrary(embedder=embedder, vector_store=vector_store)

        skill = _make_skill("test", "test skill", "pass")

        # Index the skill
        library.add(skill)

        # Verify vector_store.add was called with correct hash
        assert len(vector_store.add_calls) == 1
        id, desc, source, content_hash = vector_store.add_calls[0]

        expected_hash = compute_content_hash(skill.description, skill.source)
        assert content_hash == expected_hash

    def test_unchanged_skill_skips_re_embedding(self) -> None:
        """When skill content hasn't changed, skip re-embedding.

        If vector_store.get_content_hash() returns same hash as current content,
        don't call vector_store.add() again.
        """
        from py_code_mode.skills import MockEmbedder, SkillLibrary
        from py_code_mode.skills.vector_store import compute_content_hash

        embedder = MockEmbedder(dimension=384)
        vector_store = MockVectorStore()

        library = SkillLibrary(embedder=embedder, vector_store=vector_store)

        skill = _make_skill("test", "test skill", "pass")

        # First add - should call vector_store.add()
        library.add(skill)
        assert len(vector_store.add_calls) == 1

        # Store the hash in vector_store (simulating it was already embedded)
        expected_hash = compute_content_hash(skill.description, skill.source)
        vector_store._store["test"]["hash"] = expected_hash

        # Re-index same skill (e.g., during refresh)
        library._index_skill(skill)

        # Should check hash but NOT call add() again (hash matches)
        assert len(vector_store.get_content_hash_calls) >= 1
        assert len(vector_store.add_calls) == 1  # Still just one add call

    def test_changed_skill_triggers_re_embedding(self) -> None:
        """When skill content changes, re-embed it.

        If vector_store.get_content_hash() returns different hash,
        call vector_store.add() with new embeddings.
        """
        from py_code_mode.skills import MockEmbedder, SkillLibrary
        from py_code_mode.skills.vector_store import compute_content_hash

        embedder = MockEmbedder(dimension=384)
        vector_store = MockVectorStore()

        library = SkillLibrary(embedder=embedder, vector_store=vector_store)

        skill_v1 = _make_skill("test", "version 1", "pass")

        # First add
        library.add(skill_v1)
        assert len(vector_store.add_calls) == 1

        # Store old hash
        old_hash = compute_content_hash(skill_v1.description, skill_v1.source)
        vector_store._store["test"]["hash"] = old_hash

        # Create modified version (different description)
        skill_v2 = _make_skill("test", "version 2 updated", "pass")

        # Re-index with new content
        library._index_skill(skill_v2)

        # Should detect hash change and call add() again
        assert len(vector_store.add_calls) == 2
        _, _, _, new_hash = vector_store.add_calls[1]

        expected_new_hash = compute_content_hash(skill_v2.description, skill_v2.source)
        assert new_hash == expected_new_hash
        assert new_hash != old_hash

    def test_new_skill_always_added_to_vector_store(self) -> None:
        """New skills (not in vector_store) should always get added."""
        from py_code_mode.skills import MockEmbedder, SkillLibrary

        embedder = MockEmbedder(dimension=384)
        vector_store = MockVectorStore()

        library = SkillLibrary(embedder=embedder, vector_store=vector_store)

        skill = _make_skill("new_skill", "brand new", "pass")

        # vector_store.get_content_hash() will return None (skill doesn't exist)
        library.add(skill)

        # Should add to vector_store
        assert len(vector_store.add_calls) == 1
        assert vector_store.add_calls[0][0] == "new_skill"


class TestFallbackBehavior:
    """Test that fallback to in-memory works when vector_store=None."""

    def test_vector_store_none_uses_in_memory_vectors(self) -> None:
        """When vector_store=None, should use existing in-memory behavior."""
        from py_code_mode.skills import MockEmbedder, SkillLibrary

        embedder = MockEmbedder(dimension=384)

        # No vector_store provided
        library = SkillLibrary(embedder=embedder)

        skill = _make_skill("test", "test skill", "pass")
        library.add(skill)

        # Should have populated in-memory vectors
        assert "test" in library._description_vectors
        assert "test" in library._code_vectors

    def test_vector_store_none_search_uses_cosine_similarity(self) -> None:
        """When vector_store=None, search() should use existing cosine_similarity logic."""
        from py_code_mode.skills import MockEmbedder, SkillLibrary

        embedder = MockEmbedder(dimension=384)
        library = SkillLibrary(embedder=embedder)  # No vector_store

        # Add skills
        skill1 = _make_skill("fetch_url", "Fetch content from URL", "return requests.get(url).text")
        skill2 = _make_skill("parse_json", "Parse JSON string", "return json.loads(text)")
        library.add(skill1)
        library.add(skill2)

        # Search should work (using in-memory cosine similarity)
        results = library.search("download")

        # Should return results (exact results depend on embeddings)
        assert isinstance(results, list)
        assert all(isinstance(r, PythonSkill) for r in results)


class TestCreateSkillLibraryFactory:
    """Test create_skill_library() factory accepts vector_store parameter."""

    def test_factory_accepts_vector_store_parameter(self) -> None:
        """create_skill_library() should accept vector_store parameter.

        This test will FAIL because the factory doesn't accept it yet.
        """
        from py_code_mode.skills import MockEmbedder, create_skill_library

        embedder = MockEmbedder(dimension=384)
        vector_store = MockVectorStore()

        # This should work but will fail
        library = create_skill_library(embedder=embedder, vector_store=vector_store)

        assert library.vector_store is vector_store

    def test_factory_passes_vector_store_to_skill_library(self) -> None:
        """Factory should pass vector_store to SkillLibrary constructor."""
        from py_code_mode.skills import MockEmbedder, create_skill_library

        embedder = MockEmbedder(dimension=384)
        vector_store = MockVectorStore()

        library = create_skill_library(embedder=embedder, vector_store=vector_store)

        # Library should have the vector_store
        assert library.vector_store is vector_store


class TestIndexSkillIntegration:
    """Test _index_skill integrates with vector_store."""

    def test_index_skill_adds_to_vector_store_when_provided(self) -> None:
        """_index_skill should add to vector_store when provided."""
        from py_code_mode.skills import MockEmbedder, SkillLibrary

        embedder = MockEmbedder(dimension=384)
        vector_store = MockVectorStore()

        library = SkillLibrary(embedder=embedder, vector_store=vector_store)

        skill = _make_skill("test", "test skill", "pass")

        # Index directly (bypassing add, to test _index_skill in isolation)
        library._index_skill(skill)

        # Should have called vector_store.add()
        assert len(vector_store.add_calls) == 1

    def test_index_skill_still_adds_to_skills_dict(self) -> None:
        """_index_skill should still add to _skills dict for get() by name."""
        from py_code_mode.skills import MockEmbedder, SkillLibrary

        embedder = MockEmbedder(dimension=384)
        vector_store = MockVectorStore()

        library = SkillLibrary(embedder=embedder, vector_store=vector_store)

        skill = _make_skill("test", "test skill", "pass")
        library._index_skill(skill)

        # Should be in _skills dict
        assert "test" in library._skills
        assert library.get("test") is not None

    def test_refresh_indexes_only_new_and_changed_skills(self) -> None:
        """refresh() should only index new/changed skills, skipping unchanged ones.

        When refresh() is called, unchanged skills are skipped via content hash
        checking. Only new skills (hash not found) or changed skills (hash mismatch)
        are re-indexed.
        """
        from py_code_mode.skills import MemorySkillStore, MockEmbedder, SkillLibrary

        embedder = MockEmbedder(dimension=384)
        vector_store = MockVectorStore()
        store = MemorySkillStore()

        # Populate store with skills
        skill1 = _make_skill("skill1", "first skill", "pass")
        skill2 = _make_skill("skill2", "second skill", "pass")
        store.save(skill1)
        store.save(skill2)

        # Create library - should index on construction
        library = SkillLibrary(embedder=embedder, vector_store=vector_store, store=store)

        # Should have indexed both skills
        initial_add_count = len(vector_store.add_calls)
        assert initial_add_count == 2

        # Add another skill to store (bypassing library)
        skill3 = _make_skill("skill3", "third skill", "pass")
        store.save(skill3)

        # Refresh to pick up changes
        library.refresh()

        # Should have indexed only the NEW skill (skill3)
        # Unchanged skills (skill1, skill2) are skipped via content hash match
        # Total adds should be initial + 1 (only skill3)
        assert len(vector_store.add_calls) == initial_add_count + 1

        # Verify the new skill was indexed
        last_add = vector_store.add_calls[-1]
        assert last_add[0] == "skill3"  # id is first element


class TestRemoveSkillVectorStore:
    """Test that remove() cleans up vector_store."""

    def test_remove_deletes_from_vector_store(self) -> None:
        """remove() should delete embeddings from vector_store."""
        from py_code_mode.skills import MockEmbedder, SkillLibrary

        embedder = MockEmbedder(dimension=384)
        vector_store = MockVectorStore()

        library = SkillLibrary(embedder=embedder, vector_store=vector_store)

        skill = _make_skill("test", "test skill", "pass")
        library.add(skill)

        # Remove the skill
        result = library.remove("test")

        assert result is True
        # Should have called vector_store.remove()
        assert len(vector_store.remove_calls) == 1
        assert vector_store.remove_calls[0] == "test"

    def test_remove_still_removes_from_skills_dict(self) -> None:
        """remove() should still remove from _skills dict (existing behavior)."""
        from py_code_mode.skills import MockEmbedder, SkillLibrary

        embedder = MockEmbedder(dimension=384)
        vector_store = MockVectorStore()

        library = SkillLibrary(embedder=embedder, vector_store=vector_store)

        skill = _make_skill("test", "test skill", "pass")
        library.add(skill)

        library.remove("test")

        # Should be gone from _skills
        assert "test" not in library._skills
        assert library.get("test") is None


class TestVectorStoreProtocolCompliance:
    """Test that MockVectorStore implements VectorStore protocol correctly."""

    def test_mock_vector_store_implements_protocol(self) -> None:
        """Verify MockVectorStore implements VectorStore protocol."""
        mock = MockVectorStore()

        # Should pass isinstance check
        assert isinstance(mock, VectorStore)

    def test_mock_vector_store_has_all_required_methods(self) -> None:
        """Verify MockVectorStore has all VectorStore methods."""
        mock = MockVectorStore()

        # All protocol methods should exist
        assert hasattr(mock, "add")
        assert hasattr(mock, "remove")
        assert hasattr(mock, "search")
        assert hasattr(mock, "get_content_hash")
        assert hasattr(mock, "get_model_info")
        assert hasattr(mock, "clear")
        assert hasattr(mock, "count")


class TestWarmStartupCaching:
    """Test that vector_store caching works across library instances."""

    def test_warm_startup_skips_embedding_for_unchanged_skills(self) -> None:
        """Warm startup should skip re-embedding unchanged skills.

        When SkillLibrary restarts with existing vector_store, unchanged skills
        should NOT be re-embedded.

        Scenario: Application restarts, creates new SkillLibrary with same vector_store.
        Expected: Embeddings cached in vector_store are reused, not regenerated.

        This test will FAIL because refresh() calls clear() which defeats caching.
        """
        from py_code_mode.skills import MemorySkillStore, MockEmbedder, SkillLibrary

        embedder = MockEmbedder(dimension=384)
        vector_store = MockVectorStore()
        store = MemorySkillStore()

        # Pre-populate store with a skill
        skill = _make_skill(
            "fetch_url", "Fetch content from a URL", "return requests.get(url).text"
        )
        store.save(skill)

        # First startup: create library, indexes the skill
        SkillLibrary(embedder=embedder, vector_store=vector_store, store=store)

        # Verify first startup called add() once
        assert len(vector_store.add_calls) == 1, "First startup should embed the skill"

        # SIMULATE RESTART: Create NEW SkillLibrary instance with SAME vector_store
        # (This is what happens when app restarts with persistent ChromaDB)
        SkillLibrary(embedder=embedder, vector_store=vector_store, store=store)

        # BUG: refresh() calls clear() which wipes the cache, so add() is called AGAIN
        # EXPECTED: add() should NOT be called again (content hash matches)
        assert len(vector_store.add_calls) == 1, (
            "Warm startup should skip re-embedding (content unchanged). "
            "If this fails, refresh() is calling clear() which defeats caching."
        )


class TestEndToEndVectorStoreWorkflow:
    """Integration test: end-to-end workflow with VectorStore."""

    def test_add_search_remove_workflow(self) -> None:
        """Full workflow: add skills, search, remove.

        This is the user journey test that exercises the full integration.
        """
        from py_code_mode.skills import MockEmbedder, SkillLibrary

        embedder = MockEmbedder(dimension=384)
        vector_store = MockVectorStore()

        library = SkillLibrary(embedder=embedder, vector_store=vector_store)

        # Add skills
        skill1 = _make_skill("fetch_url", "Fetch content from URL", "return requests.get(url).text")
        skill2 = _make_skill("parse_json", "Parse JSON string", "return json.loads(text)")
        skill3 = _make_skill("write_file", "Write text to file", "Path(path).write_text(content)")

        library.add(skill1)
        library.add(skill2)
        library.add(skill3)

        # Search should delegate to vector_store
        results = library.search("download")
        assert len(results) >= 1
        assert any(r.name == "fetch_url" for r in results)

        # Verify vector_store was used
        assert len(vector_store.search_calls) >= 1

        # Remove a skill
        library.remove("fetch_url")

        # Should have removed from vector_store
        assert "fetch_url" in vector_store.remove_calls

        # Search shouldn't find removed skill
        results = library.search("download")
        assert not any(r.name == "fetch_url" for r in results)

    def test_store_backed_library_with_vector_store(self) -> None:
        """SkillLibrary with both store and vector_store.

        This tests the three-layer architecture:
        - SkillStore: persistence
        - VectorStore: embedding cache
        - SkillLibrary: orchestration
        """
        from py_code_mode.skills import MemorySkillStore, MockEmbedder, SkillLibrary

        embedder = MockEmbedder(dimension=384)
        vector_store = MockVectorStore()
        store = MemorySkillStore()

        # Populate store
        skill1 = _make_skill("skill1", "first", "pass")
        skill2 = _make_skill("skill2", "second", "pass")
        store.save(skill1)
        store.save(skill2)

        # Create library with both store and vector_store
        library = SkillLibrary(embedder=embedder, vector_store=vector_store, store=store)

        # Should have loaded from store and indexed in vector_store
        assert len(library) == 2
        assert len(vector_store.add_calls) == 2

        # Search should use vector_store
        results = library.search("first")
        assert len(results) >= 1
        assert len(vector_store.search_calls) >= 1

        # Add new skill - should go to both store and vector_store
        skill3 = _make_skill("skill3", "third", "pass")
        library.add(skill3)

        assert store.exists("skill3")
        assert any(call[0] == "skill3" for call in vector_store.add_calls)
