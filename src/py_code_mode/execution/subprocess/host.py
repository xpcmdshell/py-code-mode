"""Host-side kernel manager with async RPC handling.

This module provides KernelHost, which manages a Jupyter kernel with
bidirectional RPC support. The key insight is that the host must NEVER
truly block - it runs an async event loop that handles BOTH execution
completion AND incoming RPC requests concurrently.

The stdin channel (designed for input() calls) carries RPC messages:
- Kernel sends input_request with JSON in prompt field
- Host responds with input_reply containing JSON result
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from queue import Empty
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from jupyter_client import AsyncKernelManager

from py_code_mode.execution.subprocess.kernel_init import get_kernel_init_code
from py_code_mode.execution.subprocess.rpc import RPCRequest, RPCResponse

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _parse_method(method: str) -> tuple[str, str]:
    """Parse RPC method name into namespace and operation.

    Args:
        method: The RPC method name (e.g., "skills.invoke", "tools.call").

    Returns:
        Tuple of (namespace, operation). Returns ("rpc", method) for unknown format.
    """
    if "." in method:
        namespace, operation = method.split(".", 1)
        return namespace, operation
    return "rpc", method


@runtime_checkable
class ResourceProvider(Protocol):
    """Protocol for providing resources to the kernel.

    The host implements this protocol to handle RPC requests from the kernel.
    All methods are async to allow non-blocking I/O operations.
    """

    # Tool methods
    async def call_tool(self, name: str, args: dict[str, Any]) -> Any:
        """Call a tool by name with given arguments."""
        ...

    async def list_tools(self) -> list[dict[str, Any]]:
        """List all available tools."""
        ...

    async def search_tools(self, query: str, limit: int) -> list[dict[str, Any]]:
        """Search tools by query."""
        ...

    async def list_tool_recipes(self, name: str) -> list[dict[str, Any]]:
        """List recipes for a specific tool."""
        ...

    # Skill methods
    async def invoke_skill(self, name: str, args: dict[str, Any]) -> Any:
        """Invoke a skill by name with given arguments."""
        ...

    async def search_skills(self, query: str, limit: int) -> list[dict[str, Any]]:
        """Search for skills matching query."""
        ...

    async def list_skills(self) -> list[dict[str, Any]]:
        """List all available skills."""
        ...

    async def get_skill(self, name: str) -> dict[str, Any] | None:
        """Get a skill by name."""
        ...

    async def create_skill(self, name: str, source: str, description: str) -> dict[str, Any]:
        """Create and save a new skill."""
        ...

    async def delete_skill(self, name: str) -> bool:
        """Delete a skill."""
        ...

    # Artifact methods
    async def load_artifact(self, name: str) -> Any:
        """Load an artifact by name."""
        ...

    async def save_artifact(self, name: str, data: Any, description: str) -> dict[str, Any]:
        """Save an artifact."""
        ...

    async def list_artifacts(self) -> list[dict[str, Any]]:
        """List all artifacts."""
        ...

    async def delete_artifact(self, name: str) -> None:
        """Delete an artifact."""
        ...

    async def artifact_exists(self, name: str) -> bool:
        """Check if an artifact exists."""
        ...

    async def get_artifact(self, name: str) -> dict[str, Any] | None:
        """Get artifact metadata."""
        ...

    # Deps methods
    async def add_dep(self, package: str) -> dict[str, Any]:
        """Add and install a package."""
        ...

    async def remove_dep(self, package: str) -> bool:
        """Remove a package from configuration."""
        ...

    async def list_deps(self) -> list[str]:
        """List configured packages."""
        ...

    async def sync_deps(self) -> dict[str, Any]:
        """Install all configured packages."""
        ...


@dataclass
class ExecutionResult:
    """Result of code execution in the kernel."""

    stdout: str = ""
    stderr: str = ""
    value: Any = None
    error: str | None = None
    traceback: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """Check if execution was successful."""
        return self.error is None


class KernelHost:
    """Manages a Jupyter kernel with bidirectional RPC.

    This class provides:
    - Kernel lifecycle management (start, shutdown)
    - Code execution with RPC support
    - Concurrent handling of stdin (RPC), iopub (output), and shell (completion)

    The key design is that execute() never blocks waiting for shell reply.
    Instead, it spawns concurrent async tasks for each channel and uses
    an asyncio.Event for coordination.

    Usage:
        host = KernelHost()
        await host.start(provider, ipc_timeout=30.0)

        result = await host.execute("tools.curl.get(url='https://example.com')")
        print(result.stdout)

        await host.shutdown()
    """

    def __init__(self) -> None:
        """Initialize KernelHost."""
        self._km: AsyncKernelManager | None = None
        self._kc: Any = None  # AsyncKernelClient
        self._provider: ResourceProvider | None = None
        self._ipc_timeout: float = 30.0

    async def start(
        self,
        provider: ResourceProvider,
        kernel_name: str = "python3",
        startup_timeout: float = 30.0,
        ipc_timeout: float = 30.0,
    ) -> None:
        """Start the kernel and initialize RPC channel.

        Args:
            provider: ResourceProvider for handling RPC requests.
            kernel_name: Jupyter kernel spec name.
            startup_timeout: Timeout for kernel to become ready.
            ipc_timeout: Timeout for IPC/RPC calls.

        Raises:
            RuntimeError: If kernel initialization fails.
        """
        self._provider = provider
        self._ipc_timeout = ipc_timeout

        try:
            # Start kernel
            self._km = AsyncKernelManager(kernel_name=kernel_name)
            await self._km.start_kernel()
            self._kc = self._km.client()
            self._kc.start_channels()

            # Wait for kernel to be ready
            await self._kc.wait_for_ready(timeout=startup_timeout)

            # Initialize RPC in kernel (with allow_stdin=True)
            init_code = get_kernel_init_code(ipc_timeout=ipc_timeout)
            init_result = await self.execute(init_code, allow_stdin=True)
            if not init_result.success:
                raise RuntimeError(f"Failed to initialize kernel RPC: {init_result.error}")
        except Exception:
            await self.shutdown()
            raise

    async def execute(
        self,
        code: str,
        allow_stdin: bool = True,
        timeout: float | None = None,
    ) -> ExecutionResult:
        """Execute code in the kernel, handling RPC requests via stdin.

        Args:
            code: Python code to execute.
            allow_stdin: Whether to allow stdin (RPC). Default: True.
            timeout: Execution timeout. None means no timeout.

        Returns:
            ExecutionResult with stdout, stderr, value, and error fields.
        """
        if self._kc is None:
            return ExecutionResult(error="Kernel not started")

        result = ExecutionResult()
        done_event = asyncio.Event()

        # Send execute request with allow_stdin enabled
        msg_id = self._kc.execute(code, allow_stdin=allow_stdin)

        async def listen_stdin() -> None:
            """Listen for stdin messages (RPC requests)."""
            while not done_event.is_set():
                try:
                    msg = await self._kc.get_stdin_msg(timeout=0.5)
                    await self._handle_stdin_message(msg, msg_id)
                except Empty:
                    # Timeout on queue.get() - normal during polling, continue waiting
                    continue
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    # Log and continue to prevent listener thread crash
                    logger.warning("Error handling stdin message: %s", e)

        async def listen_iopub() -> None:
            """Listen for iopub messages (output, results, errors)."""
            while not done_event.is_set():
                try:
                    msg = await self._kc.get_iopub_msg(timeout=0.5)
                    self._handle_iopub_message(msg, result, msg_id)
                except Empty:
                    # Timeout on queue.get() - normal during polling, continue waiting
                    continue
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    # Log and continue to prevent listener thread crash
                    logger.warning("Error handling iopub message: %s", e)

        async def listen_shell() -> None:
            """Listen for shell messages (execute_reply signals completion)."""
            while not done_event.is_set():
                # Check if kernel died
                if self._km is not None and not await self._km.is_alive():
                    result.error = "Kernel died during execution"
                    done_event.set()
                    return
                try:
                    msg = await self._kc.get_shell_msg(timeout=0.5)
                    if msg["parent_header"].get("msg_id") == msg_id:
                        if msg["msg_type"] == "execute_reply":
                            content = msg["content"]
                            if content["status"] == "error":
                                result.error = content.get("evalue", "Unknown error")
                                result.traceback = content.get("traceback", [])
                            done_event.set()
                except Empty:
                    # Timeout on queue.get() - normal during polling, continue waiting
                    continue
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    # Log and continue to prevent listener thread crash
                    logger.warning("Error handling shell message: %s", e)

        async def timeout_watcher() -> None:
            """Watch for timeout if specified."""
            if timeout is None:
                return
            try:
                await asyncio.sleep(timeout)
                if not done_event.is_set():
                    result.error = f"Execution timed out after {timeout}s"
                    done_event.set()
            except asyncio.CancelledError:
                pass

        # Start concurrent listeners
        stdin_task = asyncio.create_task(listen_stdin())
        iopub_task = asyncio.create_task(listen_iopub())
        shell_task = asyncio.create_task(listen_shell())
        timeout_task = asyncio.create_task(timeout_watcher()) if timeout else None

        try:
            # Wait for execution to complete
            await done_event.wait()
        finally:
            # Cancel all listener tasks
            stdin_task.cancel()
            iopub_task.cancel()
            shell_task.cancel()
            if timeout_task:
                timeout_task.cancel()

            # Wait for tasks to finish cancellation
            tasks = [stdin_task, iopub_task, shell_task]
            if timeout_task:
                tasks.append(timeout_task)

            for task in tasks:
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Drain any remaining iopub messages after execution completes
        try:
            while True:
                iopub_msg = await self._kc.get_iopub_msg(timeout=0.1)
                self._handle_iopub_message(iopub_msg, result, msg_id)
        except Empty:
            # Queue exhausted - all remaining messages processed
            pass

        return result

    def _handle_iopub_message(
        self, msg: dict[str, Any], result: ExecutionResult, exec_msg_id: str
    ) -> None:
        """Handle a message from the iopub channel."""
        msg_type = msg.get("msg_type") or msg.get("header", {}).get("msg_type")
        content = msg.get("content", {})
        parent_msg_id = msg.get("parent_header", {}).get("msg_id")

        if msg_type == "stream":
            text = content.get("text", "")
            if content.get("name") == "stdout":
                result.stdout += text
            elif content.get("name") == "stderr":
                result.stderr += text

        elif msg_type == "execute_result":
            if parent_msg_id == exec_msg_id:
                result.value = content.get("data", {}).get("text/plain")

        elif msg_type == "error":
            if parent_msg_id == exec_msg_id:
                result.error = content.get("evalue", "Unknown error")
                result.traceback = content.get("traceback", [])

    async def _handle_stdin_message(self, msg: dict[str, Any], exec_msg_id: str) -> None:
        """Handle a stdin message - could be RPC request or regular input."""
        if msg["msg_type"] != "input_request":
            return

        content = msg.get("content", {})
        prompt = content.get("prompt", "")

        # Check if this is an RPC request (JSON in prompt)
        try:
            request_data = json.loads(prompt)
            if request_data.get("type") == "rpc_request":
                await self._handle_rpc_request(request_data)
                return
        except json.JSONDecodeError:
            pass

        # Not an RPC request - this would be regular input()
        # Send empty response (we don't support interactive input)
        self._send_input_reply("")

    async def _handle_rpc_request(self, data: dict[str, Any]) -> None:
        """Handle an RPC request from the kernel."""
        if self._provider is None:
            self._send_input_reply(
                json.dumps(RPCResponse(id=data["id"], error="No provider").to_dict())
            )
            return

        request = RPCRequest.from_dict(data)

        try:
            rpc_result = await self._dispatch_rpc(request)
            response = RPCResponse(id=request.id, result=rpc_result)
        except Exception as e:
            namespace, operation = _parse_method(request.method)
            logger.warning("RPC error for %s.%s: %s", namespace, operation, e)
            response = RPCResponse(
                id=request.id,
                error={
                    "namespace": namespace,
                    "operation": operation,
                    "message": str(e),
                    "type": type(e).__name__,
                },
            )

        # Send response back via input_reply
        self._send_input_reply(json.dumps(response.to_dict()))

    async def _dispatch_rpc(self, request: RPCRequest) -> Any:
        """Dispatch an RPC request to the appropriate provider method."""
        if self._provider is None:
            raise RuntimeError("No resource provider configured")

        method = request.method
        params = request.params

        # Tools methods
        if method == "tools.call":
            return await self._provider.call_tool(params["name"], params.get("args", {}))
        elif method == "tools.list":
            return await self._provider.list_tools()
        elif method == "tools.search":
            return await self._provider.search_tools(params["query"], params.get("limit", 10))
        elif method == "tools.list_recipes":
            return await self._provider.list_tool_recipes(params["name"])

        # Skills methods
        elif method == "skills.invoke":
            return await self._provider.invoke_skill(params["name"], params.get("args", {}))
        elif method == "skills.search":
            return await self._provider.search_skills(params["query"], params.get("limit", 5))
        elif method == "skills.list":
            return await self._provider.list_skills()
        elif method == "skills.get":
            return await self._provider.get_skill(params["name"])
        elif method == "skills.create":
            return await self._provider.create_skill(
                params["name"], params["source"], params.get("description", "")
            )
        elif method == "skills.delete":
            return await self._provider.delete_skill(params["name"])

        # Artifacts methods
        elif method == "artifacts.load":
            return await self._provider.load_artifact(params["name"])
        elif method == "artifacts.save":
            return await self._provider.save_artifact(
                params["name"], params["data"], params.get("description", "")
            )
        elif method == "artifacts.list":
            return await self._provider.list_artifacts()
        elif method == "artifacts.delete":
            return await self._provider.delete_artifact(params["name"])
        elif method == "artifacts.exists":
            return await self._provider.artifact_exists(params["name"])
        elif method == "artifacts.get":
            return await self._provider.get_artifact(params["name"])

        # Deps methods
        elif method == "deps.add":
            return await self._provider.add_dep(params["package"])
        elif method == "deps.remove":
            return await self._provider.remove_dep(params["package"])
        elif method == "deps.list":
            return await self._provider.list_deps()
        elif method == "deps.sync":
            return await self._provider.sync_deps()

        else:
            raise ValueError(f"Unknown RPC method: {method}")

    def _send_input_reply(self, value: str) -> None:
        """Send an input_reply message to the kernel."""
        if self._kc is None:
            return
        self._kc.input(value)

    async def restart(self, startup_timeout: float = 30.0) -> None:
        """Restart the kernel and reinitialize RPC.

        Args:
            startup_timeout: Timeout for kernel to become ready.

        Raises:
            RuntimeError: If restart fails.
        """
        if self._km is None:
            raise RuntimeError("Kernel not started")

        await self._km.restart_kernel()
        if self._kc is not None:
            await self._kc.wait_for_ready(timeout=startup_timeout)

        # Reinitialize RPC
        init_code = get_kernel_init_code(ipc_timeout=self._ipc_timeout)
        init_result = await self.execute(init_code, allow_stdin=True)
        if not init_result.success:
            raise RuntimeError(f"Failed to reinitialize kernel RPC: {init_result.error}")

    async def shutdown(self) -> None:
        """Shutdown the kernel and cleanup resources."""
        if self._kc is not None:
            self._kc.stop_channels()
            self._kc = None

        if self._km is not None:
            await self._km.shutdown_kernel(now=True)
            self._km = None

        self._provider = None

    @property
    def is_alive(self) -> bool:
        """Check if the kernel is alive."""
        if self._km is None:
            return False
        # is_alive() is sync for AsyncKernelManager
        return self._km.is_alive()
