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

import shutil
from pathlib import Path

import pytest
import redis

from py_code_mode.execution.container import ContainerConfig, ContainerExecutor
from py_code_mode.execution.in_process import InProcessExecutor
from py_code_mode.session import Session
from py_code_mode.storage import FileStorage, RedisStorage

# =============================================================================
# Helpers
# =============================================================================


def _docker_available() -> bool:
    """Check if Docker is available for testing."""
    return shutil.which("docker") is not None


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def echo_tool_yaml() -> str:
    """Echo tool YAML config."""
    return """
name: echo
description: Echo text back
command: echo
timeout: 10

schema:
  positional:
    - name: text
      type: string
      required: true
      description: Text to echo

recipes:
  echo:
    description: Echo text
    params:
      text: {}
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
        storage = FileStorage(tools_storage)
        executor = InProcessExecutor()

        async with Session(storage=storage, executor=executor) as session:
            # 1. Agent lists available tools
            result = await session.run("tools.list()")
            assert result.is_ok, f"tools.list() failed: {result.error}"
            assert isinstance(result.value, list)
            tool_names = [t.name if hasattr(t, "name") else t["name"] for t in result.value]
            assert "echo" in tool_names, f"echo not in tools: {tool_names}"

            # 2. Agent uses a tool
            result = await session.run('tools.echo.echo(text="hello world")')
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
        storage = FileStorage(tools_storage)
        executor = ContainerExecutor(ContainerConfig(timeout=60.0))

        async with Session(storage=storage, executor=executor) as session:
            # 1. Agent lists available tools
            result = await session.run("tools.list()")
            assert result.is_ok, f"tools.list() failed: {result.error}"
            assert isinstance(result.value, list)
            tool_names = [t.name if hasattr(t, "name") else t["name"] for t in result.value]
            assert "echo" in tool_names, f"echo not in tools: {tool_names}"

            # 2. Agent uses a tool
            result = await session.run('tools.echo.echo(text="container hello")')
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
        storage = FileStorage(tools_storage)
        executor = ContainerExecutor(ContainerConfig(timeout=30.0))

        async with Session(storage=storage, executor=executor) as session:
            result = await session.run("tools.list()")
            assert result.is_ok, f"tools.list() failed: {result.error}"
            assert isinstance(result.value, list)
            assert len(result.value) >= 1
            assert any(t.name if hasattr(t, "name") else t["name"] == "echo" for t in result.value)

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _docker_available(), reason="Docker not available")
    async def test_tools_call_in_container(self, tools_storage: Path) -> None:
        """tools.<name>() works inside container."""
        storage = FileStorage(tools_storage)
        executor = ContainerExecutor(ContainerConfig(timeout=30.0))

        async with Session(storage=storage, executor=executor) as session:
            result = await session.run('tools.echo.echo(text="container test")')
            assert result.is_ok, f"tools.echo() failed: {result.error}"
            assert "container test" in result.value

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _docker_available(), reason="Docker not available")
    async def test_tools_search_in_container(self, tools_storage: Path) -> None:
        """tools.search() works inside container."""
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
            names = [s.name if hasattr(s, "name") else s["name"] for s in result.value]
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
            names = [s.name if hasattr(s, "name") else s["name"] for s in result.value]
            assert "add_numbers" not in names

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _docker_available(), reason="Docker not available")
    async def test_skill_uses_tools_in_container(self, tools_storage: Path) -> None:
        """Skills can call tools from within container execution."""
        storage = FileStorage(tools_storage)
        executor = ContainerExecutor(ContainerConfig(timeout=30.0))

        async with Session(storage=storage, executor=executor) as session:
            # Create skill that uses tools
            result = await session.run('''
skills.create(
    name="loud_echo",
    description="Echo text and uppercase it",
    source="""def run(text: str) -> str:
    result = tools.echo.echo(text=text)
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
            names = [s.name if hasattr(s, "name") else s["name"] for s in result.value]
            assert "persistent_skill" in names, f"Skill not persisted: {names}"

            result = await session.run("skills.persistent_skill()")
            assert result.is_ok
            assert result.value == "persisted"

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _docker_available(), reason="Docker not available")
    async def test_artifact_persists_across_container_sessions(self, empty_storage: Path) -> None:
        """Artifacts saved in one container session are loadable in next."""
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


@pytest.mark.xdist_group("docker")
class TestRedisContainerIntegration:
    """Test RedisStorage + ContainerExecutor combination.

    This is the critical production deployment scenario for Azure Container Apps.
    Uses testcontainers fixture for isolated Redis per test.
    """

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _docker_available(), reason="Docker not available")
    async def test_redis_container_full_workflow(self, redis_url: str) -> None:
        """Complete workflow with Redis storage and container executor."""
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
    @pytest.mark.skipif(not _docker_available(), reason="Docker not available")
    async def test_redis_container_skill_persistence(self, redis_url: str) -> None:
        """Skills persist in Redis across container sessions."""
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
            names = [s.name if hasattr(s, "name") else s["name"] for s in result.value]
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


# =============================================================================
# FileStorage User Journey Tests
# =============================================================================


class TestFileStorageUserJourney:
    """Test user journeys specific to FileStorage setup.

    These tests simulate real developer workflows using FileStorage,
    including loading tools from YAML configurations.
    """

    @pytest.mark.asyncio
    async def test_mcp_tool_yaml_loads_through_session(self, tmp_path: Path) -> None:
        """MCP tools defined in YAML are accessible through Session.

        User story: Developer adds an MCP tool config to their tools directory.
        When they start a Session, the MCP tools should be available.

        This tests the full path: FileStorage -> Session -> ToolsNamespace

        Regression test for: MCP tools not loading due to sync get_tool_registry()
        """
        from unittest.mock import AsyncMock, MagicMock, patch

        from py_code_mode.tools import Tool, ToolCallable

        # Create tools directory with MCP config
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()

        mcp_config = """name: test_mcp
description: Test MCP tool
type: mcp
transport: stdio
command: fake_mcp_server
"""
        (tools_dir / "test_mcp.yaml").write_text(mcp_config)

        # Create mock MCP adapter that returns a tool
        mock_adapter = MagicMock()
        mock_callable = ToolCallable(
            name="mcp_test_tool",
            description="A test tool from MCP",
            parameters=(),
        )
        mock_tool = Tool(
            name="mcp_test_tool",
            description="A test tool from MCP",
            callables=(mock_callable,),
        )
        mock_adapter.list_tools.return_value = [mock_tool]
        mock_adapter._refresh_tools = AsyncMock(return_value=[mock_tool])
        mock_adapter.close = AsyncMock()

        # Patch MCPAdapter.connect_stdio to return our mock
        with patch(
            "py_code_mode.tools.adapters.mcp.MCPAdapter.connect_stdio",
            new_callable=AsyncMock,
            return_value=mock_adapter,
        ):
            storage = FileStorage(base_path=tmp_path)

            async with Session(storage=storage) as session:
                # Verify MCP tool is accessible
                result = await session.run("tools.list()")
                assert result.is_ok, f"tools.list() failed: {result.error}"
                tool_names = [t.name for t in result.value]

                assert "mcp_test_tool" in tool_names, (
                    f"MCP tool not found. Available tools: {tool_names}"
                )

    @pytest.mark.asyncio
    async def test_cli_tools_load_when_mcp_fails(self, tmp_path: Path) -> None:
        """CLI tools still load when MCP tool connection fails.

        User story: Developer has both CLI and MCP tools configured.
        If the MCP server is unavailable, CLI tools should still work.

        Tests graceful degradation of MCP failures.
        """
        from unittest.mock import AsyncMock, patch

        # Create tools directory with both CLI and MCP configs
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()

        # CLI tool config
        cli_config = """name: test_cli
description: Test CLI tool
command: echo
schema:
  positional:
    - name: message
      type: string
recipes:
  say:
    description: Echo a message
    params:
      message: {}
"""
        (tools_dir / "test_cli.yaml").write_text(cli_config)

        # MCP tool config (will fail to connect)
        mcp_config = """name: broken_mcp
description: MCP tool that fails
type: mcp
transport: stdio
command: nonexistent_mcp_server
"""
        (tools_dir / "broken_mcp.yaml").write_text(mcp_config)

        # Patch MCPAdapter.connect_stdio to raise an error
        with patch(
            "py_code_mode.tools.adapters.mcp.MCPAdapter.connect_stdio",
            new_callable=AsyncMock,
            side_effect=OSError("Connection failed"),
        ):
            storage = FileStorage(base_path=tmp_path)

            async with Session(storage=storage) as session:
                # CLI tool should still be accessible despite MCP failure
                result = await session.run("tools.list()")
                assert result.is_ok, f"tools.list() failed: {result.error}"
                tool_names = [t.name for t in result.value]

                assert "test_cli" in tool_names, (
                    f"CLI tool not found after MCP failure. Available: {tool_names}"
                )
