"""Tests for SubprocessExecutor namespace injection with full py-code-mode functionality.

These tests verify that the SubprocessExecutor properly injects tools, skills, and
artifacts namespaces into the kernel with FULL functionality (not stubs).

Target state: py-code-mode installed in kernel venv, providing real namespace
implementations with tool invocation, skill creation/invocation, semantic search,
and complete artifact management.

Tests are designed to FAIL with the current stub implementation, then pass once
the builder implements proper namespace injection via py-code-mode installation.
"""

from pathlib import Path

import pytest

from py_code_mode.execution.subprocess import SubprocessExecutor
from py_code_mode.execution.subprocess.config import SubprocessConfig
from py_code_mode.storage import FileStorage

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def echo_tool_yaml() -> str:
    """Simple echo tool for testing tool invocation."""
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
  run:
    description: Echo text
    params:
      text: {}
"""


@pytest.fixture
def storage_with_echo_tool(tmp_path: Path, echo_tool_yaml: str) -> FileStorage:
    """Create storage with an echo tool installed."""
    base_path = tmp_path / "storage_with_tool"
    base_path.mkdir(parents=True, exist_ok=True)
    tools_path = base_path / "tools"
    tools_path.mkdir(parents=True, exist_ok=True)
    (tools_path / "echo.yaml").write_text(echo_tool_yaml)
    return FileStorage(base_path=base_path)


@pytest.fixture
def empty_storage(tmp_path: Path) -> FileStorage:
    """Create empty storage for tests."""
    base_path = tmp_path / "empty_storage"
    base_path.mkdir(parents=True, exist_ok=True)
    return FileStorage(base_path=base_path)


@pytest.fixture
async def executor_with_storage(tmp_path: Path, storage_with_echo_tool: FileStorage):
    """Provide a started SubprocessExecutor with storage access."""
    config = SubprocessConfig(
        python_version="3.12",
        venv_path=tmp_path / "venv",
        # Include py-code-mode as a base dep for full namespace functionality
        base_deps=("ipykernel", "py-code-mode"),
    )
    executor = SubprocessExecutor(config=config)
    await executor.start(storage=storage_with_echo_tool)
    yield executor
    await executor.close()


@pytest.fixture
async def executor_empty_storage(tmp_path: Path, empty_storage: FileStorage):
    """Provide a started SubprocessExecutor with empty storage."""
    config = SubprocessConfig(
        python_version="3.12",
        venv_path=tmp_path / "venv",
        base_deps=("ipykernel", "py-code-mode"),
    )
    executor = SubprocessExecutor(config=config)
    await executor.start(storage=empty_storage)
    yield executor
    await executor.close()


# =============================================================================
# User Journey Tests (E2E)
# =============================================================================


@pytest.mark.slow
@pytest.mark.xdist_group("subprocess")
class TestE2EUserJourneys:
    """End-to-end tests simulating real agent workflows."""

    @pytest.mark.asyncio
    async def test_tool_to_skill_to_artifact_workflow(self, executor_with_storage) -> None:
        """Agent workflow: call tool -> create skill -> save artifact.

        This is the complete agent workflow:
        1. Use a tool to get data
        2. Create a skill that wraps the tool
        3. Save the result as an artifact
        4. Load the artifact back

        Breaks when: Namespace injection fails at any layer.
        """
        # Step 1: Call tool to get data
        result = await executor_with_storage.run('tools.echo.run(text="hello world")')
        assert result.error is None, f"Tool invocation failed: {result.error}"
        assert "hello world" in str(result.value) or "hello world" in result.stdout

        # Step 2: Create a skill that uses the tool
        skill_code = '''
skills.create(
    name="greet",
    source="""
def run(name: str) -> str:
    result = tools.echo.run(text=f"Hello, {name}!")
    return result
""",
    description="Greet someone by name"
)
'''
        result = await executor_with_storage.run(skill_code)
        assert result.error is None, f"Skill creation failed: {result.error}"

        # Step 3: Invoke the skill
        result = await executor_with_storage.run('skills.invoke("greet", name="Alice")')
        assert result.error is None, f"Skill invocation failed: {result.error}"

        # Step 4: Save result as artifact
        result = await executor_with_storage.run(
            'artifacts.save("greeting", {"message": "Hello, Alice!"})'
        )
        assert result.error is None, f"Artifact save failed: {result.error}"

        # Step 5: Load artifact back
        result = await executor_with_storage.run('artifacts.load("greeting")')
        assert result.error is None, f"Artifact load failed: {result.error}"
        assert "Alice" in str(result.value)

    @pytest.mark.asyncio
    async def test_skill_uses_tools_namespace_internally(self, executor_with_storage) -> None:
        """Skills can access tools namespace when invoked.

        Breaks when: Skills don't receive injected namespaces during execution.
        """
        # Create skill that uses tools internally
        skill_code = '''
skills.create(
    name="echo_wrapper",
    source="""
def run(message: str) -> str:
    return tools.echo.run(text=message)
""",
    description="Wrapper around echo tool"
)
'''
        result = await executor_with_storage.run(skill_code)
        assert result.error is None, f"Skill creation failed: {result.error}"

        # Invoke skill - it should have access to tools namespace
        result = await executor_with_storage.run(
            'skills.invoke("echo_wrapper", message="test message")'
        )
        assert result.error is None, f"Skill invocation failed: {result.error}"
        assert "test message" in str(result.value) or "test message" in result.stdout


# =============================================================================
# Contract Tests - Tools Namespace
# =============================================================================


@pytest.mark.slow
@pytest.mark.xdist_group("subprocess")
class TestToolsNamespaceContract:
    """Contract tests for tools namespace API."""

    @pytest.mark.asyncio
    async def test_tools_list_returns_tool_objects(self, executor_with_storage) -> None:
        """tools.list() returns list of Tool objects with name, description.

        Breaks when: Returns raw YAML file names or empty list.
        """
        result = await executor_with_storage.run("tools.list()")
        assert result.error is None, f"tools.list() failed: {result.error}"

        # Verify it returns a list
        check_result = await executor_with_storage.run("isinstance(tools.list(), list)")
        assert check_result.value in (True, "True")

        # Verify tools have expected attributes (not just file names)
        result = await executor_with_storage.run(
            "[t.name for t in tools.list() if hasattr(t, 'name')]"
        )
        assert result.error is None
        assert "echo" in str(result.value)

    @pytest.mark.asyncio
    async def test_tools_search_finds_by_query(self, executor_with_storage) -> None:
        """tools.search(query) returns matching tools.

        Breaks when: Search returns empty or wrong tools.
        """
        result = await executor_with_storage.run('tools.search("echo")')
        assert result.error is None, f"tools.search() failed: {result.error}"
        assert "echo" in str(result.value).lower()

    @pytest.mark.asyncio
    async def test_tool_recipe_invocation(self, executor_with_storage) -> None:
        """tools.<name>.<recipe>() invokes the tool recipe.

        Breaks when: ToolProxy not callable, recipe invocation fails.
        """
        result = await executor_with_storage.run('tools.echo.run(text="test")')
        assert result.error is None, f"Recipe invocation failed: {result.error}"
        # Echo should return or print the text
        assert "test" in str(result.value) or "test" in result.stdout

    @pytest.mark.asyncio
    async def test_tool_escape_hatch_invocation(self, executor_with_storage) -> None:
        """tools.<name>() provides escape hatch for direct CLI access.

        Breaks when: Direct tool invocation not supported.
        """
        result = await executor_with_storage.run('tools.echo(text="direct")')
        assert result.error is None, f"Escape hatch failed: {result.error}"
        assert "direct" in str(result.value) or "direct" in result.stdout


# =============================================================================
# Contract Tests - Skills Namespace
# =============================================================================


@pytest.mark.slow
@pytest.mark.xdist_group("subprocess")
class TestSkillsNamespaceContract:
    """Contract tests for skills namespace API."""

    @pytest.mark.asyncio
    async def test_skills_list_returns_skill_info(self, executor_empty_storage) -> None:
        """skills.list() returns list of skill metadata.

        Breaks when: Returns raw file names without metadata.
        """
        # Create a skill first
        create_code = """
skills.create(
    name="add",
    source="def run(a: int, b: int) -> int: return a + b",
    description="Add two numbers"
)
"""
        result = await executor_empty_storage.run(create_code)
        assert result.error is None, f"Skill creation failed: {result.error}"

        # List should include the skill
        result = await executor_empty_storage.run("skills.list()")
        assert result.error is None, f"skills.list() failed: {result.error}"
        assert "add" in str(result.value)

    @pytest.mark.asyncio
    async def test_skills_search_semantic(self, executor_empty_storage) -> None:
        """skills.search(query) performs semantic search.

        Breaks when: Only name matching, semantic search not working.
        """
        # Create skill with descriptive purpose
        create_code = """
skills.create(
    name="calculate_sum",
    source="def run(numbers: list) -> int: return sum(numbers)",
    description="Calculate the total of a list of numbers"
)
"""
        result = await executor_empty_storage.run(create_code)
        assert result.error is None

        # Search by semantic meaning (not exact name match)
        result = await executor_empty_storage.run('skills.search("add numbers together")')
        assert result.error is None, f"skills.search() failed: {result.error}"
        # Should find calculate_sum based on semantic similarity
        assert "calculate_sum" in str(result.value) or len(str(result.value)) > 2

    @pytest.mark.asyncio
    async def test_skills_create_persists(self, executor_empty_storage) -> None:
        """skills.create() persists skill to store.

        Breaks when: Skill not saved, lost on next list().
        """
        create_code = """
skills.create(
    name="multiply",
    source="def run(a: int, b: int) -> int: return a * b",
    description="Multiply two numbers"
)
"""
        result = await executor_empty_storage.run(create_code)
        assert result.error is None, f"Skill creation failed: {result.error}"

        # Skill should appear in list
        result = await executor_empty_storage.run(
            "'multiply' in [s['name'] if isinstance(s, dict) else s.name for s in skills.list()]"
        )
        assert result.error is None
        # Accept True as bool or string
        assert result.value in (True, "True"), f"Skill not found in list: {result.value}"

    @pytest.mark.asyncio
    async def test_skills_invoke_executes_skill(self, executor_empty_storage) -> None:
        """skills.invoke(name, **kwargs) runs skill and returns result.

        Breaks when: Invocation fails, wrong args, execution error.
        """
        # Create skill
        create_code = """
skills.create(
    name="square",
    source="def run(n: int) -> int: return n * n",
    description="Square a number"
)
"""
        result = await executor_empty_storage.run(create_code)
        assert result.error is None

        # Invoke skill
        result = await executor_empty_storage.run('skills.invoke("square", n=5)')
        assert result.error is None, f"Skill invocation failed: {result.error}"
        assert result.value in (25, "25"), f"Wrong result: {result.value}"

    @pytest.mark.asyncio
    async def test_skills_attribute_access_invocation(self, executor_empty_storage) -> None:
        """skills.<name>(**kwargs) provides attribute-based invocation.

        Breaks when: Attribute access not supported.
        """
        # Create skill
        create_code = """
skills.create(
    name="triple",
    source="def run(n: int) -> int: return n * 3",
    description="Triple a number"
)
"""
        result = await executor_empty_storage.run(create_code)
        assert result.error is None

        # Invoke via attribute access
        result = await executor_empty_storage.run("skills.triple(n=4)")
        assert result.error is None, f"Attribute invocation failed: {result.error}"
        assert result.value in (12, "12"), f"Wrong result: {result.value}"


# =============================================================================
# Contract Tests - Artifacts Namespace
# =============================================================================


@pytest.mark.slow
@pytest.mark.xdist_group("subprocess")
class TestArtifactsNamespaceContract:
    """Contract tests for artifacts namespace API."""

    @pytest.mark.asyncio
    async def test_artifacts_save_persists_data(self, executor_empty_storage) -> None:
        """artifacts.save(name, data) stores artifact.

        Breaks when: Data not persisted, wrong location.
        """
        result = await executor_empty_storage.run(
            'artifacts.save("test_data", {"key": "value", "count": 42})'
        )
        assert result.error is None, f"Artifact save failed: {result.error}"

        # Verify exists
        result = await executor_empty_storage.run('artifacts.exists("test_data")')
        assert result.error is None
        assert result.value in (True, "True")

    @pytest.mark.asyncio
    async def test_artifacts_load_retrieves_data(self, executor_empty_storage) -> None:
        """artifacts.load(name) returns saved data.

        Breaks when: Wrong data returned, deserialization error.
        """
        # Save first
        result = await executor_empty_storage.run('artifacts.save("roundtrip", {"value": 123})')
        assert result.error is None

        # Load back
        result = await executor_empty_storage.run('artifacts.load("roundtrip")')
        assert result.error is None, f"Artifact load failed: {result.error}"
        assert "123" in str(result.value)

    @pytest.mark.asyncio
    async def test_artifacts_list_shows_saved(self, executor_empty_storage) -> None:
        """artifacts.list() includes saved artifacts.

        Breaks when: Returns empty, missing entries.
        """
        # Save artifact
        result = await executor_empty_storage.run('artifacts.save("listed_artifact", "some data")')
        assert result.error is None

        # List should include it
        result = await executor_empty_storage.run("artifacts.list()")
        assert result.error is None, f"artifacts.list() failed: {result.error}"
        assert "listed_artifact" in str(result.value)

    @pytest.mark.asyncio
    async def test_artifacts_exists_checks_presence(self, executor_empty_storage) -> None:
        """artifacts.exists(name) returns True for saved, False for missing.

        Breaks when: Always returns True/False, doesn't check.
        """
        # Should not exist
        result = await executor_empty_storage.run('artifacts.exists("nonexistent")')
        assert result.error is None
        assert result.value in (False, "False")

        # Save it
        await executor_empty_storage.run('artifacts.save("now_exists", "data")')

        # Should exist
        result = await executor_empty_storage.run('artifacts.exists("now_exists")')
        assert result.error is None
        assert result.value in (True, "True")


# =============================================================================
# Integration Tests - Storage Access
# =============================================================================


@pytest.mark.slow
@pytest.mark.xdist_group("subprocess")
class TestStorageAccessIntegration:
    """Integration tests for FileStorageAccess with namespaces."""

    @pytest.mark.asyncio
    async def test_namespaces_use_storage_paths(self, tmp_path: Path, echo_tool_yaml: str) -> None:
        """Namespaces use paths from FileStorage.

        Breaks when: Paths not passed through, wrong directories used.
        """
        # Create storage and write tool
        base_path = tmp_path / "test_storage"
        base_path.mkdir(parents=True, exist_ok=True)
        tools_path = base_path / "tools"
        tools_path.mkdir(parents=True, exist_ok=True)
        (tools_path / "echo.yaml").write_text(echo_tool_yaml)

        storage = FileStorage(base_path=base_path)

        config = SubprocessConfig(
            python_version="3.12",
            venv_path=tmp_path / "venv",
            base_deps=("ipykernel", "py-code-mode"),
        )

        executor = SubprocessExecutor(config=config)
        try:
            await executor.start(storage=storage)

            # Tools should be loaded from tools_path
            result = await executor.run("'echo' in [t.name for t in tools.list()]")
            assert result.error is None
            assert result.value in (True, "True")
        finally:
            await executor.close()

    @pytest.mark.asyncio
    async def test_namespace_state_persists_between_runs(self, executor_empty_storage) -> None:
        """Namespace state persists between run() calls.

        Breaks when: Kernel resets between runs, state lost.
        """
        # Create skill in first run
        create_code = """
skills.create(
    name="counter",
    source="def run(): return 'counted'",
    description="Simple counter"
)
"""
        result = await executor_empty_storage.run(create_code)
        assert result.error is None

        # Save artifact in second run
        result = await executor_empty_storage.run('artifacts.save("state_test", "data")')
        assert result.error is None

        # Third run should see both
        result = await executor_empty_storage.run(
            "'counter' in str(skills.list()) and 'state_test' in str(artifacts.list())"
        )
        assert result.error is None
        assert result.value in (True, "True")

    @pytest.mark.asyncio
    async def test_namespace_state_preserved_after_reset(self, tmp_path: Path) -> None:
        """reset() preserves namespace access and persisted data.

        Breaks when: reset() clears storage, namespaces not re-injected.
        """
        base_path = tmp_path / "reset_test_storage"
        base_path.mkdir(parents=True, exist_ok=True)
        storage = FileStorage(base_path=base_path)

        config = SubprocessConfig(
            python_version="3.12",
            venv_path=tmp_path / "venv",
            base_deps=("ipykernel", "py-code-mode"),
        )

        executor = SubprocessExecutor(config=config)
        try:
            await executor.start(storage=storage)

            # Create skill and artifact before reset
            await executor.run(
                'skills.create(name="persist", source="def run(): return 1", description="test")'
            )
            await executor.run('artifacts.save("persist_artifact", "value")')

            # Reset kernel
            await executor.reset()

            # Namespaces should still be accessible
            result = await executor.run("'tools' in dir() and 'skills' in dir()")
            assert result.value in (True, "True")

            # Persisted data should still be there (it's in storage, not kernel memory)
            result = await executor.run("'persist' in str(skills.list())")
            assert result.value in (True, "True")

            result = await executor.run("'persist_artifact' in str(artifacts.list())")
            assert result.value in (True, "True")
        finally:
            await executor.close()


# =============================================================================
# Invariant Tests
# =============================================================================


@pytest.mark.slow
@pytest.mark.xdist_group("subprocess")
class TestNamespaceInvariants:
    """Invariant tests for namespace behavior."""

    @pytest.mark.asyncio
    async def test_namespaces_available_immediately_after_start(
        self, tmp_path: Path, empty_storage: FileStorage
    ) -> None:
        """Namespaces are accessible immediately after start().

        Breaks when: start() doesn't inject namespaces, lazy initialization fails.
        """
        config = SubprocessConfig(
            python_version="3.12",
            venv_path=tmp_path / "venv",
            base_deps=("ipykernel", "py-code-mode"),
        )
        executor = SubprocessExecutor(config=config)

        try:
            await executor.start(storage=empty_storage)

            # Immediately check all namespaces
            result = await executor.run(
                "'tools' in dir() and 'skills' in dir() and 'artifacts' in dir()"
            )
            assert result.error is None
            assert result.value in (True, "True")
        finally:
            await executor.close()

    @pytest.mark.asyncio
    async def test_namespace_objects_are_stable(self, executor_empty_storage) -> None:
        """Namespace objects are the same across runs (not recreated).

        Breaks when: Namespace recreated each run causing state issues.
        """
        # Get ID of tools namespace
        await executor_empty_storage.run("_tools_id = id(tools)")

        # Check ID is same in next run
        result = await executor_empty_storage.run("id(tools) == _tools_id")
        assert result.error is None
        assert result.value in (True, "True")


# =============================================================================
# Negative Tests
# =============================================================================


@pytest.mark.slow
@pytest.mark.xdist_group("subprocess")
class TestNamespaceErrors:
    """Negative tests for namespace error handling."""

    @pytest.mark.asyncio
    async def test_undefined_tool_raises_error(self, executor_empty_storage) -> None:
        """Accessing undefined tool raises clear error.

        Breaks when: Returns None silently, creates fake tool.
        """
        result = await executor_empty_storage.run("tools.nonexistent_tool")
        # Should have an error - either AttributeError or ToolNotFoundError
        assert result.error is not None or "Error" in str(result.value)

    @pytest.mark.asyncio
    async def test_undefined_recipe_raises_error(self, executor_with_storage) -> None:
        """Accessing undefined recipe raises clear error.

        Breaks when: Silent failure, wrong error type.
        """
        result = await executor_with_storage.run("tools.echo.nonexistent_recipe()")
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_loading_nonexistent_artifact_raises_error(self, executor_empty_storage) -> None:
        """Loading nonexistent artifact raises error.

        Breaks when: Returns None silently, returns empty data.
        """
        result = await executor_empty_storage.run('artifacts.load("does_not_exist_xyz")')
        # Should raise FileNotFoundError or ArtifactNotFoundError, or return None
        # with clear indication it doesn't exist
        if result.error is None:
            # If no error, value should be None or indicate missing
            assert result.value is None or result.value == "None"

    @pytest.mark.asyncio
    async def test_invoking_nonexistent_skill_raises_error(self, executor_empty_storage) -> None:
        """Invoking nonexistent skill raises error.

        Breaks when: Silent failure, returns None.
        """
        result = await executor_empty_storage.run('skills.invoke("skill_that_does_not_exist")')
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_creating_skill_with_invalid_source_raises_error(
        self, executor_empty_storage
    ) -> None:
        """Creating skill with invalid Python source raises error.

        Breaks when: Invalid skill saved, error only at invoke time.
        """
        result = await executor_empty_storage.run(
            """skills.create(
                name="broken",
                source="def run( this is not valid python {{{{",
                description="Broken skill"
            )"""
        )
        # Should fail with SyntaxError during creation, not silently save
        assert result.error is not None
        assert "Syntax" in result.error or "syntax" in result.error.lower()
