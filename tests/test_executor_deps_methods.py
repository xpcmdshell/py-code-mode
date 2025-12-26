"""Tests for Executor.install_deps() and uninstall_deps() methods.

These tests verify the new install_deps/uninstall_deps methods added to the
Executor protocol and their implementations in InProcessExecutor and
SubprocessExecutor.

The design:
- install_deps(packages) installs packages into the executor's OWN environment
- uninstall_deps(packages) removes packages from the executor's OWN environment
- These are SYSTEM-LEVEL APIs that do NOT check allow_runtime_deps
- Agent-initiated installs (deps.add() via run code) are blocked at the namespace level
- Return dicts with installed/already_present/failed or removed/not_found/failed keys

Test hierarchy:
1. Contract Tests - verify method signatures and return types
2. Integration Tests - verify actual package installation/removal
3. System API Tests - verify install/uninstall work regardless of allow_runtime_deps
4. VenvManager Tests - verify the underlying remove_package method
"""

from __future__ import annotations

from pathlib import Path

import pytest

from py_code_mode.execution.protocol import Capability

# =============================================================================
# InProcessExecutor install_deps() Contract Tests
# =============================================================================


class TestInProcessExecutorInstallDepsContract:
    """Contract tests for InProcessExecutor.install_deps()."""

    def test_executor_has_install_deps_method(self) -> None:
        """InProcessExecutor has install_deps() method.

        Contract: Executor protocol requires install_deps(packages) method.
        Breaks when: Method not implemented.
        """
        from py_code_mode.execution.in_process import InProcessExecutor

        executor = InProcessExecutor()
        assert hasattr(executor, "install_deps")
        assert callable(executor.install_deps)

    def test_executor_has_uninstall_deps_method(self) -> None:
        """InProcessExecutor has uninstall_deps() method.

        Contract: Executor protocol requires uninstall_deps(packages) method.
        Breaks when: Method not implemented.
        """
        from py_code_mode.execution.in_process import InProcessExecutor

        executor = InProcessExecutor()
        assert hasattr(executor, "uninstall_deps")
        assert callable(executor.uninstall_deps)

    def test_executor_supports_deps_install_capability(self) -> None:
        """InProcessExecutor reports DEPS_INSTALL capability.

        Contract: supports(Capability.DEPS_INSTALL) returns True.
        Breaks when: Capability not added to _CAPABILITIES.
        """
        from py_code_mode.execution.in_process import InProcessExecutor

        executor = InProcessExecutor()
        assert executor.supports(Capability.DEPS_INSTALL)

    def test_executor_supports_deps_uninstall_capability(self) -> None:
        """InProcessExecutor reports DEPS_UNINSTALL capability.

        Contract: supports(Capability.DEPS_UNINSTALL) returns True.
        Breaks when: Capability not added to _CAPABILITIES.
        """
        from py_code_mode.execution.in_process import InProcessExecutor

        executor = InProcessExecutor()
        assert executor.supports(Capability.DEPS_UNINSTALL)

    @pytest.mark.asyncio
    async def test_install_deps_returns_dict(self, tmp_path: Path) -> None:
        """install_deps() returns dict with expected keys.

        Contract: Return dict has installed, already_present, failed lists.
        Breaks when: Return type changes or keys missing.
        """
        from py_code_mode.execution.in_process import InProcessExecutor
        from py_code_mode.storage import FileStorage

        storage = FileStorage(tmp_path)
        executor = InProcessExecutor()
        await executor.start(storage=storage)

        try:
            result = await executor.install_deps([])
            assert isinstance(result, dict)
            assert "installed" in result
            assert "already_present" in result
            assert "failed" in result
            assert isinstance(result["installed"], list)
            assert isinstance(result["already_present"], list)
            assert isinstance(result["failed"], list)
        finally:
            await executor.close()

    @pytest.mark.asyncio
    async def test_uninstall_deps_returns_dict(self, tmp_path: Path) -> None:
        """uninstall_deps() returns dict with expected keys.

        Contract: Return dict has removed, not_found, failed lists.
        Breaks when: Return type changes or keys missing.
        """
        from py_code_mode.execution.in_process import InProcessExecutor
        from py_code_mode.storage import FileStorage

        storage = FileStorage(tmp_path)
        executor = InProcessExecutor()
        await executor.start(storage=storage)

        try:
            result = await executor.uninstall_deps([])
            assert isinstance(result, dict)
            assert "removed" in result
            assert "not_found" in result
            assert "failed" in result
            assert isinstance(result["removed"], list)
            assert isinstance(result["not_found"], list)
            assert isinstance(result["failed"], list)
        finally:
            await executor.close()


# =============================================================================
# InProcessExecutor install_deps() Blocking Tests
# =============================================================================


class TestInProcessExecutorInstallDepsBlocking:
    """Tests for install_deps/uninstall_deps behavior when runtime deps disabled.

    NOTE: executor.install_deps() and executor.uninstall_deps() are SYSTEM-LEVEL APIs
    that do NOT check allow_runtime_deps. They are called by Session._sync_deps() for
    sync_deps_on_start functionality. Agent-initiated installs are blocked at the
    namespace level (deps.add() via run code).
    """

    @pytest.mark.asyncio
    async def test_install_deps_works_when_disabled(self, tmp_path: Path) -> None:
        """install_deps() works even with allow_runtime_deps=False.

        This is a system-level API used by Session._sync_deps() for sync_deps_on_start.
        Agent-initiated installs are blocked at the namespace level, not here.

        User action: Session calls install_deps via sync_deps_on_start.
        Verification: Pre-configured packages are installed at startup.
        Breaks when: install_deps incorrectly checks allow_runtime_deps.
        """
        from py_code_mode.execution.in_process import InProcessConfig, InProcessExecutor
        from py_code_mode.storage import FileStorage

        config = InProcessConfig(allow_runtime_deps=False)
        executor = InProcessExecutor(config=config)
        storage = FileStorage(tmp_path)
        await executor.start(storage=storage)

        try:
            # Should succeed - this is a system-level API
            result = await executor.install_deps(["six"])
            assert isinstance(result, dict)
            assert "installed" in result
        finally:
            await executor.close()

    @pytest.mark.asyncio
    async def test_uninstall_deps_works_when_disabled(self, tmp_path: Path) -> None:
        """uninstall_deps() works even with allow_runtime_deps=False.

        This is a system-level API used by Session.remove_dep().
        Agent-initiated removals are blocked at the namespace level, not here.

        User action: Session calls uninstall_deps.
        Verification: Package removal works.
        Breaks when: uninstall_deps incorrectly checks allow_runtime_deps.
        """
        from py_code_mode.execution.in_process import InProcessConfig, InProcessExecutor
        from py_code_mode.storage import FileStorage

        config = InProcessConfig(allow_runtime_deps=False)
        executor = InProcessExecutor(config=config)
        storage = FileStorage(tmp_path)
        await executor.start(storage=storage)

        try:
            # Should succeed - this is a system-level API
            result = await executor.uninstall_deps(["nonexistent-pkg"])
            assert isinstance(result, dict)
            assert "removed" in result
        finally:
            await executor.close()

    @pytest.mark.asyncio
    async def test_install_deps_requires_deps_namespace(self) -> None:
        """install_deps() raises RuntimeError when deps namespace not initialized.

        User action: Call install_deps without storage/deps namespace.
        Verification: RuntimeError raised with clear message.
        Breaks when: Method doesn't validate deps namespace presence.
        """
        from py_code_mode.execution.in_process import InProcessExecutor

        executor = InProcessExecutor()
        # Don't call start() - deps namespace will be None

        with pytest.raises(RuntimeError, match="Deps namespace not initialized"):
            await executor.install_deps(["six"])


# =============================================================================
# InProcessExecutor install_deps() Integration Tests
# =============================================================================


class TestInProcessExecutorInstallDepsIntegration:
    """Integration tests for InProcessExecutor.install_deps()."""

    @pytest.mark.asyncio
    async def test_install_deps_calls_deps_namespace_add(self, tmp_path: Path) -> None:
        """install_deps() uses deps namespace to add packages.

        User action: Call install_deps with package list.
        Verification: Package appears in installed list.
        Breaks when: deps namespace not used correctly.
        """
        from py_code_mode.execution.in_process import InProcessExecutor
        from py_code_mode.storage import FileStorage

        storage = FileStorage(tmp_path)
        executor = InProcessExecutor()
        await executor.start(storage=storage)

        try:
            result = await executor.install_deps(["six"])
            # Should succeed (six is a common, fast-to-install package)
            assert "six" in result["installed"] or "six" in result["already_present"]
            assert "six" not in result["failed"]
        finally:
            await executor.close()

    @pytest.mark.asyncio
    async def test_install_deps_with_invalid_package_spec(self, tmp_path: Path) -> None:
        """install_deps() handles invalid package specs.

        User action: Try to install package with invalid characters.
        Verification: Package in failed list (due to validation error).
        Breaks when: Validation not enforced.

        Note: DepsNamespace.add() validates package specs via the store.
        Invalid specs (e.g., with shell metacharacters) raise ValueError.
        """
        from py_code_mode.execution.in_process import InProcessExecutor
        from py_code_mode.storage import FileStorage

        storage = FileStorage(tmp_path)
        executor = InProcessExecutor()
        await executor.start(storage=storage)

        try:
            # Use an invalid package spec that will fail validation
            result = await executor.install_deps(["package; rm -rf /"])
            assert "package; rm -rf /" in result["failed"]
        finally:
            await executor.close()


# =============================================================================
# Session Facade install_deps/uninstall_deps Tests
# =============================================================================


class TestSessionFacadeDepsMethodsContract:
    """Contract tests for Session.add_dep() and remove_dep() facade methods."""

    @pytest.mark.asyncio
    async def test_add_dep_returns_install_result(self, tmp_path: Path) -> None:
        """add_dep() returns result dict from executor.install_deps().

        Contract: Returns dict with installed, already_present, failed keys.
        Breaks when: Return type changes.
        """
        from py_code_mode.session import Session
        from py_code_mode.storage import FileStorage

        storage = FileStorage(tmp_path)

        async with Session(storage=storage) as session:
            result = await session.add_dep("six")
            assert isinstance(result, dict)
            assert "installed" in result
            assert "already_present" in result
            assert "failed" in result

    @pytest.mark.asyncio
    async def test_remove_dep_returns_uninstall_result(self, tmp_path: Path) -> None:
        """remove_dep() returns result dict with uninstall info.

        Contract: Returns dict with removed, not_found, failed, removed_from_config keys.
        Breaks when: Return type changes.
        """
        from py_code_mode.session import Session
        from py_code_mode.storage import FileStorage

        storage = FileStorage(tmp_path)
        # Pre-add a package to the store so there's something to remove
        storage.get_deps_store().add("six")

        async with Session(storage=storage) as session:
            result = await session.remove_dep("six")
            assert isinstance(result, dict)
            assert "removed" in result
            assert "not_found" in result
            assert "failed" in result
            assert "removed_from_config" in result

    @pytest.mark.asyncio
    async def test_sync_deps_returns_install_result(self, tmp_path: Path) -> None:
        """sync_deps() returns result dict from executor.install_deps().

        Contract: Returns dict with installed, already_present, failed keys.
        Breaks when: Return type changes.
        """
        from py_code_mode.session import Session
        from py_code_mode.storage import FileStorage

        storage = FileStorage(tmp_path)

        async with Session(storage=storage) as session:
            result = await session.sync_deps()
            assert isinstance(result, dict)
            assert "installed" in result
            assert "already_present" in result
            assert "failed" in result


class TestSessionFacadeDepsPersistence:
    """Tests for Session facade persisting deps to storage."""

    @pytest.mark.asyncio
    async def test_add_dep_persists_to_storage(self, tmp_path: Path) -> None:
        """add_dep() persists package to storage before installing.

        User action: Add dep via session.
        Verification: Package appears in storage.get_deps_store().list().
        Breaks when: Package not persisted to storage.
        """
        from py_code_mode.session import Session
        from py_code_mode.storage import FileStorage

        storage = FileStorage(tmp_path)

        async with Session(storage=storage) as session:
            await session.add_dep("six")

        # After session closed, check storage directly
        deps = storage.get_deps_store().list()
        assert "six" in deps

    @pytest.mark.asyncio
    async def test_remove_dep_removes_from_storage(self, tmp_path: Path) -> None:
        """remove_dep() removes package from storage.

        User action: Add then remove dep via session.
        Verification: Package no longer in storage.get_deps_store().list().
        Breaks when: Package not removed from storage.
        """
        from py_code_mode.session import Session
        from py_code_mode.storage import FileStorage

        storage = FileStorage(tmp_path)
        storage.get_deps_store().add("six")

        async with Session(storage=storage) as session:
            result = await session.remove_dep("six")
            assert result["removed_from_config"] is True

        # After session closed, check storage directly
        deps = storage.get_deps_store().list()
        assert "six" not in deps


class TestSessionFacadeDepsErrorHandling:
    """Tests for Session facade error handling."""

    @pytest.mark.asyncio
    async def test_add_dep_raises_when_not_started(self, tmp_path: Path) -> None:
        """add_dep() raises RuntimeError when session not started.

        Breaks when: Method doesn't check for started state.
        """
        from py_code_mode.session import Session
        from py_code_mode.storage import FileStorage

        storage = FileStorage(tmp_path)
        session = Session(storage=storage)
        # Don't call start()

        with pytest.raises(RuntimeError, match="Session not started"):
            await session.add_dep("six")

    @pytest.mark.asyncio
    async def test_remove_dep_raises_when_not_started(self, tmp_path: Path) -> None:
        """remove_dep() raises RuntimeError when session not started.

        Breaks when: Method doesn't check for started state.
        """
        from py_code_mode.session import Session
        from py_code_mode.storage import FileStorage

        storage = FileStorage(tmp_path)
        session = Session(storage=storage)
        # Don't call start()

        with pytest.raises(RuntimeError, match="Session not started"):
            await session.remove_dep("six")

    @pytest.mark.asyncio
    async def test_sync_deps_raises_when_not_started(self, tmp_path: Path) -> None:
        """sync_deps() raises RuntimeError when session not started.

        Breaks when: Method doesn't check for started state.
        """
        from py_code_mode.session import Session
        from py_code_mode.storage import FileStorage

        storage = FileStorage(tmp_path)
        storage.get_deps_store().add("six")
        session = Session(storage=storage)
        # Don't call start()

        with pytest.raises(RuntimeError, match="Session not started"):
            await session.sync_deps()


# =============================================================================
# VenvManager.remove_package() Tests
# =============================================================================


@pytest.mark.slow
@pytest.mark.xdist_group("venv")
class TestVenvManagerRemovePackage:
    """Tests for VenvManager.remove_package() method.

    These tests actually run uv to uninstall packages. They are slow and
    should not run in parallel.
    """

    @pytest.mark.asyncio
    async def test_remove_package_exists(self) -> None:
        """VenvManager has remove_package() method.

        Contract: VenvManager.remove_package(venv, package) exists.
        Breaks when: Method not implemented.
        """
        from py_code_mode.execution.subprocess.config import SubprocessConfig
        from py_code_mode.execution.subprocess.venv import VenvManager

        config = SubprocessConfig(python_version="3.12")
        manager = VenvManager(config)

        assert hasattr(manager, "remove_package")
        assert callable(manager.remove_package)

    @pytest.mark.asyncio
    async def test_remove_package_uninstalls_from_venv(self, tmp_path: Path) -> None:
        """remove_package() uninstalls package from venv.

        User action: Install then remove a package.
        Verification: Package no longer importable.
        Breaks when: Package not actually removed.
        """
        import subprocess

        from py_code_mode.execution.subprocess.config import SubprocessConfig
        from py_code_mode.execution.subprocess.venv import VenvManager

        venv_path = tmp_path / "venv-remove-test"
        config = SubprocessConfig(
            python_version="3.12",
            venv_path=venv_path,
            base_deps=("ipykernel",),
        )
        manager = VenvManager(config)
        venv = await manager.create()

        try:
            # Install a package
            await manager.add_package(venv, "six")

            # Verify it's installed
            check = subprocess.run(
                [str(venv.python_path), "-c", "import six; print('ok')"],
                capture_output=True,
                text=True,
            )
            assert check.returncode == 0

            # Remove it
            await manager.remove_package(venv, "six")

            # Verify it's gone
            check = subprocess.run(
                [str(venv.python_path), "-c", "import six"],
                capture_output=True,
                text=True,
            )
            assert check.returncode != 0  # Should fail - not installed
        finally:
            await manager.cleanup(venv)

    @pytest.mark.asyncio
    async def test_remove_package_validates_package_spec(self, tmp_path: Path) -> None:
        """remove_package() validates package name for security.

        User action: Try to remove with malicious package name.
        Verification: ValueError raised.
        Breaks when: Validation missing.
        """
        from py_code_mode.execution.subprocess.config import SubprocessConfig
        from py_code_mode.execution.subprocess.venv import VenvManager

        venv_path = tmp_path / "venv-validate-test"
        config = SubprocessConfig(
            python_version="3.12",
            venv_path=venv_path,
            base_deps=("ipykernel",),
        )
        manager = VenvManager(config)
        venv = await manager.create()

        try:
            with pytest.raises(ValueError, match="starts with -"):
                await manager.remove_package(venv, "-e /malicious/path")
        finally:
            await manager.cleanup(venv)


# =============================================================================
# SubprocessExecutor install_deps()/uninstall_deps() Contract Tests
# =============================================================================


@pytest.mark.slow
@pytest.mark.xdist_group("subprocess")
class TestSubprocessExecutorDepsMethodsContract:
    """Contract tests for SubprocessExecutor.install_deps() and uninstall_deps()."""

    def test_executor_has_install_deps_method(self) -> None:
        """SubprocessExecutor has install_deps() method.

        Contract: Executor protocol requires install_deps(packages) method.
        Breaks when: Method not implemented.
        """
        from py_code_mode.execution.subprocess import SubprocessExecutor

        executor = SubprocessExecutor()
        assert hasattr(executor, "install_deps")
        assert callable(executor.install_deps)

    def test_executor_has_uninstall_deps_method(self) -> None:
        """SubprocessExecutor has uninstall_deps() method.

        Contract: Executor protocol requires uninstall_deps(packages) method.
        Breaks when: Method not implemented.
        """
        from py_code_mode.execution.subprocess import SubprocessExecutor

        executor = SubprocessExecutor()
        assert hasattr(executor, "uninstall_deps")
        assert callable(executor.uninstall_deps)

    @pytest.mark.asyncio
    async def test_install_deps_returns_dict(self, tmp_path: Path) -> None:
        """install_deps() returns dict with expected keys.

        Contract: Return dict has installed, already_present, failed lists.
        Breaks when: Return type changes or keys missing.
        """
        from py_code_mode.execution.subprocess import SubprocessExecutor
        from py_code_mode.execution.subprocess.config import SubprocessConfig
        from py_code_mode.storage import FileStorage

        config = SubprocessConfig(
            python_version="3.12",
            venv_path=tmp_path / "venv",
            base_deps=("ipykernel", "py-code-mode"),
        )
        executor = SubprocessExecutor(config=config)
        storage = FileStorage(tmp_path)
        await executor.start(storage=storage)

        try:
            result = await executor.install_deps([])
            assert isinstance(result, dict)
            assert "installed" in result
            assert "already_present" in result
            assert "failed" in result
        finally:
            await executor.close()

    @pytest.mark.asyncio
    async def test_uninstall_deps_returns_dict(self, tmp_path: Path) -> None:
        """uninstall_deps() returns dict with expected keys.

        Contract: Return dict has removed, not_found, failed lists.
        Breaks when: Return type changes or keys missing.
        """
        from py_code_mode.execution.subprocess import SubprocessExecutor
        from py_code_mode.execution.subprocess.config import SubprocessConfig
        from py_code_mode.storage import FileStorage

        config = SubprocessConfig(
            python_version="3.12",
            venv_path=tmp_path / "venv",
            base_deps=("ipykernel", "py-code-mode"),
        )
        executor = SubprocessExecutor(config=config)
        storage = FileStorage(tmp_path)
        await executor.start(storage=storage)

        try:
            result = await executor.uninstall_deps([])
            assert isinstance(result, dict)
            assert "removed" in result
            assert "not_found" in result
            assert "failed" in result
        finally:
            await executor.close()


@pytest.mark.slow
@pytest.mark.xdist_group("subprocess")
class TestSubprocessExecutorDepsMethodsBlocking:
    """Tests for install_deps/uninstall_deps behavior when runtime deps disabled.

    NOTE: executor.install_deps() and executor.uninstall_deps() are SYSTEM-LEVEL APIs
    that do NOT check allow_runtime_deps. They are called by Session._sync_deps() for
    sync_deps_on_start functionality. Agent-initiated installs are blocked at the
    namespace level (deps.add() via run code).
    """

    @pytest.mark.asyncio
    async def test_install_deps_works_when_disabled(self, tmp_path: Path) -> None:
        """install_deps() works even with allow_runtime_deps=False.

        This is a system-level API used by Session._sync_deps() for sync_deps_on_start.
        Agent-initiated installs are blocked at the namespace level, not here.

        User action: Session calls install_deps via sync_deps_on_start.
        Verification: Pre-configured packages are installed at startup.
        Breaks when: install_deps incorrectly checks allow_runtime_deps.
        """
        from py_code_mode.execution.subprocess import SubprocessExecutor
        from py_code_mode.execution.subprocess.config import SubprocessConfig
        from py_code_mode.storage import FileStorage

        config = SubprocessConfig(
            python_version="3.12",
            venv_path=tmp_path / "venv",
            base_deps=("ipykernel", "py-code-mode"),
            allow_runtime_deps=False,
        )
        executor = SubprocessExecutor(config=config)
        storage = FileStorage(tmp_path)
        await executor.start(storage=storage)

        try:
            # Should succeed - this is a system-level API
            result = await executor.install_deps(["six"])
            assert isinstance(result, dict)
            assert "installed" in result
        finally:
            await executor.close()

    @pytest.mark.asyncio
    async def test_uninstall_deps_works_when_disabled(self, tmp_path: Path) -> None:
        """uninstall_deps() works even with allow_runtime_deps=False.

        This is a system-level API used by Session.remove_dep().
        Agent-initiated removals are blocked at the namespace level, not here.

        User action: Session calls uninstall_deps.
        Verification: Package removal works.
        Breaks when: uninstall_deps incorrectly checks allow_runtime_deps.
        """
        from py_code_mode.execution.subprocess import SubprocessExecutor
        from py_code_mode.execution.subprocess.config import SubprocessConfig
        from py_code_mode.storage import FileStorage

        config = SubprocessConfig(
            python_version="3.12",
            venv_path=tmp_path / "venv",
            base_deps=("ipykernel", "py-code-mode"),
            allow_runtime_deps=False,
        )
        executor = SubprocessExecutor(config=config)
        storage = FileStorage(tmp_path)
        await executor.start(storage=storage)

        try:
            # Should succeed - this is a system-level API
            result = await executor.uninstall_deps(["nonexistent-pkg"])
            assert isinstance(result, dict)
            assert "removed" in result
        finally:
            await executor.close()

    @pytest.mark.asyncio
    async def test_install_deps_requires_venv(self) -> None:
        """install_deps() raises RuntimeError when venv not initialized.

        User action: Call install_deps without starting executor.
        Verification: RuntimeError raised with clear message.
        Breaks when: Method doesn't validate venv presence.
        """
        from py_code_mode.execution.subprocess import SubprocessExecutor

        executor = SubprocessExecutor()
        # Don't call start() - venv will be None

        with pytest.raises(RuntimeError, match="Venv not initialized"):
            await executor.install_deps(["six"])

    @pytest.mark.asyncio
    async def test_uninstall_deps_requires_venv(self) -> None:
        """uninstall_deps() raises RuntimeError when venv not initialized.

        User action: Call uninstall_deps without starting executor.
        Verification: RuntimeError raised with clear message.
        Breaks when: Method doesn't validate venv presence.
        """
        from py_code_mode.execution.subprocess import SubprocessExecutor

        executor = SubprocessExecutor()
        # Don't call start() - venv will be None

        with pytest.raises(RuntimeError, match="Venv not initialized"):
            await executor.uninstall_deps(["six"])


@pytest.mark.slow
@pytest.mark.xdist_group("subprocess")
class TestSubprocessExecutorDepsMethodsIntegration:
    """Integration tests for SubprocessExecutor.install_deps() and uninstall_deps()."""

    @pytest.mark.asyncio
    async def test_install_deps_installs_package(self, tmp_path: Path) -> None:
        """install_deps() actually installs packages in venv.

        User action: Call install_deps with package.
        Verification: Package importable in subprocess.
        Breaks when: Package not actually installed.
        """
        from py_code_mode.execution.subprocess import SubprocessExecutor
        from py_code_mode.execution.subprocess.config import SubprocessConfig
        from py_code_mode.storage import FileStorage

        config = SubprocessConfig(
            python_version="3.12",
            venv_path=tmp_path / "venv",
            base_deps=("ipykernel", "py-code-mode"),
        )
        executor = SubprocessExecutor(config=config)
        storage = FileStorage(tmp_path)
        await executor.start(storage=storage)

        try:
            result = await executor.install_deps(["six"])
            assert "six" in result["installed"]

            # Verify it's importable via run()
            run_result = await executor.run("import six; six.__version__")
            assert run_result.is_ok, f"Import failed: {run_result.error}"
        finally:
            await executor.close()

    @pytest.mark.asyncio
    async def test_uninstall_deps_removes_package(self, tmp_path: Path) -> None:
        """uninstall_deps() actually removes packages from venv.

        User action: Install then uninstall package.
        Verification: Package reported as removed.
        Breaks when: Package not actually uninstalled.

        Note: We use 'colorama' instead of 'six' because six is a transitive
        dependency of jupyter_client (via dateutil). Uninstalling six would
        break the kernel itself.

        We verify the uninstall result rather than checking import because
        Python's sys.modules caches already-imported modules. The package IS
        removed from disk, but still in memory until restart.
        """
        from py_code_mode.execution.subprocess import SubprocessExecutor
        from py_code_mode.execution.subprocess.config import SubprocessConfig
        from py_code_mode.storage import FileStorage

        config = SubprocessConfig(
            python_version="3.12",
            venv_path=tmp_path / "venv",
            base_deps=("ipykernel", "py-code-mode"),
        )
        executor = SubprocessExecutor(config=config)
        storage = FileStorage(tmp_path)
        await executor.start(storage=storage)

        try:
            # Install first (use colorama - standalone package, no kernel deps)
            await executor.install_deps(["colorama"])

            # Verify installed
            run_result = await executor.run("import colorama; 'ok'")
            assert run_result.is_ok

            # Now uninstall
            result = await executor.uninstall_deps(["colorama"])
            assert "colorama" in result["removed"]

            # After kernel reset, the uninstalled package should not be importable
            await executor.reset()

            # Now verify it's no longer importable
            run_result = await executor.run("import colorama")
            assert not run_result.is_ok
            assert "ModuleNotFoundError" in run_result.error
        finally:
            await executor.close()

    @pytest.mark.asyncio
    async def test_install_deps_handles_invalid_package_spec(self, tmp_path: Path) -> None:
        """install_deps() handles invalid package specs.

        User action: Try to install package with invalid characters.
        Verification: Package in failed list (due to validation error).
        Breaks when: Validation not enforced.

        Note: VenvManager.add_package() validates package specs.
        Invalid specs (e.g., starting with -) raise ValueError.
        """
        from py_code_mode.execution.subprocess import SubprocessExecutor
        from py_code_mode.execution.subprocess.config import SubprocessConfig
        from py_code_mode.storage import FileStorage

        config = SubprocessConfig(
            python_version="3.12",
            venv_path=tmp_path / "venv",
            base_deps=("ipykernel", "py-code-mode"),
        )
        executor = SubprocessExecutor(config=config)
        storage = FileStorage(tmp_path)
        await executor.start(storage=storage)

        try:
            # Use an invalid package spec that will fail validation
            result = await executor.install_deps(["-e /malicious/path"])
            assert "-e /malicious/path" in result["failed"]
        finally:
            await executor.close()


# =============================================================================
# Capability Constants Tests
# =============================================================================


class TestDepsCapabilityConstants:
    """Tests for DEPS_INSTALL and DEPS_UNINSTALL capability constants."""

    def test_deps_install_capability_exists(self) -> None:
        """DEPS_INSTALL capability constant exists.

        Contract: Capability.DEPS_INSTALL is defined.
        Breaks when: Constant not added to Capability class.
        """
        assert hasattr(Capability, "DEPS_INSTALL")
        assert Capability.DEPS_INSTALL == "deps_install"

    def test_deps_uninstall_capability_exists(self) -> None:
        """DEPS_UNINSTALL capability constant exists.

        Contract: Capability.DEPS_UNINSTALL is defined.
        Breaks when: Constant not added to Capability class.
        """
        assert hasattr(Capability, "DEPS_UNINSTALL")
        assert Capability.DEPS_UNINSTALL == "deps_uninstall"

    def test_deps_capabilities_in_all_set(self) -> None:
        """DEPS_INSTALL and DEPS_UNINSTALL in Capability.all() set.

        Contract: All capabilities returned by Capability.all().
        Breaks when: New capabilities not added to all() method.
        """
        all_caps = Capability.all()
        assert Capability.DEPS_INSTALL in all_caps
        assert Capability.DEPS_UNINSTALL in all_caps


# =============================================================================
# Session + Executor Integration Tests
# =============================================================================


class TestSessionExecutorDepsIntegration:
    """Integration tests for Session delegating to Executor for deps operations."""

    @pytest.mark.asyncio
    async def test_session_add_dep_calls_executor_install_deps(self, tmp_path: Path) -> None:
        """Session.add_dep() calls executor.install_deps().

        User action: Add dep via session.
        Verification: Executor's install_deps called with package.
        Breaks when: Session doesn't delegate to executor.
        """
        from unittest.mock import AsyncMock, patch

        from py_code_mode.execution.in_process import InProcessExecutor
        from py_code_mode.session import Session
        from py_code_mode.storage import FileStorage

        storage = FileStorage(tmp_path)
        executor = InProcessExecutor()

        async with Session(storage=storage, executor=executor) as session:
            with patch.object(executor, "install_deps", new_callable=AsyncMock) as mock_install:
                mock_install.return_value = {
                    "installed": ["six"],
                    "already_present": [],
                    "failed": [],
                }
                await session.add_dep("six")
                mock_install.assert_called_once_with(["six"])

    @pytest.mark.asyncio
    async def test_session_remove_dep_calls_executor_uninstall_deps(self, tmp_path: Path) -> None:
        """Session.remove_dep() calls executor.uninstall_deps().

        User action: Remove dep via session.
        Verification: Executor's uninstall_deps called with package.
        Breaks when: Session doesn't delegate to executor.
        """
        from unittest.mock import AsyncMock, patch

        from py_code_mode.execution.in_process import InProcessExecutor
        from py_code_mode.session import Session
        from py_code_mode.storage import FileStorage

        storage = FileStorage(tmp_path)
        storage.get_deps_store().add("six")
        executor = InProcessExecutor()

        async with Session(storage=storage, executor=executor) as session:
            with patch.object(executor, "uninstall_deps", new_callable=AsyncMock) as mock_uninstall:
                mock_uninstall.return_value = {"removed": ["six"], "not_found": [], "failed": []}
                await session.remove_dep("six")
                mock_uninstall.assert_called_once_with(["six"])

    @pytest.mark.asyncio
    async def test_session_sync_deps_calls_executor_install_deps(self, tmp_path: Path) -> None:
        """Session.sync_deps() calls executor.install_deps() with all configured deps.

        User action: Pre-configure deps, call sync_deps.
        Verification: Executor's install_deps called with all packages.
        Breaks when: Session doesn't collect all deps from storage.
        """
        from unittest.mock import AsyncMock, patch

        from py_code_mode.execution.in_process import InProcessExecutor
        from py_code_mode.session import Session
        from py_code_mode.storage import FileStorage

        storage = FileStorage(tmp_path)
        storage.get_deps_store().add("six")
        storage.get_deps_store().add("colorama")
        executor = InProcessExecutor()

        async with Session(storage=storage, executor=executor) as session:
            with patch.object(executor, "install_deps", new_callable=AsyncMock) as mock_install:
                mock_install.return_value = {
                    "installed": ["six", "colorama"],
                    "already_present": [],
                    "failed": [],
                }
                await session.sync_deps()
                # Should be called with all configured deps
                call_args = mock_install.call_args[0][0]
                assert "six" in call_args
                assert "colorama" in call_args


# =============================================================================
# Sync Deps on Start Integration Tests
# =============================================================================


class TestSyncDepsOnStartIntegration:
    """Integration tests for sync_deps_on_start using executor.install_deps()."""

    @pytest.mark.asyncio
    async def test_sync_deps_on_start_calls_executor_install_deps(self, tmp_path: Path) -> None:
        """sync_deps_on_start=True calls executor.install_deps() during start.

        User action: Pre-configure deps, create session with sync_deps_on_start=True.
        Verification: Executor's install_deps called with configured deps.
        Breaks when: _sync_deps doesn't call executor.install_deps.
        """
        from unittest.mock import AsyncMock, patch

        from py_code_mode.execution.in_process import InProcessExecutor
        from py_code_mode.session import Session
        from py_code_mode.storage import FileStorage

        storage = FileStorage(tmp_path)
        storage.get_deps_store().add("six")

        executor = InProcessExecutor()

        session = Session(storage=storage, executor=executor, sync_deps_on_start=True)

        with patch.object(executor, "install_deps", new_callable=AsyncMock) as mock_install:
            mock_install.return_value = {"installed": ["six"], "already_present": [], "failed": []}
            await session.start()
            mock_install.assert_called_once()
            call_args = mock_install.call_args[0][0]
            assert "six" in call_args

        await session.close()
