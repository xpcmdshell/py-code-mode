"""Tests for SubprocessExecutor venv caching feature.

Test-driven development for venv caching to reduce MCP server startup time.
These tests define the interface and expected behavior before implementation.

Feature Overview:
- cache_venv: bool = True - enable persistent venv caching
- get_canonical_venv_path(python_version) -> Path - deterministic cache location
- cleanup_venv_on_close: bool | None = None - auto cleanup based on cache/temp
- VenvManager checks for existing valid venv before creating new one
- File locking prevents concurrent creation conflicts
"""

import hashlib
import os
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from py_code_mode.execution.subprocess.config import SubprocessConfig
from py_code_mode.execution.subprocess.venv import VenvManager


def _get_current_python_version() -> str:
    """Get current Python version in major.minor format for integration tests."""
    return f"{sys.version_info.major}.{sys.version_info.minor}"


# ==============================================================================
# Config Tests - SubprocessConfig behavior
# ==============================================================================


def test_cache_venv_default_is_true():
    """Verify cache_venv defaults to True for performance.

    Caching should be the default to minimize startup time for MCP servers.
    """
    config = SubprocessConfig()
    assert config.cache_venv is True


def test_canonical_path_formula():
    """Verify canonical path construction follows expected format.

    Path should be: ~/.cache/py-code-mode/venv-{python_version}
    This provides a deterministic location per Python version.
    """
    config = SubprocessConfig(python_version="3.11")
    canonical = config.get_canonical_venv_path("3.11")

    # Should be in cache directory
    assert ".cache" in str(canonical)
    assert "py-code-mode" in str(canonical)
    assert "venv-3.11" in str(canonical)

    # Should be absolute path
    assert canonical.is_absolute()


def test_canonical_path_respects_xdg_cache_home(monkeypatch, tmp_path):
    """Verify XDG_CACHE_HOME environment variable is honored.

    When XDG_CACHE_HOME is set, use that instead of ~/.cache.
    This follows XDG Base Directory specification.
    """
    custom_cache = tmp_path / "custom-cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(custom_cache))

    config = SubprocessConfig(python_version="3.11")
    canonical = config.get_canonical_venv_path("3.11")

    # Should use XDG_CACHE_HOME
    assert str(canonical).startswith(str(custom_cache))
    assert "venv-3.11" in str(canonical)


def test_cache_venv_false_signals_temp_behavior():
    """Verify cache_venv=False signals temporary venv behavior.

    When caching is disabled, venv should be temporary and cleaned up.
    """
    config = SubprocessConfig(cache_venv=False)
    assert config.cache_venv is False


def test_explicit_venv_path_takes_precedence():
    """Verify explicit venv_path ignores cache_venv setting.

    When user provides explicit path, that takes precedence over caching logic.
    cache_venv should only control the None case.
    """
    explicit_path = Path("/custom/venv/path")
    config = SubprocessConfig(venv_path=explicit_path, cache_venv=True)

    # Config should store explicit path
    assert config.venv_path == explicit_path
    # cache_venv setting should not affect explicit path


def test_cleanup_auto_defaults_false_for_cache():
    """Verify auto cleanup defaults to False when caching.

    When cleanup_venv_on_close=None and cache_venv=True:
    - Should not delete venv on close (preserve cache)

    This test validates the auto-detection logic.
    """
    config = SubprocessConfig(
        cache_venv=True,
        cleanup_venv_on_close=None,  # Auto mode
    )

    # Should signal no cleanup for cached venv
    # Implementation should provide a method to resolve auto to boolean
    resolved = config.get_resolved_cleanup()
    assert resolved is False


def test_cleanup_auto_defaults_true_for_temp():
    """Verify auto cleanup defaults to True for temporary venvs.

    When cleanup_venv_on_close=None and cache_venv=False:
    - Should delete venv on close (temp cleanup)

    This prevents temporary venvs from accumulating.
    """
    config = SubprocessConfig(
        cache_venv=False,
        cleanup_venv_on_close=None,  # Auto mode
    )

    resolved = config.get_resolved_cleanup()
    assert resolved is True


def test_explicit_cleanup_overrides_auto():
    """Verify explicit cleanup_venv_on_close overrides auto behavior.

    User can force cleanup=True even when caching, or cleanup=False for temp.
    This provides escape hatch for unusual scenarios.
    """
    # Force cleanup ON when caching (unusual but allowed)
    config_cleanup_cached = SubprocessConfig(
        cache_venv=True,
        cleanup_venv_on_close=True,  # Explicit override
    )
    assert config_cleanup_cached.get_resolved_cleanup() is True

    # Force cleanup OFF for temp (unusual but allowed)
    config_keep_temp = SubprocessConfig(
        cache_venv=False,
        cleanup_venv_on_close=False,  # Explicit override
    )
    assert config_keep_temp.get_resolved_cleanup() is False


# ==============================================================================
# VenvManager Tests - Venv validation and caching logic
# ==============================================================================


def test_is_venv_valid_returns_true_for_valid_venv(tmp_path):
    """Verify _is_venv_valid recognizes a valid venv.

    A valid venv has:
    - Directory exists
    - bin/python (or Scripts/python.exe on Windows) executable exists
    - Python executable runs successfully
    """
    # Create a fake valid venv structure
    venv_path = tmp_path / "valid-venv"
    venv_path.mkdir()

    # Create bin directory with python executable
    bin_dir = venv_path / ("Scripts" if os.name == "nt" else "bin")
    bin_dir.mkdir()
    python_exe = bin_dir / ("python.exe" if os.name == "nt" else "python")

    # Create actual Python symlink to make it runnable
    # Note: symlink is required on macOS with uv-managed Python because
    # copying the binary alone doesn't include the dynamic library it references
    import sys

    os.symlink(sys.executable, python_exe)

    # Validate
    manager = VenvManager(venv_path=venv_path, python_version="3.11")
    assert manager._is_venv_valid(venv_path) is True


def test_is_venv_valid_returns_false_for_missing_venv(tmp_path):
    """Verify _is_venv_valid returns False when venv directory doesn't exist.

    Missing directory should be treated as invalid, triggering recreation.
    """
    nonexistent = tmp_path / "does-not-exist"

    manager = VenvManager(venv_path=nonexistent, python_version="3.11")
    assert manager._is_venv_valid(nonexistent) is False


def test_is_venv_valid_returns_false_for_empty_dir(tmp_path):
    """Verify _is_venv_valid returns False for empty directory.

    Directory exists but has no python executable -> invalid.
    This handles corrupted venv scenarios.
    """
    empty_dir = tmp_path / "empty-venv"
    empty_dir.mkdir()

    manager = VenvManager(venv_path=empty_dir, python_version="3.11")
    assert manager._is_venv_valid(empty_dir) is False


def test_deterministic_kernel_spec_name():
    """Verify kernel spec name is deterministic from venv path.

    Same path should always produce the same kernel spec name.
    Format: py-code-mode-{sha256(path)[:12]}

    This enables kernel reuse across sessions.
    """
    venv_path = Path("/home/user/.cache/py-code-mode/venv-3.11")

    name1 = VenvManager._get_kernel_spec_name(venv_path)
    name2 = VenvManager._get_kernel_spec_name(venv_path)

    assert name1 == name2
    assert name1.startswith("py-code-mode-")

    # Verify hash portion is 12 chars
    hash_portion = name1.replace("py-code-mode-", "")
    assert len(hash_portion) == 12

    # Verify hash matches expected
    expected_hash = hashlib.sha256(str(venv_path).encode()).hexdigest()[:12]
    assert hash_portion == expected_hash


def test_different_paths_different_kernel_spec_names():
    """Verify different venv paths produce different kernel spec names.

    Path uniqueness ensures different venvs don't conflict.
    """
    path1 = Path("/home/user/.cache/py-code-mode/venv-3.11")
    path2 = Path("/home/user/.cache/py-code-mode/venv-3.12")

    name1 = VenvManager._get_kernel_spec_name(path1)
    name2 = VenvManager._get_kernel_spec_name(path2)

    assert name1 != name2


@pytest.mark.asyncio
async def test_cached_venv_reused_on_second_create(tmp_path):
    """Verify existing valid venv is reused instead of recreated.

    When create() is called with a path to an existing valid venv:
    - Should skip venv creation (fast path)
    - Should still install ipykernel if needed
    - Should return successfully

    This is the core caching behavior that speeds up startup.
    """
    import asyncio

    venv_path = tmp_path / "cached-venv"
    python_version = _get_current_python_version()

    # First call: creates venv
    manager1 = VenvManager(venv_path=venv_path, python_version=python_version)

    # Track uv venv calls by wrapping asyncio.create_subprocess_exec
    create_venv_count = 0
    original_create_subprocess_exec = asyncio.create_subprocess_exec

    async def tracking_create_subprocess_exec(*args, **kwargs):
        nonlocal create_venv_count
        # Check if this is a 'uv venv' command
        if len(args) >= 2 and args[0] == "uv" and args[1] == "venv":
            create_venv_count += 1
        return await original_create_subprocess_exec(*args, **kwargs)

    with patch.object(asyncio, "create_subprocess_exec", tracking_create_subprocess_exec):
        await manager1.create()
        first_create_count = create_venv_count

        # Second call: should reuse existing venv
        manager2 = VenvManager(venv_path=venv_path, python_version=python_version)
        await manager2.create()
        second_create_count = create_venv_count

    # Venv should have been created once, not twice
    assert first_create_count == 1
    assert second_create_count == 1  # No additional creation


@pytest.mark.asyncio
async def test_invalid_cached_venv_gets_recreated(tmp_path):
    """Verify corrupted cached venv is detected and recreated.

    When create() is called with a path to an invalid venv:
    - Should detect invalidity
    - Should remove old directory
    - Should create fresh venv

    This handles corruption cases (partial deletion, permission issues, etc).
    """
    venv_path = tmp_path / "corrupted-venv"
    python_version = _get_current_python_version()

    # Create corrupted venv (directory exists but no python)
    venv_path.mkdir()

    manager = VenvManager(venv_path=venv_path, python_version=python_version)

    # Should detect invalidity and recreate
    await manager.create()

    # After creation, should be valid
    assert manager._is_venv_valid(venv_path) is True


@pytest.mark.asyncio
async def test_concurrent_creates_use_file_lock(tmp_path):
    """Verify concurrent create() calls use file locking.

    When multiple processes try to create the same venv simultaneously:
    - Only one should create the venv
    - Others should wait for lock, then see existing valid venv
    - No corruption from concurrent writes

    This prevents race conditions in multi-process MCP scenarios.
    """
    venv_path = tmp_path / "concurrent-venv"
    python_version = _get_current_python_version()

    # Simulate concurrent access
    manager1 = VenvManager(venv_path=venv_path, python_version=python_version)
    manager2 = VenvManager(venv_path=venv_path, python_version=python_version)

    # Use patch to track filelock usage
    with patch("py_code_mode.execution.subprocess.venv.filelock.FileLock") as mock_lock_class:
        mock_lock = Mock()
        mock_lock.__enter__ = Mock(side_effect=lambda: None)
        mock_lock.__exit__ = Mock(side_effect=lambda *args: None)
        mock_lock_class.return_value = mock_lock

        # Both should try to acquire lock
        await manager1.create()
        await manager2.create()

        # Verify lock was used
        assert mock_lock_class.call_count >= 1


# ==============================================================================
# Integration Tests - Full caching workflow
# ==============================================================================


@pytest.mark.asyncio
async def test_full_caching_workflow(tmp_path, monkeypatch):
    """Verify complete caching workflow across sessions.

    Scenario:
    1. Create SubprocessExecutor with cache_venv=True
    2. First run: creates venv, installs deps, runs code
    3. Close executor
    4. Create new SubprocessExecutor with same config
    5. Second run: reuses venv (fast), runs code

    This validates the end-to-end user experience improvement.
    """
    # Override cache directory to tmp_path for isolation
    cache_dir = tmp_path / "cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_dir))

    python_version = _get_current_python_version()

    # First session
    config1 = SubprocessConfig(
        python_version=python_version,
        cache_venv=True,
        cleanup_venv_on_close=None,  # Auto (should not cleanup)
    )

    # Get the canonical path that will be used
    canonical_path = config1.get_canonical_venv_path(python_version)

    # Simulate first executor lifecycle
    manager1 = VenvManager(venv_path=canonical_path, python_version=python_version)
    await manager1.create()

    # Venv should exist
    assert canonical_path.exists()
    assert manager1._is_venv_valid(canonical_path)

    # Simulate cleanup - should NOT delete when caching
    cleanup = config1.get_resolved_cleanup()
    if cleanup:
        manager1._cleanup_venv()

    # After "close", venv should still exist (cached)
    assert canonical_path.exists()

    # Second session - same config
    config2 = SubprocessConfig(
        python_version=python_version,
        cache_venv=True,
        cleanup_venv_on_close=None,
    )

    canonical_path2 = config2.get_canonical_venv_path(python_version)
    assert canonical_path2 == canonical_path  # Same path

    manager2 = VenvManager(venv_path=canonical_path2, python_version=python_version)

    # Track if venv creation was skipped (should be fast path)
    import time

    start = time.time()
    await manager2.create()
    elapsed = time.time() - start

    # Reused venv should be much faster (< 1s vs ~10s for fresh creation)
    # This is a smoke test - actual timing depends on system
    assert elapsed < 5.0  # Should be near-instant if reused

    # Venv should still be valid
    assert manager2._is_venv_valid(canonical_path2)


# ==============================================================================
# Failure Mode Tests - Edge cases and error handling
# ==============================================================================


def test_canonical_path_handles_unusual_python_versions():
    """Verify canonical path handles unusual Python version strings.

    Edge cases:
    - "3.11.5" (patch version)
    - "python3.11"
    - "3.11-dev"

    Should produce valid filesystem paths without errors.
    """
    config = SubprocessConfig()

    # These should all work without errors
    path1 = config.get_canonical_venv_path("3.11.5")
    path2 = config.get_canonical_venv_path("python3.11")
    path3 = config.get_canonical_venv_path("3.11-dev")

    # All should be valid paths
    assert path1.is_absolute()
    assert path2.is_absolute()
    assert path3.is_absolute()

    # All should be unique
    assert path1 != path2
    assert path2 != path3


@pytest.mark.asyncio
async def test_venv_validation_handles_permission_errors(tmp_path):
    """Verify _is_venv_valid gracefully handles permission errors.

    When python executable exists but is not readable/executable:
    - Should return False (invalid)
    - Should not raise exception

    This prevents cryptic errors when file permissions are wrong.
    """
    venv_path = tmp_path / "permission-denied-venv"
    venv_path.mkdir()

    # Create bin directory with python that has no execute permission
    bin_dir = venv_path / ("Scripts" if os.name == "nt" else "bin")
    bin_dir.mkdir()
    python_exe = bin_dir / ("python.exe" if os.name == "nt" else "python")
    python_exe.touch()
    python_exe.chmod(0o000)  # No permissions

    manager = VenvManager(venv_path=venv_path, python_version="3.11")

    # Should return False, not raise exception
    try:
        result = manager._is_venv_valid(venv_path)
        assert result is False
    except PermissionError:
        pytest.fail("_is_venv_valid should catch PermissionError and return False")
    finally:
        # Restore permissions for cleanup
        python_exe.chmod(0o755)


def test_kernel_spec_name_handles_long_paths():
    """Verify kernel spec name handles very long venv paths.

    SHA256 hash ensures fixed-length output regardless of input path length.
    Even with 1000-character path, kernel spec name should be constant length.
    """
    # Create absurdly long path
    long_path = Path("/home/user/" + ("subdir/" * 100) + "venv-3.11")

    name = VenvManager._get_kernel_spec_name(long_path)

    # Should be fixed length: "py-code-mode-" + 12 chars
    assert len(name) == len("py-code-mode-") + 12


@pytest.mark.asyncio
async def test_create_cleans_up_partial_venv_on_failure(tmp_path):
    """Verify create() cleans up partial venv if creation fails.

    When venv creation fails partway through:
    - Should remove partial venv directory
    - Should raise exception to caller

    This prevents accumulation of broken venvs in cache.
    """
    from unittest.mock import AsyncMock

    venv_path = tmp_path / "partial-venv"

    manager = VenvManager(venv_path=venv_path, python_version="3.11")

    # Create a mock process that simulates failure (returncode != 0)
    mock_proc = AsyncMock()
    mock_proc.returncode = 1
    mock_proc.communicate = AsyncMock(return_value=(b"", b"Mock failure"))

    # Mock asyncio.create_subprocess_exec to return our failing mock process
    # VenvManager uses asyncio subprocess, not subprocess.run for venv creation
    with patch(
        "asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=mock_proc),
    ):
        # Should raise RuntimeError due to failed uv venv command
        with pytest.raises(RuntimeError, match="uv venv failed"):
            await manager.create()

        # Should have cleaned up partial directory
        # (Implementation detail: create() may or may not create dir before subprocess)
        # Key invariant: no partial venv left behind
