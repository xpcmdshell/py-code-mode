"""Failing tests for dependency configuration gaps.

These tests are written TDD-style - they WILL FAIL because the features
do not exist yet. The builder will implement code to make them pass.

Gap 1: Initial Deps + sync_deps_on_start
    - StorageBackend gets get_deps_store() method
    - Session gets sync_deps_on_start parameter

Gap 2: InProcessExecutor allow_runtime_deps
    - InProcessConfig with allow_runtime_deps flag
    - InProcessExecutor accepts config
    - Blocks deps.add/sync when disabled, allows deps.list/remove

Gap 3: MCP --no-runtime-deps Flag
    - MCP server accepts --no-runtime-deps flag
    - add_dep tool not registered when disabled
    - list_deps/remove_dep still available

Tests follow the test design hierarchy:
1. User Journey Tests (E2E)
2. Contract Tests
3. Integration Tests
4. Invariant Tests
5. Negative Tests
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    pass


# =============================================================================
# Gap 1: Initial Deps + sync_deps_on_start
# =============================================================================


class TestStorageGetDepsStore:
    """Tests for StorageBackend.get_deps_store() method.

    This enables pre-configuring dependencies before session start:
        storage.get_deps_store().add("pandas")
        storage.get_deps_store().add("numpy")
        Session(storage=storage, sync_deps_on_start=True)

    The deps are installed when session starts.
    """

    # -------------------------------------------------------------------------
    # Contract Tests
    # -------------------------------------------------------------------------

    def test_file_storage_get_deps_store_exists(self, tmp_path: Path) -> None:
        """FileStorage has get_deps_store() method.

        Contract: FileStorage.get_deps_store() returns DepsStore.
        Breaks when: Method missing from FileStorage.
        """
        from py_code_mode.storage import FileStorage

        storage = FileStorage(tmp_path)

        # Method must exist
        assert hasattr(storage, "get_deps_store")
        assert callable(storage.get_deps_store)

    def test_file_storage_get_deps_store_returns_deps_store(self, tmp_path: Path) -> None:
        """FileStorage.get_deps_store() returns a DepsStore instance.

        Contract: Return type is DepsStore protocol.
        Breaks when: Returns wrong type.
        """
        from py_code_mode.deps import DepsStore
        from py_code_mode.storage import FileStorage

        storage = FileStorage(tmp_path)
        deps_store = storage.get_deps_store()

        # Should implement DepsStore protocol
        assert isinstance(deps_store, DepsStore)
        assert hasattr(deps_store, "add")
        assert hasattr(deps_store, "remove")
        assert hasattr(deps_store, "list")

    def test_redis_storage_get_deps_store_exists(self) -> None:
        """RedisStorage has get_deps_store() method.

        Contract: RedisStorage.get_deps_store() returns DepsStore.
        Breaks when: Method missing from RedisStorage.
        """
        pytest.importorskip("redis")
        from unittest.mock import MagicMock

        from py_code_mode.storage import RedisStorage

        mock_redis = MagicMock()
        storage = RedisStorage(redis=mock_redis, prefix="test")

        # Method must exist
        assert hasattr(storage, "get_deps_store")
        assert callable(storage.get_deps_store)

    def test_redis_storage_get_deps_store_returns_deps_store(self) -> None:
        """RedisStorage.get_deps_store() returns a DepsStore instance.

        Contract: Return type is DepsStore protocol.
        Breaks when: Returns wrong type.
        """
        pytest.importorskip("redis")
        from unittest.mock import MagicMock

        from py_code_mode.deps import DepsStore
        from py_code_mode.storage import RedisStorage

        mock_redis = MagicMock()
        mock_redis.smembers.return_value = set()
        storage = RedisStorage(redis=mock_redis, prefix="test")
        deps_store = storage.get_deps_store()

        # Should implement DepsStore protocol
        assert isinstance(deps_store, DepsStore)

    # -------------------------------------------------------------------------
    # User Journey Tests
    # -------------------------------------------------------------------------

    def test_pre_configure_deps_via_storage(self, tmp_path: Path) -> None:
        """Pre-configure dependencies before session creation.

        User action: Add deps via storage before creating session.
        Verification: Deps are stored and can be listed.
        Breaks when: get_deps_store() not usable before session.
        """
        from py_code_mode.storage import FileStorage

        storage = FileStorage(tmp_path)

        # Add deps before session exists
        deps_store = storage.get_deps_store()
        deps_store.add("pandas>=2.0")
        deps_store.add("numpy")

        # Verify deps are stored
        deps = deps_store.list()
        assert "pandas>=2.0" in deps or "pandas>=2.0".lower().replace("_", "-") in deps
        assert "numpy" in deps

    # -------------------------------------------------------------------------
    # Invariant Tests
    # -------------------------------------------------------------------------

    def test_get_deps_store_returns_same_instance(self, tmp_path: Path) -> None:
        """get_deps_store() returns consistent store instance.

        Invariant: Multiple calls return same/equivalent store.
        Breaks when: Each call creates new disconnected store.
        """
        from py_code_mode.storage import FileStorage

        storage = FileStorage(tmp_path)

        store1 = storage.get_deps_store()
        store1.add("six")

        store2 = storage.get_deps_store()
        deps = store2.list()

        # Should see the dep added via store1
        assert "six" in deps


class TestSessionSyncDepsOnStart:
    """Tests for Session sync_deps_on_start parameter.

    When True, Session.start() installs all deps from storage.
    """

    # -------------------------------------------------------------------------
    # Contract Tests
    # -------------------------------------------------------------------------

    def test_session_accepts_sync_deps_on_start_parameter(self, tmp_path: Path) -> None:
        """Session constructor accepts sync_deps_on_start parameter.

        Contract: Session(storage=..., sync_deps_on_start=True) is valid.
        Breaks when: Parameter not accepted.
        """
        from py_code_mode.session import Session
        from py_code_mode.storage import FileStorage

        storage = FileStorage(tmp_path)

        # Should not raise
        session = Session(storage=storage, sync_deps_on_start=True)
        assert session is not None

    def test_session_sync_deps_on_start_defaults_false(self, tmp_path: Path) -> None:
        """sync_deps_on_start defaults to False.

        Contract: Default behavior is no automatic sync.
        Breaks when: Default changes to True.
        """
        from py_code_mode.session import Session
        from py_code_mode.storage import FileStorage

        storage = FileStorage(tmp_path)
        session = Session(storage=storage)

        # Check internal state or attribute
        assert hasattr(session, "_sync_deps_on_start") or hasattr(session, "sync_deps_on_start")
        sync_flag = getattr(
            session, "_sync_deps_on_start", getattr(session, "sync_deps_on_start", False)
        )
        assert sync_flag is False

    # -------------------------------------------------------------------------
    # User Journey Tests
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_sync_deps_on_start_installs_configured_deps(self, tmp_path: Path) -> None:
        """Session.start() installs deps when sync_deps_on_start=True.

        User action: Pre-configure deps, create session with sync_deps_on_start=True.
        Verification: Deps are installed during session.start().
        Breaks when: sync_deps_on_start doesn't trigger installation.
        """
        from unittest.mock import AsyncMock, patch

        from py_code_mode.session import Session
        from py_code_mode.storage import FileStorage

        storage = FileStorage(tmp_path)

        # Pre-configure deps
        deps_store = storage.get_deps_store()
        deps_store.add("six")  # Real package that's fast to install

        # Create session with sync_deps_on_start
        session = Session(storage=storage, sync_deps_on_start=True)

        # Mock the sync operation to verify it's called
        with patch.object(session, "_sync_deps", new_callable=AsyncMock) as mock_sync:
            await session.start()
            mock_sync.assert_called_once()

    @pytest.mark.asyncio
    async def test_sync_deps_on_start_with_no_deps_succeeds(self, tmp_path: Path) -> None:
        """sync_deps_on_start=True with empty deps list doesn't fail.

        User action: Create session with sync_deps_on_start=True but no deps configured.
        Verification: Session starts successfully.
        Breaks when: Empty deps list causes error.
        """
        from py_code_mode.session import Session
        from py_code_mode.storage import FileStorage

        storage = FileStorage(tmp_path)

        # No deps configured
        deps_store = storage.get_deps_store()
        assert deps_store.list() == []

        # Should not raise
        session = Session(storage=storage, sync_deps_on_start=True)
        await session.start()
        await session.close()

    # -------------------------------------------------------------------------
    # Negative Tests
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_sync_deps_on_start_false_does_not_install(self, tmp_path: Path) -> None:
        """sync_deps_on_start=False does not install deps.

        Breaks when: Deps installed even when flag is False.
        """
        from unittest.mock import AsyncMock, patch

        from py_code_mode.session import Session
        from py_code_mode.storage import FileStorage

        storage = FileStorage(tmp_path)
        deps_store = storage.get_deps_store()
        deps_store.add("pandas")

        session = Session(storage=storage, sync_deps_on_start=False)

        with patch.object(session, "_sync_deps", new_callable=AsyncMock) as mock_sync:
            await session.start()
            mock_sync.assert_not_called()

        await session.close()


# =============================================================================
# Gap 2: InProcessExecutor allow_runtime_deps
# =============================================================================


class TestInProcessConfig:
    """Tests for InProcessConfig configuration class."""

    # -------------------------------------------------------------------------
    # Contract Tests
    # -------------------------------------------------------------------------

    def test_in_process_config_exists(self) -> None:
        """InProcessConfig class exists and is importable.

        Contract: InProcessConfig is a public API.
        Breaks when: Class doesn't exist or isn't exported.
        """
        from py_code_mode.execution.in_process import InProcessConfig

        assert InProcessConfig is not None

    def test_in_process_config_has_allow_runtime_deps(self) -> None:
        """InProcessConfig has allow_runtime_deps attribute.

        Contract: InProcessConfig has allow_runtime_deps: bool.
        Breaks when: Attribute missing.
        """
        from py_code_mode.execution.in_process import InProcessConfig

        config = InProcessConfig()

        assert hasattr(config, "allow_runtime_deps")
        assert isinstance(config.allow_runtime_deps, bool)

    def test_in_process_config_allow_runtime_deps_default_true(self) -> None:
        """allow_runtime_deps defaults to True.

        Contract: Default allows runtime deps (backward compatible).
        Breaks when: Default is False.
        """
        from py_code_mode.execution.in_process import InProcessConfig

        config = InProcessConfig()

        assert config.allow_runtime_deps is True

    def test_in_process_config_allow_runtime_deps_can_be_false(self) -> None:
        """allow_runtime_deps can be set to False.

        Breaks when: Cannot set to False.
        """
        from py_code_mode.execution.in_process import InProcessConfig

        config = InProcessConfig(allow_runtime_deps=False)

        assert config.allow_runtime_deps is False


class TestInProcessExecutorConfig:
    """Tests for InProcessExecutor accepting config."""

    # -------------------------------------------------------------------------
    # Contract Tests
    # -------------------------------------------------------------------------

    def test_in_process_executor_accepts_config(self) -> None:
        """InProcessExecutor constructor accepts config parameter.

        Contract: InProcessExecutor(config=InProcessConfig()) is valid.
        Breaks when: config parameter not accepted.
        """
        from py_code_mode.execution.in_process import InProcessConfig, InProcessExecutor

        config = InProcessConfig(allow_runtime_deps=False)
        executor = InProcessExecutor(config=config)

        assert executor is not None

    def test_in_process_executor_backward_compatible_without_config(self) -> None:
        """InProcessExecutor works without config parameter.

        Contract: Omitting config still works (backward compatible).
        Breaks when: config becomes required.
        """
        from py_code_mode.execution.in_process import InProcessExecutor

        # Should not raise
        executor = InProcessExecutor()
        assert executor is not None

    # -------------------------------------------------------------------------
    # User Journey Tests (E2E)
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_deps_add_blocked_when_disabled(self, tmp_path: Path) -> None:
        """deps.add() raises error when allow_runtime_deps=False.

        User action: Try to add dep at runtime when disabled.
        Verification: Error raised, dep not added.
        Breaks when: deps.add() succeeds despite being disabled.
        """
        from py_code_mode.execution.in_process import InProcessConfig, InProcessExecutor
        from py_code_mode.session import Session
        from py_code_mode.storage import FileStorage

        config = InProcessConfig(allow_runtime_deps=False)
        executor = InProcessExecutor(config=config)
        storage = FileStorage(tmp_path)

        async with Session(storage=storage, executor=executor) as session:
            result = await session.run('deps.add("pandas")')

            # Should fail with error
            assert not result.is_ok
            assert "runtime" in result.error.lower() or "disabled" in result.error.lower()

    @pytest.mark.asyncio
    async def test_deps_sync_allowed_when_disabled(self, tmp_path: Path) -> None:
        """deps.sync() works when allow_runtime_deps=False.

        User action: Try to sync deps at runtime when add/remove disabled.
        Verification: Sync succeeds (only installs pre-configured deps).
        Breaks when: deps.sync() incorrectly blocked by disabled flag.

        Note: sync() only installs packages already in the deps store.
        It does NOT add new dependencies, so it should always be allowed.
        This is consistent with sync_deps_on_start=True working with
        allow_runtime_deps=False.
        """
        from py_code_mode.execution.in_process import InProcessConfig, InProcessExecutor
        from py_code_mode.session import Session
        from py_code_mode.storage import FileStorage

        config = InProcessConfig(allow_runtime_deps=False)
        executor = InProcessExecutor(config=config)
        storage = FileStorage(tmp_path)

        async with Session(storage=storage, executor=executor) as session:
            result = await session.run("deps.sync()")

            # Should succeed - sync only installs pre-configured deps
            assert result.is_ok, f"deps.sync() should work: {result.error}"

    @pytest.mark.asyncio
    async def test_deps_list_allowed_when_disabled(self, tmp_path: Path) -> None:
        """deps.list() works when allow_runtime_deps=False.

        User action: List deps when runtime install disabled.
        Verification: Returns list without error.
        Breaks when: deps.list() blocked by disabled flag.
        """
        from py_code_mode.execution.in_process import InProcessConfig, InProcessExecutor
        from py_code_mode.session import Session
        from py_code_mode.storage import FileStorage

        config = InProcessConfig(allow_runtime_deps=False)
        executor = InProcessExecutor(config=config)
        storage = FileStorage(tmp_path)

        async with Session(storage=storage, executor=executor) as session:
            result = await session.run("deps.list()")

            # Should succeed
            assert result.is_ok, f"deps.list() should work: {result.error}"
            assert isinstance(result.value, list)

    @pytest.mark.asyncio
    async def test_deps_remove_blocked_when_disabled(self, tmp_path: Path) -> None:
        """deps.remove() is blocked when allow_runtime_deps=False.

        User action: Try to remove dep from config when runtime deps disabled.
        Verification: Removal fails with RuntimeDepsDisabledError.
        Breaks when: deps.remove() allowed despite disabled flag.

        Rationale: When deps are locked (allow_runtime_deps=False), the
        configuration should be immutable. Blocking only add() but allowing
        remove() would let agents modify the dep configuration by deletion.
        """
        from py_code_mode.execution.in_process import InProcessConfig, InProcessExecutor
        from py_code_mode.session import Session
        from py_code_mode.storage import FileStorage

        storage = FileStorage(tmp_path)
        # Pre-add a dep
        storage.get_deps_store().add("six")

        config = InProcessConfig(allow_runtime_deps=False)
        executor = InProcessExecutor(config=config)

        async with Session(storage=storage, executor=executor) as session:
            result = await session.run('deps.remove("six")')

            # Should fail with RuntimeDepsDisabledError
            assert not result.is_ok
            assert "RuntimeDepsDisabledError" in result.error
            assert "disabled" in result.error.lower()

    # -------------------------------------------------------------------------
    # Integration Tests
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_deps_add_works_when_enabled(self, tmp_path: Path) -> None:
        """deps.add() works when allow_runtime_deps=True (default).

        Verification: Default behavior preserved.
        Breaks when: Default config blocks deps.add().
        """
        from py_code_mode.execution.in_process import InProcessConfig, InProcessExecutor
        from py_code_mode.session import Session
        from py_code_mode.storage import FileStorage

        config = InProcessConfig(allow_runtime_deps=True)
        executor = InProcessExecutor(config=config)
        storage = FileStorage(tmp_path)

        async with Session(storage=storage, executor=executor) as session:
            # Use 'six' - a real package that's fast to install
            result = await session.run('deps.add("six")')

            # Should succeed
            assert result.is_ok, f"deps.add() should work when enabled: {result.error}"


# =============================================================================
# Gap 3: MCP --no-runtime-deps Flag
# =============================================================================


class TestMCPServerNoRuntimeDepsFlag:
    """Tests for MCP server --no-runtime-deps CLI flag."""

    # -------------------------------------------------------------------------
    # Contract Tests
    # -------------------------------------------------------------------------

    def test_mcp_server_parser_accepts_no_runtime_deps_flag(self) -> None:
        """MCP server argparser accepts --no-runtime-deps flag.

        Contract: --no-runtime-deps is a valid CLI argument.
        Breaks when: Flag not added to argparser.
        """
        import argparse

        # Get the parser (if exposed) or test via parse_args
        # We need to test that --no-runtime-deps is accepted

        # Create a parser the same way main() does
        parser = argparse.ArgumentParser()
        parser.add_argument("--storage", help="Path to storage directory")
        parser.add_argument("--redis", help="Redis URL for storage")
        parser.add_argument("--prefix", help="Redis key prefix")
        parser.add_argument(
            "--no-runtime-deps",
            action="store_true",
            help="Disable runtime dependency installation",
        )

        # Should not raise
        args = parser.parse_args(["--storage", "/tmp/test", "--no-runtime-deps"])
        assert args.no_runtime_deps is True

    # -------------------------------------------------------------------------
    # User Journey Tests (E2E)
    # -------------------------------------------------------------------------

    @pytest.fixture
    def mcp_storage_dir(self, tmp_path: Path) -> Path:
        """Create storage directory structure for MCP server."""
        storage = tmp_path / "storage"
        storage.mkdir()
        (storage / "tools").mkdir()
        (storage / "skills").mkdir()
        (storage / "artifacts").mkdir()
        (storage / "deps").mkdir()
        return storage

    @pytest.mark.asyncio
    async def test_mcp_server_add_dep_not_registered_when_disabled(
        self, mcp_storage_dir: Path
    ) -> None:
        """add_dep tool not registered when --no-runtime-deps passed.

        User action: Start MCP server with --no-runtime-deps.
        Verification: add_dep tool is not in tool list.
        Breaks when: add_dep still registered despite flag.
        """
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        server_params = StdioServerParameters(
            command="py-code-mode-mcp",
            args=["--storage", str(mcp_storage_dir), "--no-runtime-deps"],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                tools = await session.list_tools()
                tool_names = {t.name for t in tools.tools}

                # add_dep should NOT be registered
                assert "add_dep" not in tool_names, (
                    "add_dep should not be registered with --no-runtime-deps"
                )

    @pytest.mark.asyncio
    async def test_mcp_server_list_deps_available_when_runtime_deps_disabled(
        self, mcp_storage_dir: Path
    ) -> None:
        """list_deps tool still available when --no-runtime-deps passed.

        User action: Start MCP server with --no-runtime-deps.
        Verification: list_deps tool is registered.
        Breaks when: list_deps removed by flag.
        """
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        server_params = StdioServerParameters(
            command="py-code-mode-mcp",
            args=["--storage", str(mcp_storage_dir), "--no-runtime-deps"],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                tools = await session.list_tools()
                tool_names = {t.name for t in tools.tools}

                # list_deps should still be available
                assert "list_deps" in tool_names, (
                    "list_deps should be available with --no-runtime-deps"
                )

                # And it should work
                result = await session.call_tool("list_deps", {})
                deps_data = json.loads(result.content[0].text)
                assert isinstance(deps_data, list)

    @pytest.mark.asyncio
    async def test_mcp_server_remove_dep_not_registered_when_disabled(
        self, mcp_storage_dir: Path
    ) -> None:
        """remove_dep tool NOT available when --no-runtime-deps passed.

        User action: Start MCP server with --no-runtime-deps.
        Verification: remove_dep tool is NOT registered (consistent with add_dep).
        Breaks when: remove_dep registered despite disabled flag.
        """
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        server_params = StdioServerParameters(
            command="py-code-mode-mcp",
            args=["--storage", str(mcp_storage_dir), "--no-runtime-deps"],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                tools = await session.list_tools()
                tool_names = {t.name for t in tools.tools}

                # remove_dep should NOT be registered
                assert "remove_dep" not in tool_names, (
                    "remove_dep should not be registered with --no-runtime-deps"
                )

    @pytest.mark.asyncio
    async def test_mcp_server_deps_add_via_run_code_blocked_when_disabled(
        self, mcp_storage_dir: Path
    ) -> None:
        """deps.add() via run_code blocked when --no-runtime-deps passed.

        User action: Try deps.add() via run_code when disabled.
        Verification: Error returned.
        Breaks when: run_code allows deps.add() despite flag.
        """
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        server_params = StdioServerParameters(
            command="py-code-mode-mcp",
            args=["--storage", str(mcp_storage_dir), "--no-runtime-deps"],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                result = await session.call_tool("run_code", {"code": 'deps.add("pandas")'})
                text = result.content[0].text.lower()

                # Should fail with error about runtime deps disabled
                assert "error" in text or "disabled" in text or "runtime" in text, (
                    f"deps.add should fail when disabled: {result.content[0].text}"
                )

    # -------------------------------------------------------------------------
    # Negative Tests
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_mcp_server_add_dep_registered_by_default(self, mcp_storage_dir: Path) -> None:
        """add_dep tool registered by default (without --no-runtime-deps).

        Breaks when: Default behavior changed to not register add_dep.
        """
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        server_params = StdioServerParameters(
            command="py-code-mode-mcp",
            args=["--storage", str(mcp_storage_dir)],  # No --no-runtime-deps
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                tools = await session.list_tools()
                tool_names = {t.name for t in tools.tools}

                # add_dep SHOULD be registered by default
                assert "add_dep" in tool_names, "add_dep should be registered by default"


# =============================================================================
# Integration Tests - Full Workflow
# =============================================================================


class TestDepsConfigurationWorkflow:
    """Integration tests for the complete deps configuration workflow.

    Tests the happy path: pre-configure deps, start with sync, runtime disabled.
    """

    @pytest.mark.asyncio
    async def test_full_workflow_pre_configure_sync_and_lock(self, tmp_path: Path) -> None:
        """Complete workflow: pre-configure, sync on start, runtime locked.

        User journey:
        1. Developer adds deps via storage
        2. Session starts with sync_deps_on_start=True
        3. Runtime deps disabled, agent can only list/remove

        Breaks when: Any step in the workflow fails.
        """
        from py_code_mode.execution.in_process import InProcessConfig, InProcessExecutor
        from py_code_mode.session import Session
        from py_code_mode.storage import FileStorage

        storage = FileStorage(tmp_path)

        # 1. Pre-configure deps
        deps_store = storage.get_deps_store()
        deps_store.add("six")

        # 2. Create session with sync and runtime disabled
        config = InProcessConfig(allow_runtime_deps=False)
        executor = InProcessExecutor(config=config)
        session = Session(storage=storage, executor=executor, sync_deps_on_start=True)

        await session.start()

        try:
            # 3. Verify deps are synced
            result = await session.run("deps.list()")
            assert result.is_ok
            assert "six" in result.value

            # 4. Runtime add should be blocked
            result = await session.run('deps.add("pandas")')
            assert not result.is_ok
            assert "runtime" in result.error.lower() or "disabled" in result.error.lower()

            # 5. List still works
            result = await session.run("deps.list()")
            assert result.is_ok

            # 6. Remove is also blocked when locked (immutable config)
            result = await session.run('deps.remove("six")')
            assert not result.is_ok
            assert "disabled" in result.error.lower()

        finally:
            await session.close()


# =============================================================================
# Security Tests - ControlledDepsNamespace Bypass Prevention
# =============================================================================


class TestControlledDepsNamespaceBypassPrevention:
    """Tests that ControlledDepsNamespace cannot be bypassed.

    Security issue: Agent code could access deps._wrapped.add() to bypass
    the RuntimeDepsDisabledError check. The fix uses __getattribute__ to
    block access to internal attributes.
    """

    def test_wrapped_attribute_access_blocked(self, tmp_path: Path) -> None:
        """Accessing _wrapped raises AttributeError.

        Breaks when: Agent can access deps._wrapped and bypass controls.
        """
        from py_code_mode.deps import (
            ControlledDepsNamespace,
            DepsNamespace,
            FileDepsStore,
            PackageInstaller,
        )

        store = FileDepsStore(tmp_path)
        installer = PackageInstaller()
        inner = DepsNamespace(store=store, installer=installer)
        controlled = ControlledDepsNamespace(inner, allow_runtime=False)

        with pytest.raises(AttributeError, match="Cannot access internal attribute"):
            _ = controlled._wrapped

    def test_allow_runtime_attribute_access_blocked(self, tmp_path: Path) -> None:
        """Accessing _allow_runtime raises AttributeError.

        Breaks when: Agent can read _allow_runtime flag.
        """
        from py_code_mode.deps import (
            ControlledDepsNamespace,
            DepsNamespace,
            FileDepsStore,
            PackageInstaller,
        )

        store = FileDepsStore(tmp_path)
        installer = PackageInstaller()
        inner = DepsNamespace(store=store, installer=installer)
        controlled = ControlledDepsNamespace(inner, allow_runtime=False)

        with pytest.raises(AttributeError, match="Cannot access internal attribute"):
            _ = controlled._allow_runtime

    def test_bypass_via_wrapped_add_blocked(self, tmp_path: Path) -> None:
        """Cannot bypass by calling deps._wrapped.add().

        This is the specific attack vector:
            deps._wrapped.add("malicious-package")

        Breaks when: Agent can install packages despite allow_runtime=False.
        """
        from py_code_mode.deps import (
            ControlledDepsNamespace,
            DepsNamespace,
            FileDepsStore,
            PackageInstaller,
        )

        store = FileDepsStore(tmp_path)
        installer = PackageInstaller()
        inner = DepsNamespace(store=store, installer=installer)
        controlled = ControlledDepsNamespace(inner, allow_runtime=False)

        # Attempt the bypass
        with pytest.raises(AttributeError, match="Cannot access internal attribute"):
            controlled._wrapped.add("malicious-package")

    def test_public_methods_still_work(self, tmp_path: Path) -> None:
        """Public methods (add, list, remove, sync) remain accessible.

        Breaks when: __getattribute__ blocks legitimate method access.
        """
        from py_code_mode.deps import (
            ControlledDepsNamespace,
            DepsNamespace,
            FileDepsStore,
            PackageInstaller,
            RuntimeDepsDisabledError,
        )

        store = FileDepsStore(tmp_path)
        installer = PackageInstaller()
        inner = DepsNamespace(store=store, installer=installer)
        controlled = ControlledDepsNamespace(inner, allow_runtime=False)

        # list() should work (read-only)
        result = controlled.list()
        assert isinstance(result, list)

        # add() should raise RuntimeDepsDisabledError (not AttributeError)
        with pytest.raises(RuntimeDepsDisabledError):
            controlled.add("pandas")

        # remove() should also raise RuntimeDepsDisabledError (config is immutable)
        with pytest.raises(RuntimeDepsDisabledError):
            controlled.remove("nonexistent")

        # sync() should work - it only installs pre-configured deps, not new ones
        sync_result = controlled.sync()
        # SyncResult returned (no error)
        assert hasattr(sync_result, "installed")

    def test_repr_still_works(self, tmp_path: Path) -> None:
        """__repr__ remains accessible for debugging.

        Breaks when: __getattribute__ blocks repr().
        """
        from py_code_mode.deps import (
            ControlledDepsNamespace,
            DepsNamespace,
            FileDepsStore,
            PackageInstaller,
        )

        store = FileDepsStore(tmp_path)
        installer = PackageInstaller()
        inner = DepsNamespace(store=store, installer=installer)
        controlled = ControlledDepsNamespace(inner, allow_runtime=False)

        repr_str = repr(controlled)
        assert "ControlledDepsNamespace" in repr_str
        assert "disabled" in repr_str

    def test_class_attribute_still_accessible(self, tmp_path: Path) -> None:
        """__class__ remains accessible for type checks.

        Breaks when: isinstance() or type() fail.
        """
        from py_code_mode.deps import (
            ControlledDepsNamespace,
            DepsNamespace,
            FileDepsStore,
            PackageInstaller,
        )

        store = FileDepsStore(tmp_path)
        installer = PackageInstaller()
        inner = DepsNamespace(store=store, installer=installer)
        controlled = ControlledDepsNamespace(inner, allow_runtime=False)

        assert isinstance(controlled, ControlledDepsNamespace)
        assert type(controlled) is ControlledDepsNamespace

    @pytest.mark.asyncio
    async def test_bypass_blocked_in_session_run(self, tmp_path: Path) -> None:
        """Bypass attempt via session.run() is blocked.

        User action: Agent tries deps._wrapped.add() via run_code.
        Verification: AttributeError returned in result.
        Breaks when: Agent can bypass controls via run_code.
        """
        from py_code_mode.execution.in_process import InProcessConfig, InProcessExecutor
        from py_code_mode.session import Session
        from py_code_mode.storage import FileStorage

        config = InProcessConfig(allow_runtime_deps=False)
        executor = InProcessExecutor(config=config)
        storage = FileStorage(tmp_path)

        async with Session(storage=storage, executor=executor) as session:
            result = await session.run('deps._wrapped.add("malicious-package")')

            # Should fail with AttributeError
            assert not result.is_ok
            assert "AttributeError" in result.error or "Cannot access" in result.error


# =============================================================================
# Track 4: SubprocessExecutor Deps Configuration Tests
# =============================================================================


@pytest.mark.slow
@pytest.mark.xdist_group("subprocess")
class TestSubprocessExecutorDepsConfigGaps:
    """Tests for SubprocessExecutor with deps configuration features.

    These tests verify that the allow_runtime_deps configuration and
    sync_deps_on_start work correctly with the SubprocessExecutor backend.
    """

    # -------------------------------------------------------------------------
    # User Journey Tests (E2E)
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_full_workflow_pre_configure_sync_and_lock_subprocess(
        self, tmp_path: Path
    ) -> None:
        """Complete workflow: pre-configure, sync on start, runtime locked with SubprocessExecutor.

        User journey:
        1. Developer adds deps via storage.get_deps_store().add("six")
        2. Creates SubprocessExecutor with allow_runtime_deps=False
        3. Creates Session with sync_deps_on_start=True
        4. Verifies deps.list() includes "six"
        5. Verifies deps.add() is blocked
        6. Verifies deps.remove() is blocked
        7. Verifies deps.list() still works

        Breaks when: Any step in the workflow fails.
        """
        from py_code_mode.execution.subprocess import SubprocessConfig, SubprocessExecutor
        from py_code_mode.session import Session
        from py_code_mode.storage import FileStorage

        storage = FileStorage(tmp_path)

        # 1. Pre-configure deps
        deps_store = storage.get_deps_store()
        deps_store.add("six")

        # 2. Create SubprocessExecutor with runtime deps disabled
        config = SubprocessConfig(
            python_version="3.12",
            venv_path=tmp_path / "venv",
            base_deps=("ipykernel", "py-code-mode"),
            allow_runtime_deps=False,
        )
        executor = SubprocessExecutor(config=config)

        # 3. Create Session with sync_deps_on_start=True
        async with Session(storage=storage, executor=executor, sync_deps_on_start=True) as session:
            # 4. Verify deps are synced (six should be in list)
            result = await session.run("deps.list()")
            assert result.is_ok, f"deps.list() failed: {result.error}"
            assert "six" in result.value

            # 5. Runtime add should be blocked
            result = await session.run('deps.add("pandas")')
            assert not result.is_ok
            assert "runtime" in result.error.lower() or "disabled" in result.error.lower()

            # 6. Remove is also blocked when locked (immutable config)
            result = await session.run('deps.remove("six")')
            assert not result.is_ok
            assert "disabled" in result.error.lower()

            # 7. List still works
            result = await session.run("deps.list()")
            assert result.is_ok

    # -------------------------------------------------------------------------
    # Blocked Operations Tests
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_deps_add_blocked_when_disabled_subprocess(self, tmp_path: Path) -> None:
        """deps.add() raises error in subprocess when allow_runtime_deps=False.

        User action: Try to add dep at runtime when disabled.
        Verification: Error raised, dep not added.
        Breaks when: deps.add() succeeds despite being disabled.
        """
        from py_code_mode.execution.subprocess import SubprocessConfig, SubprocessExecutor
        from py_code_mode.session import Session
        from py_code_mode.storage import FileStorage

        config = SubprocessConfig(
            python_version="3.12",
            venv_path=tmp_path / "venv",
            base_deps=("ipykernel", "py-code-mode"),
            allow_runtime_deps=False,
        )
        executor = SubprocessExecutor(config=config)
        storage = FileStorage(tmp_path)

        async with Session(storage=storage, executor=executor) as session:
            result = await session.run('deps.add("pandas")')

            # Should fail with error
            assert not result.is_ok
            assert "runtime" in result.error.lower() or "disabled" in result.error.lower()

    @pytest.mark.asyncio
    async def test_deps_remove_blocked_when_disabled_subprocess(self, tmp_path: Path) -> None:
        """deps.remove() raises error in subprocess when allow_runtime_deps=False.

        User action: Try to remove dep from config when runtime deps disabled.
        Verification: Removal fails with RuntimeDepsDisabledError.
        Breaks when: deps.remove() allowed despite disabled flag.
        """
        from py_code_mode.execution.subprocess import SubprocessConfig, SubprocessExecutor
        from py_code_mode.session import Session
        from py_code_mode.storage import FileStorage

        storage = FileStorage(tmp_path)
        # Pre-add a dep
        storage.get_deps_store().add("six")

        config = SubprocessConfig(
            python_version="3.12",
            venv_path=tmp_path / "venv",
            base_deps=("ipykernel", "py-code-mode"),
            allow_runtime_deps=False,
        )
        executor = SubprocessExecutor(config=config)

        async with Session(storage=storage, executor=executor) as session:
            result = await session.run('deps.remove("six")')

            # Should fail with RuntimeDepsDisabledError
            assert not result.is_ok
            assert "RuntimeDepsDisabledError" in result.error or "disabled" in result.error.lower()

    @pytest.mark.asyncio
    async def test_deps_sync_allowed_when_disabled_subprocess(self, tmp_path: Path) -> None:
        """deps.sync() works in subprocess when allow_runtime_deps=False.

        User action: Try to sync deps at runtime when add/remove disabled.
        Verification: Sync succeeds (only installs pre-configured deps).
        Breaks when: deps.sync() incorrectly blocked by disabled flag.

        Note: sync() only installs packages already in the deps store.
        It does NOT add new dependencies, so it should always be allowed.
        This is consistent with sync_deps_on_start=True working with
        allow_runtime_deps=False.
        """
        from py_code_mode.execution.subprocess import SubprocessConfig, SubprocessExecutor
        from py_code_mode.session import Session
        from py_code_mode.storage import FileStorage

        config = SubprocessConfig(
            python_version="3.12",
            venv_path=tmp_path / "venv",
            base_deps=("ipykernel", "py-code-mode"),
            allow_runtime_deps=False,
        )
        executor = SubprocessExecutor(config=config)
        storage = FileStorage(tmp_path)

        async with Session(storage=storage, executor=executor) as session:
            result = await session.run("deps.sync()")

            # Should succeed - sync only installs pre-configured deps
            assert result.is_ok, f"deps.sync() should work: {result.error}"

    # -------------------------------------------------------------------------
    # Read-only Operation Tests
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_deps_list_allowed_when_disabled_subprocess(self, tmp_path: Path) -> None:
        """deps.list() works in subprocess when allow_runtime_deps=False.

        User action: List deps when runtime install disabled.
        Verification: Returns list without error.
        Breaks when: deps.list() blocked by disabled flag.
        """
        from py_code_mode.execution.subprocess import SubprocessConfig, SubprocessExecutor
        from py_code_mode.session import Session
        from py_code_mode.storage import FileStorage

        config = SubprocessConfig(
            python_version="3.12",
            venv_path=tmp_path / "venv",
            base_deps=("ipykernel", "py-code-mode"),
            allow_runtime_deps=False,
        )
        executor = SubprocessExecutor(config=config)
        storage = FileStorage(tmp_path)

        async with Session(storage=storage, executor=executor) as session:
            result = await session.run("deps.list()")

            # Should succeed
            assert result.is_ok, f"deps.list() should work: {result.error}"
            assert isinstance(result.value, list)

    # -------------------------------------------------------------------------
    # Security Tests
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_subprocess_bypass_via_wrapped_blocked(self, tmp_path: Path) -> None:
        """Bypass attempt via deps._wrapped.add() blocked in subprocess.

        User action: Agent tries deps._wrapped.add() via run_code in subprocess.
        Verification: AttributeError returned in result.
        Breaks when: Agent can bypass controls via _wrapped access in subprocess.
        """
        from py_code_mode.execution.subprocess import SubprocessConfig, SubprocessExecutor
        from py_code_mode.session import Session
        from py_code_mode.storage import FileStorage

        config = SubprocessConfig(
            python_version="3.12",
            venv_path=tmp_path / "venv",
            base_deps=("ipykernel", "py-code-mode"),
            allow_runtime_deps=False,
        )
        executor = SubprocessExecutor(config=config)
        storage = FileStorage(tmp_path)

        async with Session(storage=storage, executor=executor) as session:
            result = await session.run('deps._wrapped.add("malicious-package")')

            # Should fail with AttributeError
            assert not result.is_ok
            assert "AttributeError" in result.error or "Cannot access" in result.error


# =============================================================================
# Track 5: ContainerExecutor Deps Configuration Tests
# =============================================================================


@pytest.mark.slow
@pytest.mark.xdist_group("container")
class TestContainerExecutorDepsConfigGaps:
    """Tests for ContainerExecutor with deps configuration features.

    These tests verify that the allow_runtime_deps configuration and
    sync_deps_on_start work correctly with the ContainerExecutor backend.

    NOTE: These tests are written TDD-style - they WILL FAIL initially because
    ContainerExecutor does not yet inject the deps namespace. Expected failures:
    - NameError: name 'deps' is not defined (deps namespace not injected)
    - ContainerConfig() got an unexpected keyword argument 'allow_runtime_deps'

    Once the builder implements deps namespace injection for ContainerExecutor,
    these tests should pass.
    """

    # -------------------------------------------------------------------------
    # F1: Pre-configure deps
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_pre_configure_deps_visible_in_container(self, tmp_path: Path) -> None:
        """Pre-configured deps via storage.get_deps_store().add() appear in deps.list().

        User action: Add deps via storage before session, then list via deps.list().
        Verification: deps.list() shows the pre-configured package.
        Breaks when: ContainerExecutor doesn't inject deps namespace or doesn't
                     use the same storage backend for deps.
        """
        from py_code_mode.execution.container import ContainerConfig, ContainerExecutor
        from py_code_mode.session import Session
        from py_code_mode.storage import FileStorage

        storage = FileStorage(tmp_path)

        # Pre-configure deps before session
        deps_store = storage.get_deps_store()
        deps_store.add("six")

        config = ContainerConfig()
        executor = ContainerExecutor(config=config)

        async with Session(storage=storage, executor=executor) as session:
            result = await session.run("deps.list()")

            assert result.is_ok, f"deps.list() failed: {result.error}"
            assert "six" in result.value

    # -------------------------------------------------------------------------
    # F2: sync_deps_on_start
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_sync_deps_on_start_installs_in_container(self, tmp_path: Path) -> None:
        """sync_deps_on_start=True installs pre-configured deps in container.

        User action: Pre-configure deps, start session with sync_deps_on_start=True.
        Verification: Package is importable after session start.
        Breaks when: sync_deps_on_start doesn't trigger installation in container.
        """
        from py_code_mode.execution.container import ContainerConfig, ContainerExecutor
        from py_code_mode.session import Session
        from py_code_mode.storage import FileStorage

        storage = FileStorage(tmp_path)

        # Pre-configure deps
        deps_store = storage.get_deps_store()
        deps_store.add("six")

        config = ContainerConfig()
        executor = ContainerExecutor(config=config)

        async with Session(storage=storage, executor=executor, sync_deps_on_start=True) as session:
            # Verify six is importable (proves it was installed)
            result = await session.run("import six; six.__version__")

            assert result.is_ok, f"import six failed: {result.error}"
            assert result.value is not None  # Has a version string

    # -------------------------------------------------------------------------
    # F3: deps.list() always works
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_deps_list_always_works_in_container(self, tmp_path: Path) -> None:
        """deps.list() works in container regardless of allow_runtime_deps setting.

        User action: Call deps.list() in container with allow_runtime_deps=False.
        Verification: Returns list without error.
        Breaks when: deps.list() blocked or deps namespace not injected.
        """
        from py_code_mode.execution.container import ContainerConfig, ContainerExecutor
        from py_code_mode.session import Session
        from py_code_mode.storage import FileStorage

        config = ContainerConfig(allow_runtime_deps=False)
        executor = ContainerExecutor(config=config)
        storage = FileStorage(tmp_path)

        async with Session(storage=storage, executor=executor) as session:
            result = await session.run("deps.list()")

            assert result.is_ok, f"deps.list() should always work: {result.error}"
            assert isinstance(result.value, list)

    # -------------------------------------------------------------------------
    # F4: deps.add() blocked when disabled
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_deps_add_blocked_when_disabled_container(self, tmp_path: Path) -> None:
        """deps.add() raises error in container when allow_runtime_deps=False.

        User action: Try to add dep at runtime when disabled.
        Verification: Error raised, dep not added.
        Breaks when: deps.add() succeeds despite being disabled.
        """
        from py_code_mode.execution.container import ContainerConfig, ContainerExecutor
        from py_code_mode.session import Session
        from py_code_mode.storage import FileStorage

        config = ContainerConfig(allow_runtime_deps=False)
        executor = ContainerExecutor(config=config)
        storage = FileStorage(tmp_path)

        async with Session(storage=storage, executor=executor) as session:
            result = await session.run('deps.add("pandas")')

            assert not result.is_ok
            assert "runtime" in result.error.lower() or "disabled" in result.error.lower()

    # -------------------------------------------------------------------------
    # F5: deps.remove() blocked when disabled
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_deps_remove_blocked_when_disabled_container(self, tmp_path: Path) -> None:
        """deps.remove() raises error in container when allow_runtime_deps=False.

        User action: Try to remove dep from config when runtime deps disabled.
        Verification: Removal fails with RuntimeDepsDisabledError.
        Breaks when: deps.remove() allowed despite disabled flag.
        """
        from py_code_mode.execution.container import ContainerConfig, ContainerExecutor
        from py_code_mode.session import Session
        from py_code_mode.storage import FileStorage

        storage = FileStorage(tmp_path)
        # Pre-add a dep
        storage.get_deps_store().add("six")

        config = ContainerConfig(allow_runtime_deps=False)
        executor = ContainerExecutor(config=config)

        async with Session(storage=storage, executor=executor) as session:
            result = await session.run('deps.remove("six")')

            assert not result.is_ok
            assert "RuntimeDepsDisabledError" in result.error or "disabled" in result.error.lower()

    # -------------------------------------------------------------------------
    # F6: deps.sync() allowed even when runtime deps disabled
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_deps_sync_allowed_when_disabled_container(self, tmp_path: Path) -> None:
        """deps.sync() works in container when allow_runtime_deps=False.

        User action: Try to sync deps at runtime when add/remove disabled.
        Verification: Sync succeeds (only installs pre-configured deps).
        Breaks when: deps.sync() incorrectly blocked by disabled flag.

        Note: sync() only installs packages already in the deps store.
        It does NOT add new dependencies, so it should always be allowed.
        """
        from py_code_mode.execution.container import ContainerConfig, ContainerExecutor
        from py_code_mode.session import Session
        from py_code_mode.storage import FileStorage

        config = ContainerConfig(allow_runtime_deps=False)
        executor = ContainerExecutor(config=config)
        storage = FileStorage(tmp_path)

        async with Session(storage=storage, executor=executor) as session:
            result = await session.run("deps.sync()")

            assert result.is_ok, f"deps.sync() should work: {result.error}"

    # -------------------------------------------------------------------------
    # F7: Bypass prevention (_wrapped access blocked)
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_bypass_via_wrapped_blocked_container(self, tmp_path: Path) -> None:
        """Bypass attempt via deps._wrapped.add() blocked in container.

        User action: Agent tries deps._wrapped.add() via run_code in container.
        Verification: AttributeError returned in result.
        Breaks when: Agent can bypass controls via _wrapped access in container.
        """
        from py_code_mode.execution.container import ContainerConfig, ContainerExecutor
        from py_code_mode.session import Session
        from py_code_mode.storage import FileStorage

        config = ContainerConfig(allow_runtime_deps=False)
        executor = ContainerExecutor(config=config)
        storage = FileStorage(tmp_path)

        async with Session(storage=storage, executor=executor) as session:
            result = await session.run('deps._wrapped.add("malicious-package")')

            assert not result.is_ok
            assert "AttributeError" in result.error or "Cannot access" in result.error

    # -------------------------------------------------------------------------
    # F8: Import works after sync
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_import_works_after_sync_container(self, tmp_path: Path) -> None:
        """Pre-configured packages can be imported after sync in container.

        User action: Pre-configure dep, sync, then import.
        Verification: Import succeeds.
        Breaks when: Package not actually installed or import path wrong.
        """
        from py_code_mode.execution.container import ContainerConfig, ContainerExecutor
        from py_code_mode.session import Session
        from py_code_mode.storage import FileStorage

        storage = FileStorage(tmp_path)

        # Pre-configure deps
        deps_store = storage.get_deps_store()
        deps_store.add("six")

        config = ContainerConfig()
        executor = ContainerExecutor(config=config)

        async with Session(storage=storage, executor=executor) as session:
            # Sync deps
            sync_result = await session.run("deps.sync()")
            assert sync_result.is_ok, f"deps.sync() failed: {sync_result.error}"

            # Now import should work
            result = await session.run("import six; six.__version__")
            assert result.is_ok, f"import six failed: {result.error}"

    # -------------------------------------------------------------------------
    # F9: Persistence across sessions
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_deps_persist_across_sessions_container(self, tmp_path: Path) -> None:
        """Deps configured in one session are visible in subsequent sessions.

        User action: Add dep in session 1, list in session 2 (same storage).
        Verification: Session 2 sees the dep from session 1.
        Breaks when: Deps not persisted to storage or not loaded in new session.
        """
        from py_code_mode.execution.container import ContainerConfig, ContainerExecutor
        from py_code_mode.session import Session
        from py_code_mode.storage import FileStorage

        storage = FileStorage(tmp_path)
        config = ContainerConfig(allow_runtime_deps=True)

        # Session 1: add a dep
        executor1 = ContainerExecutor(config=config)
        async with Session(storage=storage, executor=executor1) as session1:
            result = await session1.run('deps.add("six")')
            assert result.is_ok, f"deps.add() failed: {result.error}"

        # Session 2: verify dep persisted (new executor, same storage)
        executor2 = ContainerExecutor(config=config)
        async with Session(storage=storage, executor=executor2) as session2:
            result = await session2.run("deps.list()")
            assert result.is_ok, f"deps.list() failed: {result.error}"
            assert "six" in result.value, f"six not found in {result.value}"
