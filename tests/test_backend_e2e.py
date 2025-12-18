"""End-to-end tests for backend feature combinations.

These tests validate that intuitive feature combinations work correctly.
Tests skip for backends that don't support the required capabilities.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from py_code_mode import Capability, CodeExecutor
from py_code_mode.artifacts import FileArtifactStore


class TestNetworkIsolationWithArtifacts:
    """Test that network isolation doesn't break artifact storage."""

    @pytest.mark.asyncio
    async def test_network_denied_but_artifacts_work(self, tmp_path: Path) -> None:
        """Network blocked but local artifact storage works.

        When network is isolated, agents should still be able to save artifacts.
        This test skips for backends without network isolation support.
        """
        artifacts_path = tmp_path / "artifacts"
        artifacts_path.mkdir()
        artifact_store = FileArtifactStore(artifacts_path)
        executor = CodeExecutor(artifact_store=artifact_store)

        if not executor.supports(Capability.NETWORK_ISOLATION):
            pytest.skip("Backend doesn't support network isolation")

        async with executor:
            # Network should fail (when isolation is enabled)
            result = await executor.run(
                "import urllib.request; urllib.request.urlopen('https://example.com')"
            )
            assert not result.is_ok

            # But artifacts should still work
            result = await executor.run("artifacts.save('test.txt', b'works', 'test')")
            assert result.is_ok


class TestFilesystemIsolationWithArtifacts:
    """Test that filesystem isolation doesn't break artifact storage."""

    @pytest.mark.asyncio
    async def test_filesystem_isolated_but_artifacts_accessible(self, tmp_path: Path) -> None:
        """Host filesystem hidden but artifact store accessible.

        Filesystem isolation should prevent reading host files like /etc/passwd,
        but the artifact store should remain accessible.
        """
        artifacts_path = tmp_path / "artifacts"
        artifacts_path.mkdir()
        artifact_store = FileArtifactStore(artifacts_path)
        executor = CodeExecutor(artifact_store=artifact_store)

        if not executor.supports(Capability.FILESYSTEM_ISOLATION):
            pytest.skip("Backend doesn't support filesystem isolation")

        async with executor:
            # Can't read host files
            result = await executor.run("open('/etc/passwd').read()")
            assert not result.is_ok

            # Can use artifact store
            result = await executor.run("artifacts.save('secret.txt', b'safe', 'safe data')")
            assert result.is_ok


class TestResetWithStateAndArtifacts:
    """Test that reset clears namespace but preserves artifacts."""

    @pytest.mark.asyncio
    async def test_reset_clears_namespace_preserves_artifacts(self, tmp_path: Path) -> None:
        """Reset clears Python state but keeps artifacts.

        After reset, variables should be gone but artifacts should persist.
        """
        artifacts_path = tmp_path / "artifacts"
        artifacts_path.mkdir()
        artifact_store = FileArtifactStore(artifacts_path)
        executor = CodeExecutor(artifact_store=artifact_store)

        if not executor.supports(Capability.RESET):
            pytest.skip("Backend doesn't support reset")

        async with executor:
            # Set variable
            await executor.run("x = 42")

            # Save artifact
            await executor.run("artifacts.save('keep.txt', b'preserved', 'keep')")

            # Reset (clear namespace)
            await executor.reset()

            # Variable should be gone
            result = await executor.run("x")
            assert not result.is_ok
            assert "NameError" in str(result.error)

            # Artifact should persist
            result = await executor.run("artifacts.load('keep.txt')")
            assert result.is_ok
            assert "preserved" in str(result.value)


class TestTimeoutBehavior:
    """Test timeout handling across backends."""

    @pytest.mark.asyncio
    async def test_timeout_raises_or_returns_error(self) -> None:
        """Timeout produces an error result.

        All backends should support timeout capability.
        """
        executor = CodeExecutor()
        assert executor.supports(Capability.TIMEOUT)

        async with executor:
            # Very short timeout on long operation
            result = await executor.run("import time; time.sleep(10)", timeout=0.1)

            assert not result.is_ok
            # Error should mention timeout
            assert "timeout" in str(result.error).lower() or "Timeout" in str(result.error)


class TestToolsAndSkillsTogether:
    """Test that tools and skills work together in same session."""

    @pytest.mark.asyncio
    async def test_tools_and_skills_in_same_session(self, tmp_path: Path) -> None:
        """Can use both tools and skills in same executor session."""
        from py_code_mode.adapters import CLIAdapter, CLIToolSpec
        from py_code_mode.registry import ToolRegistry
        from py_code_mode.semantic import create_skill_library
        from py_code_mode.skill_store import FileSkillStore
        from py_code_mode.skills import PythonSkill

        # Setup tools
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

        # Setup skills
        skills_path = tmp_path / "skills"
        skills_path.mkdir()
        skill = PythonSkill.from_source(
            name="shout",
            source='def run(text: str) -> str:\n    """Shout text."""\n    return text.upper()',
            description="Convert text to uppercase",
        )
        store = FileSkillStore(skills_path)
        store.save(skill)
        library = create_skill_library(store=store)

        # Create executor with both
        async with CodeExecutor(registry=registry, skill_library=library) as executor:
            # Use a tool
            result = await executor.run('tools.echo(text="hello")')
            assert result.is_ok
            assert "hello" in result.value

            # Use a skill
            result = await executor.run('skills.shout(text="hello")')
            assert result.is_ok
            assert result.value == "HELLO"


class TestMultipleExecutors:
    """Test behavior with multiple executor instances."""

    @pytest.mark.asyncio
    async def test_executors_are_independent(self) -> None:
        """Different executors have completely independent state."""
        async with CodeExecutor() as executor1:
            await executor1.run("shared_data = [1, 2, 3]")

            async with CodeExecutor() as executor2:
                # executor2 should NOT see executor1's data
                result = await executor2.run("shared_data")
                assert not result.is_ok
                assert "NameError" in str(result.error)

                # executor2 can define its own
                await executor2.run("shared_data = ['a', 'b']")

            # executor1's data should be unchanged
            result = await executor1.run("shared_data")
            assert result.is_ok
            assert result.value == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_sequential_executors_are_fresh(self) -> None:
        """Each new executor starts with fresh state."""
        async with CodeExecutor() as executor:
            await executor.run("x = 100")

        async with CodeExecutor() as executor:
            result = await executor.run("x")
            assert not result.is_ok
            assert "NameError" in str(result.error)


class TestCapabilityQuerying:
    """Test capability introspection works correctly."""

    @pytest.mark.asyncio
    async def test_supports_returns_bool(self) -> None:
        """supports() returns boolean values."""
        executor = CodeExecutor()

        assert isinstance(executor.supports(Capability.TIMEOUT), bool)
        assert isinstance(executor.supports(Capability.NETWORK_ISOLATION), bool)
        assert isinstance(executor.supports("unknown_capability"), bool)

    @pytest.mark.asyncio
    async def test_supported_capabilities_is_consistent(self) -> None:
        """supported_capabilities() is consistent with supports()."""
        executor = CodeExecutor()

        caps = executor.supported_capabilities()
        for cap in caps:
            assert executor.supports(cap)

        # Check some that aren't supported
        all_caps = {
            Capability.TIMEOUT,
            Capability.PROCESS_ISOLATION,
            Capability.NETWORK_ISOLATION,
            Capability.FILESYSTEM_ISOLATION,
        }
        for cap in all_caps - caps:
            assert not executor.supports(cap)
