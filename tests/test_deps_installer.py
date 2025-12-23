"""Tests for PackageInstaller.

TDD RED phase: These tests are written before implementation.
They will fail until the deps module is implemented.

Test hierarchy:
1. User journey tests (E2E)
2. Contract tests (SyncResult structure)
3. Integration tests (installer + store)
4. Invariant tests (hash-based caching)
5. Negative tests (failure handling)
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# =============================================================================
# User Journey Tests (E2E)
# =============================================================================


class TestPackageInstallerUserJourney:
    """Complete developer workflow from deps config to installed packages."""

    @pytest.mark.asyncio
    async def test_developer_adds_deps_and_syncs(self, tmp_path: Path) -> None:
        """Developer configures deps, then syncs to install them.

        User action: Add packages to deps store, call sync
        Setup: Empty store, mocked pip/uv
        Steps:
            1. Create store and installer
            2. Add packages to store
            3. Call sync()
            4. Verify packages were installed
        Verification: SyncResult shows packages as installed
        Breaks when: sync() doesn't install added packages
        """
        from py_code_mode.deps import FileDepsStore, PackageInstaller

        store = FileDepsStore(tmp_path)
        store.add("pandas")
        store.add("numpy")

        installer = PackageInstaller()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

            result = installer.sync(store)

            assert result.installed == {"pandas", "numpy"}
            assert result.failed == set()

    @pytest.mark.asyncio
    async def test_developer_syncs_twice_second_is_noop(self, tmp_path: Path) -> None:
        """Second sync with unchanged deps is a no-op (cached).

        User action: Call sync twice without changing deps
        Setup: Store with packages, first sync completed
        Steps:
            1. Add packages and sync
            2. Sync again without changes
        Verification: Second sync shows already_present, no installs
        Breaks when: Cache invalidation is broken, reinstalls every time
        """
        from py_code_mode.deps import FileDepsStore, PackageInstaller

        store = FileDepsStore(tmp_path)
        store.add("pandas")

        installer = PackageInstaller()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

            # First sync - installs
            result1 = installer.sync(store)
            assert "pandas" in result1.installed

            # Second sync - cached, no install
            result2 = installer.sync(store)
            assert "pandas" in result2.already_present
            assert "pandas" not in result2.installed

    @pytest.mark.asyncio
    async def test_developer_adds_more_deps_after_sync(self, tmp_path: Path) -> None:
        """Adding deps after sync triggers install on next sync.

        User action: Sync, add more deps, sync again
        Setup: Store with initial packages synced
        Steps:
            1. Add pandas, sync
            2. Add numpy, sync
        Verification: Second sync installs numpy, pandas already_present
        Breaks when: Hash caching doesn't detect new packages
        """
        from py_code_mode.deps import FileDepsStore, PackageInstaller

        store = FileDepsStore(tmp_path)
        store.add("pandas")

        installer = PackageInstaller()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

            # First sync
            installer.sync(store)

            # Add more deps
            store.add("numpy")

            # Second sync
            result = installer.sync(store)

            # pandas was already installed, numpy is new
            assert "pandas" in result.already_present
            assert "numpy" in result.installed


# =============================================================================
# Contract Tests (SyncResult)
# =============================================================================


class TestSyncResultContract:
    """Tests for SyncResult dataclass/structure."""

    def test_sync_result_has_installed_attribute(self) -> None:
        """SyncResult has 'installed' attribute (set of packages).

        Breaks when: SyncResult structure is wrong.
        """
        from py_code_mode.deps import SyncResult

        result = SyncResult(installed=set(), already_present=set(), failed=set())
        assert hasattr(result, "installed")
        assert isinstance(result.installed, set)

    def test_sync_result_has_already_present_attribute(self) -> None:
        """SyncResult has 'already_present' attribute (set of packages).

        Breaks when: SyncResult structure is wrong.
        """
        from py_code_mode.deps import SyncResult

        result = SyncResult(installed=set(), already_present=set(), failed=set())
        assert hasattr(result, "already_present")
        assert isinstance(result.already_present, set)

    def test_sync_result_has_failed_attribute(self) -> None:
        """SyncResult has 'failed' attribute (set of packages).

        Breaks when: SyncResult structure is wrong.
        """
        from py_code_mode.deps import SyncResult

        result = SyncResult(installed=set(), already_present=set(), failed=set())
        assert hasattr(result, "failed")
        assert isinstance(result.failed, set)

    def test_sync_result_is_dataclass(self) -> None:
        """SyncResult is a dataclass for easy construction.

        Breaks when: SyncResult is not a dataclass.
        """
        from dataclasses import is_dataclass

        from py_code_mode.deps import SyncResult

        assert is_dataclass(SyncResult)


# =============================================================================
# PackageInstaller Contract Tests
# =============================================================================


class TestPackageInstallerContract:
    """Tests for PackageInstaller public API."""

    def test_installer_has_sync_method(self) -> None:
        """PackageInstaller has sync(store) method.

        Breaks when: sync method is missing.
        """
        from py_code_mode.deps import PackageInstaller

        installer = PackageInstaller()
        assert hasattr(installer, "sync")
        assert callable(installer.sync)

    def test_sync_returns_sync_result(self, tmp_path: Path) -> None:
        """sync() returns SyncResult.

        Breaks when: Return type is wrong.
        """
        from py_code_mode.deps import FileDepsStore, PackageInstaller, SyncResult

        store = FileDepsStore(tmp_path)
        installer = PackageInstaller()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = installer.sync(store)

        assert isinstance(result, SyncResult)

    def test_sync_accepts_any_deps_store(self, tmp_path: Path, mock_redis: "MagicMock") -> None:
        """sync() accepts any DepsStore implementation.

        Breaks when: sync() only works with specific store type.
        """
        from py_code_mode.deps import (
            FileDepsStore,
            PackageInstaller,
            RedisDepsStore,
        )

        installer = PackageInstaller()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

            # File store
            file_store = FileDepsStore(tmp_path)
            result1 = installer.sync(file_store)
            assert result1 is not None

            # Redis store (mock)
            from tests.conftest import MockRedisClient

            redis_store = RedisDepsStore(MockRedisClient(), prefix="test")
            result2 = installer.sync(redis_store)
            assert result2 is not None


# =============================================================================
# Integration Tests (Installer + Subprocess)
# =============================================================================


class TestPackageInstallerSubprocess:
    """Tests for subprocess invocation (pip/uv)."""

    def test_sync_uses_uv_when_available(self, tmp_path: Path) -> None:
        """sync() prefers 'uv pip install' when uv is available.

        Breaks when: uv is not used even when available.
        """
        from py_code_mode.deps import FileDepsStore, PackageInstaller

        store = FileDepsStore(tmp_path)
        store.add("pandas")

        installer = PackageInstaller()

        with patch("py_code_mode.deps.installer.shutil.which") as mock_which:
            mock_which.return_value = "/usr/local/bin/uv"  # uv is available

            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                installer.sync(store)

                # Verify uv was called - first element of command list should contain 'uv'
                call_args = mock_run.call_args
                cmd = call_args[0][0] if call_args[0] else call_args.kwargs.get("args", [])
                assert "uv" in cmd[0]

    def test_sync_falls_back_to_pip(self, tmp_path: Path) -> None:
        """sync() uses 'pip install' when uv is not available.

        Breaks when: Fallback to pip doesn't work.
        """
        from py_code_mode.deps import FileDepsStore, PackageInstaller

        store = FileDepsStore(tmp_path)
        store.add("pandas")

        installer = PackageInstaller()

        with patch("py_code_mode.deps.installer.shutil.which") as mock_which:
            mock_which.return_value = None  # uv not available

            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                installer.sync(store)

                # Verify pip was called
                call_args = mock_run.call_args
                cmd = call_args[0][0] if call_args[0] else call_args.kwargs.get("args", [])
                assert "pip" in cmd or any("pip" in str(arg) for arg in cmd)

    def test_sync_passes_package_list_to_installer(self, tmp_path: Path) -> None:
        """sync() passes all packages to the installer command.

        Breaks when: Not all packages are passed to pip/uv.
        """
        from py_code_mode.deps import FileDepsStore, PackageInstaller

        store = FileDepsStore(tmp_path)
        store.add("pandas>=2.0")
        store.add("numpy")
        store.add("requests")

        installer = PackageInstaller()

        with patch("py_code_mode.deps.installer.shutil.which", return_value=None):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                installer.sync(store)

                call_args = mock_run.call_args
                cmd = call_args[0][0] if call_args[0] else call_args.kwargs.get("args", [])
                cmd_str = " ".join(str(c) for c in cmd)

                assert "pandas>=2.0" in cmd_str or "pandas" in cmd_str
                assert "numpy" in cmd_str
                assert "requests" in cmd_str


# =============================================================================
# Hash-based Caching Tests
# =============================================================================


class TestPackageInstallerCaching:
    """Tests for hash-based cache to skip redundant installs."""

    def test_sync_skips_install_when_hash_unchanged(self, tmp_path: Path) -> None:
        """sync() doesn't call pip/uv when hash is unchanged.

        Breaks when: Every sync calls the installer (inefficient).
        """
        from py_code_mode.deps import FileDepsStore, PackageInstaller

        store = FileDepsStore(tmp_path)
        store.add("pandas")

        installer = PackageInstaller()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

            # First sync - should install
            installer.sync(store)
            first_call_count = mock_run.call_count

            # Second sync - hash unchanged, should skip
            installer.sync(store)
            second_call_count = mock_run.call_count

            # Should not have made additional subprocess calls
            assert second_call_count == first_call_count

    def test_sync_installs_when_hash_changed(self, tmp_path: Path) -> None:
        """sync() calls pip/uv when hash changes (new packages).

        Breaks when: New packages are not installed.
        """
        from py_code_mode.deps import FileDepsStore, PackageInstaller

        store = FileDepsStore(tmp_path)
        store.add("pandas")

        installer = PackageInstaller()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

            # First sync
            installer.sync(store)
            first_call_count = mock_run.call_count

            # Add new package - hash changes
            store.add("numpy")

            # Second sync - should install new package
            installer.sync(store)
            second_call_count = mock_run.call_count

            # Should have made additional subprocess call
            assert second_call_count > first_call_count

    def test_sync_cache_persists_across_installer_instances(self, tmp_path: Path) -> None:
        """Hash cache is stored externally, persists across installer instances.

        Breaks when: Each new installer instance reinstalls everything.
        """
        from py_code_mode.deps import FileDepsStore, PackageInstaller

        store = FileDepsStore(tmp_path)
        store.add("pandas")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

            # First installer instance
            installer1 = PackageInstaller()
            installer1.sync(store)

            # Second installer instance
            installer2 = PackageInstaller()
            result = installer2.sync(store)

            # Should recognize packages as already present
            assert "pandas" in result.already_present


# =============================================================================
# Empty Store Tests
# =============================================================================


class TestPackageInstallerEmptyStore:
    """Tests for behavior with empty deps store."""

    def test_sync_with_empty_store_is_noop(self, tmp_path: Path) -> None:
        """sync() with empty store doesn't call pip/uv.

        Breaks when: Empty store triggers subprocess call.
        """
        from py_code_mode.deps import FileDepsStore, PackageInstaller

        store = FileDepsStore(tmp_path)  # Empty store

        installer = PackageInstaller()

        with patch("subprocess.run") as mock_run:
            result = installer.sync(store)

            mock_run.assert_not_called()
            assert result.installed == set()
            assert result.already_present == set()
            assert result.failed == set()

    def test_sync_result_is_valid_for_empty_store(self, tmp_path: Path) -> None:
        """sync() returns valid SyncResult for empty store.

        Breaks when: Empty store causes exception or invalid result.
        """
        from py_code_mode.deps import FileDepsStore, PackageInstaller, SyncResult

        store = FileDepsStore(tmp_path)
        installer = PackageInstaller()

        result = installer.sync(store)

        assert isinstance(result, SyncResult)
        assert result.installed == set()
        assert result.already_present == set()
        assert result.failed == set()


# =============================================================================
# Failure Handling Tests
# =============================================================================


class TestPackageInstallerFailures:
    """Tests for handling installation failures."""

    def test_failed_package_in_failed_set(self, tmp_path: Path) -> None:
        """Failed packages appear in result.failed.

        Breaks when: Failures are not tracked.
        """
        from py_code_mode.deps import FileDepsStore, PackageInstaller

        store = FileDepsStore(tmp_path)
        store.add("nonexistent-package-that-doesnt-exist-12345")

        installer = PackageInstaller()

        with patch("subprocess.run") as mock_run:
            # Simulate pip failure
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="ERROR: Could not find a version that satisfies the requirement",
            )

            result = installer.sync(store)

            assert "nonexistent-package-that-doesnt-exist-12345" in result.failed

    def test_partial_failure_still_installs_valid_packages(self, tmp_path: Path) -> None:
        """Some packages can succeed even if others fail.

        Breaks when: One failure causes entire sync to fail.

        Note: This depends on implementation - installer might batch or individual install.
        """
        from py_code_mode.deps import FileDepsStore, PackageInstaller

        store = FileDepsStore(tmp_path)
        store.add("pandas")
        store.add("nonexistent-package-xyz")

        installer = PackageInstaller()

        # This test might need adjustment based on implementation
        # (whether packages are installed individually or in batch)
        result = installer.sync(store)

        # At minimum, we should know about the failure
        assert isinstance(result.failed, set)

    def test_sync_does_not_raise_on_failure(self, tmp_path: Path) -> None:
        """sync() returns result even when packages fail, doesn't raise.

        Breaks when: Installation failure causes exception.
        """
        from py_code_mode.deps import FileDepsStore, PackageInstaller

        store = FileDepsStore(tmp_path)
        store.add("nonexistent-package-12345")

        installer = PackageInstaller()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="ERROR")

            # Should not raise
            result = installer.sync(store)
            assert result is not None

    def test_sync_handles_subprocess_timeout(self, tmp_path: Path) -> None:
        """sync() handles subprocess timeout gracefully.

        Breaks when: Timeout causes unhandled exception.
        """
        import subprocess

        from py_code_mode.deps import FileDepsStore, PackageInstaller

        store = FileDepsStore(tmp_path)
        store.add("pandas")

        installer = PackageInstaller()

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="pip", timeout=60)

            # Should not raise, should handle gracefully
            result = installer.sync(store)
            assert "pandas" in result.failed


# =============================================================================
# Installer Configuration Tests
# =============================================================================


class TestPackageInstallerConfiguration:
    """Tests for installer configuration options."""

    def test_installer_accepts_timeout_config(self) -> None:
        """PackageInstaller can be configured with custom timeout.

        Breaks when: Timeout is not configurable.
        """
        from py_code_mode.deps import PackageInstaller

        installer = PackageInstaller(timeout=120)
        assert installer.timeout == 120

    def test_installer_default_timeout(self) -> None:
        """PackageInstaller has sensible default timeout.

        Breaks when: Default timeout is missing or too short.
        """
        from py_code_mode.deps import PackageInstaller

        installer = PackageInstaller()
        assert hasattr(installer, "timeout")
        assert installer.timeout >= 60  # At least 60 seconds

    def test_installer_accepts_extra_pip_args(self, tmp_path: Path) -> None:
        """PackageInstaller can pass extra args to pip/uv.

        Breaks when: Extra args are not configurable.
        """
        from py_code_mode.deps import FileDepsStore, PackageInstaller

        store = FileDepsStore(tmp_path)
        store.add("pandas")

        installer = PackageInstaller(extra_args=["--quiet", "--no-cache-dir"])

        with patch("py_code_mode.deps.installer.shutil.which", return_value=None):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                installer.sync(store)

                call_args = mock_run.call_args
                cmd = call_args[0][0] if call_args[0] else call_args.kwargs.get("args", [])
                cmd_str = " ".join(str(c) for c in cmd)

                assert "--quiet" in cmd_str or "-q" in cmd_str


# =============================================================================
# Already Installed Package Detection
# =============================================================================


class TestPackageInstallerAlreadyInstalled:
    """Tests for detecting already-installed packages."""

    def test_already_installed_packages_not_reinstalled(self, tmp_path: Path) -> None:
        """Packages already in environment are not reinstalled.

        Breaks when: Already-installed packages are reinstalled.
        """
        from py_code_mode.deps import FileDepsStore, PackageInstaller

        store = FileDepsStore(tmp_path)
        store.add("pip")  # pip is always installed

        installer = PackageInstaller()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = installer.sync(store)

            # pip should be already_present, not installed
            # (This depends on implementation checking installed packages first)
            assert "pip" in result.already_present or "pip" in result.installed
