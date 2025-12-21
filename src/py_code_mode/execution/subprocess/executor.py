"""Subprocess-based code execution using IPython kernel."""

from __future__ import annotations

import asyncio
import sys
from typing import Any

from jupyter_client import AsyncKernelManager

from py_code_mode.execution.protocol import (
    Capability,
    FileStorageAccess,
    StorageAccess,
)
from py_code_mode.execution.subprocess.config import SubprocessConfig
from py_code_mode.execution.subprocess.venv import KernelVenv, VenvManager
from py_code_mode.types import ExecutionResult


def _get_current_python_version() -> str:
    """Get current Python version in major.minor format."""
    return f"{sys.version_info.major}.{sys.version_info.minor}"


class SubprocessExecutor:
    """Execute code in an isolated subprocess with its own venv and IPython kernel.

    Capabilities:
    - TIMEOUT: Yes (via message wait timeout)
    - PROCESS_ISOLATION: Yes (code runs in subprocess)
    - NETWORK_ISOLATION: No
    - FILESYSTEM_ISOLATION: No
    - RESET: Yes (kernel restart)

    Usage:
        config = SubprocessConfig(python_version="3.11", venv_path=Path("./venv"))
        async with SubprocessExecutor(config=config) as executor:
            result = await executor.run("1 + 1")
    """

    _CAPABILITIES = frozenset(
        {
            Capability.TIMEOUT,
            Capability.PROCESS_ISOLATION,
            Capability.RESET,
        }
    )

    def __init__(self, config: SubprocessConfig | None = None) -> None:
        """Initialize SubprocessExecutor.

        Args:
            config: Configuration for venv and kernel. Uses defaults if None.
        """
        self._config = config or SubprocessConfig(python_version=_get_current_python_version())
        self._venv_manager: VenvManager | None = None
        self._venv: KernelVenv | None = None
        self._km: AsyncKernelManager | None = None
        self._kc: Any = None  # AsyncKernelClient
        self._closed = False
        self._storage_access: StorageAccess | None = None

    def supports(self, capability: str) -> bool:
        """Check if this backend supports a capability."""
        return capability in self._CAPABILITIES

    def supported_capabilities(self) -> set[str]:
        """Return set of all capabilities this backend supports."""
        return set(self._CAPABILITIES)

    async def start(self, storage_access: StorageAccess | None = None) -> None:
        """Start kernel: create venv, start kernel, inject namespaces.

        Args:
            storage_access: Optional storage access for namespace injection.

        Raises:
            RuntimeError: If already started.
        """
        if self._km is not None:
            raise RuntimeError("Executor already started")

        self._storage_access = storage_access

        # 1. Create venv with VenvManager
        self._venv_manager = VenvManager(self._config)
        self._venv = await self._venv_manager.create()

        # 2. Start kernel
        self._km = AsyncKernelManager(kernel_name=self._venv.kernel_spec_name)
        await self._km.start_kernel()

        # 3. Connect client
        self._kc = self._km.client()
        self._kc.start_channels()
        await self._kc.wait_for_ready(timeout=self._config.startup_timeout)

        # 4. Inject namespaces if storage_access provided
        await self._setup_namespaces()

    async def run(self, code: str, timeout: float | None = None) -> ExecutionResult:
        """Execute code in kernel, return result.

        Args:
            code: Python code to execute.
            timeout: Optional timeout in seconds. Uses config default if None.

        Returns:
            ExecutionResult with value, stdout, and error fields.
        """
        if self._closed or self._kc is None:
            return ExecutionResult(value=None, stdout="", error="Executor is closed")

        timeout = timeout if timeout is not None else self._config.default_timeout

        # Send execute request
        msg_id = self._kc.execute(code, store_history=True)

        # Collect output from IOPub channel
        stdout_parts: list[str] = []
        value: Any = None
        error: str | None = None

        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout

        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return ExecutionResult(
                    value=None,
                    stdout="".join(stdout_parts),
                    error=f"Timeout after {timeout}s",
                )

            try:
                msg = await asyncio.wait_for(
                    self._kc.get_iopub_msg(),
                    timeout=remaining,
                )
            except TimeoutError:
                return ExecutionResult(
                    value=None,
                    stdout="".join(stdout_parts),
                    error=f"Timeout after {timeout}s",
                )

            parent_msg_id = msg.get("parent_header", {}).get("msg_id")
            if parent_msg_id != msg_id:
                continue

            msg_type = msg["header"]["msg_type"]
            content = msg["content"]

            if msg_type == "stream" and content.get("name") == "stdout":
                stdout_parts.append(content["text"])
            elif msg_type == "execute_result":
                value = content["data"].get("text/plain")
            elif msg_type == "error":
                error = "\n".join(content["traceback"])
            elif msg_type == "status" and content.get("execution_state") == "idle":
                break

        return ExecutionResult(value=value, stdout="".join(stdout_parts), error=error)

    async def reset(self) -> None:
        """Clear kernel state by restarting.

        This clears all user-defined variables but re-injects namespaces.
        """
        if self._km is not None:
            await self._km.restart_kernel()
            if self._kc is not None:
                await self._kc.wait_for_ready(timeout=self._config.startup_timeout)
            await self._setup_namespaces()

    async def close(self) -> None:
        """Shutdown kernel and cleanup venv."""
        self._closed = True

        if self._kc is not None:
            self._kc.stop_channels()
            self._kc = None

        if self._km is not None:
            await self._km.shutdown_kernel()
            self._km = None

        if (
            self._config.cleanup_venv_on_close
            and self._venv is not None
            and self._venv_manager is not None
        ):
            await self._venv_manager.cleanup(self._venv)
            self._venv = None

    async def _setup_namespaces(self) -> None:
        """Inject tools/skills/artifacts namespaces into kernel."""
        if self._storage_access is None:
            return

        if isinstance(self._storage_access, FileStorageAccess):
            # Generate code to inject namespaces
            setup_code = self._generate_namespace_setup_code(self._storage_access)
            if setup_code:
                # Run setup code silently (no timeout since it's internal)
                await self._run_setup_code(setup_code)

    def _generate_namespace_setup_code(self, storage_access: FileStorageAccess) -> str:
        """Generate Python code to set up namespaces in the kernel.

        Uses simple stub classes that don't require py-code-mode to be installed
        in the kernel's venv. The stubs provide basic functionality and can be
        replaced with full implementations if py-code-mode is available.
        """
        tools_path_str = (
            repr(str(storage_access.tools_path)) if storage_access.tools_path else "None"
        )
        skills_path_str = (
            repr(str(storage_access.skills_path)) if storage_access.skills_path else "None"
        )
        artifacts_path_str = repr(str(storage_access.artifacts_path))

        # Use simple stub classes that don't require py-code-mode
        code = f'''
# Namespace setup for SubprocessExecutor
# Uses simple stub classes - no external dependencies required
import json
from pathlib import Path

# Simple tools namespace stub
class ToolsNamespaceStub:
    """Minimal tools namespace for subprocess kernel."""
    def __init__(self, tools_path):
        self._tools_path = tools_path

    def list(self):
        """List available tools."""
        if self._tools_path and self._tools_path.exists():
            return [f.stem for f in self._tools_path.glob("*.yaml")]
        return []

    def __repr__(self):
        return f"<ToolsNamespace tools={{len(self.list())}}>"

_tools_path = Path({tools_path_str}) if {tools_path_str} else None
tools = ToolsNamespaceStub(_tools_path)

# Simple skills namespace stub
class SkillsNamespaceStub:
    """Minimal skills namespace for subprocess kernel."""
    def __init__(self, skills_path):
        self._skills_path = skills_path

    def list(self):
        """List available skills."""
        if self._skills_path and self._skills_path.exists():
            return [f.stem for f in self._skills_path.glob("*.py")]
        return []

    def search(self, query, limit=5):
        """Search skills (basic name matching)."""
        all_skills = self.list()
        return [s for s in all_skills if query.lower() in s.lower()][:limit]

    def __repr__(self):
        return f"<SkillsNamespace skills={{len(self.list())}}>"

_skills_path = Path({skills_path_str}) if {skills_path_str} else None
if _skills_path:
    _skills_path.mkdir(parents=True, exist_ok=True)
skills = SkillsNamespaceStub(_skills_path)

# Simple artifacts namespace stub
class ArtifactsNamespaceStub:
    """Minimal artifacts namespace for subprocess kernel."""
    def __init__(self, artifacts_path):
        self._path = artifacts_path
        if self._path:
            self._path.mkdir(parents=True, exist_ok=True)

    def save(self, name, data):
        """Save artifact to file."""
        if self._path:
            filepath = self._path / name
            if isinstance(data, (dict, list)):
                filepath.write_text(json.dumps(data))
            elif isinstance(data, bytes):
                filepath.write_bytes(data)
            else:
                filepath.write_text(str(data))

    def load(self, name):
        """Load artifact from file."""
        if self._path:
            filepath = self._path / name
            if filepath.exists():
                content = filepath.read_text()
                try:
                    return json.loads(content)
                except json.JSONDecodeError:
                    return content
        return None

    def list(self):
        """List available artifacts."""
        if self._path and self._path.exists():
            return [f.name for f in self._path.iterdir() if f.is_file()]
        return []

    def __repr__(self):
        return f"<ArtifactsNamespace artifacts={{len(self.list())}}>"

_artifacts_path = Path({artifacts_path_str})
artifacts = ArtifactsNamespaceStub(_artifacts_path)

# Cleanup internal variables
del _tools_path, _skills_path, _artifacts_path
del ToolsNamespaceStub, SkillsNamespaceStub, ArtifactsNamespaceStub
'''
        return code

    async def _run_setup_code(self, code: str) -> None:
        """Run setup code in the kernel, ignoring errors."""
        if self._kc is None:
            return

        msg_id = self._kc.execute(code, store_history=False, silent=True)

        # Wait for completion
        deadline = asyncio.get_event_loop().time() + self._config.startup_timeout

        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                break

            try:
                msg = await asyncio.wait_for(
                    self._kc.get_iopub_msg(),
                    timeout=remaining,
                )
            except TimeoutError:
                break

            parent_msg_id = msg.get("parent_header", {}).get("msg_id")
            if parent_msg_id != msg_id:
                continue

            msg_type = msg["header"]["msg_type"]
            content = msg["content"]

            if msg_type == "status" and content.get("execution_state") == "idle":
                break

    async def __aenter__(self) -> SubprocessExecutor:
        """Support async context manager."""
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Close on context exit."""
        await self.close()
