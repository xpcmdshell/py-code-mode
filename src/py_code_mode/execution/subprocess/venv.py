"""Virtual environment management for SubprocessExecutor."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import sys
import tempfile
import uuid
from dataclasses import dataclass
from importlib.metadata import distribution
from pathlib import Path

import py_code_mode
from py_code_mode.execution.subprocess.config import SubprocessConfig

# Pattern for valid package specifiers
# Allows: package-name, package_name, package.name, package[extras], package>=1.0
_PACKAGE_PATTERN = re.compile(
    r"^[a-zA-Z0-9_.-]+(\[[a-zA-Z0-9_,.-]+\])?([<>=!~][a-zA-Z0-9_.,<>=!~*]*)?$"
)


def _validate_package_spec(package: str) -> None:
    """Validate package specifier to prevent argument injection.

    Args:
        package: Package specifier to validate.

    Raises:
        ValueError: If the package specifier is invalid or potentially malicious.
    """
    if package.startswith("-"):
        raise ValueError(f"Invalid package specifier (starts with -): {package}")
    if not _PACKAGE_PATTERN.match(package):
        raise ValueError(f"Invalid package specifier: {package}")


@dataclass
class KernelVenv:
    """Represents a virtual environment with an installed IPython kernel.

    Attributes:
        path: Path to the venv directory.
        python_path: Path to the Python executable within the venv.
        kernel_spec_name: Name of the installed kernel spec.
    """

    path: Path
    python_path: Path
    kernel_spec_name: str


class VenvManager:
    """Manages uv-based virtual environments with ipykernel installed."""

    def __init__(self, config: SubprocessConfig) -> None:
        """Initialize VenvManager with configuration.

        Args:
            config: Configuration for venv creation.
        """
        self._config = config

    async def create(self, extra_deps: list[str] | None = None) -> KernelVenv:
        """Create a virtual environment with ipykernel and optional extra deps.

        Args:
            extra_deps: Additional packages to install beyond base_deps.

        Returns:
            KernelVenv with path, python_path, and kernel_spec_name.

        Raises:
            RuntimeError: If uv is not found or venv creation fails.
        """
        # Check for uv
        if shutil.which("uv") is None:
            raise RuntimeError("uv is required but not found in PATH")

        # Determine venv path
        if self._config.venv_path is not None:
            venv_path = self._config.venv_path
        else:
            venv_path = Path(tempfile.mkdtemp(prefix="py-code-mode-venv-"))

        # Determine python path
        if sys.platform == "win32":
            python_path = venv_path / "Scripts" / "python.exe"
        else:
            python_path = venv_path / "bin" / "python"

        # Generate unique kernel spec name
        kernel_spec_name = f"py-code-mode-{uuid.uuid4().hex[:8]}"

        # Create venv with uv
        await self._run_uv(
            ["venv", "--python", self._config.python_version, str(venv_path)],
            error_context="uv venv failed",
        )

        # Validate extra_deps before processing
        if extra_deps:
            for dep in extra_deps:
                _validate_package_spec(dep)

        # Collect all dependencies, separating py-code-mode for special handling
        deps = list(self._config.base_deps)
        if extra_deps:
            deps.extend(extra_deps)

        # Check if py-code-mode is requested - needs special handling
        install_py_code_mode = "py-code-mode" in deps
        other_deps = [d for d in deps if d != "py-code-mode"]

        # Install regular dependencies with uv
        if other_deps:
            await self._run_uv(
                ["pip", "install", "--python", str(python_path), *other_deps],
                error_context="uv pip install failed",
            )

        # Install py-code-mode from local package if requested
        if install_py_code_mode:
            await self._install_py_code_mode(python_path)

            # Also install nest_asyncio for sync tool calls in Jupyter kernel
            await self._run_uv(
                ["pip", "install", "--python", str(python_path), "nest_asyncio"],
                error_context="uv pip install nest_asyncio failed",
            )

        # Install kernel spec
        await self._run_python(
            python_path,
            ["-m", "ipykernel", "install", "--user", "--name", kernel_spec_name],
            error_context="ipykernel install failed",
        )

        return KernelVenv(
            path=venv_path,
            python_path=python_path,
            kernel_spec_name=kernel_spec_name,
        )

    async def _install_py_code_mode(self, python_path: Path) -> None:
        """Install py-code-mode into the subprocess venv.

        Handles two installation scenarios:
        1. Dev mode (pyproject.toml exists): Install editable from source
        2. Git install (direct_url.json with vcs_info): Install from same git URL

        Args:
            python_path: Path to Python executable in the venv.

        Raises:
            RuntimeError: If installation fails or install source cannot be determined.
        """
        # Check for dev mode first (pyproject.toml exists)
        pkg_path = Path(py_code_mode.__file__).parent.parent.parent
        pyproject = pkg_path / "pyproject.toml"

        if pyproject.exists():
            # Dev mode: install editable from source
            await self._run_uv(
                ["pip", "install", "--python", str(python_path), "-e", str(pkg_path)],
                error_context="uv pip install py-code-mode (editable) failed",
            )
            return

        # Not dev mode - check direct_url.json for git install info
        install_spec = self._get_py_code_mode_install_spec()
        await self._run_uv(
            ["pip", "install", "--python", str(python_path), install_spec],
            error_context=f"uv pip install {install_spec} failed",
        )

    def _get_py_code_mode_install_spec(self) -> str:
        """Determine how to install py-code-mode based on current installation.

        Returns:
            A pip install specifier (e.g., "git+https://github.com/...@commit").

        Raises:
            RuntimeError: If the install source cannot be determined.
        """
        dist = distribution("py-code-mode")

        # Check for direct_url.json (PEP 610) to detect VCS/URL installs
        for f in dist.files or []:
            if f.name == "direct_url.json":
                try:
                    direct_url = json.loads(f.read_text())
                    url = direct_url.get("url", "")

                    # VCS install (git, hg, etc.)
                    if "vcs_info" in direct_url:
                        vcs = direct_url["vcs_info"].get("vcs", "git")
                        commit = direct_url["vcs_info"].get("commit_id", "")
                        if commit:
                            return f"{vcs}+{url}@{commit}"
                        return f"{vcs}+{url}"

                    # Direct URL install (not VCS, not local file)
                    if url and not url.startswith("file://"):
                        return url
                except (json.JSONDecodeError, OSError):
                    pass
                break

        raise RuntimeError(
            "Cannot determine py-code-mode install source. "
            "py-code-mode must be installed from git or in editable mode."
        )

    async def add_package(self, venv: KernelVenv, package: str) -> None:
        """Install a package to an existing venv.

        Args:
            venv: The KernelVenv to install the package into.
            package: The package specifier to install (e.g., "requests>=2.28").

        Raises:
            ValueError: If the package specifier is invalid.
            RuntimeError: If package installation fails.
        """
        _validate_package_spec(package)
        await self._run_uv(
            ["pip", "install", "--python", str(venv.python_path), package],
            error_context=f"uv pip install {package} failed",
        )

    async def cleanup(self, venv: KernelVenv) -> None:
        """Remove a venv directory.

        This is idempotent - does not raise if venv doesn't exist.

        Args:
            venv: The KernelVenv to remove.
        """
        shutil.rmtree(venv.path, ignore_errors=True)

    async def _run_uv(self, args: list[str], error_context: str) -> tuple[str, str]:
        """Run a uv command and return stdout/stderr.

        Args:
            args: Arguments to pass to uv.
            error_context: Context message for error reporting.

        Returns:
            Tuple of (stdout, stderr).

        Raises:
            RuntimeError: If the command fails.
        """
        proc = await asyncio.create_subprocess_exec(
            "uv",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(f"{error_context}: {stderr.decode()}")

        return stdout.decode(), stderr.decode()

    async def _run_python(
        self, python_path: Path, args: list[str], error_context: str
    ) -> tuple[str, str]:
        """Run a Python command and return stdout/stderr.

        Args:
            python_path: Path to the Python executable.
            args: Arguments to pass to Python.
            error_context: Context message for error reporting.

        Returns:
            Tuple of (stdout, stderr).

        Raises:
            RuntimeError: If the command fails.
        """
        proc = await asyncio.create_subprocess_exec(
            str(python_path),
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(f"{error_context}: {stderr.decode()}")

        return stdout.decode(), stderr.decode()
