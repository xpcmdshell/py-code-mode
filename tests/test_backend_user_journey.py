"""User journey tests for backend feature combinations.

These tests simulate real agent workflows that use multiple features together:
- Tools discovery and invocation
- Skills creation, invocation, and persistence
- Artifacts save/load
- Cross-namespace operations (skills calling tools)

Critical deployment scenarios:
- FileStorage + ContainerExecutor (standard)
- RedisStorage + ContainerExecutor (Azure Container Apps)
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from py_code_mode.session import Session
from py_code_mode.storage import FileStorage

# =============================================================================
# Helpers
# =============================================================================


def _docker_available() -> bool:
    """Check if Docker is available for testing."""
    return shutil.which("docker") is not None


def _testcontainers_available() -> bool:
    """Check if testcontainers can spin up Redis."""
    try:
        from testcontainers.redis import RedisContainer  # noqa: F401

        return _docker_available()
    except ImportError:
        return False


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def echo_tool_yaml() -> str:
    """Echo tool YAML config."""
    return """
name: echo
type: cli
command: echo
args: "{text}"
description: Echo text back
"""


@pytest.fixture
def tools_storage(tmp_path: Path, echo_tool_yaml: str) -> Path:
    """Create storage with echo tool configured."""
    tools = tmp_path / "tools"
    tools.mkdir(parents=True)
    (tools / "echo.yaml").write_text(echo_tool_yaml)
    return tmp_path


@pytest.fixture
def empty_storage(tmp_path: Path) -> Path:
    """Create empty storage directory."""
    return tmp_path


# =============================================================================
# Agent Full Workflow E2E Tests
# =============================================================================


class TestAgentFullWorkflow:
    """Test complete agent workflows that use all features together.

    These tests simulate a real LLM agent session where the agent:
    1. Discovers available tools
    2. Uses tools to accomplish tasks
    3. Creates reusable skills from patterns
    4. Saves results as artifacts
    """

    @pytest.mark.asyncio
    async def test_agent_full_workflow_in_process(self, tools_storage: Path) -> None:
        """Complete agent workflow with InProcessExecutor.

        User story: An agent lists tools, uses a tool, creates a skill,
        invokes the skill, and saves results as an artifact.
        """
        from py_code_mode.backends.in_process import InProcessExecutor

        storage = FileStorage(tools_storage)
        executor = InProcessExecutor()

        async with Session(storage=storage, executor=executor) as session:
            # 1. Agent lists available tools
            result = await session.run("tools.list()")
            assert result.is_ok, f"tools.list() failed: {result.error}"
            assert isinstance(result.value, list)
            tool_names = [t["name"] for t in result.value]
            assert "echo" in tool_names, f"echo not in tools: {tool_names}"

            # 2. Agent uses a tool
            result = await session.run('tools.echo(text="hello world")')
            assert result.is_ok, f"tools.echo() failed: {result.error}"
            assert "hello world" in result.value

            # 3. Agent creates a skill from what it learned
            result = await session.run("""
skills.create(
    name="shout",
    description="Echo text in uppercase",
    source="def run(text: str) -> str:\\n    return text.upper()"
)
""")
            assert result.is_ok, f"skills.create() failed: {result.error}"

            # 4. Agent invokes the created skill
            result = await session.run('skills.shout(text="quiet")')
            assert result.is_ok, f"skills.shout() failed: {result.error}"
            assert result.value == "QUIET"

            # 5. Agent saves results as artifact
            result = await session.run(
                'artifacts.save("session_log.json", {"steps": 5, "success": True}, "Work log")'
            )
            assert result.is_ok, f"artifacts.save() failed: {result.error}"

            # 6. Agent loads artifact to verify
            result = await session.run('artifacts.load("session_log.json")')
            assert result.is_ok, f"artifacts.load() failed: {result.error}"
            assert result.value == {"steps": 5, "success": True}

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _docker_available(), reason="Docker not available")
    @pytest.mark.xdist_group("docker")
    async def test_agent_full_workflow_container(self, tools_storage: Path) -> None:
        """Complete agent workflow with ContainerExecutor.

        Same workflow as in-process but running inside a Docker container.
        This validates that all namespace injections work in container context.
        """
        from py_code_mode.backends.container import ContainerConfig, ContainerExecutor

        storage = FileStorage(tools_storage)
        executor = ContainerExecutor(ContainerConfig(timeout=60.0))

        async with Session(storage=storage, executor=executor) as session:
            # 1. Agent lists available tools
            result = await session.run("tools.list()")
            assert result.is_ok, f"tools.list() failed: {result.error}"
            assert isinstance(result.value, list)
            tool_names = [t["name"] for t in result.value]
            assert "echo" in tool_names, f"echo not in tools: {tool_names}"

            # 2. Agent uses a tool
            result = await session.run('tools.echo(text="container hello")')
            assert result.is_ok, f"tools.echo() failed: {result.error}"
            assert "container hello" in result.value

            # 3. Agent creates a skill
            result = await session.run("""
skills.create(
    name="container_shout",
    description="Echo text in uppercase",
    source="def run(text: str) -> str:\\n    return text.upper()"
)
""")
            assert result.is_ok, f"skills.create() failed: {result.error}"

            # 4. Agent invokes the created skill
            result = await session.run('skills.container_shout(text="whisper")')
            assert result.is_ok, f"skills.container_shout() failed: {result.error}"
            assert result.value == "WHISPER"

            # 5. Agent saves artifact
            result = await session.run(
                'artifacts.save("container_log.json", {"container": True}, "Container log")'
            )
            assert result.is_ok, f"artifacts.save() failed: {result.error}"

            # 6. Agent loads artifact
            result = await session.run('artifacts.load("container_log.json")')
            assert result.is_ok, f"artifacts.load() failed: {result.error}"
            assert result.value == {"container": True}


# =============================================================================
# Container + Tools Tests
# =============================================================================


@pytest.mark.xdist_group("docker")
class TestContainerToolsInvocation:
    """Test that tools work correctly inside a container."""

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _docker_available(), reason="Docker not available")
    async def test_tools_list_in_container(self, tools_storage: Path) -> None:
        """tools.list() returns configured tools inside container."""
        from py_code_mode.backends.container import ContainerConfig, ContainerExecutor

        storage = FileStorage(tools_storage)
        executor = ContainerExecutor(ContainerConfig(timeout=30.0))

        async with Session(storage=storage, executor=executor) as session:
            result = await session.run("tools.list()")
            assert result.is_ok, f"tools.list() failed: {result.error}"
            assert isinstance(result.value, list)
            assert len(result.value) >= 1
            assert any(t["name"] == "echo" for t in result.value)

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _docker_available(), reason="Docker not available")
    async def test_tools_call_in_container(self, tools_storage: Path) -> None:
        """tools.<name>() works inside container."""
        from py_code_mode.backends.container import ContainerConfig, ContainerExecutor

        storage = FileStorage(tools_storage)
        executor = ContainerExecutor(ContainerConfig(timeout=30.0))

        async with Session(storage=storage, executor=executor) as session:
            result = await session.run('tools.echo(text="container test")')
            assert result.is_ok, f"tools.echo() failed: {result.error}"
            assert "container test" in result.value

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _docker_available(), reason="Docker not available")
    async def test_tools_search_in_container(self, tools_storage: Path) -> None:
        """tools.search() works inside container."""
        from py_code_mode.backends.container import ContainerConfig, ContainerExecutor

        storage = FileStorage(tools_storage)
        executor = ContainerExecutor(ContainerConfig(timeout=30.0))

        async with Session(storage=storage, executor=executor) as session:
            result = await session.run('tools.search("echo")')
            assert result.is_ok, f"tools.search() failed: {result.error}"
            assert isinstance(result.value, list)


# =============================================================================
# Container + Skills Lifecycle Tests
# =============================================================================


@pytest.mark.xdist_group("docker")
class TestContainerSkillsLifecycle:
    """Test full skills lifecycle inside a container."""

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _docker_available(), reason="Docker not available")
    async def test_skills_create_invoke_delete(self, empty_storage: Path) -> None:
        """Skills can be created, invoked, and deleted in container."""
        from py_code_mode.backends.container import ContainerConfig, ContainerExecutor

        storage = FileStorage(empty_storage)
        executor = ContainerExecutor(ContainerConfig(timeout=30.0))

        async with Session(storage=storage, executor=executor) as session:
            # 1. Verify empty skills
            result = await session.run("skills.list()")
            assert result.is_ok
            assert result.value == []

            # 2. Create skill
            result = await session.run("""
skills.create(
    name="add_numbers",
    description="Add two numbers",
    source="def run(a: int, b: int) -> int:\\n    return a + b"
)
""")
            assert result.is_ok, f"skills.create() failed: {result.error}"

            # 3. List shows new skill
            result = await session.run("skills.list()")
            assert result.is_ok
            names = [s["name"] for s in result.value]
            assert "add_numbers" in names

            # 4. Invoke skill
            result = await session.run("skills.add_numbers(a=5, b=3)")
            assert result.is_ok, f"skills.add_numbers() failed: {result.error}"
            assert result.value == 8

            # 5. Delete skill
            result = await session.run('skills.delete("add_numbers")')
            assert result.is_ok, f"skills.delete() failed: {result.error}"

            # 6. Verify deletion
            result = await session.run("skills.list()")
            assert result.is_ok
            names = [s["name"] for s in result.value]
            assert "add_numbers" not in names

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _docker_available(), reason="Docker not available")
    async def test_skill_uses_tools_in_container(self, tools_storage: Path) -> None:
        """Skills can call tools from within container execution."""
        from py_code_mode.backends.container import ContainerConfig, ContainerExecutor

        storage = FileStorage(tools_storage)
        executor = ContainerExecutor(ContainerConfig(timeout=30.0))

        async with Session(storage=storage, executor=executor) as session:
            # Create skill that uses tools
            result = await session.run('''
skills.create(
    name="loud_echo",
    description="Echo text and uppercase it",
    source="""def run(text: str) -> str:
    result = tools.echo(text=text)
    return result.strip().upper()
"""
)
''')
            assert result.is_ok, f"skills.create() failed: {result.error}"

            # Invoke skill that calls tool
            result = await session.run('skills.loud_echo(text="hello")')
            assert result.is_ok, f"skills.loud_echo() failed: {result.error}"
            assert result.value == "HELLO"


# =============================================================================
# Cross-Session Persistence Tests
# =============================================================================


@pytest.mark.xdist_group("docker")
class TestContainerSessionPersistence:
    """Test that data persists across container sessions."""

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _docker_available(), reason="Docker not available")
    async def test_skill_persists_across_container_sessions(self, empty_storage: Path) -> None:
        """Skills created in one container session are available in next."""
        from py_code_mode.backends.container import ContainerConfig, ContainerExecutor

        # Session 1: Create skill
        storage1 = FileStorage(empty_storage)
        executor1 = ContainerExecutor(ContainerConfig(timeout=30.0))

        async with Session(storage=storage1, executor=executor1) as session:
            result = await session.run("""
skills.create(
    name="persistent_skill",
    description="Should persist",
    source="def run() -> str:\\n    return 'persisted'"
)
""")
            assert result.is_ok

            result = await session.run("skills.persistent_skill()")
            assert result.is_ok
            assert result.value == "persisted"

        # Session 2: Skill should still exist
        storage2 = FileStorage(empty_storage)
        executor2 = ContainerExecutor(ContainerConfig(timeout=30.0))

        async with Session(storage=storage2, executor=executor2) as session:
            result = await session.run("skills.list()")
            assert result.is_ok
            names = [s["name"] for s in result.value]
            assert "persistent_skill" in names, f"Skill not persisted: {names}"

            result = await session.run("skills.persistent_skill()")
            assert result.is_ok
            assert result.value == "persisted"

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _docker_available(), reason="Docker not available")
    async def test_artifact_persists_across_container_sessions(self, empty_storage: Path) -> None:
        """Artifacts saved in one container session are loadable in next."""
        from py_code_mode.backends.container import ContainerConfig, ContainerExecutor

        # Session 1: Save artifact
        storage1 = FileStorage(empty_storage)
        executor1 = ContainerExecutor(ContainerConfig(timeout=30.0))

        async with Session(storage=storage1, executor=executor1) as session:
            result = await session.run(
                'artifacts.save("persistent.json", {"session": 1}, "First session")'
            )
            assert result.is_ok

        # Session 2: Load artifact
        storage2 = FileStorage(empty_storage)
        executor2 = ContainerExecutor(ContainerConfig(timeout=30.0))

        async with Session(storage=storage2, executor=executor2) as session:
            result = await session.run('artifacts.load("persistent.json")')
            assert result.is_ok, f"Artifact not persisted: {result.error}"
            assert result.value == {"session": 1}


# =============================================================================
# Redis + Container Integration Tests
# =============================================================================


@pytest.mark.skip(reason="Requires testcontainers Redis - times out in CI, run locally")
@pytest.mark.xdist_group("docker")
class TestRedisContainerIntegration:
    """Test RedisStorage + ContainerExecutor combination.

    This is the critical production deployment scenario for Azure Container Apps.
    """

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _testcontainers_available(), reason="testcontainers not available")
    async def test_redis_container_full_workflow(self) -> None:
        """Complete workflow with Redis storage and container executor."""
        import redis
        from testcontainers.redis import RedisContainer

        from py_code_mode.backends.container import ContainerConfig, ContainerExecutor
        from py_code_mode.storage import RedisStorage

        # Configure Docker socket for macOS Docker Desktop
        docker_socket = Path.home() / ".docker" / "run" / "docker.sock"
        if docker_socket.exists() and "DOCKER_HOST" not in os.environ:
            os.environ["DOCKER_HOST"] = f"unix://{docker_socket}"

        with RedisContainer() as redis_tc:
            host = redis_tc.get_container_host_ip()
            port = redis_tc.get_exposed_port(6379)
            redis_url = f"redis://{host}:{port}"

            client = redis.from_url(redis_url)
            storage = RedisStorage(client, prefix="test")
            executor = ContainerExecutor(ContainerConfig(timeout=60.0))

            async with Session(storage=storage, executor=executor) as session:
                # 1. Create skill (stored in Redis)
                result = await session.run("""
skills.create(
    name="redis_skill",
    description="Test skill in Redis",
    source="def run(x: int) -> int:\\n    return x * 2"
)
""")
                assert result.is_ok, f"skills.create() failed: {result.error}"

                # 2. Invoke skill
                result = await session.run("skills.redis_skill(x=21)")
                assert result.is_ok, f"skills.redis_skill() failed: {result.error}"
                assert result.value == 42

                # 3. Save artifact (stored in Redis)
                result = await session.run(
                    'artifacts.save("redis_data.json", {"from": "container"}, "Redis test")'
                )
                assert result.is_ok, f"artifacts.save() failed: {result.error}"

                # 4. Load artifact
                result = await session.run('artifacts.load("redis_data.json")')
                assert result.is_ok, f"artifacts.load() failed: {result.error}"
                assert result.value == {"from": "container"}

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _testcontainers_available(), reason="testcontainers not available")
    async def test_redis_container_skill_persistence(self) -> None:
        """Skills persist in Redis across container sessions."""
        import redis
        from testcontainers.redis import RedisContainer

        from py_code_mode.backends.container import ContainerConfig, ContainerExecutor
        from py_code_mode.storage import RedisStorage

        docker_socket = Path.home() / ".docker" / "run" / "docker.sock"
        if docker_socket.exists() and "DOCKER_HOST" not in os.environ:
            os.environ["DOCKER_HOST"] = f"unix://{docker_socket}"

        with RedisContainer() as redis_tc:
            host = redis_tc.get_container_host_ip()
            port = redis_tc.get_exposed_port(6379)
            redis_url = f"redis://{host}:{port}"

            client = redis.from_url(redis_url)

            # Session 1: Create skill
            storage1 = RedisStorage(client, prefix="persist_test")
            executor1 = ContainerExecutor(ContainerConfig(timeout=30.0))

            async with Session(storage=storage1, executor=executor1) as session:
                result = await session.run("""
skills.create(
    name="redis_persistent",
    description="Should persist in Redis",
    source="def run() -> str:\\n    return 'from redis'"
)
""")
                assert result.is_ok

            # Session 2: Skill should exist
            storage2 = RedisStorage(client, prefix="persist_test")
            executor2 = ContainerExecutor(ContainerConfig(timeout=30.0))

            async with Session(storage=storage2, executor=executor2) as session:
                result = await session.run("skills.list()")
                assert result.is_ok
                names = [s["name"] for s in result.value]
                assert "redis_persistent" in names

                result = await session.run("skills.redis_persistent()")
                assert result.is_ok
                assert result.value == "from redis"


# =============================================================================
# Negative Tests
# =============================================================================


@pytest.mark.xdist_group("docker")
class TestContainerNegativeCases:
    """Test error handling in container execution."""

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _docker_available(), reason="Docker not available")
    async def test_container_timeout_returns_error(self, empty_storage: Path) -> None:
        """Infinite loop with short timeout produces error."""
        from py_code_mode.backends.container import ContainerConfig, ContainerExecutor

        storage = FileStorage(empty_storage)
        executor = ContainerExecutor(ContainerConfig(timeout=30.0))

        async with Session(storage=storage, executor=executor) as session:
            result = await session.run("while True: pass", timeout=1.0)
            assert not result.is_ok, "Expected timeout error"
            assert result.error is not None
            assert "timeout" in result.error.lower() or "Timeout" in result.error

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _docker_available(), reason="Docker not available")
    async def test_container_tool_not_found_error(self, empty_storage: Path) -> None:
        """Calling non-existent tool gives clear error."""
        from py_code_mode.backends.container import ContainerConfig, ContainerExecutor

        storage = FileStorage(empty_storage)
        executor = ContainerExecutor(ContainerConfig(timeout=30.0))

        async with Session(storage=storage, executor=executor) as session:
            result = await session.run('tools.nonexistent_tool(arg="value")')
            assert not result.is_ok, "Expected error for missing tool"
            assert result.error is not None

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _docker_available(), reason="Docker not available")
    async def test_container_skill_not_found_error(self, empty_storage: Path) -> None:
        """Calling non-existent skill gives clear error."""
        from py_code_mode.backends.container import ContainerConfig, ContainerExecutor

        storage = FileStorage(empty_storage)
        executor = ContainerExecutor(ContainerConfig(timeout=30.0))

        async with Session(storage=storage, executor=executor) as session:
            result = await session.run("skills.nonexistent_skill()")
            assert not result.is_ok, "Expected error for missing skill"
            assert result.error is not None

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _docker_available(), reason="Docker not available")
    async def test_container_invalid_skill_source_rejected(self, empty_storage: Path) -> None:
        """Creating skill with syntax error fails gracefully."""
        from py_code_mode.backends.container import ContainerConfig, ContainerExecutor

        storage = FileStorage(empty_storage)
        executor = ContainerExecutor(ContainerConfig(timeout=30.0))

        async with Session(storage=storage, executor=executor) as session:
            result = await session.run("""
skills.create(
    name="bad_skill",
    description="Invalid syntax",
    source="def run( broken"
)
""")
            assert not result.is_ok, "Expected error for invalid syntax"
            assert result.error is not None


# =============================================================================
# Invariant Tests
# =============================================================================


@pytest.mark.xdist_group("docker")
class TestContainerInvariants:
    """Test invariants that must hold in container execution."""

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _docker_available(), reason="Docker not available")
    async def test_container_namespace_isolation(self, empty_storage: Path) -> None:
        """Variables in one container session don't leak to another."""
        from py_code_mode.backends.container import ContainerConfig, ContainerExecutor

        # Session 1: Define variable
        storage1 = FileStorage(empty_storage)
        executor1 = ContainerExecutor(ContainerConfig(timeout=30.0))

        async with Session(storage=storage1, executor=executor1) as session:
            await session.run("secret = 'private_data'")
            result = await session.run("secret")
            assert result.is_ok
            assert result.value == "private_data"

        # Session 2: Variable should NOT exist
        storage2 = FileStorage(empty_storage)
        executor2 = ContainerExecutor(ContainerConfig(timeout=30.0))

        async with Session(storage=storage2, executor=executor2) as session:
            result = await session.run("secret")
            assert not result.is_ok, "Variable leaked between sessions"
            assert "NameError" in str(result.error)
