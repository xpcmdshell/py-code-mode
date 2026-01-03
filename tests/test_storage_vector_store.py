"""Tests for VectorStore integration into StorageBackend implementations.

Phase 4: Storage Backend Integration

This module tests that FileStorage and RedisStorage properly integrate
with VectorStore implementations, providing vector stores to SkillLibrary
for semantic search.

TDD RED phase: These tests define the interface before implementation.
They will fail until:
1. FileStorage.get_vector_store() is implemented
2. RedisStorage.get_vector_store() is implemented
3. FileStorageAccess gains vectors_path field
4. RedisStorageAccess gains vectors_prefix field
5. Storage.get_skill_library() passes vector_store to create_skill_library()
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

from py_code_mode.storage import FileStorage, RedisStorage

if TYPE_CHECKING:
    from tests.conftest import MockRedisClient


# =============================================================================
# Phase 4.1: FileStorage.get_vector_store()
# =============================================================================


class TestFileStorageVectorStoreIntegration:
    """Tests for FileStorage vector store integration."""

    def test_get_vector_store_method_exists(self, tmp_path: Path) -> None:
        """FileStorage has get_vector_store() method.

        Breaks when: Method doesn't exist on FileStorage.
        """
        storage = FileStorage(tmp_path)
        assert hasattr(storage, "get_vector_store")
        assert callable(storage.get_vector_store)

    def test_get_vector_store_returns_chroma_when_available(self, tmp_path: Path) -> None:
        """get_vector_store() returns ChromaVectorStore when chromadb installed.

        Breaks when: Returns None despite chromadb being available.
        """
        # Assume chromadb is installed in test environment
        storage = FileStorage(tmp_path)

        vector_store = storage.get_vector_store()

        # Should return ChromaVectorStore if chromadb available
        assert vector_store is not None
        # Check it has VectorStore protocol methods
        assert hasattr(vector_store, "add")
        assert hasattr(vector_store, "remove")
        assert hasattr(vector_store, "search")
        assert hasattr(vector_store, "count")

    def test_get_vector_store_uses_correct_path(self, tmp_path: Path) -> None:
        """get_vector_store() uses {base_path}/vectors/ directory.

        Breaks when: Vector store uses wrong directory or doesn't create it.
        """
        storage = FileStorage(tmp_path)

        vector_store = storage.get_vector_store()

        if vector_store is not None:
            # Expected vectors directory
            expected_path = tmp_path / "vectors"
            # ChromaVectorStore should have created this directory
            assert expected_path.exists()
            assert expected_path.is_dir()

    @patch("py_code_mode.storage.backends.ChromaVectorStore", None)
    def test_get_vector_store_returns_none_when_chromadb_unavailable(self, tmp_path: Path) -> None:
        """get_vector_store() returns None when chromadb not installed.

        Breaks when: Raises ImportError instead of graceful fallback.
        """
        storage = FileStorage(tmp_path)

        # Mock chromadb not being available
        with patch.dict("sys.modules", {"chromadb": None}):
            vector_store = storage.get_vector_store()

        assert vector_store is None

    def test_get_vector_store_creates_embedder(self, tmp_path: Path) -> None:
        """get_vector_store() creates Embedder for the vector store.

        Breaks when: Vector store created without embedder, search fails.
        """
        storage = FileStorage(tmp_path)

        vector_store = storage.get_vector_store()

        if vector_store is not None:
            # Should have an embedder to generate vectors
            model_info = vector_store.get_model_info()
            assert model_info.dimension > 0  # Valid dimension


# =============================================================================
# Phase 4.2: FileStorage.get_skill_library() with vector_store
# =============================================================================


class TestFileStorageSkillLibraryVectorStoreIntegration:
    """Tests for SkillLibrary receiving vector_store from FileStorage."""

    def test_skill_library_has_vector_store_attribute(self, tmp_path: Path) -> None:
        """SkillLibrary created by FileStorage has vector_store attribute.

        Breaks when: create_skill_library() not called with vector_store parameter.
        """
        storage = FileStorage(tmp_path)

        library = storage.get_skill_library()

        # Should have vector_store attribute
        assert hasattr(library, "vector_store")

    def test_skill_library_vector_store_matches_get_vector_store(self, tmp_path: Path) -> None:
        """SkillLibrary.vector_store is same instance as storage.get_vector_store().

        Breaks when: Different vector store instances created.
        """
        storage = FileStorage(tmp_path)

        vector_store = storage.get_vector_store()
        library = storage.get_skill_library()

        # Should be the same instance (or both None)
        assert library.vector_store is vector_store

    def test_skill_library_uses_vector_store_for_search(self, tmp_path: Path) -> None:
        """SkillLibrary.search() uses vector_store when available.

        Breaks when: Vector store not used for semantic search.
        """
        from py_code_mode.skills import PythonSkill

        storage = FileStorage(tmp_path)
        library = storage.get_skill_library()

        # Add a skill with distinctive description
        skill = PythonSkill.from_source(
            name="calculate_total",
            source="async def run(numbers): return sum(numbers)",
            description="Add up all numbers in a list",
        )
        library.add(skill)

        # Search by semantic meaning
        results = library.search("sum values together")

        # Should find the skill via semantic similarity
        assert len(results) > 0
        assert any(r.name == "calculate_total" for r in results)


# =============================================================================
# Phase 4.3: RedisStorage.get_vector_store() (placeholder for Phase 6)
# =============================================================================


class TestRedisStorageVectorStorePlaceholder:
    """Tests for RedisStorage vector store integration (Phase 6 placeholder)."""

    def test_get_vector_store_method_exists(self, mock_redis: MockRedisClient) -> None:
        """RedisStorage has get_vector_store() method.

        Breaks when: Method doesn't exist on RedisStorage.
        """
        storage = RedisStorage(redis=mock_redis, prefix="test")
        assert hasattr(storage, "get_vector_store")
        assert callable(storage.get_vector_store)

    def test_get_vector_store_returns_none_for_now(self, mock_redis: MockRedisClient) -> None:
        """get_vector_store() returns None (RedisVectorStore not implemented yet).

        Breaks when: Returns non-None value before RedisVectorStore exists.
        """
        storage = RedisStorage(redis=mock_redis, prefix="test")

        vector_store = storage.get_vector_store()

        # Phase 6 will implement RedisVectorStore, for now should be None
        assert vector_store is None


# =============================================================================
# Phase 4.4: FileStorageAccess.vectors_path field
# =============================================================================


class TestFileStorageAccessVectorsPath:
    """Tests for vectors_path field in FileStorageAccess."""

    def test_file_storage_access_has_vectors_path_field(self, tmp_path: Path) -> None:
        """FileStorageAccess has vectors_path field.

        Breaks when: Field doesn't exist in dataclass definition.
        """
        storage = FileStorage(tmp_path)

        access = storage.get_serializable_access()

        assert hasattr(access, "vectors_path")

    def test_vectors_path_is_optional(self, tmp_path: Path) -> None:
        """vectors_path can be None when vector store unavailable.

        Breaks when: Field is not Optional[Path].
        """
        storage = FileStorage(tmp_path)

        # Mock chromadb being unavailable
        with patch.object(storage, "get_vector_store", return_value=None):
            access = storage.get_serializable_access()

        # Should be None when vector store not available
        # (or set to path if chromadb is available)
        assert access.vectors_path is None or isinstance(access.vectors_path, Path)

    def test_vectors_path_points_to_vectors_directory(self, tmp_path: Path) -> None:
        """vectors_path points to {base_path}/vectors/ when vector store available.

        Breaks when: Path doesn't match expected vectors directory.
        """
        storage = FileStorage(tmp_path)

        access = storage.get_serializable_access()

        if access.vectors_path is not None:
            expected_path = tmp_path / "vectors"
            assert access.vectors_path == expected_path

    def test_vectors_path_is_absolute(self, tmp_path: Path) -> None:
        """vectors_path is absolute path (for cross-process use).

        Breaks when: Relative path returned, subprocess can't find vectors.
        """
        storage = FileStorage(tmp_path)

        access = storage.get_serializable_access()

        if access.vectors_path is not None:
            assert access.vectors_path.is_absolute()


# =============================================================================
# Phase 4.5: RedisStorageAccess.vectors_prefix field (placeholder)
# =============================================================================


class TestRedisStorageAccessVectorsPrefixPlaceholder:
    """Tests for vectors_prefix field in RedisStorageAccess (Phase 6 placeholder)."""

    def test_redis_storage_access_has_vectors_prefix_field(
        self, mock_redis: MockRedisClient
    ) -> None:
        """RedisStorageAccess has vectors_prefix field.

        Breaks when: Field doesn't exist in dataclass definition.
        """
        storage = RedisStorage(redis=mock_redis, prefix="test")

        access = storage.get_serializable_access()

        assert hasattr(access, "vectors_prefix")

    def test_vectors_prefix_is_optional(self, mock_redis: MockRedisClient) -> None:
        """vectors_prefix can be None when RedisVectorStore not implemented.

        Breaks when: Field is not Optional[str].
        """
        storage = RedisStorage(redis=mock_redis, prefix="test")

        access = storage.get_serializable_access()

        # Should be None until Phase 6 implements RedisVectorStore
        assert access.vectors_prefix is None or isinstance(access.vectors_prefix, str)

    def test_vectors_prefix_follows_pattern_when_implemented(
        self, mock_redis: MockRedisClient
    ) -> None:
        """vectors_prefix follows {prefix}:vectors pattern when available.

        Breaks when: Prefix format doesn't match other prefixes.
        """
        storage = RedisStorage(redis=mock_redis, prefix="myapp")

        access = storage.get_serializable_access()

        # When implemented, should follow the pattern
        if access.vectors_prefix is not None:
            assert access.vectors_prefix == "myapp:vectors"


# =============================================================================
# Integration Tests
# =============================================================================


class TestStorageVectorStoreIntegration:
    """Integration tests for storage + vector store + skill library."""

    def test_file_storage_end_to_end_semantic_search(self, tmp_path: Path) -> None:
        """Complete workflow: FileStorage -> VectorStore -> SkillLibrary -> search.

        User journey: Developer uses FileStorage with semantic search.
        Breaks when: Any link in the chain fails.
        """
        from py_code_mode.skills import PythonSkill

        storage = FileStorage(tmp_path)
        library = storage.get_skill_library()

        # Add skills with semantic descriptions
        library.add(
            PythonSkill.from_source(
                name="http_get",
                source="async def run(url): import requests; return requests.get(url)",
                description="Fetch data from a URL using HTTP GET request",
            )
        )
        library.add(
            PythonSkill.from_source(
                name="parse_json",
                source="async def run(text): import json; return json.loads(text)",
                description="Parse JSON string into Python object",
            )
        )

        # Search by semantic meaning (not exact name)
        results = library.search("download webpage")

        # Should find http_get via semantic similarity
        assert len(results) > 0
        skill_names = [r.name for r in results]
        assert "http_get" in skill_names

    def test_vector_store_persists_across_storage_instances(self, tmp_path: Path) -> None:
        """Vector store persists when FileStorage recreated.

        Breaks when: Vectors not saved to disk, lost on restart.
        """
        from py_code_mode.skills import PythonSkill

        # First session: create skill
        storage1 = FileStorage(tmp_path)
        library1 = storage1.get_skill_library()
        library1.add(
            PythonSkill.from_source(
                name="test_skill",
                source="async def run(): return 1",
                description="A test skill for persistence",
            )
        )

        # Second session: new storage instance
        storage2 = FileStorage(tmp_path)
        library2 = storage2.get_skill_library()

        # Should still find the skill (vectors persisted)
        results = library2.search("test skill")
        assert len(results) > 0
        assert any(r.name == "test_skill" for r in results)

    def test_storage_access_includes_vector_store_path(self, tmp_path: Path) -> None:
        """get_serializable_access() includes vectors_path for subprocess.

        Breaks when: Subprocess can't reconstruct vector store from access descriptor.
        """
        storage = FileStorage(tmp_path)

        # Force vector store creation
        vector_store = storage.get_vector_store()
        assert vector_store is not None

        access = storage.get_serializable_access()

        # Should include vectors_path
        assert access.vectors_path is not None
        assert access.vectors_path.exists()


# =============================================================================
# Negative Tests
# =============================================================================


class TestVectorStoreEdgeCases:
    """Edge cases and error handling for vector store integration."""

    def test_skill_library_works_without_vector_store(self, tmp_path: Path) -> None:
        """SkillLibrary works when vector_store is None (fallback mode).

        Breaks when: Library requires vector store, fails when chromadb unavailable.
        """
        from py_code_mode.skills import PythonSkill

        storage = FileStorage(tmp_path)

        # Mock vector store being unavailable
        with patch.object(storage, "get_vector_store", return_value=None):
            library = storage.get_skill_library()

        # Should still work for basic operations
        skill = PythonSkill.from_source(
            name="basic",
            source="async def run(): return 1",
            description="Basic skill",
        )
        library.add(skill)

        # Search should still work (using fallback embedder)
        results = library.search("basic")
        assert len(results) > 0

    def test_vector_store_handles_empty_skills_directory(self, tmp_path: Path) -> None:
        """Vector store handles empty skills directory gracefully.

        Breaks when: Vector store crashes on empty collection.
        """
        storage = FileStorage(tmp_path)
        library = storage.get_skill_library()

        # Search with no skills should return empty
        results = library.search("anything")
        assert results == []

    def test_vector_store_count_matches_skill_count(self, tmp_path: Path) -> None:
        """vector_store.count() matches number of skills in library.

        Breaks when: Vector count diverges from skill count.
        """
        from py_code_mode.skills import PythonSkill

        storage = FileStorage(tmp_path)
        library = storage.get_skill_library()
        vector_store = storage.get_vector_store()

        # Add skills
        for i in range(3):
            library.add(
                PythonSkill.from_source(
                    name=f"skill_{i}",
                    source="async def run(): return 1",
                    description=f"Skill number {i}",
                )
            )

        # Counts should match
        if vector_store is not None:
            assert vector_store.count() == 3
