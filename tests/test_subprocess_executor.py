"""Tests for SubprocessExecutor and SubprocessConfig."""

from pathlib import Path

import pytest

from py_code_mode.execution.subprocess.config import SubprocessConfig


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
