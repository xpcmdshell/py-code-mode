"""End-to-end tests for backend feature combinations.

These tests validate that intuitive feature combinations work correctly.
Tests that require unimplemented features are marked xfail.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from py_code_mode import Capability, CodeExecutor


def _docker_available() -> bool:
    """Check if Docker is available for testing."""
    return shutil.which("docker") is not None


class TestNetworkIsolationWithArtifacts:
    """Test that network isolation doesn't break artifact storage."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="NETWORK_ISOLATION capability not yet implemented")
    async def test_network_denied_but_artifacts_work(self, tmp_path: Path) -> None:
        """Network blocked but local artifact storage works.

        When network is isolated, agents should still be able to save artifacts.
        """
        artifacts_path = tmp_path / "artifacts"
        artifacts_path.mkdir(parents=True, exist_ok=True)

        # Use container backend which should support network isolation
        from py_code_mode.backends.container import ContainerConfig, ContainerExecutor

        config = ContainerConfig(
            host_artifacts_path=artifacts_path,
        )
        executor = ContainerExecutor(config)

        try:
            # Network should fail (when isolation is enabled)
            result = await executor.run(
                "import urllib.request; urllib.request.urlopen('https://example.com')"
            )
            assert not result.is_ok

            # But artifacts should still work
            result = await executor.run("artifacts.save('test.txt', b'works', 'test')")
            assert result.is_ok
        finally:
            await executor.close()


class TestFilesystemIsolationWithArtifacts:
    """Test that filesystem isolation doesn't break artifact storage."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="FILESYSTEM_ISOLATION capability not yet implemented")
    async def test_filesystem_isolated_but_artifacts_accessible(
        self, tmp_path: Path
    ) -> None:
        """Host filesystem hidden but artifact store accessible.

        Filesystem isolation should prevent reading host files like /etc/passwd,
        but the artifact store should remain accessible.
        """
        artifacts_path = tmp_path / "artifacts"
        artifacts_path.mkdir(parents=True, exist_ok=True)

        # Use container backend which should support filesystem isolation
        from py_code_mode.backends.container import ContainerConfig, ContainerExecutor

        config = ContainerConfig(
            host_artifacts_path=artifacts_path,
        )
        executor = ContainerExecutor(config)

        try:
            # Can't read host files
            result = await executor.run("open('/etc/passwd').read()")
            assert not result.is_ok

            # Can use artifact store
            result = await executor.run(
                "artifacts.save('secret.txt', b'safe', 'safe data')"
            )
            assert result.is_ok
        finally:
            await executor.close()


class TestContainerWithFileArtifacts:
    """Test container backend with file-based artifact storage."""

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _docker_available(), reason="Docker not available")
    async def test_file_artifacts_save_load(self, tmp_path: Path) -> None:
        """Container with file artifacts can save and load data."""
        from py_code_mode.backends.container import ContainerConfig, ContainerExecutor
        from py_code_mode.session import Session
        from py_code_mode.storage import FileStorage

        # Create storage with artifacts
        storage = FileStorage(tmp_path)

        # Use Session with ContainerExecutor
        config = ContainerConfig(timeout=30.0)
        executor = ContainerExecutor(config)
        async with Session(storage=storage, executor=executor) as session:
            # Save artifact
            result = await session.run(
                "artifacts.save('report.txt', b'test data', 'Test report')"
            )
            assert result.is_ok, f"artifacts.save() failed: {result.error}"

            # Load artifact
            result = await session.run("artifacts.load('report.txt')")
            assert result.is_ok, f"artifacts.load() failed: {result.error}"
            # Handle both bytes and string return types
            if isinstance(result.value, bytes):
                assert b"test data" in result.value
            else:
                assert "test data" in str(result.value)

            # List artifacts
            result = await session.run("artifacts.list()")
            assert result.is_ok, f"artifacts.list() failed: {result.error}"
            assert result.value is not None, "artifacts.list() returned None"

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _docker_available(), reason="Docker not available")
    async def test_file_artifacts_persist_on_host(self, tmp_path: Path) -> None:
        """File artifacts written in container are visible on host filesystem."""
        from py_code_mode.backends.container import ContainerConfig, ContainerExecutor
        from py_code_mode.session import Session
        from py_code_mode.storage import FileStorage

        # Create storage
        storage = FileStorage(tmp_path)
        artifacts_path = tmp_path / "artifacts"

        # Use Session with ContainerExecutor
        config = ContainerConfig(timeout=30.0)
        executor = ContainerExecutor(config)
        async with Session(storage=storage, executor=executor) as session:
            await session.run(
                "artifacts.save('host_visible.txt', b'from container', 'test')"
            )

        # Verify file exists on host (artifact store may create subdirectories)
        found = list(artifacts_path.rglob("host_visible.txt"))
        assert len(found) > 0, "Artifact not visible on host filesystem"


def _redis_available() -> bool:
    """Check if Redis is available for testing."""
    try:
        import os

        import redis

        url = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379")
        client = redis.from_url(url)
        client.ping()
        return True
    except Exception:
        return False


class TestContainerWithRedisArtifacts:
    """Test container backend with Redis artifact storage."""

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _docker_available(), reason="Docker not available")
    @pytest.mark.skipif(
        not _redis_available(), reason="Redis not available for testing"
    )
    async def test_redis_artifacts_save_load(self) -> None:
        """Container with Redis artifacts can save and load data."""
        import os

        import redis

        from py_code_mode.backends.container import ContainerConfig, ContainerExecutor
        from py_code_mode.session import Session
        from py_code_mode.storage import RedisStorage

        redis_url = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379")

        # Create Redis storage
        client = redis.from_url(redis_url)
        storage = RedisStorage(client)

        # Use Session with ContainerExecutor
        config = ContainerConfig(timeout=30.0)
        executor = ContainerExecutor(config)
        async with Session(storage=storage, executor=executor) as session:
            # Save artifact
            result = await session.run(
                "artifacts.save('redis_test.txt', b'redis data', 'Redis test')"
            )
            assert result.is_ok, f"artifacts.save() failed: {result.error}"

            # Load artifact
            result = await session.run("artifacts.load('redis_test.txt')")
            assert result.is_ok, f"artifacts.load() failed: {result.error}"
            # Handle both bytes and string return types
            if isinstance(result.value, bytes):
                assert b"redis data" in result.value
            else:
                assert "redis data" in str(result.value)


class TestResetWithStateAndArtifacts:
    """Test that reset clears namespace but preserves artifacts."""

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _docker_available(), reason="Docker not available")
    async def test_reset_clears_namespace_preserves_artifacts(
        self, tmp_path: Path
    ) -> None:
        """Reset clears Python state but keeps artifacts.

        After reset, variables should be gone but artifacts should persist.
        Uses container backend which supports RESET capability.
        """
        from py_code_mode.backends.container import ContainerConfig, ContainerExecutor
        from py_code_mode.session import Session
        from py_code_mode.storage import FileStorage

        # Create storage
        storage = FileStorage(tmp_path)

        # Use Session with ContainerExecutor (supports RESET)
        config = ContainerConfig(timeout=30.0)
        executor = ContainerExecutor(config)
        async with Session(storage=storage, executor=executor) as session:
            # Set variable
            await session.run("x = 42")

            # Save artifact
            await session.run("artifacts.save('keep.txt', b'preserved', 'keep')")

            # Reset (clear namespace) - access executor directly
            await session._executor.reset()

            # Variable should be gone
            result = await session.run("x")
            assert not result.is_ok
            assert "NameError" in str(result.error)

            # Artifact should persist
            result = await session.run("artifacts.load('keep.txt')")
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
            assert "timeout" in str(result.error).lower() or "Timeout" in str(
                result.error
            )


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
