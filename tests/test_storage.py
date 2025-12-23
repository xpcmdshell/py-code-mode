"""Tests for StorageBackend.get_serializable_access() method.

This method returns serializable access descriptors for cross-process communication.
Used by executors that run in separate processes (like ContainerExecutor) and need
connection info rather than direct object references.

TDD RED phase: These tests are written before implementation.
They will fail until get_serializable_access() is implemented on both backends.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from py_code_mode.execution.protocol import FileStorageAccess, RedisStorageAccess
from py_code_mode.storage import FileStorage, RedisStorage

if TYPE_CHECKING:
    from tests.conftest import MockRedisClient


class TestGetSerializableAccess:
    """Tests for StorageBackend.get_serializable_access() method.

    This method enables cross-process communication by returning
    serializable descriptors that contain paths/URLs instead of
    live object references.
    """

    # =========================================================================
    # FileStorage.get_serializable_access() tests
    # =========================================================================

    class TestFileStorageAccess:
        """Tests for FileStorage.get_serializable_access()."""

        def test_returns_file_storage_access_type(self, tmp_path: Path) -> None:
            """get_serializable_access() returns FileStorageAccess instance.

            Breaks when: Return type is wrong or method doesn't exist.
            """
            storage = FileStorage(tmp_path)

            result = storage.get_serializable_access()

            assert isinstance(result, FileStorageAccess)

        def test_tools_path_is_none_when_directory_does_not_exist(self, tmp_path: Path) -> None:
            """tools_path is None if tools/ directory doesn't exist.

            Breaks when: tools_path is set even when directory is missing.
            """
            # Create storage but don't create tools/ directory
            storage = FileStorage(tmp_path)
            # Verify tools/ doesn't exist (FileStorage creates it lazily)
            tools_dir = tmp_path / "tools"
            assert not tools_dir.exists()

            result = storage.get_serializable_access()

            assert result.tools_path is None

        def test_tools_path_is_set_when_directory_exists(self, tmp_path: Path) -> None:
            """tools_path points to tools/ when directory exists.

            Breaks when: tools_path is None despite directory existing.
            """
            # Create the tools directory before getting access
            tools_dir = tmp_path / "tools"
            tools_dir.mkdir(parents=True, exist_ok=True)
            storage = FileStorage(tmp_path)

            result = storage.get_serializable_access()

            assert result.tools_path is not None
            assert result.tools_path == tools_dir

        def test_skills_path_is_always_set(self, tmp_path: Path) -> None:
            """skills_path is always set (points to skills/ subdirectory).

            Breaks when: skills_path is None or points to wrong location.
            """
            storage = FileStorage(tmp_path)

            result = storage.get_serializable_access()

            expected_skills_path = tmp_path / "skills"
            assert result.skills_path == expected_skills_path

        def test_artifacts_path_is_always_set(self, tmp_path: Path) -> None:
            """artifacts_path is always set (points to artifacts/ subdirectory).

            Breaks when: artifacts_path is None or points to wrong location.
            """
            storage = FileStorage(tmp_path)

            result = storage.get_serializable_access()

            expected_artifacts_path = tmp_path / "artifacts"
            assert result.artifacts_path == expected_artifacts_path

        def test_paths_are_absolute(self, tmp_path: Path) -> None:
            """All returned paths are absolute paths.

            Breaks when: Relative paths are returned (would break cross-process use).
            """
            storage = FileStorage(tmp_path)
            # Create tools dir so tools_path is not None
            (tmp_path / "tools").mkdir(exist_ok=True)

            result = storage.get_serializable_access()

            if result.tools_path is not None:
                assert result.tools_path.is_absolute()
            assert result.skills_path.is_absolute()
            assert result.artifacts_path.is_absolute()

        def test_access_descriptor_is_frozen_dataclass(self, tmp_path: Path) -> None:
            """FileStorageAccess is immutable (frozen dataclass).

            Breaks when: Descriptor can be mutated after creation.
            """
            storage = FileStorage(tmp_path)

            result = storage.get_serializable_access()

            with pytest.raises(AttributeError):
                result.artifacts_path = Path("/hacked")  # type: ignore[misc]

    # =========================================================================
    # RedisStorage.get_serializable_access() tests
    # =========================================================================

    class TestRedisStorageAccess:
        """Tests for RedisStorage.get_serializable_access()."""

        def test_returns_redis_storage_access_type(self, mock_redis: MockRedisClient) -> None:
            """get_serializable_access() returns RedisStorageAccess instance.

            Breaks when: Return type is wrong or method doesn't exist.
            """
            storage = RedisStorage(mock_redis, prefix="test")

            result = storage.get_serializable_access()

            assert isinstance(result, RedisStorageAccess)

        def test_redis_url_is_correctly_reconstructed(self, mock_redis: MockRedisClient) -> None:
            """redis_url is reconstructed from connection pool kwargs.

            Breaks when: URL format is wrong or components are missing.
            """
            storage = RedisStorage(mock_redis, prefix="test")

            result = storage.get_serializable_access()

            # MockRedisClient defaults: host=localhost, port=6379, db=0
            assert result.redis_url == "redis://localhost:6379/0"

        def test_redis_url_includes_password_when_present(self) -> None:
            """redis_url includes password in URL format when set.

            Breaks when: Password is omitted or URL format is wrong.
            """
            from tests.conftest import MockRedisClient

            # Create mock with password
            mock_with_password = MockRedisClient(
                host="redis.example.com",
                port=6380,
                db=2,
                password="secret123",
            )
            storage = RedisStorage(mock_with_password, prefix="secure")

            result = storage.get_serializable_access()

            assert result.redis_url == "redis://:secret123@redis.example.com:6380/2"

        def test_redis_url_without_password(self) -> None:
            """redis_url works correctly when no password is set.

            Breaks when: Empty password breaks URL format.
            """
            from tests.conftest import MockRedisClient

            mock_no_password = MockRedisClient(
                host="localhost",
                port=6379,
                db=0,
                password=None,
            )
            storage = RedisStorage(mock_no_password, prefix="test")

            result = storage.get_serializable_access()

            # Should not have :password@ in URL
            assert "@" not in result.redis_url
            assert result.redis_url == "redis://localhost:6379/0"

        def test_tools_prefix_is_correctly_formatted(self, mock_redis: MockRedisClient) -> None:
            """tools_prefix follows {prefix}:tools format.

            Breaks when: Prefix format doesn't match expected pattern.
            """
            storage = RedisStorage(mock_redis, prefix="myapp")

            result = storage.get_serializable_access()

            assert result.tools_prefix == "myapp:tools"

        def test_skills_prefix_is_correctly_formatted(self, mock_redis: MockRedisClient) -> None:
            """skills_prefix follows {prefix}:skills format.

            Breaks when: Prefix format doesn't match expected pattern.
            """
            storage = RedisStorage(mock_redis, prefix="myapp")

            result = storage.get_serializable_access()

            assert result.skills_prefix == "myapp:skills"

        def test_artifacts_prefix_is_correctly_formatted(self, mock_redis: MockRedisClient) -> None:
            """artifacts_prefix follows {prefix}:artifacts format.

            Breaks when: Prefix format doesn't match expected pattern.
            """
            storage = RedisStorage(mock_redis, prefix="myapp")

            result = storage.get_serializable_access()

            assert result.artifacts_prefix == "myapp:artifacts"

        def test_access_descriptor_is_frozen_dataclass(self, mock_redis: MockRedisClient) -> None:
            """RedisStorageAccess is immutable (frozen dataclass).

            Breaks when: Descriptor can be mutated after creation.
            """
            storage = RedisStorage(mock_redis, prefix="test")

            result = storage.get_serializable_access()

            with pytest.raises(AttributeError):
                result.redis_url = "redis://hacked:6379/0"  # type: ignore[misc]

        def test_uses_custom_host_and_port(self) -> None:
            """redis_url uses custom host and port from connection.

            Breaks when: Default host/port is used instead of actual values.
            """
            from tests.conftest import MockRedisClient

            mock_custom = MockRedisClient(
                host="redis-cluster.internal",
                port=16379,
                db=5,
            )
            storage = RedisStorage(mock_custom, prefix="production")

            result = storage.get_serializable_access()

            assert result.redis_url == "redis://redis-cluster.internal:16379/5"

    # =========================================================================
    # Protocol compliance tests
    # =========================================================================

    class TestProtocolCompliance:
        """Tests verifying both implementations satisfy the protocol."""

        def test_file_storage_returns_union_type(self, tmp_path: Path) -> None:
            """FileStorage returns type compatible with StorageAccess union.

            Breaks when: Return type doesn't match expected union.
            """
            storage = FileStorage(tmp_path)

            result = storage.get_serializable_access()

            # Should be FileStorageAccess (part of the union)
            assert isinstance(result, FileStorageAccess)

        def test_redis_storage_returns_union_type(self, mock_redis: MockRedisClient) -> None:
            """RedisStorage returns type compatible with StorageAccess union.

            Breaks when: Return type doesn't match expected union.
            """
            storage = RedisStorage(mock_redis, prefix="test")

            result = storage.get_serializable_access()

            # Should be RedisStorageAccess (part of the union)
            assert isinstance(result, RedisStorageAccess)

        def test_method_exists_on_file_storage(self, tmp_path: Path) -> None:
            """FileStorage has get_serializable_access method.

            Breaks when: Method is missing from implementation.
            """
            storage = FileStorage(tmp_path)

            assert hasattr(storage, "get_serializable_access")
            assert callable(storage.get_serializable_access)

        def test_method_exists_on_redis_storage(self, mock_redis: MockRedisClient) -> None:
            """RedisStorage has get_serializable_access method.

            Breaks when: Method is missing from implementation.
            """
            storage = RedisStorage(mock_redis, prefix="test")

            assert hasattr(storage, "get_serializable_access")
            assert callable(storage.get_serializable_access)


class TestStorageBackendExecutionMethods:
    """Tests for StorageBackend.get_tool_registry() and get_skill_library() methods.

    These methods enable executors to access tools and skills from storage backends.
    They initialize the appropriate registries and libraries based on the storage type.

    TDD RED phase: These tests are written before implementation.
    """

    # =========================================================================
    # User Journey Tests (E2E)
    # =========================================================================

    class TestUserJourney:
        """Complete developer workflow from storage to execution."""

        @pytest.mark.asyncio
        async def test_file_storage_complete_journey(self, tmp_path: Path) -> None:
            """Developer sets up FileStorage, gets registry and library, uses in code.

            User action: Set up local dev environment with file-based storage
            Setup: FileStorage with tools and skills on disk
            Steps:
                1. Create storage with tools/ and skills/
                2. Get tool registry
                3. Get skill library
                4. Use tools and skills in code execution
            Verification: All components work together
            Breaks when: Any step in the workflow fails or components don't integrate
            """
            from py_code_mode.skills import SkillLibrary
            from py_code_mode.tools import ToolRegistry

            # Setup: Create storage with content
            storage = FileStorage(tmp_path)
            tools_dir = tmp_path / "tools"
            skills_dir = tmp_path / "skills"
            tools_dir.mkdir()
            skills_dir.mkdir()

            # Add a sample tool YAML
            tool_yaml = tools_dir / "echo.yaml"
            tool_yaml.write_text("""
name: echo
description: Echo text
command: echo
timeout: 10
schema:
  positional:
    - name: text
      type: string
      required: true
recipes:
  say:
    description: Echo text
    params:
      text: {}
""")

            # Add a sample skill
            skill_file = skills_dir / "greet.py"
            skill_file.write_text('''
"""Greet a user."""

def run(name: str) -> str:
    return f"Hello, {name}!"
''')

            # Step 1: Get tool registry
            tool_registry = await storage.get_tool_registry()
            assert isinstance(tool_registry, ToolRegistry)

            # Step 2: Get skill library
            skill_library = storage.get_skill_library()
            assert isinstance(skill_library, SkillLibrary)

            # Step 3: Verify tools are loaded
            tools = tool_registry.list_tools()
            tool_names = [t.name for t in tools]
            assert "echo" in tool_names

            # Step 4: Verify skills are loaded
            all_skills = skill_library.list()
            assert any(s.name == "greet" for s in all_skills)

        @pytest.mark.asyncio
        async def test_redis_storage_complete_journey(self, mock_redis: MockRedisClient) -> None:
            """Developer sets up RedisStorage, gets registry and library, uses in code.

            User action: Set up distributed environment with Redis-based storage
            Setup: RedisStorage with tools and skills in Redis
            Steps:
                1. Create storage with prefix
                2. Populate tools and skills
                3. Get tool registry
                4. Get skill library
                5. Use tools and skills in code execution
            Verification: All components work together across Redis boundary
            Breaks when: Redis integration fails or components don't load correctly
            """
            from py_code_mode.skills import PythonSkill, SkillLibrary
            from py_code_mode.tools import ToolRegistry

            # Setup: Create storage
            storage = RedisStorage(mock_redis, prefix="test")

            # Populate a skill directly to Redis store
            skill_store = storage.get_skill_store()
            test_skill = PythonSkill.from_source(
                name="greet",
                source='def run(name: str) -> str:\n    return f"Hello, {name}!"',
                description="Greet a user",
            )
            skill_store.save(test_skill)

            # Step 1: Get tool registry
            tool_registry = await storage.get_tool_registry()
            assert isinstance(tool_registry, ToolRegistry)

            # Step 2: Get skill library
            skill_library = storage.get_skill_library()
            assert isinstance(skill_library, SkillLibrary)

            # Step 3: Verify skills are loaded
            loaded_skill = skill_library.get("greet")
            assert loaded_skill is not None
            assert loaded_skill.name == "greet"

    # =========================================================================
    # Contract Tests - FileStorage
    # =========================================================================

    class TestFileStorageContracts:
        """Contract tests for FileStorage methods."""

        @pytest.mark.asyncio
        async def test_get_tool_registry_returns_tool_registry_instance(
            self, tmp_path: Path
        ) -> None:
            """get_tool_registry() returns ToolRegistry instance.

            Contract: Method must return initialized ToolRegistry
            Verification: Return type is ToolRegistry
            Breaks when: Method returns wrong type or None
            """
            from py_code_mode.tools import ToolRegistry

            storage = FileStorage(tmp_path)

            result = await storage.get_tool_registry()

            assert isinstance(result, ToolRegistry)

        @pytest.mark.asyncio
        async def test_get_skill_library_returns_skill_library_instance(
            self, tmp_path: Path
        ) -> None:
            """get_skill_library() returns SkillLibrary instance.

            Contract: Method must return initialized SkillLibrary
            Verification: Return type is SkillLibrary
            Breaks when: Method returns wrong type or None
            """
            from py_code_mode.skills import SkillLibrary

            storage = FileStorage(tmp_path)

            result = storage.get_skill_library()

            assert isinstance(result, SkillLibrary)

        @pytest.mark.asyncio
        async def test_get_tool_registry_loads_tools_from_tools_directory(
            self, tmp_path: Path
        ) -> None:
            """get_tool_registry() loads all tool YAMLs from tools/ directory.

            Contract: Registry must contain tools from tools/ directory
            Verification: Tool defined in YAML is present in registry
            Breaks when: Tools directory is not scanned or YAMLs are not loaded
            """
            storage = FileStorage(tmp_path)
            tools_dir = tmp_path / "tools"
            tools_dir.mkdir()

            # Create a tool YAML
            tool_yaml = tools_dir / "test_tool.yaml"
            tool_yaml.write_text("""
name: test_tool
description: A test tool
command: echo
timeout: 10
schema:
  positional:
    - name: arg
      type: string
      required: true
recipes:
  run:
    description: Run test
    params:
      arg: {}
""")

            registry = await storage.get_tool_registry()

            tools = registry.list_tools()
            tool_names = [t.name for t in tools]
            assert "test_tool" in tool_names

        @pytest.mark.asyncio
        async def test_get_skill_library_loads_skills_from_skills_directory(
            self, tmp_path: Path
        ) -> None:
            """get_skill_library() loads all .py files from skills/ directory.

            Contract: Library must contain skills from skills/ directory
            Verification: Skill defined in .py file is present in library
            Breaks when: Skills directory is not scanned or .py files are not loaded
            """
            storage = FileStorage(tmp_path)
            skills_dir = tmp_path / "skills"
            skills_dir.mkdir()

            # Create a skill file
            skill_file = skills_dir / "test_skill.py"
            skill_file.write_text('''
"""A test skill."""

def run() -> str:
    return "test"
''')

            library = storage.get_skill_library()

            skill = library.get("test_skill")
            assert skill is not None
            assert skill.name == "test_skill"

        @pytest.mark.asyncio
        async def test_get_tool_registry_returns_empty_when_no_tools_directory(
            self, tmp_path: Path
        ) -> None:
            """get_tool_registry() returns empty registry when tools/ doesn't exist.

            Contract: Method should not fail when tools directory is absent
            Verification: Returns valid but empty ToolRegistry
            Breaks when: Method raises exception or returns None
            """
            storage = FileStorage(tmp_path)
            # Don't create tools/ directory

            registry = await storage.get_tool_registry()

            tools = registry.list_tools()
            assert len(tools) == 0

        @pytest.mark.asyncio
        async def test_get_skill_library_works_when_skills_directory_empty(
            self, tmp_path: Path
        ) -> None:
            """get_skill_library() works when skills/ exists but is empty.

            Contract: Method should not fail when skills directory is empty
            Verification: Returns valid but empty SkillLibrary
            Breaks when: Method raises exception or returns None
            """
            storage = FileStorage(tmp_path)
            skills_dir = tmp_path / "skills"
            skills_dir.mkdir()

            library = storage.get_skill_library()

            skills = library.list()
            assert len(skills) == 0

    # =========================================================================
    # Contract Tests - RedisStorage
    # =========================================================================

    class TestRedisStorageContracts:
        """Contract tests for RedisStorage methods."""

        @pytest.mark.asyncio
        async def test_get_tool_registry_returns_tool_registry_instance(
            self, mock_redis: MockRedisClient
        ) -> None:
            """get_tool_registry() returns ToolRegistry instance.

            Contract: Method must return initialized ToolRegistry
            Verification: Return type is ToolRegistry
            Breaks when: Method returns wrong type or None
            """
            from py_code_mode.tools import ToolRegistry

            storage = RedisStorage(mock_redis, prefix="test")

            result = await storage.get_tool_registry()

            assert isinstance(result, ToolRegistry)

        @pytest.mark.asyncio
        async def test_get_skill_library_returns_skill_library_instance(
            self, mock_redis: MockRedisClient
        ) -> None:
            """get_skill_library() returns SkillLibrary instance.

            Contract: Method must return initialized SkillLibrary
            Verification: Return type is SkillLibrary
            Breaks when: Method returns wrong type or None
            """
            from py_code_mode.skills import SkillLibrary

            storage = RedisStorage(mock_redis, prefix="test")

            result = storage.get_skill_library()

            assert isinstance(result, SkillLibrary)

        @pytest.mark.asyncio
        async def test_get_tool_registry_loads_tools_from_redis(
            self, mock_redis: MockRedisClient
        ) -> None:
            """get_tool_registry() loads tools from Redis keys.

            Contract: Registry must contain tools stored in Redis
            Verification: Tool stored in Redis is present in registry
            Breaks when: Redis keys are not scanned or tools are not loaded
            """
            import json

            storage = RedisStorage(mock_redis, prefix="test")

            # Store a tool config directly in Redis using RedisToolStore format
            tool_config = {
                "name": "test_tool",
                "description": "A test tool",
                "command": "echo",
                "timeout": 10,
                "schema": {"positional": [{"name": "arg", "type": "string", "required": True}]},
                "recipes": {"run": {"description": "Run test", "params": {"arg": {}}}},
            }

            # RedisToolStore uses a hash at {prefix}:__tools__
            hash_key = "test:tools:__tools__"
            mock_redis._data[hash_key] = {"test_tool": json.dumps(tool_config)}

            registry = await storage.get_tool_registry()

            tools = registry.list_tools()
            tool_names = [t.name for t in tools]
            assert "test_tool" in tool_names

        @pytest.mark.asyncio
        async def test_get_skill_library_loads_skills_from_redis(
            self, mock_redis: MockRedisClient
        ) -> None:
            """get_skill_library() loads skills from Redis keys.

            Contract: Library must contain skills stored in Redis
            Verification: Skill stored in Redis is present in library
            Breaks when: Redis keys are not scanned or skills are not loaded
            """
            from py_code_mode.skills import PythonSkill

            storage = RedisStorage(mock_redis, prefix="test")

            # Store a skill via the skill store
            skill_store = storage.get_skill_store()
            test_skill = PythonSkill.from_source(
                name="test_skill",
                source='def run() -> str:\n    return "test"',
                description="A test skill",
            )
            skill_store.save(test_skill)

            library = storage.get_skill_library()

            skill = library.get("test_skill")
            assert skill is not None
            assert skill.name == "test_skill"

        @pytest.mark.asyncio
        async def test_get_tool_registry_returns_empty_when_no_tools_in_redis(
            self, mock_redis: MockRedisClient
        ) -> None:
            """get_tool_registry() returns empty registry when no tools in Redis.

            Contract: Method should not fail when no tools are stored
            Verification: Returns valid but empty ToolRegistry
            Breaks when: Method raises exception or returns None
            """
            storage = RedisStorage(mock_redis, prefix="test")
            # Don't store any tools

            registry = await storage.get_tool_registry()

            tools = registry.list_tools()
            assert len(tools) == 0

        @pytest.mark.asyncio
        async def test_get_skill_library_works_when_no_skills_in_redis(
            self, mock_redis: MockRedisClient
        ) -> None:
            """get_skill_library() works when no skills are stored in Redis.

            Contract: Method should not fail when no skills are stored
            Verification: Returns valid but empty SkillLibrary
            Breaks when: Method raises exception or returns None
            """
            storage = RedisStorage(mock_redis, prefix="test")
            # Don't store any skills

            library = storage.get_skill_library()

            skills = library.list()
            assert len(skills) == 0

    # =========================================================================
    # Integration Tests
    # =========================================================================

    class TestStorageExecutorIntegration:
        """Tests for storage backend and executor integration."""

        @pytest.mark.asyncio
        async def test_file_storage_registry_and_library_use_same_paths(
            self, tmp_path: Path
        ) -> None:
            """Registry and library from FileStorage reference same directories.

            Boundary: FileStorage -> ToolRegistry, SkillLibrary
            Verification: Both use base_path subdirectories consistently
            Breaks when: Registry and library point to different locations
            """
            storage = FileStorage(tmp_path)
            tools_dir = tmp_path / "tools"
            skills_dir = tmp_path / "skills"
            tools_dir.mkdir()
            skills_dir.mkdir()

            # Create content in both
            (tools_dir / "tool.yaml").write_text("""
name: tool
description: Test
command: echo
timeout: 10
schema:
  positional:
    - name: arg
      type: string
      required: true
recipes:
  run:
    description: Run
    params:
      arg: {}
""")
            (skills_dir / "skill.py").write_text('''
"""Test skill."""
def run() -> str:
    return "test"
''')

            registry = await storage.get_tool_registry()
            library = storage.get_skill_library()

            # Both should see the content
            tool_names = [t.name for t in registry.list_tools()]
            assert "tool" in tool_names
            assert library.get("skill") is not None

        @pytest.mark.asyncio
        async def test_redis_storage_registry_and_library_use_same_prefix(
            self, mock_redis: MockRedisClient
        ) -> None:
            """Registry and library from RedisStorage use same prefix.

            Boundary: RedisStorage -> ToolRegistry, SkillLibrary
            Verification: Both use storage prefix consistently
            Breaks when: Registry and library use different Redis prefixes
            """
            from py_code_mode.skills import PythonSkill

            storage = RedisStorage(mock_redis, prefix="myapp")

            # Store a skill
            skill_store = storage.get_skill_store()
            test_skill = PythonSkill.from_source(
                name="test_skill",
                source='def run() -> str:\n    return "test"',
                description="Test",
            )
            skill_store.save(test_skill)

            library = storage.get_skill_library()

            # Library should find the skill with same prefix
            skill = library.get("test_skill")
            assert skill is not None

    # =========================================================================
    # Negative Tests
    # =========================================================================

    class TestNegativeCases:
        """Tests for error conditions and edge cases."""

        @pytest.mark.asyncio
        async def test_file_storage_handles_invalid_tool_yaml_gracefully(
            self, tmp_path: Path
        ) -> None:
            """get_tool_registry() handles malformed YAML without crashing.

            Input: Invalid YAML in tools/ directory
            Expected behavior: Method completes, skips invalid file
            Breaks when: Method raises exception for malformed YAML
            """
            from py_code_mode.tools import ToolRegistry

            storage = FileStorage(tmp_path)
            tools_dir = tmp_path / "tools"
            tools_dir.mkdir()

            # Create invalid YAML
            (tools_dir / "broken.yaml").write_text("{ invalid yaml content ]")

            # Should not raise
            registry = await storage.get_tool_registry()
            assert isinstance(registry, ToolRegistry)

        @pytest.mark.asyncio
        async def test_file_storage_handles_invalid_skill_python_gracefully(
            self, tmp_path: Path
        ) -> None:
            """get_skill_library() handles malformed Python without crashing.

            Input: Syntax error in .py file in skills/ directory
            Expected behavior: Method completes, skips invalid file
            Breaks when: Method raises exception for syntax errors
            """
            from py_code_mode.skills import SkillLibrary

            storage = FileStorage(tmp_path)
            skills_dir = tmp_path / "skills"
            skills_dir.mkdir()

            # Create invalid Python
            (skills_dir / "broken.py").write_text("def run(:\n    invalid syntax")

            # Should not raise
            library = storage.get_skill_library()
            assert isinstance(library, SkillLibrary)

        @pytest.mark.asyncio
        async def test_file_storage_skips_non_yaml_files_in_tools(self, tmp_path: Path) -> None:
            """get_tool_registry() ignores non-.yaml files in tools/ directory.

            Input: .txt, .md files in tools/ directory
            Expected behavior: Only .yaml files are processed
            Breaks when: Non-YAML files cause errors or are incorrectly processed
            """
            storage = FileStorage(tmp_path)
            tools_dir = tmp_path / "tools"
            tools_dir.mkdir()

            # Create non-YAML files
            (tools_dir / "readme.txt").write_text("Not a tool")
            (tools_dir / "notes.md").write_text("# Notes")

            # Should not raise
            registry = await storage.get_tool_registry()
            tools = registry.list_tools()
            assert len(tools) == 0

        @pytest.mark.asyncio
        async def test_file_storage_skips_non_python_files_in_skills(self, tmp_path: Path) -> None:
            """get_skill_library() ignores non-.py files in skills/ directory.

            Input: .txt, .md files in skills/ directory
            Expected behavior: Only .py files are processed
            Breaks when: Non-Python files cause errors or are incorrectly processed
            """
            storage = FileStorage(tmp_path)
            skills_dir = tmp_path / "skills"
            skills_dir.mkdir()

            # Create non-Python files
            (skills_dir / "readme.txt").write_text("Not a skill")
            (skills_dir / "__pycache__").mkdir()

            # Should not raise
            library = storage.get_skill_library()
            skills = library.list()
            assert len(skills) == 0

        @pytest.mark.asyncio
        async def test_redis_storage_handles_corrupted_tool_data(
            self, mock_redis: MockRedisClient
        ) -> None:
            """get_tool_registry() handles corrupted JSON in Redis gracefully.

            Input: Invalid JSON in Redis tool key
            Expected behavior: Method completes, skips corrupted entry
            Breaks when: Method raises exception for corrupted data
            """
            from py_code_mode.tools import ToolRegistry

            storage = RedisStorage(mock_redis, prefix="test")

            # Store corrupted data
            mock_redis._data["test:tools:broken"] = "{ invalid json ]"

            # Should not raise
            registry = await storage.get_tool_registry()
            assert isinstance(registry, ToolRegistry)

        @pytest.mark.asyncio
        async def test_redis_storage_handles_corrupted_skill_data(
            self, mock_redis: MockRedisClient
        ) -> None:
            """get_skill_library() handles corrupted data in Redis gracefully.

            Input: Invalid JSON in Redis skill key
            Expected behavior: Method completes, skips corrupted entry
            Breaks when: Method raises exception for corrupted data
            """
            from py_code_mode.skills import SkillLibrary

            storage = RedisStorage(mock_redis, prefix="test")

            # Store corrupted data directly
            mock_redis._data["test:skills:broken"] = "{ invalid json ]"

            # Should not raise
            library = storage.get_skill_library()
            assert isinstance(library, SkillLibrary)
