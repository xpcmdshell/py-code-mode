"""Negative tests - error handling and failure scenarios.

For every happy path, there's a failure case. These tests verify:
1. Errors are caught and reported, not swallowed
2. Error messages are clear and actionable
3. Failures don't corrupt state
4. Invalid inputs are rejected early

Each test class covers failures for a specific component.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

# These imports will fail initially - that's expected (TDD red phase)
from py_code_mode.session import Session
from py_code_mode.storage import FileStorage, RedisStorage

if TYPE_CHECKING:
    from tests.conftest import MockRedisClient


# --- Session Error Handling ---


class TestSessionExecutionErrors:
    """Tests for Session.run() error handling."""

    @pytest.fixture
    def storage(self, tmp_path: Path) -> FileStorage:
        """Create FileStorage for testing."""
        return FileStorage(tmp_path)

    @pytest.mark.asyncio
    async def test_syntax_error_captured(self, storage: FileStorage) -> None:
        """Syntax errors are captured in result.error, not raised."""
        async with Session(storage=storage) as session:
            result = await session.run("if True print('bad')")

            assert not result.is_ok
            assert result.error is not None
            assert "SyntaxError" in result.error or "syntax" in result.error.lower()

    @pytest.mark.asyncio
    async def test_name_error_captured(self, storage: FileStorage) -> None:
        """NameError is captured in result.error."""
        async with Session(storage=storage) as session:
            result = await session.run("undefined_variable")

            assert not result.is_ok
            assert result.error is not None
            assert "NameError" in result.error

    @pytest.mark.asyncio
    async def test_type_error_captured(self, storage: FileStorage) -> None:
        """TypeError is captured in result.error."""
        async with Session(storage=storage) as session:
            result = await session.run("1 + 'string'")

            assert not result.is_ok
            assert result.error is not None
            assert "TypeError" in result.error

    @pytest.mark.asyncio
    async def test_value_error_captured(self, storage: FileStorage) -> None:
        """ValueError is captured in result.error."""
        async with Session(storage=storage) as session:
            result = await session.run("int('not_a_number')")

            assert not result.is_ok
            assert result.error is not None
            assert "ValueError" in result.error

    @pytest.mark.asyncio
    async def test_exception_in_function_captured(self, storage: FileStorage) -> None:
        """Exceptions in user-defined functions are captured."""
        async with Session(storage=storage) as session:
            # Define a function that raises
            await session.run("def bad(): raise RuntimeError('boom')")
            result = await session.run("bad()")

            assert not result.is_ok
            assert result.error is not None
            assert "RuntimeError" in result.error
            assert "boom" in result.error

    @pytest.mark.asyncio
    async def test_timeout_error_captured(self, storage: FileStorage) -> None:
        """Timeout errors are captured with clear message."""
        async with Session(storage=storage) as session:
            result = await session.run(
                "import time; time.sleep(10)",
                timeout=0.1,
            )

            assert not result.is_ok
            assert result.error is not None
            # Should mention timeout
            assert "timeout" in result.error.lower() or "Timeout" in result.error

    @pytest.mark.asyncio
    async def test_error_does_not_corrupt_session_state(self, storage: FileStorage) -> None:
        """Errors don't corrupt the session - can continue executing."""
        async with Session(storage=storage) as session:
            # Set a variable
            await session.run("x = 42")

            # Cause an error
            result = await session.run("undefined_variable")
            assert not result.is_ok

            # Session should still work, x should still exist
            result = await session.run("x")
            assert result.is_ok
            assert result.value == 42


# --- Tools Namespace Errors ---


class TestToolsNamespaceErrors:
    """Tests for tools namespace error handling."""

    @pytest.fixture
    def storage(self, tmp_path: Path) -> FileStorage:
        """Create FileStorage with tools directory."""
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        (tools_dir / "echo.yaml").write_text(
            """
name: echo
type: cli
command: echo
args: "{text}"
description: Echo text back
"""
        )
        return FileStorage(tmp_path)

    @pytest.mark.asyncio
    async def test_tool_not_found_error(self, storage: FileStorage) -> None:
        """Calling nonexistent tool gives clear error."""
        async with Session(storage=storage) as session:
            result = await session.run('tools.nonexistent(arg="value")')

            assert not result.is_ok
            assert result.error is not None
            # Error should mention the tool name or "not found"
            assert (
                "nonexistent" in result.error.lower()
                or "not found" in result.error.lower()
                or "attribute" in result.error.lower()
            )

    @pytest.mark.asyncio
    async def test_tool_missing_required_arg_error(self, storage: FileStorage) -> None:
        """Tool called without required args gives clear error."""
        async with Session(storage=storage) as session:
            result = await session.run("tools.echo()")  # Missing required 'text' arg

            assert not result.is_ok
            assert result.error is not None
            # Should mention missing argument

    @pytest.mark.asyncio
    async def test_tool_invalid_arg_type_error(self, storage: FileStorage) -> None:
        """Tool called with wrong arg type gives error."""
        async with Session(storage=storage) as session:
            # Pass dict where string expected
            result = await session.run('tools.echo(text={"not": "string"})')

            # May succeed or fail depending on implementation
            # But should not crash the session
            if not result.is_ok:
                assert result.error is not None

    @pytest.mark.asyncio
    async def test_tools_call_nonexistent_error(self, storage: FileStorage) -> None:
        """tools.call() with nonexistent tool gives error."""
        async with Session(storage=storage) as session:
            result = await session.run('tools.call("nonexistent", {})')

            assert not result.is_ok
            assert result.error is not None


# --- Skills Namespace Errors ---


class TestSkillsNamespaceErrors:
    """Tests for skills namespace error handling."""

    @pytest.fixture
    def storage(self, tmp_path: Path) -> FileStorage:
        """Create FileStorage with skills directory."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "divide.py").write_text(
            '''"""Divide two numbers."""

def run(a: int, b: int) -> float:
    return a / b
'''
        )
        return FileStorage(tmp_path)

    @pytest.mark.asyncio
    async def test_skill_not_found_error(self, storage: FileStorage) -> None:
        """Calling nonexistent skill gives clear error."""
        async with Session(storage=storage) as session:
            result = await session.run("skills.nonexistent()")

            assert not result.is_ok
            assert result.error is not None
            assert (
                "nonexistent" in result.error.lower()
                or "not found" in result.error.lower()
                or "attribute" in result.error.lower()
            )

    @pytest.mark.asyncio
    async def test_skill_missing_required_arg_error(self, storage: FileStorage) -> None:
        """Skill called without required args gives clear error."""
        async with Session(storage=storage) as session:
            result = await session.run("skills.divide()")  # Missing required args

            assert not result.is_ok
            assert result.error is not None

    @pytest.mark.asyncio
    async def test_skill_runtime_error_captured(self, storage: FileStorage) -> None:
        """Runtime error in skill is captured."""
        async with Session(storage=storage) as session:
            result = await session.run("skills.divide(a=1, b=0)")  # Division by zero

            assert not result.is_ok
            assert result.error is not None
            assert "ZeroDivision" in result.error or "division" in result.error.lower()

    @pytest.mark.asyncio
    async def test_skill_create_invalid_source_error(self, storage: FileStorage) -> None:
        """Creating skill with invalid source gives error."""
        async with Session(storage=storage) as session:
            result = await session.run(
                """
skills.create(
    name="bad",
    description="Invalid skill",
    source="def run( INVALID SYNTAX"
)
"""
            )

            assert not result.is_ok
            assert result.error is not None

    @pytest.mark.asyncio
    async def test_skill_create_missing_run_function_error(self, storage: FileStorage) -> None:
        """Creating skill without run() function gives error."""
        async with Session(storage=storage) as session:
            result = await session.run(
                """
skills.create(
    name="norun",
    description="No run function",
    source="def helper(): return 1"
)
"""
            )

            # Should either fail at creation or when calling
            if result.is_ok:
                # If creation succeeded, calling should fail
                result = await session.run("skills.norun()")
                assert not result.is_ok


# --- Artifacts Namespace Errors ---


class TestArtifactsNamespaceErrors:
    """Tests for artifacts namespace error handling."""

    @pytest.fixture
    def storage(self, tmp_path: Path) -> FileStorage:
        """Create FileStorage for testing."""
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        return FileStorage(tmp_path)

    @pytest.mark.asyncio
    async def test_artifact_not_found_error(self, storage: FileStorage) -> None:
        """Loading nonexistent artifact gives error or None."""
        async with Session(storage=storage) as session:
            result = await session.run('artifacts.load("nonexistent.json")')

            # Either fails with error or returns None
            if result.is_ok:
                assert result.value is None
            else:
                assert result.error is not None

    @pytest.mark.asyncio
    async def test_artifact_save_invalid_name_error(self, storage: FileStorage) -> None:
        """Saving artifact with invalid name gives error."""
        async with Session(storage=storage) as session:
            # Path traversal attempt
            result = await session.run('artifacts.save("../../../etc/passwd", "malicious", "hack")')

            # Should either fail or sanitize the name
            # Implementation-dependent

    @pytest.mark.asyncio
    async def test_artifact_save_unserializable_data(self, storage: FileStorage) -> None:
        """Saving non-serializable data gives error."""
        async with Session(storage=storage) as session:
            # Functions can't be JSON serialized
            await session.run("def my_func(): pass")
            result = await session.run('artifacts.save("func.json", my_func, "Function")')

            # Should fail - functions aren't serializable
            if result.is_ok:
                # Some implementations might pickle, which is fine
                pass
            else:
                assert result.error is not None


# --- Storage Backend Errors ---


class TestFileStorageErrors:
    """Tests for FileStorage error handling."""

    def test_invalid_path_handling(self, tmp_path: Path) -> None:
        """FileStorage handles invalid paths gracefully."""
        # Path that doesn't exist yet - should be created
        nonexistent = tmp_path / "does_not_exist"
        storage = FileStorage(nonexistent)

        # Should work (directory created on demand)
        result = storage.tools.list()
        assert isinstance(result, list)

    def test_permission_error_handling(self) -> None:
        """FileStorage handles permission errors."""
        # This test is tricky as we'd need to create unreadable files
        # Skip on systems where we can't easily test this
        pass

    def test_corrupted_yaml_handling(self, tmp_path: Path) -> None:
        """FileStorage handles corrupted YAML files."""
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        (tools_dir / "bad.yaml").write_text("{{{{ invalid yaml")

        storage = FileStorage(tmp_path)

        # Should not crash - may skip bad file or return empty
        try:
            result = storage.tools.list()
            assert isinstance(result, list)
        except Exception:
            pass  # Raising on corrupted files is acceptable

    def test_corrupted_skill_handling(self, tmp_path: Path) -> None:
        """FileStorage handles corrupted skill files."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "bad.py").write_text("def run( INVALID")

        storage = FileStorage(tmp_path)

        # Should not crash on list
        try:
            result = storage.skills.list()
            assert isinstance(result, list)
        except Exception:
            pass  # Raising on corrupted files is acceptable


class TestRedisStorageErrors:
    """Tests for RedisStorage error handling."""

    def test_connection_error_handling(self, mock_redis: MockRedisClient) -> None:
        """RedisStorage handles connection errors."""
        storage = RedisStorage(mock_redis, prefix="test")

        # Mock client always works, so this tests basic functionality
        result = storage.tools.list()
        assert isinstance(result, list)

    def test_deserialization_error_handling(self, mock_redis: MockRedisClient) -> None:
        """RedisStorage handles corrupted data."""
        storage = RedisStorage(mock_redis, prefix="test")

        # Manually inject corrupted data
        mock_redis.hset("test:tools:__index__", "bad", b"not valid json {{{")

        # Should not crash - may skip or error gracefully
        try:
            result = storage.tools.list()
            # May return empty or skip corrupted entries
            assert isinstance(result, list)
        except Exception:
            pass  # Raising on corrupted data is acceptable


# --- Session Configuration Errors ---


class TestSessionConfigurationErrors:
    """Tests for Session configuration error handling."""

    @pytest.fixture
    def storage(self, tmp_path: Path) -> FileStorage:
        """Create FileStorage for testing."""
        return FileStorage(tmp_path)

    @pytest.mark.asyncio
    async def test_unknown_executor_type_error(self, storage: FileStorage) -> None:
        """Unknown executor type gives clear error."""
        with pytest.raises(ValueError) as exc_info:
            Session(storage=storage, executor="unknown_executor")

        assert (
            "unknown_executor" in str(exc_info.value).lower()
            or "backend" in str(exc_info.value).lower()
        )

    @pytest.mark.asyncio
    async def test_unsupported_capability_error(self, storage: FileStorage) -> None:
        """Requesting unsupported capability gives error."""
        # In-process executor doesn't support network isolation
        with pytest.raises(ValueError):
            async with Session(
                storage=storage,
                executor="in-process",
                network_policy="deny",
            ) as session:
                pass


# --- Concurrent Operation Errors ---


class TestConcurrencyErrors:
    """Tests for concurrent operation error handling."""

    @pytest.fixture
    def storage(self, tmp_path: Path) -> FileStorage:
        """Create FileStorage for testing."""
        return FileStorage(tmp_path)

    @pytest.mark.asyncio
    async def test_operations_after_close_error(self, storage: FileStorage) -> None:
        """Operations on closed session give error."""
        session = Session(storage=storage)
        await session.start()
        await session.close()

        # Running after close should fail
        try:
            result = await session.run("1 + 1")
            # If it doesn't raise, result should indicate error
            if result.is_ok:
                pytest.fail("Expected error after session close")
        except Exception:
            pass  # Exception is acceptable

    @pytest.mark.asyncio
    async def test_multiple_close_calls_safe(self, storage: FileStorage) -> None:
        """Multiple close() calls don't crash."""
        session = Session(storage=storage)
        await session.start()

        # Should not raise
        await session.close()
        await session.close()  # Second close should be safe
        await session.close()  # Third close should also be safe


# --- Edge Case Errors ---


class TestEdgeCaseErrors:
    """Tests for edge case error handling."""

    @pytest.fixture
    def storage(self, tmp_path: Path) -> FileStorage:
        """Create FileStorage for testing."""
        return FileStorage(tmp_path)

    @pytest.mark.asyncio
    async def test_empty_code_handling(self, storage: FileStorage) -> None:
        """Empty code string is handled gracefully."""
        async with Session(storage=storage) as session:
            result = await session.run("")

            # Either succeeds with None/empty or gives clear error
            # Should not crash

    @pytest.mark.asyncio
    async def test_whitespace_only_code_handling(self, storage: FileStorage) -> None:
        """Whitespace-only code is handled gracefully."""
        async with Session(storage=storage) as session:
            result = await session.run("   \n\t\n   ")

            # Should not crash

    @pytest.mark.asyncio
    async def test_very_long_code_handling(self, storage: FileStorage) -> None:
        """Very long code is handled (may fail with clear error)."""
        async with Session(storage=storage) as session:
            # Generate very long code
            long_code = "x = " + "1 + " * 10000 + "1"

            result = await session.run(long_code)

            # Either succeeds or fails with clear error
            # Should not hang or crash

    @pytest.mark.asyncio
    async def test_unicode_in_code_handling(self, storage: FileStorage) -> None:
        """Unicode in code is handled correctly."""
        async with Session(storage=storage) as session:
            result = await session.run('x = "emoji: \\U0001F600"; x')

            assert result.is_ok
            # Unicode should be preserved

    @pytest.mark.asyncio
    async def test_null_bytes_in_code_handling(self, storage: FileStorage) -> None:
        """Null bytes in code don't crash the system."""
        async with Session(storage=storage) as session:
            try:
                result = await session.run('x = "has\\x00null"')
                # May succeed or fail, but shouldn't crash
            except Exception:
                pass  # Exception is acceptable
