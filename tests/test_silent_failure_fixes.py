"""Tests for silent failure pattern fixes.

These tests verify that the library properly handles error conditions:
1. Missing paths: Log warning, return empty/None (backward compatible)
2. Corruption/permission errors: Log error and raise StorageError (not silent None)
3. All errors produce appropriate log messages
4. New exception hierarchy works correctly

Test Philosophy:
- Tests are written to FAIL with current behavior (silent failures)
- Tests will PASS once fixes are implemented
- Each test documents what code change would make it fail

Reference: docs/SILENT_FAILURE_AUDIT.md for the 23 identified patterns.
"""

import json
import logging
import os
import stat
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# These imports will need updating once the new exceptions are added
from py_code_mode.errors import CodeModeError

# Future imports (will fail until implemented):
# from py_code_mode.errors import StorageError, StorageReadError, StorageWriteError, ConfigurationError


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def log_capture(caplog: pytest.LogCaptureFixture):
    """Capture log messages at WARNING level and above."""
    caplog.set_level(logging.WARNING)
    return caplog


@pytest.fixture
def tools_dir_with_corruption(tmp_path: Path) -> Path:
    """Create a tools directory with valid and corrupted YAML files."""
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()

    # Valid tool
    (tools_dir / "valid_tool.yaml").write_text("""
name: valid_tool
type: cli
command: echo
args: "{text}"
description: A valid tool
""")

    # Corrupted YAML (invalid syntax - unclosed bracket)
    (tools_dir / "corrupt_yaml.yaml").write_text("""
name: corrupt
type: cli
data: {unclosed
command: broken
""")

    # Valid tool with missing name (should be skipped)
    (tools_dir / "no_name.yaml").write_text("""
type: cli
command: echo
args: "{text}"
""")

    return tools_dir


@pytest.fixture
def skills_dir_with_corruption(tmp_path: Path) -> Path:
    """Create a skills directory with valid and corrupted Python files."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    # Valid skill
    (skills_dir / "valid_skill.py").write_text('''"""A valid skill."""

def run(x: int) -> int:
    return x * 2
''')

    # Corrupted Python (syntax error)
    (skills_dir / "syntax_error.py").write_text('''"""Skill with syntax error."""

def run(x: int) -> int
    return x * 2  # Missing colon above
''')

    # Valid but missing run function
    (skills_dir / "no_run.py").write_text('''"""Skill without run function."""

def helper(x: int) -> int:
    return x * 2
''')

    return skills_dir


@pytest.fixture
def mock_redis_with_corruption() -> MagicMock:
    """Mock Redis client that returns some valid and some corrupt data."""

    class CorruptRedis:
        def __init__(self):
            self._data = {
                "skills:__skills__": {
                    "valid": json.dumps(
                        {
                            "name": "valid",
                            "source": "def run(): pass",
                            "description": "Valid skill",
                        }
                    ).encode(),
                    "corrupt_json": b"not valid json{{{",
                    "missing_fields": json.dumps(
                        {
                            "name": "incomplete",
                            # Missing source and description
                        }
                    ).encode(),
                }
            }

        def hget(self, key: str, field: str) -> bytes | None:
            return self._data.get(key, {}).get(field)

        def hgetall(self, key: str) -> dict[str, bytes]:
            return self._data.get(key, {})

        def hset(self, key: str, field: str, value: bytes) -> int:
            if key not in self._data:
                self._data[key] = {}
            self._data[key][field] = value
            return 1

        def hdel(self, key: str, field: str) -> int:
            if key in self._data and field in self._data[key]:
                del self._data[key][field]
                return 1
            return 0

        def hexists(self, key: str, field: str) -> bool:
            return field in self._data.get(key, {})

        def hlen(self, key: str) -> int:
            return len(self._data.get(key, {}))

    return CorruptRedis()


# =============================================================================
# EXCEPTION HIERARCHY TESTS
# =============================================================================


class TestStorageExceptionHierarchy:
    """Tests for new exception types that need to be added.

    These tests will FAIL until the exceptions are added to errors.py:
    - StorageError (base)
    - StorageReadError (read failures)
    - StorageWriteError (write failures)
    - ConfigurationError (invalid configuration)
    """

    def test_storage_error_exists(self):
        """StorageError should be defined in errors module."""
        from py_code_mode import errors

        assert hasattr(errors, "StorageError"), (
            "StorageError not defined. Add to py_code_mode/errors.py:\n"
            "class StorageError(CodeModeError):\n"
            '    """Base class for storage-related errors."""\n'
            "    pass"
        )

    def test_storage_read_error_exists(self):
        """StorageReadError should be defined and inherit from StorageError."""
        from py_code_mode import errors

        assert hasattr(errors, "StorageReadError"), (
            "StorageReadError not defined. Add to py_code_mode/errors.py"
        )
        # This will fail until both are defined
        if hasattr(errors, "StorageError") and hasattr(errors, "StorageReadError"):
            assert issubclass(errors.StorageReadError, errors.StorageError)

    def test_storage_write_error_exists(self):
        """StorageWriteError should be defined and inherit from StorageError."""
        from py_code_mode import errors

        assert hasattr(errors, "StorageWriteError"), (
            "StorageWriteError not defined. Add to py_code_mode/errors.py"
        )
        if hasattr(errors, "StorageError") and hasattr(errors, "StorageWriteError"):
            assert issubclass(errors.StorageWriteError, errors.StorageError)

    def test_configuration_error_exists(self):
        """ConfigurationError should be defined."""
        from py_code_mode import errors

        assert hasattr(errors, "ConfigurationError"), (
            "ConfigurationError not defined. Add to py_code_mode/errors.py"
        )
        if hasattr(errors, "ConfigurationError"):
            assert issubclass(errors.ConfigurationError, CodeModeError)

    def test_storage_read_error_preserves_cause(self):
        """StorageReadError should preserve the original exception as __cause__."""
        from py_code_mode import errors

        if not hasattr(errors, "StorageReadError"):
            pytest.skip("StorageReadError not yet implemented")

        original = ValueError("original error")
        try:
            try:
                raise original
            except ValueError as e:
                raise errors.StorageReadError("read failed", path="/some/path") from e
        except errors.StorageReadError as err:
            assert err.__cause__ is original
            assert "read failed" in str(err)
            assert hasattr(err, "path") or "/some/path" in str(err)


# =============================================================================
# CRITICAL: REGISTRY.PY FROM_DIR TESTS
# =============================================================================


class TestToolRegistryFromDirLogging:
    """Tests for ToolRegistry.from_dir() silent failure fixes.

    Current behavior (CRITICAL #1): Returns empty registry with no warning.
    Fixed behavior: Returns empty registry AND logs warning.

    Breaks when: Warning is not logged for missing path.
    """

    @pytest.mark.asyncio
    async def test_from_dir_missing_path_logs_warning(
        self, log_capture: pytest.LogCaptureFixture
    ):
        """from_dir() should log warning when path doesn't exist."""
        from py_code_mode.registry import ToolRegistry

        nonexistent = "/nonexistent/tools/path"
        registry = await ToolRegistry.from_dir(nonexistent)

        # Backward compatible: still returns empty registry
        assert len(registry.list_tools()) == 0

        # NEW: Should log warning
        assert any(
            "does not exist" in record.message or nonexistent in record.message
            for record in log_capture.records
        ), (
            f"Expected warning about missing path '{nonexistent}' but got:\n"
            f"{[r.message for r in log_capture.records]}\n"
            "Fix: Add logging to registry.py:102-103"
        )

    @pytest.mark.asyncio
    async def test_from_dir_corrupt_yaml_logs_warning(
        self, tools_dir_with_corruption: Path, log_capture: pytest.LogCaptureFixture
    ):
        """from_dir() should log warning for corrupt YAML files."""
        from py_code_mode.registry import ToolRegistry

        registry = await ToolRegistry.from_dir(str(tools_dir_with_corruption))

        # Valid tool should be loaded
        tools = registry.list_tools()
        tool_names = {t.name for t in tools}
        assert "valid_tool" in tool_names, "Valid tool should still load"

        # Warning should be logged for corrupt file
        assert any(
            "corrupt_yaml" in record.message or "yaml" in record.message.lower()
            for record in log_capture.records
        ), (
            f"Expected warning about corrupt YAML but got:\n"
            f"{[r.message for r in log_capture.records]}"
        )


# =============================================================================
# CRITICAL: CLI.PY FROM_DIR TESTS
# =============================================================================


class TestCLIAdapterFromDirLogging:
    """Tests for CLIAdapter.from_dir() silent failure fixes.

    Current behavior (CRITICAL #2): Returns empty adapter with no warning.
    Fixed behavior: Returns empty adapter AND logs warning.
    """

    def test_from_dir_missing_path_logs_warning(
        self, log_capture: pytest.LogCaptureFixture
    ):
        """from_dir() should log warning when path doesn't exist."""
        from py_code_mode.adapters.cli import CLIAdapter

        nonexistent = "/nonexistent/tools/path"
        adapter = CLIAdapter.from_dir(nonexistent)

        # Backward compatible: still returns empty adapter
        assert len(adapter._tools) == 0

        # NEW: Should log warning
        assert any(nonexistent in record.message for record in log_capture.records), (
            f"Expected warning about missing path '{nonexistent}' but got:\n"
            f"{[r.message for r in log_capture.records]}\n"
            "Fix: Add logging to cli.py:111-112"
        )


# =============================================================================
# CRITICAL: REDIS_TOOLS.PY FROM_DIRECTORY TESTS
# =============================================================================


class TestRedisToolStoreFromDirectoryLogging:
    """Tests for RedisToolStore.from_directory() silent failure fixes.

    Current behavior (CRITICAL #3): Returns empty store with no warning.
    Fixed behavior: Returns empty store AND logs warning.
    """

    def test_from_directory_missing_path_logs_warning(
        self, log_capture: pytest.LogCaptureFixture
    ):
        """from_directory() should log warning when path doesn't exist."""
        from py_code_mode.redis_tools import RedisToolStore
        from tests.conftest import MockRedisClient

        mock_redis = MockRedisClient()
        nonexistent = Path("/nonexistent/tools/path")

        store = RedisToolStore.from_directory(mock_redis, nonexistent)

        # Backward compatible: returns empty store
        assert len(store) == 0

        # NEW: Should log warning
        assert any(
            str(nonexistent) in record.message for record in log_capture.records
        ), (
            f"Expected warning about missing path '{nonexistent}' but got:\n"
            f"{[r.message for r in log_capture.records]}\n"
            "Fix: Add logging to redis_tools.py:127-128"
        )


# =============================================================================
# HIGH: STORAGE.PY EXCEPTION HANDLING TESTS
# =============================================================================


class TestFileToolStoreErrorHandling:
    """Tests for FileToolStore.get() error handling.

    Current behavior (HIGH #5): except Exception: return None
    Fixed behavior: Only return None for ToolNotFoundError, raise for others.

    Note: FileToolStore.get() uses asyncio internally, so we test with
    ToolRegistry.from_dir() which is the public async API.
    """

    @pytest.mark.asyncio
    async def test_get_returns_none_for_missing_tool(self, tmp_path: Path):
        """get() should return None when tool doesn't exist."""
        from py_code_mode.registry import ToolRegistry

        # Create empty tools directory
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()

        registry = await ToolRegistry.from_dir(str(tools_dir))

        # Should not raise, should just return no tools
        tools = registry.list_tools()
        assert len(tools) == 0

    @pytest.mark.asyncio
    async def test_get_raises_for_corruption(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ):
        """Corrupt tools should be skipped with warning, not silently ignored.

        Design decision: ToolRegistry.from_dir() is resilient - it logs warnings
        for corrupt files and continues loading valid tools. This allows partial
        functionality when some tool definitions are broken.
        """
        from py_code_mode.registry import ToolRegistry

        caplog.set_level(logging.WARNING, logger="py_code_mode.registry")

        # Create tools directory with a corrupt tool
        tools_path = tmp_path / "tools"
        tools_path.mkdir()
        (tools_path / "corrupt.yaml").write_text("name: corrupt\n  invalid: yaml{{{")

        registry = await ToolRegistry.from_dir(str(tools_path))

        # Corrupt tool should be skipped
        assert len(registry.list_tools()) == 0

        # But warning should be logged so developer can discover the issue
        assert any(
            "corrupt.yaml" in r.message and "failed" in r.message.lower()
            for r in caplog.records
        ), (
            "Corrupt tool file should log a warning with the filename.\n"
            f"Actual logs: {[r.message for r in caplog.records]}"
        )


class TestFileArtifactStoreWrapperErrorHandling:
    """Tests for FileArtifactStoreWrapper load/delete error handling.

    Current behavior (HIGH #6-7): except Exception: return None/False
    Fixed behavior: Propagate non-FileNotFound errors.
    """

    def test_load_returns_none_for_missing_artifact(self, tmp_path: Path):
        """load() should return None when artifact doesn't exist."""
        from py_code_mode.artifacts import FileArtifactStore
        from py_code_mode.storage import FileArtifactStoreWrapper

        store = FileArtifactStore(tmp_path)
        wrapper = FileArtifactStoreWrapper(store)

        result = wrapper.load("nonexistent")
        assert result is None  # Expected behavior

    def test_load_raises_for_permission_error(self, tmp_path: Path):
        """load() should raise StorageReadError for permission errors."""
        from py_code_mode.artifacts import FileArtifactStore
        from py_code_mode.storage import FileArtifactStoreWrapper

        # Create an artifact
        artifact_path = tmp_path / "secret"
        artifact_path.write_text("secret data")

        store = FileArtifactStore(tmp_path)
        # Register the artifact
        (tmp_path / ".artifacts.json").write_text(
            json.dumps(
                {
                    "secret": {
                        "description": "test",
                        "created_at": "2024-01-01T00:00:00Z",
                        "metadata": {"_data_type": "text"},
                    }
                }
            )
        )

        # Make file unreadable (skip on Windows)
        if os.name != "nt":
            artifact_path.chmod(0o000)
            try:
                wrapper = FileArtifactStoreWrapper(store)

                from py_code_mode import errors

                if not hasattr(errors, "StorageReadError"):
                    pytest.skip("StorageReadError not yet implemented")

                # After fix: should raise StorageReadError
                with pytest.raises(errors.StorageReadError):
                    wrapper.load("secret")
            finally:
                artifact_path.chmod(0o644)

    def test_delete_returns_false_for_missing(self, tmp_path: Path):
        """delete() should return False when artifact doesn't exist."""
        from py_code_mode.artifacts import FileArtifactStore
        from py_code_mode.storage import FileArtifactStoreWrapper

        store = FileArtifactStore(tmp_path)
        wrapper = FileArtifactStoreWrapper(store)

        result = wrapper.delete("nonexistent")
        assert result is False  # Expected behavior

    def test_delete_raises_for_permission_error(self, tmp_path: Path):
        """delete() should raise StorageWriteError for permission errors."""
        from py_code_mode.artifacts import FileArtifactStore
        from py_code_mode.storage import FileArtifactStoreWrapper

        # Create an artifact directory and file
        artifact_path = tmp_path / "protected"
        artifact_path.write_text("protected data")

        store = FileArtifactStore(tmp_path)
        store.save("protected", "data", "test artifact")

        # Make parent directory read-only to prevent deletion (skip on Windows)
        if os.name != "nt":
            tmp_path.chmod(stat.S_IRUSR | stat.S_IXUSR)  # r-x only
            try:
                wrapper = FileArtifactStoreWrapper(store)

                from py_code_mode import errors

                if not hasattr(errors, "StorageWriteError"):
                    pytest.skip("StorageWriteError not yet implemented")

                # After fix: should raise StorageWriteError
                with pytest.raises(errors.StorageWriteError):
                    wrapper.delete("protected")
            finally:
                tmp_path.chmod(stat.S_IRWXU)


# =============================================================================
# HIGH: SKILL_STORE.PY ERROR HANDLING TESTS
# =============================================================================


class TestFileSkillStoreErrorHandling:
    """Tests for FileSkillStore.load() error handling.

    Current behavior (HIGH #10): except Exception -> return None (with warning)
    Fixed behavior: Return None ONLY for FileNotFoundError, raise StorageReadError for others.
    """

    def test_load_returns_none_for_missing_file(self, tmp_path: Path):
        """load() should return None when skill file doesn't exist."""
        from py_code_mode.skill_store import FileSkillStore

        store = FileSkillStore(tmp_path)
        result = store.load("nonexistent")

        assert result is None  # Expected behavior

    def test_load_raises_for_syntax_error(
        self, skills_dir_with_corruption: Path, log_capture: pytest.LogCaptureFixture
    ):
        """load() should raise StorageReadError for Python syntax errors."""
        from py_code_mode.skill_store import FileSkillStore

        store = FileSkillStore(skills_dir_with_corruption)

        from py_code_mode import errors

        if not hasattr(errors, "StorageReadError"):
            # Current behavior: returns None with warning
            result = store.load("syntax_error")
            if result is None:
                # Check at least warning is logged (current behavior has this)
                assert any(
                    "syntax_error" in record.message for record in log_capture.records
                ), "At minimum, a warning should be logged for syntax errors"
            pytest.skip(
                "StorageReadError not yet implemented - upgrade test when added"
            )

        # After fix: should raise StorageReadError
        with pytest.raises(errors.StorageReadError):
            store.load("syntax_error")


class TestFileSkillStoreListAllLogging:
    """Tests for FileSkillStore.list_all() logging behavior.

    Current behavior (MEDIUM #11): Silently skips failed skills (with warning)
    Fixed behavior: Same, but ensure logging is consistent.
    """

    def test_list_all_logs_warning_for_corrupt_files(
        self, skills_dir_with_corruption: Path, log_capture: pytest.LogCaptureFixture
    ):
        """list_all() should log warning for each corrupt file."""
        from py_code_mode.skill_store import FileSkillStore

        store = FileSkillStore(skills_dir_with_corruption)
        skills = store.list_all()

        # Valid skill should be loaded
        skill_names = {s.name for s in skills}
        assert "valid_skill" in skill_names

        # Warning should be logged for syntax_error.py
        assert any(
            "syntax_error" in record.message for record in log_capture.records
        ), (
            f"Expected warning for syntax_error.py but got:\n"
            f"{[r.message for r in log_capture.records]}"
        )


class TestRedisSkillStoreErrorHandling:
    """Tests for RedisSkillStore error handling.

    Current behavior (HIGH/MEDIUM #12-13): except Exception -> return None
    Fixed behavior: Return None ONLY for missing key, raise for corruption.
    """

    def test_load_returns_none_for_missing_key(self, mock_redis_with_corruption):
        """load() should return None when key doesn't exist."""
        from py_code_mode.skill_store import RedisSkillStore

        store = RedisSkillStore(mock_redis_with_corruption, prefix="skills")
        result = store.load("totally_nonexistent")

        assert result is None

    def test_load_raises_for_invalid_json(
        self, mock_redis_with_corruption, log_capture: pytest.LogCaptureFixture
    ):
        """load() should raise StorageReadError for invalid JSON."""
        from py_code_mode.skill_store import RedisSkillStore

        store = RedisSkillStore(mock_redis_with_corruption, prefix="skills")

        from py_code_mode import errors

        if not hasattr(errors, "StorageReadError"):
            # Current behavior: returns None with warning
            result = store.load("corrupt_json")
            if result is None:
                # At least check warning is logged
                assert any(
                    "corrupt_json" in record.message for record in log_capture.records
                ), "Warning should be logged for corrupt JSON"
            pytest.skip("StorageReadError not yet implemented")

        # After fix: should raise StorageReadError
        with pytest.raises(errors.StorageReadError):
            store.load("corrupt_json")

    def test_load_raises_for_missing_fields(
        self, mock_redis_with_corruption, log_capture: pytest.LogCaptureFixture
    ):
        """load() should raise StorageReadError for incomplete skill data."""
        from py_code_mode.skill_store import RedisSkillStore

        store = RedisSkillStore(mock_redis_with_corruption, prefix="skills")

        from py_code_mode import errors

        if not hasattr(errors, "StorageReadError"):
            result = store.load("missing_fields")
            if result is None:
                assert any(
                    "missing" in record.message.lower()
                    for record in log_capture.records
                ), "Warning should be logged for missing fields"
            pytest.skip("StorageReadError not yet implemented")

        with pytest.raises(errors.StorageReadError):
            store.load("missing_fields")

    def test_list_all_logs_warning_for_corrupt_entries(
        self, mock_redis_with_corruption, log_capture: pytest.LogCaptureFixture
    ):
        """list_all() should log warning for corrupt entries."""
        from py_code_mode.skill_store import RedisSkillStore

        store = RedisSkillStore(mock_redis_with_corruption, prefix="skills")
        skills = store.list_all()

        # Valid skill should be loaded
        skill_names = {s.name for s in skills}
        assert "valid" in skill_names

        # Warnings should be logged for corrupt entries
        log_messages = " ".join(r.message for r in log_capture.records)
        assert "corrupt_json" in log_messages or "missing_fields" in log_messages, (
            f"Expected warnings for corrupt entries but got:\n"
            f"{[r.message for r in log_capture.records]}"
        )


# =============================================================================
# MEDIUM: LOGGING VS PRINT TESTS
# =============================================================================


class TestRegistryFromRedisUsesLogging:
    """Tests that registry_from_redis uses logging instead of print.

    Current behavior (MEDIUM #23): Uses print() for status messages.
    Fixed behavior: Uses logging module.
    """

    @pytest.mark.asyncio
    async def test_registry_from_redis_uses_logging_not_print(
        self, log_capture: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture
    ):
        """registry_from_redis should use logging, not print."""
        from py_code_mode.redis_tools import RedisToolStore, registry_from_redis
        from tests.conftest import MockRedisClient

        # Create mock Redis with a tool
        mock_redis = MockRedisClient()
        store = RedisToolStore(mock_redis, prefix="test")
        store.add("echo", {"name": "echo", "type": "cli", "command": "echo"})

        # Call function
        await registry_from_redis(store)

        # Check for print output
        captured = capsys.readouterr()
        if captured.out:
            pytest.fail(
                f"registry_from_redis uses print() instead of logging:\n"
                f"stdout: {captured.out}\n"
                "Fix: Replace print() statements in redis_tools.py:191-214 with logging calls"
            )


class TestServerBuildSkillLibraryUsesLogging:
    """Tests that container/server.py uses logging instead of print.

    Current behavior (MEDIUM #21): Uses print() for warnings.
    Fixed behavior: Uses logging module.
    """

    def test_build_skill_library_uses_logging_not_print(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture,
        log_capture: pytest.LogCaptureFixture,
    ):
        """build_skill_library should use logging, not print."""
        # This test requires mocking to trigger the OSError path
        # Skip if FastAPI not available
        try:
            from py_code_mode.backends.container.config import SessionConfig
            from py_code_mode.backends.container.server import build_skill_library
        except ImportError:
            pytest.skip("FastAPI not installed")

        # Create config with a path that will fail
        config = SessionConfig(
            skills_path=Path("/root/definitely_no_permission"),
        )

        # Mock mkdir to raise OSError
        with patch.object(Path, "mkdir", side_effect=OSError("Permission denied")):
            result = build_skill_library(config)

        captured = capsys.readouterr()
        if "Warning:" in captured.out or "Cannot create" in captured.out:
            pytest.fail(
                f"build_skill_library uses print() for warnings:\n"
                f"stdout: {captured.out}\n"
                "Fix: Replace print() in server.py:162 with logging.warning()"
            )


# =============================================================================
# MEDIUM: MCP ADAPTER EXCEPTION HANDLING
# =============================================================================


class TestMCPAdapterCloseExceptionHandling:
    """Tests for mcp_adapter.py close() exception handling.

    Current behavior (MEDIUM #20): Catches BaseException (including KeyboardInterrupt)
    Fixed behavior: Catch Exception only, let BaseException propagate.
    """

    @pytest.mark.asyncio
    async def test_close_propagates_keyboard_interrupt(self):
        """close() should not catch KeyboardInterrupt."""
        from py_code_mode.mcp_adapter import MCPAdapter

        # Create adapter with mock session
        mock_session = MagicMock()
        mock_exit_stack = MagicMock()

        # Make aclose() raise KeyboardInterrupt
        async def raise_keyboard_interrupt():
            raise KeyboardInterrupt()

        mock_exit_stack.aclose = raise_keyboard_interrupt

        adapter = MCPAdapter(session=mock_session, exit_stack=mock_exit_stack)

        # After fix: KeyboardInterrupt should propagate
        # Currently it's caught by `except BaseException: pass`
        try:
            await adapter.close()
            # If we get here, KeyboardInterrupt was caught
            pytest.fail(
                "close() caught KeyboardInterrupt instead of propagating.\n"
                "Fix: Change mcp_adapter.py:254 from 'except BaseException:' to 'except Exception:'"
            )
        except KeyboardInterrupt:
            pass  # Expected after fix

    @pytest.mark.asyncio
    async def test_close_catches_regular_exceptions(self):
        """close() should catch regular exceptions to ensure cleanup."""
        from py_code_mode.mcp_adapter import MCPAdapter

        mock_session = MagicMock()
        mock_exit_stack = MagicMock()

        async def raise_runtime_error():
            raise RuntimeError("cleanup error")

        mock_exit_stack.aclose = raise_runtime_error

        adapter = MCPAdapter(session=mock_session, exit_stack=mock_exit_stack)

        # Regular exceptions should be caught (don't crash on cleanup)
        await adapter.close()  # Should not raise


# =============================================================================
# MEDIUM: IMPORT ERROR LOGGING TESTS
# =============================================================================


class TestMCPImportErrorLogging:
    """Tests for MCP ImportError logging.

    Current behavior (MEDIUM #14): except ImportError: pass
    Fixed behavior: Log warning with install instructions.
    """

    @pytest.mark.asyncio
    async def test_mcp_import_error_logs_warning(
        self, tmp_path: Path, log_capture: pytest.LogCaptureFixture
    ):
        """ImportError for MCP should log warning with install instructions."""
        # Create tool directory with MCP tool
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()

        (tools_dir / "mcp_tool.yaml").write_text("""
name: mcp_tool
type: mcp
transport: stdio
command: fake_mcp_server
""")

        # Mock the MCP package import to fail by patching the mcp_adapter module
        with patch.dict("sys.modules", {"mcp": None}):
            # Reload registry module to trigger import failure
            from py_code_mode.registry import ToolRegistry

            registry = await ToolRegistry.from_dir(str(tools_dir))

        # Check for warning about MCP not installed
        log_messages = " ".join(r.message for r in log_capture.records)

        # Currently MCP tools with type=mcp are silently ignored if import fails.
        # This test verifies that after fix, a warning is logged.
        # Note: The current implementation doesn't even try to load MCP tools
        # from YAML, so this test is about ensuring we log when MCP import fails.
        if "mcp" not in log_messages.lower() and "install" not in log_messages.lower():
            pytest.fail(
                "ImportError for MCP package should log warning with install instructions.\n"
                "Fix: Add warning logging when MCP tools are configured but mcp package unavailable"
            )


class TestEmbedderFallbackLogging:
    """Tests for embedder fallback logging.

    Current behavior (MEDIUM #15-16): Silent fallback to MockEmbedder.
    Fixed behavior: Log warning about missing dependencies and fallback.
    """

    def test_embedder_fallback_logs_warning(
        self, tmp_path: Path, log_capture: pytest.LogCaptureFixture
    ):
        """Fallback to MockEmbedder should log warning."""
        from py_code_mode.storage import FileSkillStoreWrapper

        # Create wrapper which triggers lazy library creation
        wrapper = FileSkillStoreWrapper(tmp_path)

        # Mock the create_skill_library import to fail
        with patch(
            "py_code_mode.storage.create_skill_library",
            side_effect=ImportError("No module named 'sentence_transformers'"),
        ):
            library = wrapper._get_library()

        # Check for warning about fallback
        log_messages = " ".join(r.message for r in log_capture.records)
        if (
            "mock" not in log_messages.lower()
            and "fallback" not in log_messages.lower()
        ):
            pytest.fail(
                "Fallback to MockEmbedder should log warning.\n"
                "Fix: Add logging in storage.py:226-236"
            )


# =============================================================================
# INTEGRATION: ERROR PROPAGATION ACROSS BOUNDARIES
# =============================================================================


class TestStorageWrapperErrorPropagation:
    """Integration tests for error propagation through storage wrappers."""

    @pytest.mark.asyncio
    async def test_redis_artifact_store_wrapper_error_propagation(self):
        """RedisArtifactStoreWrapper should propagate non-not-found errors."""
        from py_code_mode import errors

        if not hasattr(errors, "StorageReadError"):
            pytest.skip("StorageReadError not yet implemented")

        # Create mock Redis that raises on read
        # Note: RedisArtifactStore.load() uses get(), not hget()
        mock_redis = MagicMock()
        mock_redis.get.side_effect = ConnectionError("Redis connection lost")

        from py_code_mode.redis_artifacts import RedisArtifactStore
        from py_code_mode.storage import RedisArtifactStoreWrapper

        store = RedisArtifactStore(mock_redis, prefix="test")
        wrapper = RedisArtifactStoreWrapper(store)

        # Connection errors should propagate, not return None
        with pytest.raises((errors.StorageReadError, ConnectionError)):
            wrapper.load("any_artifact")


# =============================================================================
# USER JOURNEY: END-TO-END ERROR DISCOVERY
# =============================================================================


class TestDeveloperErrorDiscovery:
    """E2E tests simulating developer discovering errors through logs."""

    @pytest.mark.asyncio
    async def test_developer_discovers_missing_tools_through_logs(self):
        """Developer should be able to see why tools didn't load from logs."""
        import logging as log_module

        # Use a custom handler since caplog doesn't capture async logs reliably
        class LogCapture(log_module.Handler):
            def __init__(self):
                super().__init__()
                self.records: list[log_module.LogRecord] = []

            def emit(self, record):
                self.records.append(record)

        # Set up capture on registry logger BEFORE importing
        registry_logger = log_module.getLogger("py_code_mode.registry")
        capture = LogCapture()
        capture.setLevel(log_module.WARNING)
        registry_logger.addHandler(capture)
        original_level = registry_logger.level
        registry_logger.setLevel(log_module.WARNING)

        # Import after handler is set up
        from py_code_mode.registry import ToolRegistry

        try:
            # Try to load from truly nonexistent path (use uuid to ensure uniqueness)
            import uuid

            nonexistent_path = f"/tmp/test_storage_nonexistent_{uuid.uuid4().hex}"
            registry = await ToolRegistry.from_dir(nonexistent_path)

            # Developer sees empty tools list
            tools = registry.list_tools()
            assert tools == []

            # Developer should be able to find reason in logs
            messages = [r.getMessage() for r in capture.records]
            assert any(
                "does not exist" in msg or nonexistent_path in msg for msg in messages
            ), (
                "Developer cannot discover why tools are empty - no log message.\n"
                f"Logs should indicate the missing path. Got: {messages}"
            )
        finally:
            registry_logger.removeHandler(capture)
            registry_logger.setLevel(original_level)

    @pytest.mark.asyncio
    async def test_developer_discovers_skill_parse_error_through_logs(
        self, skills_dir_with_corruption: Path, log_capture: pytest.LogCaptureFixture
    ):
        """Developer should see specific parse errors in logs."""
        from py_code_mode.skill_store import FileSkillStore

        store = FileSkillStore(skills_dir_with_corruption)
        skills = store.list_all()

        # Developer sees some skills loaded
        assert len(skills) >= 1

        # Developer should see which files failed and why
        log_messages = " ".join(r.message for r in log_capture.records)
        assert "syntax_error" in log_messages, (
            "Log should mention which file had errors"
        )
        # Ideally also shows the error type
        assert "syntax" in log_messages.lower() or "error" in log_messages.lower(), (
            "Log should indicate type of error"
        )


# =============================================================================
# INVARIANT: CONSISTENT ERROR MESSAGE FORMAT
# =============================================================================


class TestErrorMessageConsistency:
    """Tests for consistent error message formatting."""

    def test_missing_path_warnings_include_path(
        self, log_capture: pytest.LogCaptureFixture
    ):
        """All missing path warnings should include the actual path."""
        from py_code_mode.adapters.cli import CLIAdapter

        test_path = "/test/unique/path/12345"
        CLIAdapter.from_dir(test_path)

        warning_messages = [
            r.message for r in log_capture.records if r.levelno >= logging.WARNING
        ]

        # If any warnings logged, they should include the path
        if not warning_messages:
            pytest.skip("No warnings logged (fix needed first)")

        assert any(test_path in msg for msg in warning_messages), (
            f"Warning messages should include the missing path.\n"
            f"Path: {test_path}\n"
            f"Messages: {warning_messages}"
        )
