"""Integration tests for backend abstraction.

These tests verify that artifacts, skills, and tools work consistently
across all execution backends (in-process, container).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from py_code_mode import Capability, CodeExecutor
from py_code_mode.artifacts import FileArtifactStore
from py_code_mode.registry import ToolRegistry
from py_code_mode.semantic import create_skill_library
from py_code_mode.skill_store import FileSkillStore
from py_code_mode.skills import PythonSkill

if TYPE_CHECKING:
    pass


class TestCreateExecutorIntegration:
    """Test create_executor() factory with tools, skills, artifacts."""

    @pytest.fixture
    def tools_dir(self, tmp_path: Path) -> Path:
        """Create a tools directory with a simple CLI tool."""
        tools = tmp_path / "tools"
        tools.mkdir()
        (tools / "echo.yaml").write_text(
            """
name: echo
type: cli
command: echo
args: "{text}"
description: Echo text back
"""
        )
        return tools

    @pytest.fixture
    def skills_dir(self, tmp_path: Path) -> Path:
        """Create a skills directory with a simple skill."""
        skills = tmp_path / "skills"
        skills.mkdir()
        (skills / "double.py").write_text(
            '''"""Double a number."""

def run(n: int) -> int:
    return n * 2
'''
        )
        return skills

    @pytest.fixture
    def artifacts_dir(self, tmp_path: Path) -> Path:
        """Create an artifacts directory."""
        artifacts = tmp_path / "artifacts"
        # Don't create - let executor create it
        return artifacts

    @pytest.mark.asyncio
    async def test_create_executor_with_tools(self, tools_dir: Path) -> None:
        """Executor loads tools and makes them callable."""
        registry = await ToolRegistry.from_dir(str(tools_dir))
        executor = CodeExecutor(registry=registry)

        try:
            # Tool should be callable
            result = await executor.run('tools.echo(text="hello")')
            assert result.is_ok, f"Tool call failed: {result.error}"
            assert "hello" in result.value
        finally:
            await executor.close()

    @pytest.mark.asyncio
    async def test_create_executor_tools_list(self, tools_dir: Path) -> None:
        """Executor provides tools.list() that returns tool info."""
        registry = await ToolRegistry.from_dir(str(tools_dir))
        executor = CodeExecutor(registry=registry)

        try:
            result = await executor.run("tools.list()")
            assert result.is_ok, f"tools.list() failed: {result.error}"
            assert result.value is not None, "tools.list() returned None"
            # Should contain our echo tool
            tools_str = str(result.value)
            assert "echo" in tools_str.lower(), f"echo not in {tools_str}"
        finally:
            await executor.close()

    @pytest.mark.asyncio
    async def test_create_executor_with_skills(self, skills_dir: Path) -> None:
        """Executor loads skills and makes them callable."""
        store = FileSkillStore(skills_dir)
        skill_library = create_skill_library(store=store)
        executor = CodeExecutor(skill_library=skill_library)

        try:
            # Skill should be callable
            result = await executor.run("skills.double(n=21)")
            assert result.is_ok, f"Skill call failed: {result.error}"
            assert result.value == 42
        finally:
            await executor.close()

    @pytest.mark.asyncio
    async def test_create_executor_skills_list(self, skills_dir: Path) -> None:
        """Executor provides skills.list() that returns skill info."""
        store = FileSkillStore(skills_dir)
        skill_library = create_skill_library(store=store)
        executor = CodeExecutor(skill_library=skill_library)

        try:
            result = await executor.run("skills.list()")
            assert result.is_ok, f"skills.list() failed: {result.error}"
            assert result.value is not None, "skills.list() returned None"
            # Should contain our double skill
            skills_str = str(result.value)
            assert "double" in skills_str.lower(), f"double not in {skills_str}"
        finally:
            await executor.close()

    @pytest.mark.asyncio
    async def test_create_executor_skills_search(self, skills_dir: Path) -> None:
        """Executor provides skills.search() for semantic search."""
        store = FileSkillStore(skills_dir)
        skill_library = create_skill_library(store=store)
        executor = CodeExecutor(skill_library=skill_library)

        try:
            result = await executor.run('skills.search("multiply number")')
            assert result.is_ok, f"skills.search() failed: {result.error}"
            assert result.value is not None
            # Should find double skill (semantically similar to multiply)
            assert len(result.value) > 0
        finally:
            await executor.close()

    @pytest.mark.asyncio
    async def test_create_executor_with_artifacts(self, artifacts_dir: Path) -> None:
        """Executor sets up artifact storage."""
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        artifact_store = FileArtifactStore(artifacts_dir)
        executor = CodeExecutor(artifact_store=artifact_store)

        try:
            # Should be able to save and load
            result = await executor.run(
                'artifacts.save("test.json", {"key": "value"}, "test data")'
            )
            assert result.is_ok, f"artifacts.save() failed: {result.error}"

            result = await executor.run('artifacts.load("test.json")')
            assert result.is_ok, f"artifacts.load() failed: {result.error}"
            assert result.value == {"key": "value"}
        finally:
            await executor.close()

    @pytest.mark.asyncio
    async def test_create_executor_artifacts_list(self, artifacts_dir: Path) -> None:
        """Executor provides artifacts.list()."""
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        artifact_store = FileArtifactStore(artifacts_dir)
        executor = CodeExecutor(artifact_store=artifact_store)

        try:
            await executor.run('artifacts.save("a.json", {}, "first")')
            await executor.run('artifacts.save("b.json", {}, "second")')

            result = await executor.run("list(artifacts.list())")
            assert result.is_ok, f"artifacts.list() failed: {result.error}"
            assert len(result.value) == 2
        finally:
            await executor.close()

    @pytest.mark.asyncio
    async def test_create_executor_full_integration(
        self, tools_dir: Path, skills_dir: Path, artifacts_dir: Path
    ) -> None:
        """Executor with all three: tools, skills, artifacts."""
        registry = await ToolRegistry.from_dir(str(tools_dir))
        store = FileSkillStore(skills_dir)
        skill_library = create_skill_library(store=store)
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        artifact_store = FileArtifactStore(artifacts_dir)
        executor = CodeExecutor(
            registry=registry,
            skill_library=skill_library,
            artifact_store=artifact_store,
        )

        try:
            # Tools work
            result = await executor.run('tools.echo(text="test")')
            assert result.is_ok, f"tools failed: {result.error}"

            # Skills work
            result = await executor.run("skills.double(n=5)")
            assert result.is_ok, f"skills failed: {result.error}"
            assert result.value == 10

            # Artifacts work
            result = await executor.run('artifacts.save("result.json", {"done": True}, "result")')
            assert result.is_ok, f"artifacts.save failed: {result.error}"
            result = await executor.run('artifacts.load("result.json")')
            assert result.is_ok, f"artifacts.load failed: {result.error}"
        finally:
            await executor.close()


class TestBackendArtifacts:
    """Test artifact handling works consistently across backends."""

    @pytest.fixture
    def executor_with_artifacts(self, tmp_path: Path) -> CodeExecutor:
        """Create executor with artifact store."""
        artifacts_path = tmp_path / "artifacts"
        artifacts_path.mkdir()
        artifact_store = FileArtifactStore(artifacts_path)
        return CodeExecutor(artifact_store=artifact_store)

    @pytest.mark.asyncio
    async def test_artifact_save_load_roundtrip(
        self, executor_with_artifacts: CodeExecutor
    ) -> None:
        """Artifacts can be saved and loaded back."""
        async with executor_with_artifacts as executor:
            # Save artifact (requires description)
            result = await executor.run("artifacts.save('test.txt', b'hello world', 'test file')")
            assert result.is_ok, f"Save failed: {result.error}"

            # Load artifact (returns decoded string for text)
            result = await executor.run("artifacts.load('test.txt')")
            assert result.is_ok, f"Load failed: {result.error}"
            assert "hello world" in str(result.value)

    @pytest.mark.asyncio
    async def test_artifacts_persist_across_runs(
        self, executor_with_artifacts: CodeExecutor
    ) -> None:
        """Artifacts saved in one run are available in subsequent runs."""
        async with executor_with_artifacts as executor:
            await executor.run("artifacts.save('persist.txt', b'persistent data', 'persisted')")
            result = await executor.run("artifacts.load('persist.txt')")

            assert result.is_ok
            assert "persistent data" in str(result.value)

    @pytest.mark.asyncio
    async def test_artifact_list(self, executor_with_artifacts: CodeExecutor) -> None:
        """Can list saved artifacts."""
        async with executor_with_artifacts as executor:
            await executor.run("artifacts.save('file1.txt', b'one', 'first')")
            await executor.run("artifacts.save('file2.txt', b'two', 'second')")

            result = await executor.run("artifacts.list()")
            assert result.is_ok
            assert "file1.txt" in str(result.value)
            assert "file2.txt" in str(result.value)

    @pytest.mark.asyncio
    async def test_artifact_delete(self, executor_with_artifacts: CodeExecutor) -> None:
        """Can delete artifacts."""
        async with executor_with_artifacts as executor:
            await executor.run("artifacts.save('to_delete.txt', b'temp', 'temporary')")
            result = await executor.run("artifacts.delete('to_delete.txt')")
            assert result.is_ok

            # Should not exist anymore
            result = await executor.run("artifacts.load('to_delete.txt')")
            assert not result.is_ok or result.value is None


class TestBackendSkills:
    """Test skills invocation across backends."""

    @pytest.fixture
    def executor_with_skills(self, tmp_path: Path) -> CodeExecutor:
        """Create executor with skills."""
        skills_path = tmp_path / "skills"
        skills_path.mkdir()

        # Create a test skill using from_source
        skill = PythonSkill.from_source(
            name="double",
            source='def run(n: int) -> int:\n    """Double a number."""\n    return n * 2',
            description="Double a number",
        )

        store = FileSkillStore(skills_path)
        store.save(skill)

        library = create_skill_library(store=store)
        return CodeExecutor(skill_library=library)

    @pytest.mark.asyncio
    async def test_skill_invocation(self, executor_with_skills: CodeExecutor) -> None:
        """Skills can be invoked via skills namespace."""
        async with executor_with_skills as executor:
            result = await executor.run("skills.double(n=21)")

            assert result.is_ok, f"Skill invocation failed: {result.error}"
            assert result.value == 42

    @pytest.mark.asyncio
    async def test_skills_list(self, executor_with_skills: CodeExecutor) -> None:
        """Can list available skills."""
        async with executor_with_skills as executor:
            result = await executor.run("skills.list()")

            assert result.is_ok
            # Should contain our skill
            assert any("double" in str(s) for s in result.value)

    @pytest.mark.asyncio
    async def test_skill_with_default_args(self, tmp_path: Path) -> None:
        """Skills with default arguments work correctly."""
        skills_path = tmp_path / "skills"
        skills_path.mkdir()

        source = (
            'def run(name: str = "World") -> str:\n'
            '    """Greet someone."""\n'
            '    return f"Hello, {name}!"'
        )
        skill = PythonSkill.from_source(
            name="greet",
            source=source,
            description="Greet someone",
        )

        store = FileSkillStore(skills_path)
        store.save(skill)
        library = create_skill_library(store=store)

        async with CodeExecutor(skill_library=library) as executor:
            # With default
            result = await executor.run("skills.greet()")
            assert result.is_ok
            assert result.value == "Hello, World!"

            # With override
            result = await executor.run('skills.greet(name="Alice")')
            assert result.is_ok
            assert result.value == "Hello, Alice!"


class TestBackendTools:
    """Test tools invocation across backends."""

    @pytest.mark.asyncio
    async def test_tool_invocation(self, tmp_path: Path) -> None:
        """Tools can be invoked via tools namespace."""
        from py_code_mode.adapters import CLIAdapter, CLIToolSpec

        # Create a simple echo tool
        specs = [
            CLIToolSpec(
                name="echo",
                description="Echo text",
                command="echo",
                args_template="{text}",
            )
        ]
        adapter = CLIAdapter(specs)
        registry = ToolRegistry()
        await registry.register_adapter(adapter)

        async with CodeExecutor(registry=registry) as executor:
            result = await executor.run('tools.echo(text="hello")')

            assert result.is_ok, f"Tool invocation failed: {result.error}"
            assert "hello" in result.value

    @pytest.mark.asyncio
    async def test_tools_list(self, tmp_path: Path) -> None:
        """Can list available tools."""
        from py_code_mode.adapters import CLIAdapter, CLIToolSpec

        specs = [
            CLIToolSpec(
                name="echo",
                description="Echo text",
                command="echo",
                args_template="{text}",
            )
        ]
        adapter = CLIAdapter(specs)
        registry = ToolRegistry()
        await registry.register_adapter(adapter)

        async with CodeExecutor(registry=registry) as executor:
            result = await executor.run("tools.list()")

            assert result.is_ok
            # Result should mention echo tool
            assert "echo" in str(result.value).lower()


class TestBackendStateIsolation:
    """Test that state is properly isolated within executor sessions."""

    @pytest.mark.asyncio
    async def test_variables_persist_within_session(self) -> None:
        """Variables set in one run persist to subsequent runs in same session."""
        async with CodeExecutor() as executor:
            await executor.run("x = 42")
            result = await executor.run("x * 2")

            assert result.is_ok
            assert result.value == 84

    @pytest.mark.asyncio
    async def test_state_isolation_between_executors(self) -> None:
        """Different executor instances have isolated state."""
        async with CodeExecutor() as executor1:
            await executor1.run("shared_var = 'executor1'")

            async with CodeExecutor() as executor2:
                # executor2 should not see executor1's variable
                result = await executor2.run("shared_var")
                assert not result.is_ok
                assert "NameError" in result.error


class TestBackendCapabilities:
    """Test capability querying works correctly."""

    @pytest.mark.asyncio
    async def test_in_process_supports_timeout(self) -> None:
        """In-process executor supports timeout capability."""
        executor = CodeExecutor()
        assert executor.supports(Capability.TIMEOUT)
        assert Capability.TIMEOUT in executor.supported_capabilities()

    @pytest.mark.asyncio
    async def test_in_process_capabilities_are_minimal(self) -> None:
        """In-process executor has minimal capabilities (no isolation)."""
        executor = CodeExecutor()
        caps = executor.supported_capabilities()

        # Should have timeout
        assert Capability.TIMEOUT in caps

        # Should NOT have isolation capabilities
        assert Capability.PROCESS_ISOLATION not in caps
        assert Capability.NETWORK_ISOLATION not in caps
        assert Capability.FILESYSTEM_ISOLATION not in caps


class TestBackendContextManager:
    """Test async context manager behavior."""

    @pytest.mark.asyncio
    async def test_executor_as_context_manager(self) -> None:
        """Executor works as async context manager."""
        async with CodeExecutor() as executor:
            result = await executor.run("1 + 1")
            assert result.is_ok
            assert result.value == 2

    @pytest.mark.asyncio
    async def test_close_can_be_called_directly(self) -> None:
        """Close method can be called explicitly."""
        executor = CodeExecutor()
        result = await executor.run("1 + 1")
        assert result.is_ok

        await executor.close()  # Should not raise
