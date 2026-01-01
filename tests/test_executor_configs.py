"""Tests for executor configuration dataclasses.

These tests validate the new config fields added as part of the executor/storage
responsibility split (WS-1: Config Fields).

New fields added to all 3 executor configs:
- tools_path: Path | None - Path to directory with YAML tool definitions
- deps: tuple[str, ...] | None - List of package specs
- deps_file: Path | None - Path to requirements.txt-style file
- ipc_timeout: float - Timeout for IPC queries (default 30.0)
"""

from __future__ import annotations

from pathlib import Path

import pytest


class TestInProcessConfig:
    """Tests for InProcessConfig fields."""

    def test_tools_path_default_is_none(self) -> None:
        """tools_path defaults to None.

        Contract: InProcessConfig().tools_path is None
        Breaks when: Default changed or field missing.
        """
        from py_code_mode.execution import InProcessConfig

        config = InProcessConfig()
        assert config.tools_path is None

    def test_tools_path_accepts_path(self, tmp_path: Path) -> None:
        """tools_path accepts a Path value.

        Contract: InProcessConfig(tools_path=path).tools_path == path
        Breaks when: Field missing or wrong type.
        """
        from py_code_mode.execution import InProcessConfig

        config = InProcessConfig(tools_path=tmp_path)
        assert config.tools_path == tmp_path

    def test_deps_default_is_none(self) -> None:
        """deps defaults to None.

        Contract: InProcessConfig().deps is None
        Breaks when: Default changed or field missing.
        """
        from py_code_mode.execution import InProcessConfig

        config = InProcessConfig()
        assert config.deps is None

    def test_deps_accepts_tuple(self) -> None:
        """deps accepts a tuple of package specs.

        Contract: InProcessConfig(deps=(...)).deps matches input
        Breaks when: Field missing or wrong type.
        """
        from py_code_mode.execution import InProcessConfig

        deps = ("pandas>=2.0", "numpy")
        config = InProcessConfig(deps=deps)
        assert config.deps == deps

    def test_deps_file_default_is_none(self) -> None:
        """deps_file defaults to None.

        Contract: InProcessConfig().deps_file is None
        Breaks when: Default changed or field missing.
        """
        from py_code_mode.execution import InProcessConfig

        config = InProcessConfig()
        assert config.deps_file is None

    def test_deps_file_accepts_path(self, tmp_path: Path) -> None:
        """deps_file accepts a Path value.

        Contract: InProcessConfig(deps_file=path).deps_file == path
        Breaks when: Field missing or wrong type.
        """
        from py_code_mode.execution import InProcessConfig

        deps_file = tmp_path / "requirements.txt"
        config = InProcessConfig(deps_file=deps_file)
        assert config.deps_file == deps_file

    def test_ipc_timeout_default_is_30(self) -> None:
        """ipc_timeout defaults to 30.0 seconds.

        Contract: InProcessConfig().ipc_timeout == 30.0
        Breaks when: Default changed or field missing.
        """
        from py_code_mode.execution import InProcessConfig

        config = InProcessConfig()
        assert config.ipc_timeout == 30.0

    def test_ipc_timeout_accepts_custom_value(self) -> None:
        """ipc_timeout accepts a custom value.

        Contract: InProcessConfig(ipc_timeout=60.0).ipc_timeout == 60.0
        Breaks when: Field missing or not settable.
        """
        from py_code_mode.execution import InProcessConfig

        config = InProcessConfig(ipc_timeout=60.0)
        assert config.ipc_timeout == 60.0

    def test_existing_fields_preserved(self) -> None:
        """Existing fields (default_timeout, allow_runtime_deps) still work.

        Contract: Backward compatibility with existing config usage.
        Breaks when: Existing fields removed or renamed.
        """
        from py_code_mode.execution import InProcessConfig

        config = InProcessConfig(default_timeout=45.0, allow_runtime_deps=False)
        assert config.default_timeout == 45.0
        assert config.allow_runtime_deps is False

    def test_config_is_frozen(self) -> None:
        """InProcessConfig is immutable (frozen dataclass).

        Contract: Cannot modify config after creation.
        Breaks when: frozen=True removed from dataclass.
        """
        from py_code_mode.execution import InProcessConfig

        config = InProcessConfig()
        with pytest.raises(AttributeError):
            config.tools_path = Path("/some/path")  # type: ignore[misc]


class TestSubprocessConfig:
    """Tests for SubprocessConfig fields."""

    def test_tools_path_default_is_none(self) -> None:
        """tools_path defaults to None.

        Contract: SubprocessConfig().tools_path is None
        Breaks when: Default changed or field missing.
        """
        from py_code_mode.execution import SubprocessConfig

        config = SubprocessConfig()
        assert config.tools_path is None

    def test_tools_path_accepts_path(self, tmp_path: Path) -> None:
        """tools_path accepts a Path value.

        Contract: SubprocessConfig(tools_path=path).tools_path == path
        Breaks when: Field missing or wrong type.
        """
        from py_code_mode.execution import SubprocessConfig

        config = SubprocessConfig(tools_path=tmp_path)
        assert config.tools_path == tmp_path

    def test_deps_default_is_none(self) -> None:
        """deps defaults to None (distinct from base_deps).

        Contract: SubprocessConfig().deps is None
        Breaks when: Default changed or field missing.

        Note: base_deps is for kernel deps (ipykernel, py-code-mode).
        deps is for user-configured deps (pandas, numpy, etc.).
        """
        from py_code_mode.execution import SubprocessConfig

        config = SubprocessConfig()
        assert config.deps is None
        # base_deps still has its default
        assert config.base_deps == ("ipykernel", "py-code-mode")

    def test_deps_accepts_tuple(self) -> None:
        """deps accepts a tuple of package specs.

        Contract: SubprocessConfig(deps=(...)).deps matches input
        Breaks when: Field missing or wrong type.
        """
        from py_code_mode.execution import SubprocessConfig

        deps = ("pandas>=2.0", "numpy")
        config = SubprocessConfig(deps=deps)
        assert config.deps == deps

    def test_deps_file_default_is_none(self) -> None:
        """deps_file defaults to None.

        Contract: SubprocessConfig().deps_file is None
        Breaks when: Default changed or field missing.
        """
        from py_code_mode.execution import SubprocessConfig

        config = SubprocessConfig()
        assert config.deps_file is None

    def test_deps_file_accepts_path(self, tmp_path: Path) -> None:
        """deps_file accepts a Path value.

        Contract: SubprocessConfig(deps_file=path).deps_file == path
        Breaks when: Field missing or wrong type.
        """
        from py_code_mode.execution import SubprocessConfig

        deps_file = tmp_path / "requirements.txt"
        config = SubprocessConfig(deps_file=deps_file)
        assert config.deps_file == deps_file

    def test_ipc_timeout_default_is_30(self) -> None:
        """ipc_timeout defaults to 30.0 seconds.

        Contract: SubprocessConfig().ipc_timeout == 30.0
        Breaks when: Default changed or field missing.
        """
        from py_code_mode.execution import SubprocessConfig

        config = SubprocessConfig()
        assert config.ipc_timeout == 30.0

    def test_ipc_timeout_accepts_custom_value(self) -> None:
        """ipc_timeout accepts a custom value.

        Contract: SubprocessConfig(ipc_timeout=60.0).ipc_timeout == 60.0
        Breaks when: Field missing or not settable.
        """
        from py_code_mode.execution import SubprocessConfig

        config = SubprocessConfig(ipc_timeout=60.0)
        assert config.ipc_timeout == 60.0

    def test_existing_fields_preserved(self) -> None:
        """Existing fields (python_version, base_deps, etc.) still work.

        Contract: Backward compatibility with existing config usage.
        Breaks when: Existing fields removed or renamed.
        """
        from py_code_mode.execution import SubprocessConfig

        config = SubprocessConfig(
            python_version="3.11",
            startup_timeout=45.0,
            default_timeout=90.0,
            allow_runtime_deps=False,
            cache_venv=False,
        )
        assert config.python_version == "3.11"
        assert config.startup_timeout == 45.0
        assert config.default_timeout == 90.0
        assert config.allow_runtime_deps is False
        assert config.cache_venv is False

    def test_config_is_frozen(self) -> None:
        """SubprocessConfig is immutable (frozen dataclass).

        Contract: Cannot modify config after creation.
        Breaks when: frozen=True removed from dataclass.
        """
        from py_code_mode.execution import SubprocessConfig

        config = SubprocessConfig()
        with pytest.raises(AttributeError):
            config.tools_path = Path("/some/path")  # type: ignore[misc]


class TestContainerConfig:
    """Tests for ContainerConfig fields."""

    def test_tools_path_default_is_none(self) -> None:
        """tools_path defaults to None.

        Contract: ContainerConfig().tools_path is None
        Breaks when: Default changed or field missing.
        """
        from py_code_mode.execution import ContainerConfig

        config = ContainerConfig()
        assert config.tools_path is None

    def test_tools_path_accepts_path(self, tmp_path: Path) -> None:
        """tools_path accepts a Path value.

        Contract: ContainerConfig(tools_path=path).tools_path == path
        Breaks when: Field missing or wrong type.
        """
        from py_code_mode.execution import ContainerConfig

        config = ContainerConfig(tools_path=tmp_path)
        assert config.tools_path == tmp_path

    def test_deps_default_is_none(self) -> None:
        """deps defaults to None.

        Contract: ContainerConfig().deps is None
        Breaks when: Default changed or field missing.
        """
        from py_code_mode.execution import ContainerConfig

        config = ContainerConfig()
        assert config.deps is None

    def test_deps_accepts_tuple(self) -> None:
        """deps accepts a tuple of package specs.

        Contract: ContainerConfig(deps=(...)).deps matches input
        Breaks when: Field missing or wrong type.
        """
        from py_code_mode.execution import ContainerConfig

        deps = ("pandas>=2.0", "numpy")
        config = ContainerConfig(deps=deps)
        assert config.deps == deps

    def test_deps_file_default_is_none(self) -> None:
        """deps_file defaults to None.

        Contract: ContainerConfig().deps_file is None
        Breaks when: Default changed or field missing.
        """
        from py_code_mode.execution import ContainerConfig

        config = ContainerConfig()
        assert config.deps_file is None

    def test_deps_file_accepts_path(self, tmp_path: Path) -> None:
        """deps_file accepts a Path value.

        Contract: ContainerConfig(deps_file=path).deps_file == path
        Breaks when: Field missing or wrong type.
        """
        from py_code_mode.execution import ContainerConfig

        deps_file = tmp_path / "requirements.txt"
        config = ContainerConfig(deps_file=deps_file)
        assert config.deps_file == deps_file

    def test_ipc_timeout_default_is_30(self) -> None:
        """ipc_timeout defaults to 30.0 seconds.

        Contract: ContainerConfig().ipc_timeout == 30.0
        Breaks when: Default changed or field missing.
        """
        from py_code_mode.execution import ContainerConfig

        config = ContainerConfig()
        assert config.ipc_timeout == 30.0

    def test_ipc_timeout_accepts_custom_value(self) -> None:
        """ipc_timeout accepts a custom value.

        Contract: ContainerConfig(ipc_timeout=60.0).ipc_timeout == 60.0
        Breaks when: Field missing or not settable.
        """
        from py_code_mode.execution import ContainerConfig

        config = ContainerConfig(ipc_timeout=60.0)
        assert config.ipc_timeout == 60.0

    def test_existing_fields_preserved(self) -> None:
        """Existing fields (image, port, timeout, etc.) still work.

        Contract: Backward compatibility with existing config usage.
        Breaks when: Existing fields removed or renamed.
        """
        from py_code_mode.execution import ContainerConfig

        config = ContainerConfig(
            image="custom:latest",
            port=9000,
            timeout=45.0,
            startup_timeout=90.0,
            allow_runtime_deps=False,
            auth_disabled=True,
        )
        assert config.image == "custom:latest"
        assert config.port == 9000
        assert config.timeout == 45.0
        assert config.startup_timeout == 90.0
        assert config.allow_runtime_deps is False
        assert config.auth_disabled is True

    def test_to_docker_config_includes_tools_path(self, tmp_path: Path) -> None:
        """to_docker_config() includes tools_path as volume mount.

        Contract: When tools_path is set, it appears in volumes.
        Breaks when: to_docker_config doesn't handle tools_path.
        """
        from py_code_mode.execution import ContainerConfig

        tools_path = tmp_path / "tools"
        tools_path.mkdir()

        config = ContainerConfig(tools_path=tools_path, auth_disabled=True)
        docker_config = config.to_docker_config()

        # tools_path should create a volume mount
        assert "volumes" in docker_config
        assert str(tools_path.absolute()) in docker_config["volumes"]
        assert docker_config["environment"].get("TOOLS_PATH") == "/app/tools"

    def test_to_docker_config_includes_deps_file(self, tmp_path: Path) -> None:
        """to_docker_config() includes deps_file as volume mount.

        Contract: When deps_file is set, it appears in volumes.
        Breaks when: to_docker_config doesn't handle deps_file.
        """
        from py_code_mode.execution import ContainerConfig

        deps_file = tmp_path / "requirements.txt"
        deps_file.write_text("pandas>=2.0\n")

        config = ContainerConfig(deps_file=deps_file, auth_disabled=True)
        docker_config = config.to_docker_config()

        # deps_file should create a volume mount
        assert "volumes" in docker_config
        # The file's parent directory should be mounted
        assert str(deps_file.parent.absolute()) in docker_config["volumes"]


class TestAllConfigsHaveNewFields:
    """Cross-cutting tests to ensure all configs have the new fields."""

    def test_all_configs_have_tools_path(self) -> None:
        """All executor configs have tools_path field.

        Contract: Consistent API across all executors.
        Breaks when: Any config missing the field.
        """
        from py_code_mode.execution import ContainerConfig, InProcessConfig, SubprocessConfig

        assert hasattr(InProcessConfig(), "tools_path")
        assert hasattr(SubprocessConfig(), "tools_path")
        assert hasattr(ContainerConfig(), "tools_path")

    def test_all_configs_have_deps(self) -> None:
        """All executor configs have deps field.

        Contract: Consistent API across all executors.
        Breaks when: Any config missing the field.
        """
        from py_code_mode.execution import ContainerConfig, InProcessConfig, SubprocessConfig

        assert hasattr(InProcessConfig(), "deps")
        assert hasattr(SubprocessConfig(), "deps")
        assert hasattr(ContainerConfig(), "deps")

    def test_all_configs_have_deps_file(self) -> None:
        """All executor configs have deps_file field.

        Contract: Consistent API across all executors.
        Breaks when: Any config missing the field.
        """
        from py_code_mode.execution import ContainerConfig, InProcessConfig, SubprocessConfig

        assert hasattr(InProcessConfig(), "deps_file")
        assert hasattr(SubprocessConfig(), "deps_file")
        assert hasattr(ContainerConfig(), "deps_file")

    def test_all_configs_have_ipc_timeout(self) -> None:
        """All executor configs have ipc_timeout field.

        Contract: Consistent API across all executors.
        Breaks when: Any config missing the field.
        """
        from py_code_mode.execution import ContainerConfig, InProcessConfig, SubprocessConfig

        assert hasattr(InProcessConfig(), "ipc_timeout")
        assert hasattr(SubprocessConfig(), "ipc_timeout")
        assert hasattr(ContainerConfig(), "ipc_timeout")

    def test_all_configs_ipc_timeout_default_30(self) -> None:
        """All executor configs have ipc_timeout default of 30.0.

        Contract: Consistent default across all executors.
        Breaks when: Any config has different default.
        """
        from py_code_mode.execution import ContainerConfig, InProcessConfig, SubprocessConfig

        assert InProcessConfig().ipc_timeout == 30.0
        assert SubprocessConfig().ipc_timeout == 30.0
        assert ContainerConfig().ipc_timeout == 30.0
