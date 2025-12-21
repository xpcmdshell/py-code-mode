"""Tests for SubprocessExecutor, SubprocessConfig, and VenvManager."""

import shutil
import sys
from pathlib import Path

import pytest

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
