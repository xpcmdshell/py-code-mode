"""Tests for VectorStore protocol and core types - Phase 1 (TDD RED phase).

This test file defines the VectorStore interface through failing tests.
Tests fail because the implementation doesn't exist yet.
"""

from __future__ import annotations

import hashlib

import pytest


class TestVectorStoreProtocol:
    """Protocol compliance tests for VectorStore implementations."""

    def test_vector_store_protocol_exists(self) -> None:
        """VectorStore protocol should be importable from skills module."""
        from py_code_mode.skills.vector_store import VectorStore

        # Protocol should be runtime checkable
        from typing import Protocol, runtime_checkable

        assert isinstance(VectorStore, type)

    def test_protocol_has_add_method(self) -> None:
        """VectorStore must define add() method signature."""
        from py_code_mode.skills.vector_store import VectorStore

        # Protocol defines method signatures at class level
        assert hasattr(VectorStore, "add")

    def test_protocol_has_remove_method(self) -> None:
        """VectorStore must define remove() method signature."""
        from py_code_mode.skills.vector_store import VectorStore

        assert hasattr(VectorStore, "remove")

    def test_protocol_has_search_method(self) -> None:
        """VectorStore must define search() method signature."""
        from py_code_mode.skills.vector_store import VectorStore

        assert hasattr(VectorStore, "search")

    def test_protocol_has_get_content_hash_method(self) -> None:
        """VectorStore must define get_content_hash() for change detection."""
        from py_code_mode.skills.vector_store import VectorStore

        assert hasattr(VectorStore, "get_content_hash")

    def test_protocol_has_get_model_info_method(self) -> None:
        """VectorStore must define get_model_info() for model validation."""
        from py_code_mode.skills.vector_store import VectorStore

        assert hasattr(VectorStore, "get_model_info")

    def test_protocol_has_clear_method(self) -> None:
        """VectorStore must define clear() to reset index."""
        from py_code_mode.skills.vector_store import VectorStore

        assert hasattr(VectorStore, "clear")

    def test_protocol_has_count_method(self) -> None:
        """VectorStore must define count() to get indexed skill count."""
        from py_code_mode.skills.vector_store import VectorStore

        assert hasattr(VectorStore, "count")

    def test_protocol_is_runtime_checkable(self) -> None:
        """Protocol should support isinstance() checks."""
        from py_code_mode.skills.vector_store import VectorStore
        from typing import runtime_checkable

        # Check that VectorStore has the runtime_checkable marker
        # This allows isinstance(obj, VectorStore) to work
        assert hasattr(VectorStore, "__protocol_attrs__") or hasattr(
            VectorStore, "_is_protocol"
        )


class TestModelInfo:
    """Tests for ModelInfo dataclass."""

    def test_model_info_dataclass_exists(self) -> None:
        """ModelInfo should be importable and constructible."""
        from py_code_mode.skills.vector_store import ModelInfo

        info = ModelInfo(model_name="bge-small", dimension=384, version="1.5")

        assert info.model_name == "bge-small"
        assert info.dimension == 384
        assert info.version == "1.5"

    def test_model_info_is_frozen(self) -> None:
        """ModelInfo should be immutable (frozen dataclass)."""
        from py_code_mode.skills.vector_store import ModelInfo

        info = ModelInfo(model_name="bge-small", dimension=384, version="1.5")

        # Frozen dataclasses raise FrozenInstanceError on assignment
        with pytest.raises(Exception):  # dataclasses.FrozenInstanceError
            info.model_name = "different-model"  # type: ignore[misc]

    def test_model_info_equality(self) -> None:
        """ModelInfo instances with same values should be equal."""
        from py_code_mode.skills.vector_store import ModelInfo

        info1 = ModelInfo(model_name="bge-small", dimension=384, version="1.5")
        info2 = ModelInfo(model_name="bge-small", dimension=384, version="1.5")
        info3 = ModelInfo(model_name="bge-base", dimension=768, version="1.5")

        assert info1 == info2
        assert info1 != info3

    def test_model_info_hashable(self) -> None:
        """Frozen dataclass should be hashable for use in sets/dicts."""
        from py_code_mode.skills.vector_store import ModelInfo

        info1 = ModelInfo(model_name="bge-small", dimension=384, version="1.5")
        info2 = ModelInfo(model_name="bge-base", dimension=768, version="1.5")

        # Should be usable in sets
        model_set = {info1, info2}
        assert len(model_set) == 2
        assert info1 in model_set


class TestSearchResult:
    """Tests for SearchResult dataclass."""

    def test_search_result_dataclass_exists(self) -> None:
        """SearchResult should be importable and constructible."""
        from py_code_mode.skills.vector_store import SearchResult

        result = SearchResult(id="skill_name", score=0.85, metadata={"tags": ["network"]})

        assert result.id == "skill_name"
        assert result.score == 0.85
        assert result.metadata == {"tags": ["network"]}

    def test_search_result_is_frozen(self) -> None:
        """SearchResult should be immutable."""
        from py_code_mode.skills.vector_store import SearchResult

        result = SearchResult(id="skill_name", score=0.85, metadata={})

        with pytest.raises(Exception):  # dataclasses.FrozenInstanceError
            result.score = 0.95  # type: ignore[misc]

    def test_search_result_equality(self) -> None:
        """SearchResult instances with same values should be equal."""
        from py_code_mode.skills.vector_store import SearchResult

        r1 = SearchResult(id="skill", score=0.85, metadata={})
        r2 = SearchResult(id="skill", score=0.85, metadata={})
        r3 = SearchResult(id="skill", score=0.90, metadata={})

        assert r1 == r2
        assert r1 != r3

    def test_search_result_with_empty_metadata(self) -> None:
        """SearchResult should work with empty metadata dict."""
        from py_code_mode.skills.vector_store import SearchResult

        result = SearchResult(id="skill", score=0.75, metadata={})

        assert result.metadata == {}

    def test_search_result_ordering_by_score(self) -> None:
        """SearchResult should be comparable by score for sorting."""
        from py_code_mode.skills.vector_store import SearchResult

        r1 = SearchResult(id="a", score=0.9, metadata={})
        r2 = SearchResult(id="b", score=0.7, metadata={})
        r3 = SearchResult(id="c", score=0.95, metadata={})

        results = [r1, r2, r3]
        # Sort by score descending (highest scores first)
        sorted_results = sorted(results, key=lambda r: r.score, reverse=True)

        assert sorted_results[0].id == "c"
        assert sorted_results[1].id == "a"
        assert sorted_results[2].id == "b"


class TestContentHashUtility:
    """Tests for content hash computation utility."""

    def test_compute_content_hash_exists(self) -> None:
        """compute_content_hash() should be importable and callable."""
        from py_code_mode.skills.vector_store import compute_content_hash

        hash_value = compute_content_hash(
            description="Scan network ports",
            source='def run(): return "nmap"',
        )

        # Should return a string (hex digest)
        assert isinstance(hash_value, str)

    def test_content_hash_is_16_chars(self) -> None:
        """Hash should be 16-character hex string (8 bytes)."""
        from py_code_mode.skills.vector_store import compute_content_hash

        hash_value = compute_content_hash(description="test", source="def run(): pass")

        assert len(hash_value) == 16
        # Should be valid hex
        int(hash_value, 16)  # Raises ValueError if not hex

    def test_same_input_produces_same_hash(self) -> None:
        """Deterministic: same input should produce same hash."""
        from py_code_mode.skills.vector_store import compute_content_hash

        description = "Scan network ports"
        source = 'def run(target: str):\n    return f"nmap {target}"'

        hash1 = compute_content_hash(description, source)
        hash2 = compute_content_hash(description, source)

        assert hash1 == hash2

    def test_different_description_produces_different_hash(self) -> None:
        """Different description should change hash."""
        from py_code_mode.skills.vector_store import compute_content_hash

        source = "def run(): pass"

        hash1 = compute_content_hash("Description A", source)
        hash2 = compute_content_hash("Description B", source)

        assert hash1 != hash2

    def test_different_source_produces_different_hash(self) -> None:
        """Different source code should change hash."""
        from py_code_mode.skills.vector_store import compute_content_hash

        description = "Test skill"

        hash1 = compute_content_hash(description, "def run(): return 1")
        hash2 = compute_content_hash(description, "def run(): return 2")

        assert hash1 != hash2

    def test_whitespace_changes_affect_hash(self) -> None:
        """Whitespace is significant - changes should affect hash."""
        from py_code_mode.skills.vector_store import compute_content_hash

        description = "Test"
        source1 = "def run(): pass"
        source2 = "def run():  pass"  # Extra space

        hash1 = compute_content_hash(description, source1)
        hash2 = compute_content_hash(description, source2)

        assert hash1 != hash2

    def test_hash_uses_sha256_algorithm(self) -> None:
        """Hash should be first 16 chars of SHA-256 hex digest."""
        from py_code_mode.skills.vector_store import compute_content_hash

        description = "Test description"
        source = "def run(): pass"

        # Compute what the hash SHOULD be
        combined = f"{description}|||{source}"
        expected_hash = hashlib.sha256(combined.encode()).hexdigest()[:16]

        actual_hash = compute_content_hash(description, source)

        assert actual_hash == expected_hash

    def test_hash_separates_description_and_source(self) -> None:
        """Hash should use delimiter to prevent collision."""
        from py_code_mode.skills.vector_store import compute_content_hash

        # These would collide if we just concatenated without delimiter
        hash1 = compute_content_hash("AB", "C")
        hash2 = compute_content_hash("A", "BC")

        assert hash1 != hash2

    def test_empty_strings_produce_valid_hash(self) -> None:
        """Should handle empty description and source gracefully."""
        from py_code_mode.skills.vector_store import compute_content_hash

        hash_value = compute_content_hash("", "")

        assert isinstance(hash_value, str)
        assert len(hash_value) == 16


class TestVectorStoreSignatures:
    """Tests that verify method signatures match protocol definition.

    These tests create a minimal mock implementation to verify the protocol
    signatures are correct. Tests fail because VectorStore doesn't exist yet.
    """

    def test_add_signature_accepts_required_params(self) -> None:
        """add() should accept id, description, source, content_hash."""
        from py_code_mode.skills.vector_store import VectorStore

        class MinimalVectorStore:
            def add(
                self, id: str, description: str, source: str, content_hash: str
            ) -> None:
                pass

            def remove(self, id: str) -> bool:
                return True

            def search(
                self, query: str, limit: int, desc_weight: float, code_weight: float
            ) -> list:
                return []

            def get_content_hash(self, id: str) -> str | None:
                return None

            def get_model_info(self):
                from py_code_mode.skills.vector_store import ModelInfo

                return ModelInfo("test", 384, "1.0")

            def clear(self) -> None:
                pass

            def count(self) -> int:
                return 0

        store = MinimalVectorStore()
        assert isinstance(store, VectorStore)

        # Should be callable with these parameters
        store.add(
            id="test_skill",
            description="Test description",
            source="def run(): pass",
            content_hash="abcd1234",
        )

    def test_search_returns_list_of_search_results(self) -> None:
        """search() should return list[SearchResult]."""
        from py_code_mode.skills.vector_store import SearchResult, VectorStore

        class MinimalVectorStore:
            def add(
                self, id: str, description: str, source: str, content_hash: str
            ) -> None:
                pass

            def remove(self, id: str) -> bool:
                return True

            def search(
                self, query: str, limit: int, desc_weight: float, code_weight: float
            ) -> list[SearchResult]:
                return [SearchResult(id="test", score=0.9, metadata={})]

            def get_content_hash(self, id: str) -> str | None:
                return None

            def get_model_info(self):
                from py_code_mode.skills.vector_store import ModelInfo

                return ModelInfo("test", 384, "1.0")

            def clear(self) -> None:
                pass

            def count(self) -> int:
                return 0

        store = MinimalVectorStore()
        assert isinstance(store, VectorStore)

        results = store.search(query="test", limit=10, desc_weight=0.7, code_weight=0.3)

        assert isinstance(results, list)
        assert len(results) == 1
        assert isinstance(results[0], SearchResult)

    def test_get_model_info_returns_model_info(self) -> None:
        """get_model_info() should return ModelInfo dataclass."""
        from py_code_mode.skills.vector_store import ModelInfo, VectorStore

        class MinimalVectorStore:
            def add(
                self, id: str, description: str, source: str, content_hash: str
            ) -> None:
                pass

            def remove(self, id: str) -> bool:
                return True

            def search(
                self, query: str, limit: int, desc_weight: float, code_weight: float
            ) -> list:
                return []

            def get_content_hash(self, id: str) -> str | None:
                return None

            def get_model_info(self) -> ModelInfo:
                return ModelInfo(model_name="test", dimension=384, version="1.0")

            def clear(self) -> None:
                pass

            def count(self) -> int:
                return 0

        store = MinimalVectorStore()
        assert isinstance(store, VectorStore)

        info = store.get_model_info()

        assert isinstance(info, ModelInfo)
        assert info.model_name == "test"
        assert info.dimension == 384
