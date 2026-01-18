"""Tests for WorkflowLibrary VectorStore integration - TDD RED phase.

These tests define the new behavior we want:
- WorkflowLibrary accepts vector_store parameter
- Search delegates to VectorStore when provided
- Content hash change detection skips re-embedding when unchanged
- Fallback to in-memory when vector_store=None
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from py_code_mode.workflows import PythonWorkflow
from py_code_mode.workflows.vector_store import ModelInfo, SearchResult, VectorStore


def _make_workflow(name: str, description: str, code: str) -> PythonWorkflow:
    """Helper to create a PythonWorkflow from minimal info."""
    source = f'"""{description}"""\n\nasync def run():\n    {code}'
    return PythonWorkflow.from_source(name=name, source=source, description=description)


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

        # Return all stored workflows as results (mock similarity)
        results = []
        for workflow_id, data in self._store.items():
            # Mock score based on presence of query term in description
            score = 0.8 if query.lower() in data["description"].lower() else 0.5
            results.append(SearchResult(id=workflow_id, score=score, metadata={"mock": True}))

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
        """Return count of stored workflows."""
        return len(self._store)


class TestWorkflowLibraryParameterAcceptance:
    """Test that WorkflowLibrary accepts vector_store parameter."""

    def test_accepts_vector_store_parameter(self) -> None:
        """WorkflowLibrary constructor should accept vector_store parameter.

        This test will FAIL because WorkflowLibrary doesn't accept vector_store yet.
        """
        from py_code_mode.workflows import MockEmbedder, WorkflowLibrary

        embedder = MockEmbedder(dimension=384)
        vector_store = MockVectorStore()

        # This should work but will fail - parameter doesn't exist yet
        library = WorkflowLibrary(embedder=embedder, vector_store=vector_store)

        assert library.vector_store is vector_store

    def test_works_with_vector_store_none(self) -> None:
        """WorkflowLibrary should work with vector_store=None (current behavior).

        This ensures backward compatibility.
        """
        from py_code_mode.workflows import MockEmbedder, WorkflowLibrary

        embedder = MockEmbedder(dimension=384)

        # This should work - None is default
        library = WorkflowLibrary(embedder=embedder, vector_store=None)

        assert library.vector_store is None

    def test_works_with_vector_store_instance(self) -> None:
        """WorkflowLibrary should work with a VectorStore instance."""
        from py_code_mode.workflows import MockEmbedder, WorkflowLibrary

        embedder = MockEmbedder(dimension=384)
        vector_store = MockVectorStore()

        library = WorkflowLibrary(embedder=embedder, vector_store=vector_store)

        # Should store the vector_store
        assert isinstance(library.vector_store, VectorStore)


class TestSearchDelegation:
    """Test that search() delegates to VectorStore when provided."""

    def test_search_delegates_to_vector_store(self) -> None:
        """When vector_store provided, search() should delegate to vector_store.search().

        This test will FAIL because delegation logic doesn't exist yet.
        """
        from py_code_mode.workflows import MockEmbedder, WorkflowLibrary

        embedder = MockEmbedder(dimension=384)
        vector_store = MockVectorStore()

        library = WorkflowLibrary(embedder=embedder, vector_store=vector_store)

        # Add a workflow (so search has something to find)
        workflow = _make_workflow("test", "test workflow", "pass")
        library.add(workflow)

        # Search should delegate to vector_store
        library.search("test")

        # Verify delegation occurred
        assert len(vector_store.search_calls) == 1
        query, limit, desc_weight, code_weight = vector_store.search_calls[0]
        assert query == "test"
        assert limit == 10  # default

    def test_search_returns_python_workflow_objects(self) -> None:
        """search() should return PythonWorkflow objects, not SearchResult.

        VectorStore.search() returns SearchResult, but WorkflowLibrary.search()
        should map those back to PythonWorkflow objects.
        """
        from py_code_mode.workflows import MockEmbedder, WorkflowLibrary

        embedder = MockEmbedder(dimension=384)
        vector_store = MockVectorStore()

        library = WorkflowLibrary(embedder=embedder, vector_store=vector_store)

        workflow = _make_workflow(
            "fetch_url", "Fetch content from a URL", "return requests.get(url).text"
        )
        library.add(workflow)

        results = library.search("download")

        # Should return PythonWorkflow objects
        assert len(results) >= 1
        assert all(isinstance(r, PythonWorkflow) for r in results)
        assert results[0].name == "fetch_url"

    def test_search_respects_limit_parameter(self) -> None:
        """search(limit=N) should pass limit to vector_store.search()."""
        from py_code_mode.workflows import MockEmbedder, WorkflowLibrary

        embedder = MockEmbedder(dimension=384)
        vector_store = MockVectorStore()

        library = WorkflowLibrary(embedder=embedder, vector_store=vector_store)

        # Add multiple workflows
        for i in range(5):
            library.add(_make_workflow(f"workflow_{i}", f"workflow {i}", "pass"))

        # Search with custom limit
        results = library.search("workflow", limit=3)

        # Verify limit was passed through
        assert len(vector_store.search_calls) == 1
        _, limit, _, _ = vector_store.search_calls[0]
        assert limit == 3

        # Results should respect limit
        assert len(results) <= 3

    def test_search_passes_ranking_config_weights(self) -> None:
        """search() should pass RankingConfig weights to vector_store.search()."""
        from py_code_mode.workflows import MockEmbedder, RankingConfig, WorkflowLibrary

        embedder = MockEmbedder(dimension=384)
        vector_store = MockVectorStore()

        # Custom ranking config
        ranking = RankingConfig(description_weight=0.8, code_weight=0.2)

        library = WorkflowLibrary(
            embedder=embedder,
            vector_store=vector_store,
            ranking=ranking,
        )

        workflow = _make_workflow("test", "test", "pass")
        library.add(workflow)

        library.search("test")

        # Verify weights were passed
        assert len(vector_store.search_calls) == 1
        _, _, desc_weight, code_weight = vector_store.search_calls[0]
        assert desc_weight == 0.8
        assert code_weight == 0.2

    def test_search_filters_missing_workflows(self) -> None:
        """search() should filter out SearchResults whose IDs aren't in _workflows.

        VectorStore might return stale results for deleted workflows.
        WorkflowLibrary should filter those out.
        """
        from py_code_mode.workflows import MockEmbedder, WorkflowLibrary

        embedder = MockEmbedder(dimension=384)
        vector_store = MockVectorStore()

        library = WorkflowLibrary(embedder=embedder, vector_store=vector_store)

        # Add workflow to vector_store directly (bypassing library)
        vector_store.add("stale_workflow", "stale", "pass", "hash123")

        # Search - should not crash, should filter out the stale result
        results = library.search("stale")

        # Should be empty (workflow not in library._workflows)
        assert len(results) == 0


class TestContentHashChangeDetection:
    """Test content hash change detection to skip re-embedding."""

    def test_index_workflow_computes_content_hash(self) -> None:
        """_index_workflow should compute content hash for the workflow.

        This test will FAIL because hash computation doesn't exist yet.
        """
        from py_code_mode.workflows import MockEmbedder, WorkflowLibrary
        from py_code_mode.workflows.vector_store import compute_content_hash

        embedder = MockEmbedder(dimension=384)
        vector_store = MockVectorStore()

        library = WorkflowLibrary(embedder=embedder, vector_store=vector_store)

        workflow = _make_workflow("test", "test workflow", "pass")

        # Index the workflow
        library.add(workflow)

        # Verify vector_store.add was called with correct hash
        assert len(vector_store.add_calls) == 1
        id, desc, source, content_hash = vector_store.add_calls[0]

        expected_hash = compute_content_hash(workflow.description, workflow.source)
        assert content_hash == expected_hash

    def test_unchanged_workflow_skips_re_embedding(self) -> None:
        """When workflow content hasn't changed, skip re-embedding.

        If vector_store.get_content_hash() returns same hash as current content,
        don't call vector_store.add() again.
        """
        from py_code_mode.workflows import MockEmbedder, WorkflowLibrary
        from py_code_mode.workflows.vector_store import compute_content_hash

        embedder = MockEmbedder(dimension=384)
        vector_store = MockVectorStore()

        library = WorkflowLibrary(embedder=embedder, vector_store=vector_store)

        workflow = _make_workflow("test", "test workflow", "pass")

        # First add - should call vector_store.add()
        library.add(workflow)
        assert len(vector_store.add_calls) == 1

        # Store the hash in vector_store (simulating it was already embedded)
        expected_hash = compute_content_hash(workflow.description, workflow.source)
        vector_store._store["test"]["hash"] = expected_hash

        # Re-index same workflow (e.g., during refresh)
        library._index_workflow(workflow)

        # Should check hash but NOT call add() again (hash matches)
        assert len(vector_store.get_content_hash_calls) >= 1
        assert len(vector_store.add_calls) == 1  # Still just one add call

    def test_changed_workflow_triggers_re_embedding(self) -> None:
        """When workflow content changes, re-embed it.

        If vector_store.get_content_hash() returns different hash,
        call vector_store.add() with new embeddings.
        """
        from py_code_mode.workflows import MockEmbedder, WorkflowLibrary
        from py_code_mode.workflows.vector_store import compute_content_hash

        embedder = MockEmbedder(dimension=384)
        vector_store = MockVectorStore()

        library = WorkflowLibrary(embedder=embedder, vector_store=vector_store)

        workflow_v1 = _make_workflow("test", "version 1", "pass")

        # First add
        library.add(workflow_v1)
        assert len(vector_store.add_calls) == 1

        # Store old hash
        old_hash = compute_content_hash(workflow_v1.description, workflow_v1.source)
        vector_store._store["test"]["hash"] = old_hash

        # Create modified version (different description)
        workflow_v2 = _make_workflow("test", "version 2 updated", "pass")

        # Re-index with new content
        library._index_workflow(workflow_v2)

        # Should detect hash change and call add() again
        assert len(vector_store.add_calls) == 2
        _, _, _, new_hash = vector_store.add_calls[1]

        expected_new_hash = compute_content_hash(workflow_v2.description, workflow_v2.source)
        assert new_hash == expected_new_hash
        assert new_hash != old_hash

    def test_new_workflow_always_added_to_vector_store(self) -> None:
        """New workflows (not in vector_store) should always get added."""
        from py_code_mode.workflows import MockEmbedder, WorkflowLibrary

        embedder = MockEmbedder(dimension=384)
        vector_store = MockVectorStore()

        library = WorkflowLibrary(embedder=embedder, vector_store=vector_store)

        workflow = _make_workflow("new_workflow", "brand new", "pass")

        # vector_store.get_content_hash() will return None (workflow doesn't exist)
        library.add(workflow)

        # Should add to vector_store
        assert len(vector_store.add_calls) == 1
        assert vector_store.add_calls[0][0] == "new_workflow"


class TestFallbackBehavior:
    """Test that fallback to in-memory works when vector_store=None."""

    def test_vector_store_none_uses_in_memory_vectors(self) -> None:
        """When vector_store=None, should use existing in-memory behavior."""
        from py_code_mode.workflows import MockEmbedder, WorkflowLibrary

        embedder = MockEmbedder(dimension=384)

        # No vector_store provided
        library = WorkflowLibrary(embedder=embedder)

        workflow = _make_workflow("test", "test workflow", "pass")
        library.add(workflow)

        # Should have populated in-memory vectors
        assert "test" in library._description_vectors
        assert "test" in library._code_vectors

    def test_vector_store_none_search_uses_cosine_similarity(self) -> None:
        """When vector_store=None, search() should use existing cosine_similarity logic."""
        from py_code_mode.workflows import MockEmbedder, WorkflowLibrary

        embedder = MockEmbedder(dimension=384)
        library = WorkflowLibrary(embedder=embedder)  # No vector_store

        # Add workflows
        workflow1 = _make_workflow(
            "fetch_url", "Fetch content from URL", "return requests.get(url).text"
        )
        workflow2 = _make_workflow("parse_json", "Parse JSON string", "return json.loads(text)")
        library.add(workflow1)
        library.add(workflow2)

        # Search should work (using in-memory cosine similarity)
        results = library.search("download")

        # Should return results (exact results depend on embeddings)
        assert isinstance(results, list)
        assert all(isinstance(r, PythonWorkflow) for r in results)


class TestCreateWorkflowLibraryFactory:
    """Test create_workflow_library() factory accepts vector_store parameter."""

    def test_factory_accepts_vector_store_parameter(self) -> None:
        """create_workflow_library() should accept vector_store parameter.

        This test will FAIL because the factory doesn't accept it yet.
        """
        from py_code_mode.workflows import MockEmbedder, create_workflow_library

        embedder = MockEmbedder(dimension=384)
        vector_store = MockVectorStore()

        # This should work but will fail
        library = create_workflow_library(embedder=embedder, vector_store=vector_store)

        assert library.vector_store is vector_store

    def test_factory_passes_vector_store_to_workflow_library(self) -> None:
        """Factory should pass vector_store to WorkflowLibrary constructor."""
        from py_code_mode.workflows import MockEmbedder, create_workflow_library

        embedder = MockEmbedder(dimension=384)
        vector_store = MockVectorStore()

        library = create_workflow_library(embedder=embedder, vector_store=vector_store)

        # Library should have the vector_store
        assert library.vector_store is vector_store


class TestIndexWorkflowIntegration:
    """Test _index_workflow integrates with vector_store."""

    def test_index_workflow_adds_to_vector_store_when_provided(self) -> None:
        """_index_workflow should add to vector_store when provided."""
        from py_code_mode.workflows import MockEmbedder, WorkflowLibrary

        embedder = MockEmbedder(dimension=384)
        vector_store = MockVectorStore()

        library = WorkflowLibrary(embedder=embedder, vector_store=vector_store)

        workflow = _make_workflow("test", "test workflow", "pass")

        # Index directly (bypassing add, to test _index_workflow in isolation)
        library._index_workflow(workflow)

        # Should have called vector_store.add()
        assert len(vector_store.add_calls) == 1

    def test_index_workflow_still_adds_to_workflows_dict(self) -> None:
        """_index_workflow should still add to _workflows dict for get() by name."""
        from py_code_mode.workflows import MockEmbedder, WorkflowLibrary

        embedder = MockEmbedder(dimension=384)
        vector_store = MockVectorStore()

        library = WorkflowLibrary(embedder=embedder, vector_store=vector_store)

        workflow = _make_workflow("test", "test workflow", "pass")
        library._index_workflow(workflow)

        # Should be in _workflows dict
        assert "test" in library._workflows
        assert library.get("test") is not None

    def test_refresh_indexes_only_new_and_changed_workflows(self) -> None:
        """refresh() should only index new/changed workflows, skipping unchanged ones.

        When refresh() is called, unchanged workflows are skipped via content hash
        checking. Only new workflows (hash not found) or changed workflows (hash mismatch)
        are re-indexed.
        """
        from py_code_mode.workflows import MemoryWorkflowStore, MockEmbedder, WorkflowLibrary

        embedder = MockEmbedder(dimension=384)
        vector_store = MockVectorStore()
        store = MemoryWorkflowStore()

        # Populate store with workflows
        workflow1 = _make_workflow("workflow1", "first workflow", "pass")
        workflow2 = _make_workflow("workflow2", "second workflow", "pass")
        store.save(workflow1)
        store.save(workflow2)

        # Create library - should index on construction
        library = WorkflowLibrary(embedder=embedder, vector_store=vector_store, store=store)

        # Should have indexed both workflows
        initial_add_count = len(vector_store.add_calls)
        assert initial_add_count == 2

        # Add another workflow to store (bypassing library)
        workflow3 = _make_workflow("workflow3", "third workflow", "pass")
        store.save(workflow3)

        # Refresh to pick up changes
        library.refresh()

        # Should have indexed only the NEW workflow (workflow3)
        # Unchanged workflows (workflow1, workflow2) are skipped via content hash match
        # Total adds should be initial + 1 (only workflow3)
        assert len(vector_store.add_calls) == initial_add_count + 1

        # Verify the new workflow was indexed
        last_add = vector_store.add_calls[-1]
        assert last_add[0] == "workflow3"  # id is first element


class TestRemoveWorkflowVectorStore:
    """Test that remove() cleans up vector_store."""

    def test_remove_deletes_from_vector_store(self) -> None:
        """remove() should delete embeddings from vector_store."""
        from py_code_mode.workflows import MockEmbedder, WorkflowLibrary

        embedder = MockEmbedder(dimension=384)
        vector_store = MockVectorStore()

        library = WorkflowLibrary(embedder=embedder, vector_store=vector_store)

        workflow = _make_workflow("test", "test workflow", "pass")
        library.add(workflow)

        # Remove the workflow
        result = library.remove("test")

        assert result is True
        # Should have called vector_store.remove()
        assert len(vector_store.remove_calls) == 1
        assert vector_store.remove_calls[0] == "test"

    def test_remove_still_removes_from_workflows_dict(self) -> None:
        """remove() should still remove from _workflows dict (existing behavior)."""
        from py_code_mode.workflows import MockEmbedder, WorkflowLibrary

        embedder = MockEmbedder(dimension=384)
        vector_store = MockVectorStore()

        library = WorkflowLibrary(embedder=embedder, vector_store=vector_store)

        workflow = _make_workflow("test", "test workflow", "pass")
        library.add(workflow)

        library.remove("test")

        # Should be gone from _workflows
        assert "test" not in library._workflows
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

    def test_warm_startup_skips_embedding_for_unchanged_workflows(self) -> None:
        """Warm startup should skip re-embedding unchanged workflows.

        When WorkflowLibrary restarts with existing vector_store, unchanged workflows
        should NOT be re-embedded.

        Scenario: Application restarts, creates new WorkflowLibrary with same vector_store.
        Expected: Embeddings cached in vector_store are reused, not regenerated.

        This test will FAIL because refresh() calls clear() which defeats caching.
        """
        from py_code_mode.workflows import MemoryWorkflowStore, MockEmbedder, WorkflowLibrary

        embedder = MockEmbedder(dimension=384)
        vector_store = MockVectorStore()
        store = MemoryWorkflowStore()

        # Pre-populate store with a workflow
        workflow = _make_workflow(
            "fetch_url", "Fetch content from a URL", "return requests.get(url).text"
        )
        store.save(workflow)

        # First startup: create library, indexes the workflow
        WorkflowLibrary(embedder=embedder, vector_store=vector_store, store=store)

        # Verify first startup called add() once
        assert len(vector_store.add_calls) == 1, "First startup should embed the workflow"

        # SIMULATE RESTART: Create NEW WorkflowLibrary instance with SAME vector_store
        # (This is what happens when app restarts with persistent ChromaDB)
        WorkflowLibrary(embedder=embedder, vector_store=vector_store, store=store)

        # BUG: refresh() calls clear() which wipes the cache, so add() is called AGAIN
        # EXPECTED: add() should NOT be called again (content hash matches)
        assert len(vector_store.add_calls) == 1, (
            "Warm startup should skip re-embedding (content unchanged). "
            "If this fails, refresh() is calling clear() which defeats caching."
        )


class TestEndToEndVectorStoreWorkflow:
    """Integration test: end-to-end workflow with VectorStore."""

    def test_add_search_remove_workflow(self) -> None:
        """Full workflow: add workflows, search, remove.

        This is the user journey test that exercises the full integration.
        """
        from py_code_mode.workflows import MockEmbedder, WorkflowLibrary

        embedder = MockEmbedder(dimension=384)
        vector_store = MockVectorStore()

        library = WorkflowLibrary(embedder=embedder, vector_store=vector_store)

        # Add workflows
        workflow1 = _make_workflow(
            "fetch_url", "Fetch content from URL", "return requests.get(url).text"
        )
        workflow2 = _make_workflow("parse_json", "Parse JSON string", "return json.loads(text)")
        workflow3 = _make_workflow(
            "write_file", "Write text to file", "Path(path).write_text(content)"
        )

        library.add(workflow1)
        library.add(workflow2)
        library.add(workflow3)

        # Search should delegate to vector_store
        results = library.search("download")
        assert len(results) >= 1
        assert any(r.name == "fetch_url" for r in results)

        # Verify vector_store was used
        assert len(vector_store.search_calls) >= 1

        # Remove a workflow
        library.remove("fetch_url")

        # Should have removed from vector_store
        assert "fetch_url" in vector_store.remove_calls

        # Search shouldn't find removed workflow
        results = library.search("download")
        assert not any(r.name == "fetch_url" for r in results)

    def test_store_backed_library_with_vector_store(self) -> None:
        """WorkflowLibrary with both store and vector_store.

        This tests the three-layer architecture:
        - WorkflowStore: persistence
        - VectorStore: embedding cache
        - WorkflowLibrary: orchestration
        """
        from py_code_mode.workflows import MemoryWorkflowStore, MockEmbedder, WorkflowLibrary

        embedder = MockEmbedder(dimension=384)
        vector_store = MockVectorStore()
        store = MemoryWorkflowStore()

        # Populate store
        workflow1 = _make_workflow("workflow1", "first", "pass")
        workflow2 = _make_workflow("workflow2", "second", "pass")
        store.save(workflow1)
        store.save(workflow2)

        # Create library with both store and vector_store
        library = WorkflowLibrary(embedder=embedder, vector_store=vector_store, store=store)

        # Should have loaded from store and indexed in vector_store
        assert len(library) == 2
        assert len(vector_store.add_calls) == 2

        # Search should use vector_store
        results = library.search("first")
        assert len(results) >= 1
        assert len(vector_store.search_calls) >= 1

        # Add new workflow - should go to both store and vector_store
        workflow3 = _make_workflow("workflow3", "third", "pass")
        library.add(workflow3)

        assert store.exists("workflow3")
        assert any(call[0] == "workflow3" for call in vector_store.add_calls)
