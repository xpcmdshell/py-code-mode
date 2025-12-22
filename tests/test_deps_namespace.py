"""Tests for DepsNamespace (agent-facing API).

TDD RED phase: These tests are written before implementation.
They will fail until the deps module is implemented.

Test hierarchy:
1. User journey tests (E2E)
2. Contract tests (namespace API)
3. Integration tests (namespace + store + installer)
4. Negative tests (error handling)
"""

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

if TYPE_CHECKING:
    pass


# =============================================================================
# User Journey Tests (E2E)
# =============================================================================


class TestDepsNamespaceUserJourney:
    """Complete agent workflow from import to installed packages."""

    def test_agent_adds_and_uses_package(self, tmp_path: Path) -> None:
        """Agent adds a package and it becomes available.

        User action: Agent writes deps.add("pandas") then uses pandas
        Setup: Empty deps store
        Steps:
            1. Create namespace with store
            2. Call deps.add("pandas")
            3. Package is installed
        Verification: Package is installed successfully
        Breaks when: add() doesn't trigger installation
        """
        from py_code_mode.deps import DepsNamespace, FileDepsStore, PackageInstaller

        store = FileDepsStore(tmp_path)
        installer = PackageInstaller()
        namespace = DepsNamespace(store=store, installer=installer)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            # Agent adds package - should install immediately
            namespace.add("pandas")

            # Verify pip/uv was called
            assert mock_run.called

            # Package should be in deps list
            assert "pandas" in namespace.list()

    def test_agent_lists_configured_deps(self, tmp_path: Path) -> None:
        """Agent can see what packages are configured.

        User action: Agent calls deps.list()
        Setup: Store with pre-configured deps
        Steps:
            1. Create store with packages
            2. Create namespace
            3. Call deps.list()
        Verification: Returns list of package names
        Breaks when: list() doesn't reflect store contents
        """
        from py_code_mode.deps import DepsNamespace, FileDepsStore, PackageInstaller

        store = FileDepsStore(tmp_path)
        store.add("pandas")
        store.add("numpy")

        installer = PackageInstaller()
        namespace = DepsNamespace(store=store, installer=installer)

        deps = namespace.list()

        assert "pandas" in deps
        assert "numpy" in deps

    def test_agent_removes_unneeded_package(self, tmp_path: Path) -> None:
        """Agent removes a package from configuration.

        User action: Agent calls deps.remove("package")
        Setup: Store with package added
        Steps:
            1. Add package
            2. Remove package
        Verification: Package no longer in list
        Breaks when: remove() doesn't update store
        """
        from py_code_mode.deps import DepsNamespace, FileDepsStore, PackageInstaller

        store = FileDepsStore(tmp_path)
        store.add("pandas")

        installer = PackageInstaller()
        namespace = DepsNamespace(store=store, installer=installer)

        # Remove the package
        result = namespace.remove("pandas")

        assert result is True
        assert "pandas" not in namespace.list()

    def test_agent_syncs_all_deps(self, tmp_path: Path) -> None:
        """Agent ensures all configured deps are installed.

        User action: Agent calls deps.sync()
        Setup: Store with multiple packages
        Steps:
            1. Configure multiple packages
            2. Call sync()
        Verification: All packages installed
        Breaks when: sync() doesn't install all packages
        """
        from py_code_mode.deps import DepsNamespace, FileDepsStore, PackageInstaller

        store = FileDepsStore(tmp_path)
        store.add("pandas")
        store.add("numpy")
        store.add("requests")

        installer = PackageInstaller()
        namespace = DepsNamespace(store=store, installer=installer)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            result = namespace.sync()

            # Should have sync result
            assert result is not None
            # All packages should be in installed or already_present
            all_handled = result.installed | result.already_present
            assert "pandas" in all_handled or mock_run.called


# =============================================================================
# Contract Tests (Namespace API)
# =============================================================================


class TestDepsNamespaceContract:
    """Tests for DepsNamespace public API."""

    def test_namespace_has_add_method(self, tmp_path: Path) -> None:
        """DepsNamespace has add(package) method.

        Breaks when: add method is missing.
        """
        from py_code_mode.deps import DepsNamespace, FileDepsStore, PackageInstaller

        store = FileDepsStore(tmp_path)
        installer = PackageInstaller()
        namespace = DepsNamespace(store=store, installer=installer)

        assert hasattr(namespace, "add")
        assert callable(namespace.add)

    def test_namespace_has_list_method(self, tmp_path: Path) -> None:
        """DepsNamespace has list() method.

        Breaks when: list method is missing.
        """
        from py_code_mode.deps import DepsNamespace, FileDepsStore, PackageInstaller

        store = FileDepsStore(tmp_path)
        installer = PackageInstaller()
        namespace = DepsNamespace(store=store, installer=installer)

        assert hasattr(namespace, "list")
        assert callable(namespace.list)

    def test_namespace_has_remove_method(self, tmp_path: Path) -> None:
        """DepsNamespace has remove(package) method.

        Breaks when: remove method is missing.
        """
        from py_code_mode.deps import DepsNamespace, FileDepsStore, PackageInstaller

        store = FileDepsStore(tmp_path)
        installer = PackageInstaller()
        namespace = DepsNamespace(store=store, installer=installer)

        assert hasattr(namespace, "remove")
        assert callable(namespace.remove)

    def test_namespace_has_sync_method(self, tmp_path: Path) -> None:
        """DepsNamespace has sync() method.

        Breaks when: sync method is missing.
        """
        from py_code_mode.deps import DepsNamespace, FileDepsStore, PackageInstaller

        store = FileDepsStore(tmp_path)
        installer = PackageInstaller()
        namespace = DepsNamespace(store=store, installer=installer)

        assert hasattr(namespace, "sync")
        assert callable(namespace.sync)

    def test_list_returns_list_of_strings(self, tmp_path: Path) -> None:
        """list() returns list[str].

        Breaks when: Return type is wrong.
        """
        from py_code_mode.deps import DepsNamespace, FileDepsStore, PackageInstaller

        store = FileDepsStore(tmp_path)
        store.add("pandas")

        installer = PackageInstaller()
        namespace = DepsNamespace(store=store, installer=installer)

        result = namespace.list()

        assert isinstance(result, list)
        assert all(isinstance(item, str) for item in result)

    def test_add_returns_sync_result(self, tmp_path: Path) -> None:
        """add() returns SyncResult after installing.

        Breaks when: add() doesn't return result or returns wrong type.
        """
        from py_code_mode.deps import (
            DepsNamespace,
            FileDepsStore,
            PackageInstaller,
            SyncResult,
        )

        store = FileDepsStore(tmp_path)
        installer = PackageInstaller()
        namespace = DepsNamespace(store=store, installer=installer)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            result = namespace.add("pandas")

            assert isinstance(result, SyncResult)

    def test_remove_returns_bool(self, tmp_path: Path) -> None:
        """remove() returns bool indicating success.

        Breaks when: Return type is wrong.
        """
        from py_code_mode.deps import DepsNamespace, FileDepsStore, PackageInstaller

        store = FileDepsStore(tmp_path)
        store.add("pandas")

        installer = PackageInstaller()
        namespace = DepsNamespace(store=store, installer=installer)

        result = namespace.remove("pandas")
        assert isinstance(result, bool)

    def test_sync_returns_sync_result(self, tmp_path: Path) -> None:
        """sync() returns SyncResult.

        Breaks when: Return type is wrong.
        """
        from py_code_mode.deps import (
            DepsNamespace,
            FileDepsStore,
            PackageInstaller,
            SyncResult,
        )

        store = FileDepsStore(tmp_path)
        installer = PackageInstaller()
        namespace = DepsNamespace(store=store, installer=installer)

        result = namespace.sync()

        assert isinstance(result, SyncResult)


# =============================================================================
# Integration Tests (Namespace + Store + Installer)
# =============================================================================


class TestDepsNamespaceIntegration:
    """Tests for namespace integration with store and installer."""

    def test_add_updates_store_and_calls_installer(self, tmp_path: Path) -> None:
        """add() updates store AND calls installer.

        Breaks when: add() only updates store without installing.
        """
        from py_code_mode.deps import DepsNamespace, FileDepsStore, PackageInstaller

        store = FileDepsStore(tmp_path)
        installer = PackageInstaller()
        namespace = DepsNamespace(store=store, installer=installer)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            namespace.add("pandas")

            # Store should have the package
            assert "pandas" in store.list()

            # Installer should have been called
            assert mock_run.called

    def test_remove_only_updates_store_not_uninstalls(self, tmp_path: Path) -> None:
        """remove() removes from config, doesn't uninstall from environment.

        Breaks when: remove() tries to pip uninstall.
        """
        from py_code_mode.deps import DepsNamespace, FileDepsStore, PackageInstaller

        store = FileDepsStore(tmp_path)
        store.add("pandas")

        installer = PackageInstaller()
        namespace = DepsNamespace(store=store, installer=installer)

        with patch("subprocess.run") as mock_run:
            namespace.remove("pandas")

            # Should NOT call pip uninstall
            # (remove() only updates config, doesn't touch installed packages)
            if mock_run.called:
                cmd = mock_run.call_args[0][0]
                cmd_str = " ".join(str(c) for c in cmd)
                assert "uninstall" not in cmd_str

    def test_sync_delegates_to_installer(self, tmp_path: Path) -> None:
        """sync() calls installer.sync() with store.

        Breaks when: sync() doesn't use the installer.
        """
        from py_code_mode.deps import DepsNamespace, FileDepsStore, PackageInstaller

        store = FileDepsStore(tmp_path)
        store.add("pandas")

        installer = PackageInstaller()
        namespace = DepsNamespace(store=store, installer=installer)

        with patch.object(installer, "sync", wraps=installer.sync) as mock_sync:
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)

                namespace.sync()

                mock_sync.assert_called_once_with(store)

    def test_namespace_uses_same_store_instance(self, tmp_path: Path) -> None:
        """Namespace operations affect the same store instance.

        Breaks when: Namespace creates new store on each operation.
        """
        from py_code_mode.deps import DepsNamespace, FileDepsStore, PackageInstaller

        store = FileDepsStore(tmp_path)
        installer = PackageInstaller()
        namespace = DepsNamespace(store=store, installer=installer)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            namespace.add("pandas")

            # Check original store instance has the package
            assert "pandas" in store.list()


# =============================================================================
# Version Specifier Tests
# =============================================================================


class TestDepsNamespaceVersionSpecifiers:
    """Tests for handling version specifiers in package names."""

    def test_add_with_version_specifier(self, tmp_path: Path) -> None:
        """add() accepts version specifiers.

        Breaks when: Version specifiers cause errors.
        """
        from py_code_mode.deps import DepsNamespace, FileDepsStore, PackageInstaller

        store = FileDepsStore(tmp_path)
        installer = PackageInstaller()
        namespace = DepsNamespace(store=store, installer=installer)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            namespace.add("pandas>=2.0")

            assert "pandas>=2.0" in namespace.list()

    def test_add_with_exact_version(self, tmp_path: Path) -> None:
        """add() accepts exact version pins.

        Breaks when: Exact versions cause errors.
        """
        from py_code_mode.deps import DepsNamespace, FileDepsStore, PackageInstaller

        store = FileDepsStore(tmp_path)
        installer = PackageInstaller()
        namespace = DepsNamespace(store=store, installer=installer)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            namespace.add("requests==2.31.0")

            assert "requests==2.31.0" in namespace.list()

    def test_add_with_extras(self, tmp_path: Path) -> None:
        """add() accepts extras syntax.

        Breaks when: Extras syntax causes errors.
        """
        from py_code_mode.deps import DepsNamespace, FileDepsStore, PackageInstaller

        store = FileDepsStore(tmp_path)
        installer = PackageInstaller()
        namespace = DepsNamespace(store=store, installer=installer)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            namespace.add("httpx[http2]")

            assert "httpx[http2]" in namespace.list()


# =============================================================================
# Negative Tests (Error Handling)
# =============================================================================


class TestDepsNamespaceNegativeCases:
    """Tests for error conditions and edge cases."""

    def test_add_empty_string_raises(self, tmp_path: Path) -> None:
        """add('') raises ValueError.

        Breaks when: Empty string is accepted.
        """
        from py_code_mode.deps import DepsNamespace, FileDepsStore, PackageInstaller

        store = FileDepsStore(tmp_path)
        installer = PackageInstaller()
        namespace = DepsNamespace(store=store, installer=installer)

        with pytest.raises(ValueError, match="[Ii]nvalid|[Ee]mpty"):
            namespace.add("")

    def test_add_whitespace_only_raises(self, tmp_path: Path) -> None:
        """add('   ') raises ValueError.

        Breaks when: Whitespace-only string is accepted.
        """
        from py_code_mode.deps import DepsNamespace, FileDepsStore, PackageInstaller

        store = FileDepsStore(tmp_path)
        installer = PackageInstaller()
        namespace = DepsNamespace(store=store, installer=installer)

        with pytest.raises(ValueError, match="[Ii]nvalid|[Ee]mpty"):
            namespace.add("   ")

    def test_add_with_shell_metacharacters_raises(self, tmp_path: Path) -> None:
        """add() rejects dangerous shell metacharacters.

        Breaks when: Command injection is possible.
        """
        from py_code_mode.deps import DepsNamespace, FileDepsStore, PackageInstaller

        store = FileDepsStore(tmp_path)
        installer = PackageInstaller()
        namespace = DepsNamespace(store=store, installer=installer)

        dangerous_inputs = [
            "pandas; rm -rf /",
            "numpy && cat /etc/passwd",
            "$(whoami)",
            "`id`",
            "requests|cat /etc/shadow",
        ]

        for dangerous in dangerous_inputs:
            with pytest.raises(ValueError, match="[Ii]nvalid"):
                namespace.add(dangerous)

    def test_remove_nonexistent_returns_false(self, tmp_path: Path) -> None:
        """remove() returns False for nonexistent package.

        Breaks when: Returns True or raises for missing package.
        """
        from py_code_mode.deps import DepsNamespace, FileDepsStore, PackageInstaller

        store = FileDepsStore(tmp_path)
        installer = PackageInstaller()
        namespace = DepsNamespace(store=store, installer=installer)

        result = namespace.remove("nonexistent")
        assert result is False

    def test_add_handles_installation_failure_gracefully(self, tmp_path: Path) -> None:
        """add() handles installation failure, package still in list.

        Breaks when: Installation failure removes package from config.
        """
        from py_code_mode.deps import DepsNamespace, FileDepsStore, PackageInstaller

        store = FileDepsStore(tmp_path)
        installer = PackageInstaller()
        namespace = DepsNamespace(store=store, installer=installer)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="ERROR")

            result = namespace.add("nonexistent-package-xyz")

            # Package should still be in config even if install failed
            assert "nonexistent-package-xyz" in namespace.list()

            # SyncResult should indicate failure
            assert "nonexistent-package-xyz" in result.failed

    def test_sync_on_empty_deps_returns_valid_result(self, tmp_path: Path) -> None:
        """sync() with no deps returns valid empty result.

        Breaks when: Empty deps causes exception.
        """
        from py_code_mode.deps import (
            DepsNamespace,
            FileDepsStore,
            PackageInstaller,
            SyncResult,
        )

        store = FileDepsStore(tmp_path)
        installer = PackageInstaller()
        namespace = DepsNamespace(store=store, installer=installer)

        result = namespace.sync()

        assert isinstance(result, SyncResult)
        assert result.installed == set()
        assert result.already_present == set()
        assert result.failed == set()


# =============================================================================
# Namespace Creation Tests
# =============================================================================


class TestDepsNamespaceCreation:
    """Tests for DepsNamespace construction."""

    def test_namespace_requires_store(self) -> None:
        """DepsNamespace requires a store parameter.

        Breaks when: store is optional or auto-created.
        """
        from py_code_mode.deps import DepsNamespace

        with pytest.raises(TypeError):
            DepsNamespace()  # Missing required args

    def test_namespace_requires_installer(self, tmp_path: Path) -> None:
        """DepsNamespace requires an installer parameter.

        Breaks when: installer is optional or auto-created.
        """
        from py_code_mode.deps import DepsNamespace, FileDepsStore

        store = FileDepsStore(tmp_path)

        with pytest.raises(TypeError):
            DepsNamespace(store=store)  # Missing installer

    def test_namespace_accepts_file_store(self, tmp_path: Path) -> None:
        """DepsNamespace works with FileDepsStore.

        Breaks when: File store is not compatible.
        """
        from py_code_mode.deps import DepsNamespace, FileDepsStore, PackageInstaller

        store = FileDepsStore(tmp_path)
        installer = PackageInstaller()

        namespace = DepsNamespace(store=store, installer=installer)
        assert namespace is not None

    def test_namespace_accepts_redis_store(self) -> None:
        """DepsNamespace works with RedisDepsStore.

        Breaks when: Redis store is not compatible.
        """
        from py_code_mode.deps import DepsNamespace, PackageInstaller, RedisDepsStore
        from tests.conftest import MockRedisClient

        mock_redis = MockRedisClient()
        store = RedisDepsStore(mock_redis, prefix="test")
        installer = PackageInstaller()

        namespace = DepsNamespace(store=store, installer=installer)
        assert namespace is not None


# =============================================================================
# Session Integration Tests
# =============================================================================


class TestDepsNamespaceSessionIntegration:
    """Tests for DepsNamespace integration with Session run_code()."""

    @pytest.mark.asyncio
    async def test_deps_namespace_exposed_in_run_code(self, tmp_path: Path) -> None:
        """deps.* is available in run_code execution context.

        Breaks when: deps namespace is not injected into run_code.
        """
        from py_code_mode import FileStorage, Session

        storage = FileStorage(tmp_path)

        async with Session(storage=storage) as session:
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)

                # Agent code can access deps.*
                result = await session.run("deps.list()")

                assert result.is_ok
                assert isinstance(result.value, list)

    @pytest.mark.asyncio
    async def test_deps_add_available_in_run_code(self, tmp_path: Path) -> None:
        """deps.add() is callable from run_code.

        Breaks when: deps.add is not available or not callable.
        """
        from py_code_mode import FileStorage, Session

        storage = FileStorage(tmp_path)

        async with Session(storage=storage) as session:
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)

                # Agent adds a package via code
                result = await session.run('deps.add("pandas")')

                assert result.is_ok

    @pytest.mark.asyncio
    async def test_deps_sync_available_in_run_code(self, tmp_path: Path) -> None:
        """deps.sync() is callable from run_code.

        Breaks when: deps.sync is not available or not callable.
        """
        from py_code_mode import FileStorage, Session

        storage = FileStorage(tmp_path)

        async with Session(storage=storage) as session:
            result = await session.run("deps.sync()")

            assert result.is_ok


# =============================================================================
# Repr/String Tests
# =============================================================================


class TestDepsNamespaceRepr:
    """Tests for namespace string representation (for agent discoverability)."""

    def test_namespace_has_repr(self, tmp_path: Path) -> None:
        """DepsNamespace has useful __repr__.

        Breaks when: repr is unhelpful or missing.
        """
        from py_code_mode.deps import DepsNamespace, FileDepsStore, PackageInstaller

        store = FileDepsStore(tmp_path)
        installer = PackageInstaller()
        namespace = DepsNamespace(store=store, installer=installer)

        repr_str = repr(namespace)

        # Should mention what it is
        assert "Deps" in repr_str or "deps" in repr_str

    def test_namespace_dir_lists_methods(self, tmp_path: Path) -> None:
        """dir(namespace) lists available methods.

        Breaks when: Agent can't discover methods via dir().
        """
        from py_code_mode.deps import DepsNamespace, FileDepsStore, PackageInstaller

        store = FileDepsStore(tmp_path)
        installer = PackageInstaller()
        namespace = DepsNamespace(store=store, installer=installer)

        methods = dir(namespace)

        assert "add" in methods
        assert "list" in methods
        assert "remove" in methods
        assert "sync" in methods
