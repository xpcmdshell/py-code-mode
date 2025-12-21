"""Tests for SubprocessExecutor, SubprocessConfig, and VenvManager."""

import shutil
import sys
from pathlib import Path

import pytest

from py_code_mode.execution.protocol import Capability
from py_code_mode.execution.subprocess.config import SubprocessConfig
from py_code_mode.execution.subprocess.venv import KernelVenv, VenvManager


class TestSubprocessConfig:
    """Tests for SubprocessConfig dataclass."""

    # =========================================================================
    # Default Values
    # =========================================================================

    def test_default_venv_path_is_none(self) -> None:
        """Default venv_path is None (auto-create in temp)."""
        config = SubprocessConfig(python_version="3.11")
        assert config.venv_path is None

    def test_default_base_deps(self) -> None:
        """Default base_deps includes ipykernel."""
        config = SubprocessConfig(python_version="3.11")
        assert config.base_deps == ("ipykernel",)

    def test_default_startup_timeout(self) -> None:
        """Default startup_timeout is 30.0 seconds."""
        config = SubprocessConfig(python_version="3.11")
        assert config.startup_timeout == 30.0

    def test_default_execution_timeout(self) -> None:
        """Default default_timeout is 60.0 seconds."""
        config = SubprocessConfig(python_version="3.11")
        assert config.default_timeout == 60.0

    def test_default_allow_runtime_deps(self) -> None:
        """Default allow_runtime_deps is True."""
        config = SubprocessConfig(python_version="3.11")
        assert config.allow_runtime_deps is True

    def test_default_cleanup_venv_on_close(self) -> None:
        """Default cleanup_venv_on_close is True."""
        config = SubprocessConfig(python_version="3.11")
        assert config.cleanup_venv_on_close is True

    # =========================================================================
    # Custom Values
    # =========================================================================

    def test_custom_venv_path(self, tmp_path: Path) -> None:
        """Can set custom venv_path."""
        venv_path = tmp_path / "my-venv"
        config = SubprocessConfig(python_version="3.11", venv_path=venv_path)
        assert config.venv_path == venv_path

    def test_custom_python_version(self) -> None:
        """Can set custom python_version."""
        config = SubprocessConfig(python_version="3.12")
        assert config.python_version == "3.12"

    def test_custom_base_deps(self) -> None:
        """Can set custom base_deps."""
        deps = ("ipykernel", "numpy", "pandas")
        config = SubprocessConfig(python_version="3.11", base_deps=deps)
        assert config.base_deps == deps

    def test_custom_startup_timeout(self) -> None:
        """Can set custom startup_timeout."""
        config = SubprocessConfig(python_version="3.11", startup_timeout=60.0)
        assert config.startup_timeout == 60.0

    def test_custom_default_timeout(self) -> None:
        """Can set custom default_timeout."""
        config = SubprocessConfig(python_version="3.11", default_timeout=120.0)
        assert config.default_timeout == 120.0

    def test_custom_allow_runtime_deps_false(self) -> None:
        """Can disable allow_runtime_deps."""
        config = SubprocessConfig(python_version="3.11", allow_runtime_deps=False)
        assert config.allow_runtime_deps is False

    def test_custom_cleanup_venv_on_close_false(self) -> None:
        """Can disable cleanup_venv_on_close."""
        config = SubprocessConfig(python_version="3.11", cleanup_venv_on_close=False)
        assert config.cleanup_venv_on_close is False

    # =========================================================================
    # Frozen Dataclass Behavior
    # =========================================================================

    def test_config_is_frozen(self) -> None:
        """Config is immutable after creation."""
        config = SubprocessConfig(python_version="3.11")

        with pytest.raises(AttributeError):
            config.python_version = "3.12"  # type: ignore[misc]

    def test_config_is_frozen_venv_path(self, tmp_path: Path) -> None:
        """Cannot modify venv_path after creation."""
        config = SubprocessConfig(python_version="3.11")

        with pytest.raises(AttributeError):
            config.venv_path = tmp_path  # type: ignore[misc]

    def test_config_is_frozen_startup_timeout(self) -> None:
        """Cannot modify startup_timeout after creation."""
        config = SubprocessConfig(python_version="3.11")

        with pytest.raises(AttributeError):
            config.startup_timeout = 999.0  # type: ignore[misc]

    # =========================================================================
    # Validation - Empty python_version
    # =========================================================================

    def test_empty_python_version_raises_value_error(self) -> None:
        """Empty python_version raises ValueError."""
        with pytest.raises(ValueError, match="python_version"):
            SubprocessConfig(python_version="")

    def test_whitespace_python_version_raises_value_error(self) -> None:
        """Whitespace-only python_version raises ValueError."""
        with pytest.raises(ValueError, match="python_version"):
            SubprocessConfig(python_version="   ")

    # =========================================================================
    # Validation - Invalid python_version format
    # =========================================================================

    def test_invalid_python_version_format_raises_value_error(self) -> None:
        """Invalid python_version format raises ValueError."""
        with pytest.raises(ValueError, match="python_version"):
            SubprocessConfig(python_version="python3.11")

    def test_python_version_with_patch_is_invalid(self) -> None:
        """python_version with patch version raises ValueError (only major.minor)."""
        with pytest.raises(ValueError, match="python_version"):
            SubprocessConfig(python_version="3.11.4")

    def test_python_version_single_digit_is_invalid(self) -> None:
        """Single digit python_version raises ValueError."""
        with pytest.raises(ValueError, match="python_version"):
            SubprocessConfig(python_version="3")

    def test_python_version_with_v_prefix_is_invalid(self) -> None:
        """python_version with 'v' prefix raises ValueError."""
        with pytest.raises(ValueError, match="python_version"):
            SubprocessConfig(python_version="v3.11")

    # =========================================================================
    # Validation - Negative timeouts
    # =========================================================================

    def test_negative_startup_timeout_raises_value_error(self) -> None:
        """Negative startup_timeout raises ValueError."""
        with pytest.raises(ValueError, match="startup_timeout"):
            SubprocessConfig(python_version="3.11", startup_timeout=-1.0)

    def test_zero_startup_timeout_raises_value_error(self) -> None:
        """Zero startup_timeout raises ValueError."""
        with pytest.raises(ValueError, match="startup_timeout"):
            SubprocessConfig(python_version="3.11", startup_timeout=0.0)

    def test_negative_default_timeout_raises_value_error(self) -> None:
        """Negative default_timeout raises ValueError."""
        with pytest.raises(ValueError, match="default_timeout"):
            SubprocessConfig(python_version="3.11", default_timeout=-1.0)

    def test_zero_default_timeout_raises_value_error(self) -> None:
        """Zero default_timeout raises ValueError."""
        with pytest.raises(ValueError, match="default_timeout"):
            SubprocessConfig(python_version="3.11", default_timeout=0.0)

    # =========================================================================
    # Valid python_version formats (positive tests)
    # =========================================================================

    def test_valid_python_version_3_11(self) -> None:
        """python_version 3.11 is valid."""
        config = SubprocessConfig(python_version="3.11")
        assert config.python_version == "3.11"

    def test_valid_python_version_3_12(self) -> None:
        """python_version 3.12 is valid."""
        config = SubprocessConfig(python_version="3.12")
        assert config.python_version == "3.12"

    def test_valid_python_version_3_10(self) -> None:
        """python_version 3.10 is valid."""
        config = SubprocessConfig(python_version="3.10")
        assert config.python_version == "3.10"


# =============================================================================
# KernelVenv Dataclass Tests
# =============================================================================


class TestKernelVenv:
    """Tests for KernelVenv dataclass structure."""

    # =========================================================================
    # Field Existence
    # =========================================================================

    def test_has_path_field(self, tmp_path: Path) -> None:
        """KernelVenv has path field."""
        venv = KernelVenv(
            path=tmp_path / "venv",
            python_path=tmp_path / "venv" / "bin" / "python",
            kernel_spec_name="test-kernel",
        )
        assert hasattr(venv, "path")
        assert venv.path == tmp_path / "venv"

    def test_has_python_path_field(self, tmp_path: Path) -> None:
        """KernelVenv has python_path field."""
        python_path = tmp_path / "venv" / "bin" / "python"
        venv = KernelVenv(
            path=tmp_path / "venv",
            python_path=python_path,
            kernel_spec_name="test-kernel",
        )
        assert hasattr(venv, "python_path")
        assert venv.python_path == python_path

    def test_has_kernel_spec_name_field(self, tmp_path: Path) -> None:
        """KernelVenv has kernel_spec_name field."""
        venv = KernelVenv(
            path=tmp_path / "venv",
            python_path=tmp_path / "venv" / "bin" / "python",
            kernel_spec_name="my-kernel-spec",
        )
        assert hasattr(venv, "kernel_spec_name")
        assert venv.kernel_spec_name == "my-kernel-spec"

    # =========================================================================
    # Type Correctness
    # =========================================================================

    def test_path_is_path_type(self, tmp_path: Path) -> None:
        """path field is Path type."""
        venv = KernelVenv(
            path=tmp_path / "venv",
            python_path=tmp_path / "venv" / "bin" / "python",
            kernel_spec_name="test-kernel",
        )
        assert isinstance(venv.path, Path)

    def test_python_path_is_path_type(self, tmp_path: Path) -> None:
        """python_path field is Path type."""
        venv = KernelVenv(
            path=tmp_path / "venv",
            python_path=tmp_path / "venv" / "bin" / "python",
            kernel_spec_name="test-kernel",
        )
        assert isinstance(venv.python_path, Path)

    def test_kernel_spec_name_is_str_type(self, tmp_path: Path) -> None:
        """kernel_spec_name field is str type."""
        venv = KernelVenv(
            path=tmp_path / "venv",
            python_path=tmp_path / "venv" / "bin" / "python",
            kernel_spec_name="test-kernel",
        )
        assert isinstance(venv.kernel_spec_name, str)


# =============================================================================
# VenvManager Initialization Tests
# =============================================================================


class TestVenvManagerInit:
    """Tests for VenvManager initialization."""

    def test_accepts_subprocess_config(self) -> None:
        """VenvManager accepts SubprocessConfig."""
        config = SubprocessConfig(python_version="3.11")
        manager = VenvManager(config)
        assert manager is not None

    def test_stores_config(self) -> None:
        """VenvManager stores the config for later use."""
        config = SubprocessConfig(python_version="3.11")
        manager = VenvManager(config)
        # Access internal config to verify it's stored
        assert manager._config is config


# =============================================================================
# VenvManager.create() Tests
# =============================================================================


@pytest.mark.slow
@pytest.mark.xdist_group("venv")
class TestVenvManagerCreate:
    """Tests for VenvManager.create() - venv creation with ipykernel.

    These tests actually run uv to create venvs. They are slow (~5-10s each)
    and should not run in parallel to avoid resource contention.
    """

    # =========================================================================
    # Venv Directory Creation
    # =========================================================================

    @pytest.mark.asyncio
    async def test_creates_venv_at_specified_path(self, tmp_path: Path) -> None:
        """Creates venv directory at config.venv_path when specified."""
        venv_path = tmp_path / "my-venv"
        config = SubprocessConfig(python_version="3.11", venv_path=venv_path)
        manager = VenvManager(config)

        result = await manager.create()

        assert result.path == venv_path
        assert result.path.exists()
        assert result.path.is_dir()

    @pytest.mark.asyncio
    async def test_creates_temp_venv_when_path_is_none(self) -> None:
        """Creates venv in temp directory when venv_path is None."""
        config = SubprocessConfig(python_version="3.11", venv_path=None)
        manager = VenvManager(config)

        result = await manager.create()

        try:
            assert result.path.exists()
            assert result.path.is_dir()
            # Temp venvs should be in system temp directory
            # macOS uses /var/folders/.../T/..., Linux uses /tmp, Windows uses %TEMP%
            import tempfile

            temp_root = tempfile.gettempdir()
            assert str(result.path).startswith(temp_root)
        finally:
            # Cleanup temp venv
            await manager.cleanup(result)

    @pytest.mark.asyncio
    async def test_venv_contains_python_executable(self, tmp_path: Path) -> None:
        """Created venv contains a working Python executable."""
        venv_path = tmp_path / "venv-with-python"
        config = SubprocessConfig(python_version="3.11", venv_path=venv_path)
        manager = VenvManager(config)

        result = await manager.create()

        assert result.python_path.exists()
        assert result.python_path.is_file()
        # Verify it's executable (on Unix) or exists (on Windows)
        if sys.platform != "win32":
            import os

            assert os.access(result.python_path, os.X_OK)

    @pytest.mark.asyncio
    async def test_uses_python_version_from_config(self, tmp_path: Path) -> None:
        """Venv uses the Python version specified in config."""
        venv_path = tmp_path / "venv-version-test"
        config = SubprocessConfig(python_version="3.11", venv_path=venv_path)
        manager = VenvManager(config)

        result = await manager.create()

        # Verify Python version by running python --version
        import subprocess

        version_output = subprocess.run(
            [str(result.python_path), "--version"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert "3.11" in version_output.stdout

    # =========================================================================
    # ipykernel Installation
    # =========================================================================

    @pytest.mark.asyncio
    async def test_installs_ipykernel_in_venv(self, tmp_path: Path) -> None:
        """ipykernel is installed in the created venv."""
        venv_path = tmp_path / "venv-ipykernel"
        config = SubprocessConfig(python_version="3.11", venv_path=venv_path)
        manager = VenvManager(config)

        result = await manager.create()

        # Verify ipykernel is importable
        import subprocess

        check = subprocess.run(
            [str(result.python_path), "-c", "import ipykernel; print('ok')"],
            capture_output=True,
            text=True,
        )
        assert check.returncode == 0
        assert "ok" in check.stdout

    @pytest.mark.asyncio
    async def test_installs_base_deps_from_config(self, tmp_path: Path) -> None:
        """Installs all base_deps from config."""
        venv_path = tmp_path / "venv-base-deps"
        # Include an additional package in base_deps
        config = SubprocessConfig(
            python_version="3.11",
            venv_path=venv_path,
            base_deps=("ipykernel", "requests"),
        )
        manager = VenvManager(config)

        result = await manager.create()

        # Verify both packages are importable
        import subprocess

        check = subprocess.run(
            [str(result.python_path), "-c", "import ipykernel; import requests; print('ok')"],
            capture_output=True,
            text=True,
        )
        assert check.returncode == 0
        assert "ok" in check.stdout

    @pytest.mark.asyncio
    async def test_installs_extra_deps_when_provided(self, tmp_path: Path) -> None:
        """Installs extra_deps when provided to create()."""
        venv_path = tmp_path / "venv-extra-deps"
        config = SubprocessConfig(python_version="3.11", venv_path=venv_path)
        manager = VenvManager(config)

        result = await manager.create(extra_deps=["requests"])

        # Verify extra package is importable
        import subprocess

        check = subprocess.run(
            [str(result.python_path), "-c", "import requests; print('ok')"],
            capture_output=True,
            text=True,
        )
        assert check.returncode == 0
        assert "ok" in check.stdout

    # =========================================================================
    # Kernel Spec
    # =========================================================================

    @pytest.mark.asyncio
    async def test_returns_kernel_spec_name(self, tmp_path: Path) -> None:
        """Returns KernelVenv with kernel_spec_name populated."""
        venv_path = tmp_path / "venv-kernel-spec"
        config = SubprocessConfig(python_version="3.11", venv_path=venv_path)
        manager = VenvManager(config)

        result = await manager.create()

        assert result.kernel_spec_name is not None
        assert len(result.kernel_spec_name) > 0

    @pytest.mark.asyncio
    async def test_kernel_spec_name_is_unique(self, tmp_path: Path) -> None:
        """Each created venv gets a unique kernel_spec_name."""
        venv_path_1 = tmp_path / "venv-1"
        venv_path_2 = tmp_path / "venv-2"
        config_1 = SubprocessConfig(python_version="3.11", venv_path=venv_path_1)
        config_2 = SubprocessConfig(python_version="3.11", venv_path=venv_path_2)
        manager_1 = VenvManager(config_1)
        manager_2 = VenvManager(config_2)

        result_1 = await manager_1.create()
        result_2 = await manager_2.create()

        assert result_1.kernel_spec_name != result_2.kernel_spec_name

    @pytest.mark.asyncio
    async def test_installs_kernel_spec(self, tmp_path: Path) -> None:
        """Kernel spec is installed and discoverable by jupyter."""
        venv_path = tmp_path / "venv-kernel-install"
        config = SubprocessConfig(python_version="3.11", venv_path=venv_path)
        manager = VenvManager(config)

        result = await manager.create()

        # Verify kernel spec is installed via jupyter kernelspec list
        import subprocess

        list_output = subprocess.run(
            [str(result.python_path), "-m", "jupyter", "kernelspec", "list"],
            capture_output=True,
            text=True,
        )
        assert result.kernel_spec_name in list_output.stdout


# =============================================================================
# VenvManager.add_package() Tests
# =============================================================================


@pytest.mark.slow
@pytest.mark.xdist_group("venv")
class TestVenvManagerAddPackage:
    """Tests for VenvManager.add_package() - hot package installation.

    These tests actually run uv to install packages. They are slow and
    should not run in parallel.
    """

    @pytest.mark.asyncio
    async def test_installs_package_to_venv(self, tmp_path: Path) -> None:
        """add_package() installs package to the venv."""
        venv_path = tmp_path / "venv-add-pkg"
        config = SubprocessConfig(python_version="3.11", venv_path=venv_path)
        manager = VenvManager(config)
        venv = await manager.create()

        # Verify package is NOT installed before
        import subprocess

        before = subprocess.run(
            [str(venv.python_path), "-c", "import requests"],
            capture_output=True,
        )
        assert before.returncode != 0  # Should fail - not installed

        # Install package
        await manager.add_package(venv, "requests")

        # Verify package IS installed after
        after = subprocess.run(
            [str(venv.python_path), "-c", "import requests; print('ok')"],
            capture_output=True,
            text=True,
        )
        assert after.returncode == 0
        assert "ok" in after.stdout

    @pytest.mark.asyncio
    async def test_package_available_immediately(self, tmp_path: Path) -> None:
        """Package is importable immediately after add_package() returns."""
        venv_path = tmp_path / "venv-immediate"
        config = SubprocessConfig(python_version="3.11", venv_path=venv_path)
        manager = VenvManager(config)
        venv = await manager.create()

        # Install and immediately verify
        await manager.add_package(venv, "requests")

        import subprocess

        result = subprocess.run(
            [str(venv.python_path), "-c", "import requests; print(requests.__version__)"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        # Should print a version number
        assert result.stdout.strip()  # Non-empty output

    @pytest.mark.asyncio
    async def test_add_package_with_version_spec(self, tmp_path: Path) -> None:
        """add_package() accepts version specifiers."""
        venv_path = tmp_path / "venv-version-spec"
        config = SubprocessConfig(python_version="3.11", venv_path=venv_path)
        manager = VenvManager(config)
        venv = await manager.create()

        # Install specific version
        await manager.add_package(venv, "requests>=2.28,<3.0")

        import subprocess

        result = subprocess.run(
            [str(venv.python_path), "-c", "import requests; print(requests.__version__)"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        version = result.stdout.strip()
        # Verify version is in expected range (starts with 2.)
        assert version.startswith("2.")


# =============================================================================
# VenvManager.cleanup() Tests
# =============================================================================


@pytest.mark.slow
@pytest.mark.xdist_group("venv")
class TestVenvManagerCleanup:
    """Tests for VenvManager.cleanup() - venv removal."""

    @pytest.mark.asyncio
    async def test_removes_venv_directory(self, tmp_path: Path) -> None:
        """cleanup() removes the venv directory."""
        venv_path = tmp_path / "venv-to-cleanup"
        config = SubprocessConfig(python_version="3.11", venv_path=venv_path)
        manager = VenvManager(config)
        venv = await manager.create()

        assert venv.path.exists()

        await manager.cleanup(venv)

        assert not venv.path.exists()

    @pytest.mark.asyncio
    async def test_cleanup_safe_if_venv_does_not_exist(self, tmp_path: Path) -> None:
        """cleanup() does not raise if venv already deleted."""
        venv_path = tmp_path / "venv-already-gone"
        config = SubprocessConfig(python_version="3.11", venv_path=venv_path)
        manager = VenvManager(config)
        venv = await manager.create()

        # Manually delete the venv
        shutil.rmtree(venv.path)
        assert not venv.path.exists()

        # cleanup() should not raise
        await manager.cleanup(venv)  # Should not raise

    @pytest.mark.asyncio
    async def test_cleanup_removes_all_venv_contents(self, tmp_path: Path) -> None:
        """cleanup() removes venv including all installed packages."""
        venv_path = tmp_path / "venv-full-cleanup"
        config = SubprocessConfig(python_version="3.11", venv_path=venv_path)
        manager = VenvManager(config)
        venv = await manager.create()

        # Install an extra package to add more files
        await manager.add_package(venv, "requests")

        # Verify venv has contents
        assert any(venv.path.iterdir())

        await manager.cleanup(venv)

        # Verify completely removed
        assert not venv.path.exists()


# =============================================================================
# VenvManager Error Condition Tests
# =============================================================================


@pytest.mark.xdist_group("venv")
class TestVenvManagerErrors:
    """Tests for VenvManager error handling.

    These tests verify that VenvManager fails loudly with clear error messages
    rather than silently falling back or guessing.
    """

    @pytest.mark.asyncio
    async def test_uv_not_found_raises_runtime_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Raises RuntimeError with clear message when uv is not in PATH."""
        # Remove uv from PATH by setting empty PATH
        monkeypatch.setenv("PATH", "")

        config = SubprocessConfig(python_version="3.11", venv_path=tmp_path / "venv")
        manager = VenvManager(config)

        with pytest.raises(RuntimeError, match="uv is required but not found"):
            await manager.create()

    @pytest.mark.asyncio
    async def test_venv_creation_failure_propagates_with_context(self, tmp_path: Path) -> None:
        """Venv creation failure propagates with context about what failed."""
        # Use an invalid python version that uv cannot satisfy
        config = SubprocessConfig(
            python_version="99.99",  # Impossible version
            venv_path=tmp_path / "venv",
        )
        manager = VenvManager(config)

        # Should raise an error (exact type may vary, but should not silently succeed)
        with pytest.raises(Exception) as exc_info:
            await manager.create()

        # Error should contain useful context
        error_msg = str(exc_info.value).lower()
        assert "99.99" in error_msg or "python" in error_msg or "version" in error_msg

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_package_install_failure_propagates_with_context(self, tmp_path: Path) -> None:
        """Package install failure propagates with context about what failed."""
        venv_path = tmp_path / "venv-bad-pkg"
        config = SubprocessConfig(python_version="3.11", venv_path=venv_path)
        manager = VenvManager(config)
        venv = await manager.create()

        # Try to install a non-existent package
        with pytest.raises(Exception) as exc_info:
            await manager.add_package(venv, "this-package-definitely-does-not-exist-xyz123")

        # Error should contain the package name for debugging
        error_msg = str(exc_info.value).lower()
        assert "this-package-definitely-does-not-exist" in error_msg or "not found" in error_msg

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_invalid_extra_deps_propagates_error(self, tmp_path: Path) -> None:
        """Invalid extra_deps in create() propagates error with context."""
        venv_path = tmp_path / "venv-bad-extra"
        config = SubprocessConfig(python_version="3.11", venv_path=venv_path)
        manager = VenvManager(config)

        # Try to create with a non-existent extra dep
        with pytest.raises(Exception) as exc_info:
            await manager.create(extra_deps=["fake-nonexistent-package-abc789"])

        # Error should contain useful information
        error_msg = str(exc_info.value).lower()
        assert "fake-nonexistent-package" in error_msg or "not found" in error_msg


# =============================================================================
# SubprocessExecutor Initialization Tests
# =============================================================================


@pytest.mark.xdist_group("subprocess")
class TestSubprocessExecutorInit:
    """Tests for SubprocessExecutor initialization."""

    def test_accepts_none_config_uses_defaults(self) -> None:
        """When config is None, uses default SubprocessConfig."""
        # Import will fail until implementation exists - this is expected (TDD)
        from py_code_mode.execution.subprocess import SubprocessExecutor

        executor = SubprocessExecutor(config=None)
        # Default config should have python_version set
        assert executor._config is not None
        assert executor._config.python_version is not None

    def test_accepts_custom_config(self, tmp_path: Path) -> None:
        """SubprocessExecutor accepts custom SubprocessConfig."""
        from py_code_mode.execution.subprocess import SubprocessExecutor

        config = SubprocessConfig(
            python_version="3.12",
            venv_path=tmp_path / "custom-venv",
            startup_timeout=45.0,
        )
        executor = SubprocessExecutor(config=config)

        assert executor._config is config
        assert executor._config.python_version == "3.12"
        assert executor._config.startup_timeout == 45.0

    def test_does_not_start_kernel_until_start_called(self) -> None:
        """Kernel is not started on __init__, only on start()."""
        from py_code_mode.execution.subprocess import SubprocessExecutor

        executor = SubprocessExecutor()

        # Kernel should not exist yet
        assert not hasattr(executor, "_km") or executor._km is None
        assert not hasattr(executor, "_kc") or executor._kc is None


# =============================================================================
# SubprocessExecutor Capabilities Tests
# =============================================================================


@pytest.mark.xdist_group("subprocess")
class TestSubprocessExecutorCapabilities:
    """Tests for SubprocessExecutor capability reporting."""

    def test_supports_timeout(self) -> None:
        """supports(TIMEOUT) returns True."""
        from py_code_mode.execution.subprocess import SubprocessExecutor

        executor = SubprocessExecutor()
        assert executor.supports(Capability.TIMEOUT) is True

    def test_supports_process_isolation(self) -> None:
        """supports(PROCESS_ISOLATION) returns True."""
        from py_code_mode.execution.subprocess import SubprocessExecutor

        executor = SubprocessExecutor()
        assert executor.supports(Capability.PROCESS_ISOLATION) is True

    def test_supports_reset(self) -> None:
        """supports(RESET) returns True."""
        from py_code_mode.execution.subprocess import SubprocessExecutor

        executor = SubprocessExecutor()
        assert executor.supports(Capability.RESET) is True

    def test_does_not_support_network_isolation(self) -> None:
        """supports(NETWORK_ISOLATION) returns False."""
        from py_code_mode.execution.subprocess import SubprocessExecutor

        executor = SubprocessExecutor()
        assert executor.supports(Capability.NETWORK_ISOLATION) is False

    def test_does_not_support_filesystem_isolation(self) -> None:
        """supports(FILESYSTEM_ISOLATION) returns False."""
        from py_code_mode.execution.subprocess import SubprocessExecutor

        executor = SubprocessExecutor()
        assert executor.supports(Capability.FILESYSTEM_ISOLATION) is False

    def test_supported_capabilities_returns_correct_set(self) -> None:
        """supported_capabilities() returns set with TIMEOUT, PROCESS_ISOLATION, RESET."""
        from py_code_mode.execution.subprocess import SubprocessExecutor

        executor = SubprocessExecutor()
        caps = executor.supported_capabilities()

        assert Capability.TIMEOUT in caps
        assert Capability.PROCESS_ISOLATION in caps
        assert Capability.RESET in caps
        assert Capability.NETWORK_ISOLATION not in caps
        assert Capability.FILESYSTEM_ISOLATION not in caps


# =============================================================================
# SubprocessExecutor Lifecycle Tests
# =============================================================================


@pytest.mark.slow
@pytest.mark.xdist_group("subprocess")
class TestSubprocessExecutorLifecycle:
    """Tests for SubprocessExecutor lifecycle (start/close/context manager)."""

    @pytest.mark.asyncio
    async def test_start_creates_kernel_that_can_execute(self, tmp_path: Path) -> None:
        """start() creates a kernel that can execute code."""
        from py_code_mode.execution.subprocess import SubprocessExecutor

        config = SubprocessConfig(python_version="3.11", venv_path=tmp_path / "venv")
        executor = SubprocessExecutor(config=config)

        try:
            await executor.start()

            result = await executor.run("1 + 1")
            assert result.value == "2" or result.value == 2
            assert result.error is None
        finally:
            await executor.close()

    @pytest.mark.asyncio
    async def test_start_with_storage_access_injects_namespaces(self, tmp_path: Path) -> None:
        """start() with storage_access injects tools, skills, artifacts namespaces."""
        from py_code_mode.execution.protocol import FileStorageAccess
        from py_code_mode.execution.subprocess import SubprocessExecutor

        tools_path = tmp_path / "tools"
        skills_path = tmp_path / "skills"
        artifacts_path = tmp_path / "artifacts"
        tools_path.mkdir()
        skills_path.mkdir()
        artifacts_path.mkdir()

        storage_access = FileStorageAccess(
            tools_path=tools_path,
            skills_path=skills_path,
            artifacts_path=artifacts_path,
        )

        config = SubprocessConfig(python_version="3.11", venv_path=tmp_path / "venv")
        executor = SubprocessExecutor(config=config)

        try:
            await executor.start(storage_access=storage_access)

            # Verify namespaces are injected
            result = await executor.run("'tools' in dir()")
            assert result.value in (True, "True")

            result = await executor.run("'skills' in dir()")
            assert result.value in (True, "True")

            result = await executor.run("'artifacts' in dir()")
            assert result.value in (True, "True")
        finally:
            await executor.close()

    @pytest.mark.asyncio
    async def test_close_shuts_down_kernel(self, tmp_path: Path) -> None:
        """close() shuts down the kernel."""
        from py_code_mode.execution.subprocess import SubprocessExecutor

        config = SubprocessConfig(python_version="3.11", venv_path=tmp_path / "venv")
        executor = SubprocessExecutor(config=config)

        await executor.start()
        await executor.close()

        # Kernel should be shut down - trying to run should indicate closed state
        result = await executor.run("1 + 1")
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_close_cleans_up_venv_when_cleanup_enabled(self, tmp_path: Path) -> None:
        """close() removes venv when cleanup_venv_on_close=True."""
        from py_code_mode.execution.subprocess import SubprocessExecutor

        venv_path = tmp_path / "venv-cleanup-test"
        config = SubprocessConfig(
            python_version="3.11",
            venv_path=venv_path,
            cleanup_venv_on_close=True,
        )
        executor = SubprocessExecutor(config=config)

        await executor.start()
        assert venv_path.exists()

        await executor.close()
        assert not venv_path.exists()

    @pytest.mark.asyncio
    async def test_close_preserves_venv_when_cleanup_disabled(self, tmp_path: Path) -> None:
        """close() preserves venv when cleanup_venv_on_close=False."""
        from py_code_mode.execution.subprocess import SubprocessExecutor

        venv_path = tmp_path / "venv-preserve-test"
        config = SubprocessConfig(
            python_version="3.11",
            venv_path=venv_path,
            cleanup_venv_on_close=False,
        )
        executor = SubprocessExecutor(config=config)

        await executor.start()
        assert venv_path.exists()

        await executor.close()
        assert venv_path.exists()  # Still exists

    @pytest.mark.asyncio
    async def test_context_manager_calls_start_and_close(self, tmp_path: Path) -> None:
        """async with SubprocessExecutor calls start() and close()."""
        from py_code_mode.execution.subprocess import SubprocessExecutor

        venv_path = tmp_path / "venv-context-manager"
        config = SubprocessConfig(
            python_version="3.11",
            venv_path=venv_path,
            cleanup_venv_on_close=True,
        )

        async with SubprocessExecutor(config=config) as executor:
            result = await executor.run("2 + 2")
            assert result.error is None

        # Venv should be cleaned up after context exit
        assert not venv_path.exists()


# =============================================================================
# SubprocessExecutor run() - Basic Execution Tests
# =============================================================================


@pytest.mark.slow
@pytest.mark.xdist_group("subprocess")
class TestSubprocessExecutorRun:
    """Tests for SubprocessExecutor.run() - basic code execution."""

    @pytest.fixture
    async def executor(self, tmp_path: Path):
        """Provide a started SubprocessExecutor for tests."""
        from py_code_mode.execution.subprocess import SubprocessExecutor

        config = SubprocessConfig(python_version="3.11", venv_path=tmp_path / "venv")
        exec = SubprocessExecutor(config=config)
        await exec.start()
        yield exec
        await exec.close()

    @pytest.mark.asyncio
    async def test_simple_expression_returns_value(self, executor) -> None:
        """Simple expression returns evaluated value."""
        result = await executor.run("1 + 2 + 3")

        assert result.error is None
        # Value may be int or string representation depending on implementation
        assert result.value in (6, "6")

    @pytest.mark.asyncio
    async def test_multi_statement_returns_last_expression(self, executor) -> None:
        """Multi-statement code with final expression returns last value."""
        code = """
x = 10
y = 20
x + y
"""
        result = await executor.run(code)

        assert result.error is None
        assert result.value in (30, "30")

    @pytest.mark.asyncio
    async def test_statements_without_expression_returns_none(self, executor) -> None:
        """Statements without trailing expression return None."""
        result = await executor.run("x = 42")

        assert result.error is None
        assert result.value is None

    @pytest.mark.asyncio
    async def test_captures_stdout_from_print(self, executor) -> None:
        """Captures stdout from print() calls."""
        result = await executor.run('print("hello world")')

        assert result.error is None
        assert "hello world" in result.stdout

    @pytest.mark.asyncio
    async def test_returns_traceback_on_exception(self, executor) -> None:
        """Returns formatted traceback on exception."""
        result = await executor.run("1 / 0")

        assert result.error is not None
        assert "ZeroDivisionError" in result.error

    @pytest.mark.asyncio
    async def test_string_expression_returns_string_value(self, executor) -> None:
        """String expression returns string value."""
        result = await executor.run('"hello"')

        assert result.error is None
        # IPython may include quotes in the repr
        assert "hello" in str(result.value)

    @pytest.mark.asyncio
    async def test_list_expression_returns_list(self, executor) -> None:
        """List expression returns list representation."""
        result = await executor.run("[1, 2, 3]")

        assert result.error is None
        # Value should represent [1, 2, 3]
        assert "1" in str(result.value)
        assert "2" in str(result.value)
        assert "3" in str(result.value)


# =============================================================================
# SubprocessExecutor run() - Top-level Await Tests
# =============================================================================


@pytest.mark.slow
@pytest.mark.xdist_group("subprocess")
class TestSubprocessExecutorAsync:
    """Tests for SubprocessExecutor top-level await support.

    This is a KEY DIFFERENTIATOR from InProcessExecutor.
    """

    @pytest.fixture
    async def executor(self, tmp_path: Path):
        """Provide a started SubprocessExecutor for tests."""
        from py_code_mode.execution.subprocess import SubprocessExecutor

        config = SubprocessConfig(python_version="3.11", venv_path=tmp_path / "venv")
        exec = SubprocessExecutor(config=config)
        await exec.start()
        yield exec
        await exec.close()

    @pytest.mark.asyncio
    async def test_can_await_async_function(self, executor) -> None:
        """Can await async functions at top level."""
        code = """
import asyncio

async def get_value():
    await asyncio.sleep(0.01)
    return 42

await get_value()
"""
        result = await executor.run(code)

        assert result.error is None
        assert result.value in (42, "42")

    @pytest.mark.asyncio
    async def test_can_use_async_for_loop(self, executor) -> None:
        """Can use async for loops at top level."""
        code = """
import asyncio

async def async_gen():
    for i in range(3):
        await asyncio.sleep(0.001)
        yield i

items = []
async for item in async_gen():
    items.append(item)

items
"""
        result = await executor.run(code)

        assert result.error is None
        # Should be [0, 1, 2]
        assert "0" in str(result.value)
        assert "1" in str(result.value)
        assert "2" in str(result.value)

    @pytest.mark.asyncio
    async def test_can_use_async_with_statement(self, executor) -> None:
        """Can use async with statements at top level."""
        code = """
import asyncio

class AsyncContextManager:
    async def __aenter__(self):
        await asyncio.sleep(0.001)
        return "entered"

    async def __aexit__(self, *args):
        await asyncio.sleep(0.001)

async with AsyncContextManager() as value:
    result = value

result
"""
        result = await executor.run(code)

        assert result.error is None
        assert "entered" in str(result.value)


# =============================================================================
# SubprocessExecutor State Persistence Tests
# =============================================================================


@pytest.mark.slow
@pytest.mark.xdist_group("subprocess")
class TestSubprocessExecutorState:
    """Tests for SubprocessExecutor state persistence between runs."""

    @pytest.fixture
    async def executor(self, tmp_path: Path):
        """Provide a started SubprocessExecutor for tests."""
        from py_code_mode.execution.subprocess import SubprocessExecutor

        config = SubprocessConfig(python_version="3.11", venv_path=tmp_path / "venv")
        exec = SubprocessExecutor(config=config)
        await exec.start()
        yield exec
        await exec.close()

    @pytest.mark.asyncio
    async def test_variables_persist_between_runs(self, executor) -> None:
        """Variables defined in one run are accessible in next run."""
        await executor.run("my_var = 123")
        result = await executor.run("my_var")

        assert result.error is None
        assert result.value in (123, "123")

    @pytest.mark.asyncio
    async def test_imports_persist_between_runs(self, executor) -> None:
        """Imports from one run are accessible in next run."""
        await executor.run("import math")
        result = await executor.run("math.pi")

        assert result.error is None
        assert "3.14" in str(result.value)

    @pytest.mark.asyncio
    async def test_functions_persist_between_runs(self, executor) -> None:
        """Functions defined in one run are callable in next run."""
        await executor.run("def double(x): return x * 2")
        result = await executor.run("double(21)")

        assert result.error is None
        assert result.value in (42, "42")

    @pytest.mark.asyncio
    async def test_class_definitions_persist(self, executor) -> None:
        """Classes defined in one run are usable in next run."""
        await executor.run("class Counter:\n    def __init__(self): self.n = 0")
        await executor.run("c = Counter()")
        result = await executor.run("c.n")

        assert result.error is None
        assert result.value in (0, "0")


# =============================================================================
# SubprocessExecutor Timeout Tests
# =============================================================================


@pytest.mark.slow
@pytest.mark.xdist_group("subprocess")
class TestSubprocessExecutorTimeout:
    """Tests for SubprocessExecutor timeout behavior."""

    @pytest.fixture
    async def executor(self, tmp_path: Path):
        """Provide a started SubprocessExecutor with short timeout."""
        from py_code_mode.execution.subprocess import SubprocessExecutor

        config = SubprocessConfig(
            python_version="3.11",
            venv_path=tmp_path / "venv",
            default_timeout=2.0,  # Short timeout for tests
        )
        exec = SubprocessExecutor(config=config)
        await exec.start()
        yield exec
        await exec.close()

    @pytest.mark.asyncio
    async def test_times_out_long_running_code(self, executor) -> None:
        """Times out code that runs longer than timeout."""
        code = """
import time
time.sleep(10)  # Sleep longer than timeout
"""
        result = await executor.run(code)

        assert result.error is not None
        # Error should indicate timeout
        assert "timeout" in result.error.lower() or "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_returns_timeout_error_in_result(self, executor) -> None:
        """Timeout error is in ExecutionResult.error field."""
        code = "import time; time.sleep(10)"
        result = await executor.run(code)

        assert result.value is None
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_uses_config_default_timeout(self, tmp_path: Path) -> None:
        """Uses default_timeout from config when not specified."""
        from py_code_mode.execution.subprocess import SubprocessExecutor

        config = SubprocessConfig(
            python_version="3.11",
            venv_path=tmp_path / "venv-timeout",
            default_timeout=1.0,  # Very short
        )
        async with SubprocessExecutor(config=config) as executor:
            result = await executor.run("import time; time.sleep(5)")

            assert result.error is not None
            assert "timeout" in result.error.lower() or "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_timeout_can_be_overridden_per_call(self, executor) -> None:
        """Timeout can be overridden per-call with timeout parameter."""
        # This should timeout quickly because we override to 0.5s
        result = await executor.run("import time; time.sleep(5)", timeout=0.5)

        assert result.error is not None
        assert "timeout" in result.error.lower() or "timed out" in result.error.lower()


# =============================================================================
# SubprocessExecutor Reset Tests
# =============================================================================


@pytest.mark.slow
@pytest.mark.xdist_group("subprocess")
class TestSubprocessExecutorReset:
    """Tests for SubprocessExecutor.reset() functionality."""

    @pytest.fixture
    async def executor(self, tmp_path: Path):
        """Provide a started SubprocessExecutor for tests."""
        from py_code_mode.execution.protocol import FileStorageAccess
        from py_code_mode.execution.subprocess import SubprocessExecutor

        tools_path = tmp_path / "tools"
        skills_path = tmp_path / "skills"
        artifacts_path = tmp_path / "artifacts"
        tools_path.mkdir()
        skills_path.mkdir()
        artifacts_path.mkdir()

        storage_access = FileStorageAccess(
            tools_path=tools_path,
            skills_path=skills_path,
            artifacts_path=artifacts_path,
        )

        config = SubprocessConfig(python_version="3.11", venv_path=tmp_path / "venv")
        exec = SubprocessExecutor(config=config)
        await exec.start(storage_access=storage_access)
        yield exec
        await exec.close()

    @pytest.mark.asyncio
    async def test_reset_clears_user_defined_variables(self, executor) -> None:
        """reset() clears user-defined variables."""
        await executor.run("my_data = [1, 2, 3]")
        result = await executor.run("my_data")
        assert result.error is None  # Variable exists

        await executor.reset()

        result = await executor.run("my_data")
        assert result.error is not None  # Variable no longer exists

    @pytest.mark.asyncio
    async def test_reset_preserves_injected_namespaces(self, executor) -> None:
        """reset() preserves tools, skills, artifacts namespaces."""
        # Verify namespaces exist before reset
        result = await executor.run("'tools' in dir()")
        assert result.value in (True, "True")

        await executor.reset()

        # Namespaces should still exist after reset
        result = await executor.run("'tools' in dir()")
        assert result.value in (True, "True")

        result = await executor.run("'skills' in dir()")
        assert result.value in (True, "True")

        result = await executor.run("'artifacts' in dir()")
        assert result.value in (True, "True")


# =============================================================================
# SubprocessExecutor Error Condition Tests
# =============================================================================


@pytest.mark.slow
@pytest.mark.xdist_group("subprocess")
class TestSubprocessExecutorErrors:
    """Tests for SubprocessExecutor error handling.

    NO silent fallbacks - errors should propagate with clear messages.
    """

    @pytest.mark.asyncio
    async def test_run_on_closed_executor_returns_error(self, tmp_path: Path) -> None:
        """run() on closed executor returns error in result."""
        from py_code_mode.execution.subprocess import SubprocessExecutor

        config = SubprocessConfig(python_version="3.11", venv_path=tmp_path / "venv")
        executor = SubprocessExecutor(config=config)

        await executor.start()
        await executor.close()

        result = await executor.run("1 + 1")
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_start_twice_is_safe_or_raises(self, tmp_path: Path) -> None:
        """start() called twice either raises or is idempotent."""
        from py_code_mode.execution.subprocess import SubprocessExecutor

        config = SubprocessConfig(python_version="3.11", venv_path=tmp_path / "venv")
        executor = SubprocessExecutor(config=config)

        try:
            await executor.start()

            # Second start should either:
            # 1. Raise an error (preferred - explicit)
            # 2. Be idempotent (acceptable - no harm)
            try:
                await executor.start()
                # If it doesn't raise, verify it still works
                result = await executor.run("1 + 1")
                assert result.error is None
            except RuntimeError:
                # This is fine - explicit error on double start
                pass
        finally:
            await executor.close()

    @pytest.mark.asyncio
    async def test_syntax_error_returns_error_in_result(self, tmp_path: Path) -> None:
        """Syntax errors are captured in ExecutionResult.error."""
        from py_code_mode.execution.subprocess import SubprocessExecutor

        config = SubprocessConfig(python_version="3.11", venv_path=tmp_path / "venv")
        async with SubprocessExecutor(config=config) as executor:
            result = await executor.run("def broken(")

            assert result.error is not None
            assert "SyntaxError" in result.error or "syntax" in result.error.lower()

    @pytest.mark.asyncio
    async def test_import_error_returns_error_in_result(self, tmp_path: Path) -> None:
        """Import errors are captured in ExecutionResult.error."""
        from py_code_mode.execution.subprocess import SubprocessExecutor

        config = SubprocessConfig(python_version="3.11", venv_path=tmp_path / "venv")
        async with SubprocessExecutor(config=config) as executor:
            result = await executor.run("import this_module_does_not_exist_xyz")

            assert result.error is not None
            assert "ModuleNotFoundError" in result.error or "No module" in result.error

    @pytest.mark.asyncio
    async def test_attribute_error_returns_error_in_result(self, tmp_path: Path) -> None:
        """Attribute errors are captured in ExecutionResult.error."""
        from py_code_mode.execution.subprocess import SubprocessExecutor

        config = SubprocessConfig(python_version="3.11", venv_path=tmp_path / "venv")
        async with SubprocessExecutor(config=config) as executor:
            result = await executor.run("'hello'.nonexistent_method()")

            assert result.error is not None
            assert "AttributeError" in result.error
