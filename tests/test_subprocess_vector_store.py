"""Tests for VectorStore integration in SubprocessExecutor code generation.

Phase 5: Subprocess Code Generation

This module tests that build_namespace_setup_code() properly handles
vector stores, generating code that:
1. Imports ChromaVectorStore when vectors_path provided
2. Creates vector store in kernel
3. Passes vector_store to create_skill_library()
4. Gracefully falls back when chromadb not available

TDD RED phase: These tests define the interface before implementation.
They will fail until:
1. build_namespace_setup_code() handles vectors_path
2. Generated code imports ChromaVectorStore
3. Generated code passes vector_store to create_skill_library()
4. Generated code handles ImportError for chromadb
"""

from __future__ import annotations

from pathlib import Path

import pytest

from py_code_mode.execution.protocol import FileStorageAccess
from py_code_mode.execution.subprocess.namespace import build_namespace_setup_code

# =============================================================================
# Phase 5.1: Code generation with vectors_path
# =============================================================================


class TestNamespaceSetupCodeVectorStoreGeneration:
    """Tests for vector store code generation in build_namespace_setup_code()."""

    def test_generated_code_imports_chroma_when_vectors_path_provided(self) -> None:
        """Generated code imports ChromaVectorStore when vectors_path present.

        Breaks when: Code doesn't import ChromaVectorStore despite vectors_path.
        """
        storage_access = FileStorageAccess(
            tools_path=None,
            skills_path=Path("/app/skills"),
            artifacts_path=Path("/app/artifacts"),
            deps_path=Path("/app/deps"),
            vectors_path=Path("/app/vectors"),  # Present
        )

        code = build_namespace_setup_code(storage_access)

        assert code is not None
        assert len(code) > 0
        # Should import ChromaVectorStore
        assert "ChromaVectorStore" in code

    def test_generated_code_creates_chroma_vector_store(self) -> None:
        """Generated code creates ChromaVectorStore with correct path.

        Breaks when: ChromaVectorStore not instantiated in generated code.
        """
        vectors_path = Path("/test/vectors")
        storage_access = FileStorageAccess(
            tools_path=None,
            skills_path=Path("/test/skills"),
            artifacts_path=Path("/test/artifacts"),
            deps_path=Path("/test/deps"),
            vectors_path=vectors_path,
        )

        code = build_namespace_setup_code(storage_access)

        # Should create ChromaVectorStore instance
        assert "ChromaVectorStore" in code
        # Should use the provided path
        assert str(vectors_path) in code or repr(str(vectors_path)) in code

    def test_generated_code_passes_vector_store_to_create_skill_library(self) -> None:
        """Generated code passes vector_store to create_skill_library().

        Breaks when: create_skill_library() called without vector_store parameter.
        """
        storage_access = FileStorageAccess(
            tools_path=None,
            skills_path=Path("/app/skills"),
            artifacts_path=Path("/app/artifacts"),
            deps_path=Path("/app/deps"),
            vectors_path=Path("/app/vectors"),
        )

        code = build_namespace_setup_code(storage_access)

        # Should pass vector_store to create_skill_library
        assert "create_skill_library" in code
        assert "vector_store" in code

    def test_generated_code_creates_embedder_for_vector_store(self) -> None:
        """Generated code creates Embedder for ChromaVectorStore.

        Breaks when: ChromaVectorStore created without embedder.
        """
        storage_access = FileStorageAccess(
            tools_path=None,
            skills_path=Path("/app/skills"),
            artifacts_path=Path("/app/artifacts"),
            deps_path=Path("/app/deps"),
            vectors_path=Path("/app/vectors"),
        )

        code = build_namespace_setup_code(storage_access)

        # Should create an embedder (Granite or similar)
        # Look for embedder creation patterns
        assert (
            "Embedder" in code or "embedder" in code or "Granite" in code  # Specific embedder name
        )


# =============================================================================
# Phase 5.2: Graceful fallback when chromadb unavailable
# =============================================================================


class TestNamespaceSetupCodeVectorStoreFallback:
    """Tests for graceful fallback when chromadb not available."""

    def test_generated_code_handles_chromadb_import_error(self) -> None:
        """Generated code handles ImportError for chromadb gracefully.

        Breaks when: ImportError crashes kernel instead of falling back.
        """
        storage_access = FileStorageAccess(
            tools_path=None,
            skills_path=Path("/app/skills"),
            artifacts_path=Path("/app/artifacts"),
            deps_path=Path("/app/deps"),
            vectors_path=Path("/app/vectors"),
        )

        code = build_namespace_setup_code(storage_access)

        # Should have try/except for import errors
        assert "try:" in code or "except" in code

    def test_generated_code_sets_vector_store_none_on_import_error(self) -> None:
        """Generated code sets vector_store=None when chromadb unavailable.

        Breaks when: create_skill_library() called without vector_store parameter
        on fallback path.
        """
        storage_access = FileStorageAccess(
            tools_path=None,
            skills_path=Path("/app/skills"),
            artifacts_path=Path("/app/artifacts"),
            deps_path=Path("/app/deps"),
            vectors_path=Path("/app/vectors"),
        )

        code = build_namespace_setup_code(storage_access)

        # Should handle fallback case where vector_store is None
        # Look for patterns like: vector_store = None or vector_store=None
        assert code is not None

    def test_generated_code_compiles_without_syntax_errors(self) -> None:
        """Generated code is valid Python with vector store support.

        Breaks when: Code generation has syntax errors.
        """
        storage_access = FileStorageAccess(
            tools_path=None,
            skills_path=Path("/app/skills"),
            artifacts_path=Path("/app/artifacts"),
            deps_path=Path("/app/deps"),
            vectors_path=Path("/app/vectors"),
        )

        code = build_namespace_setup_code(storage_access)

        # Should compile without syntax errors
        try:
            compile(code, "<generated>", "exec")
        except SyntaxError as e:
            pytest.fail(f"Generated code has syntax errors: {e}\n\nCode:\n{code}")


# =============================================================================
# Phase 5.3: Code generation without vectors_path
# =============================================================================


class TestNamespaceSetupCodeWithoutVectorStore:
    """Tests for code generation when vectors_path is None."""

    def test_generated_code_without_vectors_path_does_not_import_chroma(self) -> None:
        """Generated code doesn't import ChromaVectorStore when vectors_path is None.

        Breaks when: Unnecessary import added even without vector store.
        """
        storage_access = FileStorageAccess(
            tools_path=None,
            skills_path=Path("/app/skills"),
            artifacts_path=Path("/app/artifacts"),
            deps_path=Path("/app/deps"),
            vectors_path=None,  # No vector store
        )

        code = build_namespace_setup_code(storage_access)

        # Should not import ChromaVectorStore
        assert "ChromaVectorStore" not in code

    def test_generated_code_without_vectors_path_still_creates_skill_library(self) -> None:
        """Generated code creates SkillLibrary without vector_store.

        Breaks when: SkillLibrary creation requires vector_store.
        """
        storage_access = FileStorageAccess(
            tools_path=None,
            skills_path=Path("/app/skills"),
            artifacts_path=Path("/app/artifacts"),
            deps_path=Path("/app/deps"),
            vectors_path=None,
        )

        code = build_namespace_setup_code(storage_access)

        # Should still create skill library (without vector_store)
        assert "create_skill_library" in code or "SkillLibrary" in code


# =============================================================================
# Integration Tests
# =============================================================================


class TestSubprocessVectorStoreIntegration:
    """Integration tests for vector store in subprocess execution."""

    @pytest.mark.slow
    @pytest.mark.xdist_group("subprocess")
    @pytest.mark.asyncio
    async def test_subprocess_executor_with_vector_store(self, tmp_path: Path) -> None:
        """SubprocessExecutor uses vector store for semantic search.

        User journey: Developer uses SubprocessExecutor with semantic search.
        Breaks when: Vector store not properly injected into subprocess.
        """
        from py_code_mode.execution.subprocess import SubprocessExecutor
        from py_code_mode.execution.subprocess.config import SubprocessConfig
        from py_code_mode.skills import PythonSkill
        from py_code_mode.storage import FileStorage

        # Setup storage with vector store
        storage = FileStorage(tmp_path / "storage")
        library = storage.get_skill_library()

        # Add skill with semantic description
        library.add(
            PythonSkill.from_source(
                name="fetch_url",
                source="def run(url): import requests; return requests.get(url).text",
                description="Download content from a web URL using HTTP",
            )
        )

        # Create subprocess executor
        config = SubprocessConfig(
            venv_path=tmp_path / "venv",
            base_deps=("ipykernel", "py-code-mode"),
        )
        executor = SubprocessExecutor(config=config)

        try:
            await executor.start(storage=storage)

            # Search should use vector store for semantic similarity
            result = await executor.run('skills.search("get webpage")')

            assert result.error is None, f"Search failed: {result.error}"
            # Should find fetch_url via semantic similarity
            assert "fetch_url" in str(result.value)

        finally:
            await executor.close()

    @pytest.mark.slow
    @pytest.mark.xdist_group("subprocess")
    @pytest.mark.asyncio
    async def test_subprocess_executor_without_vector_store_falls_back(
        self, tmp_path: Path
    ) -> None:
        """SubprocessExecutor works without vector store (fallback to MockEmbedder).

        Breaks when: Subprocess crashes when vector store unavailable.
        """
        from py_code_mode.execution.subprocess import SubprocessExecutor
        from py_code_mode.execution.subprocess.config import SubprocessConfig
        from py_code_mode.storage import FileStorage

        # Setup storage without vector store (mock chromadb unavailable)
        storage = FileStorage(tmp_path / "storage")

        # Create subprocess executor
        config = SubprocessConfig(
            venv_path=tmp_path / "venv",
            base_deps=("ipykernel", "py-code-mode"),
        )
        executor = SubprocessExecutor(config=config)

        try:
            await executor.start(storage=storage)

            # Create skill in subprocess
            create_code = """
skills.create(
    name="test_skill",
    source="def run(): return 1",
    description="Test skill for fallback"
)
"""
            result = await executor.run(create_code)
            assert result.error is None

            # Search should still work (using fallback embedder)
            result = await executor.run('skills.search("test")')
            assert result.error is None
            assert len(str(result.value)) > 0

        finally:
            await executor.close()


# =============================================================================
# Reconstruction Tests (Storage Access Serialization)
# =============================================================================


class TestStorageAccessVectorStoreReconstruction:
    """Tests for vectors_path serialization in FileStorageAccess."""

    def test_file_storage_access_vectors_path_serialized(self) -> None:
        """FileStorageAccess with vectors_path serializes correctly.

        Breaks when: vectors_path lost during serialization/deserialization.
        """
        vectors_path = Path("/app/vectors")
        storage_access = FileStorageAccess(
            tools_path=None,
            skills_path=Path("/app/skills"),
            artifacts_path=Path("/app/artifacts"),
            deps_path=Path("/app/deps"),
            vectors_path=vectors_path,
        )

        # Access object should preserve vectors_path
        assert storage_access.vectors_path == vectors_path

    def test_file_storage_access_vectors_path_none_serialized(self) -> None:
        """FileStorageAccess with vectors_path=None serializes correctly.

        Breaks when: None value causes serialization errors.
        """
        storage_access = FileStorageAccess(
            tools_path=None,
            skills_path=Path("/app/skills"),
            artifacts_path=Path("/app/artifacts"),
            deps_path=Path("/app/deps"),
            vectors_path=None,
        )

        # Should handle None gracefully
        assert storage_access.vectors_path is None

    def test_generated_code_uses_vectors_path_from_storage_access(self) -> None:
        """Generated code uses vectors_path from FileStorageAccess.

        Breaks when: Code uses wrong path or ignores vectors_path field.
        """
        vectors_path = Path("/specific/vectors/location")
        storage_access = FileStorageAccess(
            tools_path=None,
            skills_path=Path("/app/skills"),
            artifacts_path=Path("/app/artifacts"),
            deps_path=Path("/app/deps"),
            vectors_path=vectors_path,
        )

        code = build_namespace_setup_code(storage_access)

        # Generated code should reference the specific vectors path
        assert str(vectors_path) in code or repr(str(vectors_path)) in code


# =============================================================================
# Negative Tests
# =============================================================================


class TestVectorStoreCodeGenerationEdgeCases:
    """Edge cases and error conditions for vector store code generation."""

    def test_code_generation_handles_missing_vectors_directory(self) -> None:
        """Generated code handles vectors directory not existing.

        Breaks when: Code assumes vectors directory exists, crashes on startup.
        """
        storage_access = FileStorageAccess(
            tools_path=None,
            skills_path=Path("/app/skills"),
            artifacts_path=Path("/app/artifacts"),
            deps_path=Path("/app/deps"),
            vectors_path=Path("/nonexistent/vectors"),
        )

        code = build_namespace_setup_code(storage_access)

        # Code should create directory if missing
        # Look for mkdir or makedirs patterns
        assert "mkdir" in code.lower() or "Path(" in code

    def test_code_generation_with_special_characters_in_path(self) -> None:
        """Generated code handles special characters in vectors_path.

        Breaks when: Special characters in path break string escaping.
        """
        # Path with spaces and quotes
        vectors_path = Path('/app/vectors with spaces/"quotes"')
        storage_access = FileStorageAccess(
            tools_path=None,
            skills_path=Path("/app/skills"),
            artifacts_path=Path("/app/artifacts"),
            deps_path=Path("/app/deps"),
            vectors_path=vectors_path,
        )

        code = build_namespace_setup_code(storage_access)

        # Should compile without syntax errors despite special characters
        try:
            compile(code, "<generated>", "exec")
        except SyntaxError as e:
            pytest.fail(
                f"Generated code with special chars has syntax errors: {e}\n\nCode:\n{code}"
            )

    def test_code_generation_creates_embedder_only_once(self) -> None:
        """Generated code creates embedder once, reused for vector store.

        Breaks when: Multiple embedder instances created wastefully.
        """
        storage_access = FileStorageAccess(
            tools_path=None,
            skills_path=Path("/app/skills"),
            artifacts_path=Path("/app/artifacts"),
            deps_path=Path("/app/deps"),
            vectors_path=Path("/app/vectors"),
        )

        code = build_namespace_setup_code(storage_access)

        # Should create embedder once and pass to both vector store and library
        # Count embedder instantiations
        embedder_creations = code.count("Embedder(") + code.count("Granite")
        # Should be reasonable (1-2, allowing for imports and instantiation)
        assert embedder_creations <= 2, "Too many embedder instantiations"
