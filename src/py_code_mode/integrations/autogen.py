"""AutoGen integration for py-code-mode.

Provides a pre-built tool that can be registered with AutoGen agents.
Supports both in-process execution and remote session server.

Usage (standalone):
    from py_code_mode import CodeExecutor, ToolRegistry
    from py_code_mode.integrations.autogen import create_run_code_tool

    executor = CodeExecutor(registry=registry)
    run_code = create_run_code_tool(executor=executor)

    agent.register_for_llm()(run_code)

Usage (remote session server):
    from py_code_mode.integrations.autogen import create_run_code_tool

    run_code = create_run_code_tool(session_url="http://session-server:8080")

    agent.register_for_llm()(run_code)
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from py_code_mode import CodeExecutor


def create_run_code_tool(
    executor: CodeExecutor | None = None,
    session_url: str | None = None,
    timeout: float = 30.0,
    session_id: str | None = None,
) -> Callable[[str], str]:
    """Create a run_code tool for AutoGen agents.

    Provide either an executor (for in-process execution) or a session_url
    (for remote execution via session server). Not both.

    Args:
        executor: CodeExecutor instance for in-process execution
        session_url: URL of py-code-mode session server for remote execution
        timeout: Execution timeout in seconds
        session_id: Optional session ID for remote execution. If not provided,
                   a unique session is created. Use this to isolate different
                   agents using the same session server.

    Returns:
        A function that can be registered as an AutoGen tool

    Raises:
        ValueError: If neither or both executor and session_url are provided
    """
    if executor is None and session_url is None:
        raise ValueError("Must provide either executor or session_url")
    if executor is not None and session_url is not None:
        raise ValueError("Provide executor OR session_url, not both")

    if executor is not None:
        return _create_local_tool(executor, timeout)
    else:
        return _create_remote_tool(session_url, timeout, session_id)  # type: ignore


def _create_local_tool(
    executor: CodeExecutor,
    timeout: float,
) -> Callable[[str], str]:
    """Create tool using local CodeExecutor."""

    async def run_code(code: str) -> str:
        """Execute Python code with access to tools.*, skills.*, and artifacts.*.

        The code runs in a persistent environment where:
        - tools.name(arg=value) invokes registered tools
        - skills.invoke("skill_name", arg=value) runs registered skills
        - artifacts.save(name, data) persists data across executions
        - artifacts.load(name) retrieves previously saved data
        - Variables persist across calls

        Args:
            code: Python code to execute

        Returns:
            String representation of the result or error message
        """
        try:
            result = await executor.run(code, timeout=timeout)

            if result.is_ok:
                output = str(result.value) if result.value is not None else ""
                if result.stdout:
                    output = f"{result.stdout}\n{output}" if output else result.stdout
                return output
            else:
                return f"Error: {result.error}"
        except Exception as e:
            return f"Error: {e}"

    return run_code


def _create_remote_tool(
    session_url: str,
    timeout: float,
    session_id: str | None = None,
) -> Callable[[str], str]:
    """Create tool using remote session server."""

    # Lazy import to avoid requiring httpx for local-only usage
    import uuid

    import httpx

    # Each tool instance gets its own session
    _session_id = session_id or str(uuid.uuid4())

    def run_code(code: str) -> str:
        """Execute Python code with access to tools.*, skills.*, and artifacts.*.

        The code runs on a remote session server where:
        - tools.call("namespace.name", {"arg": value}) invokes registered tools
        - skills.run("skill_name", arg=value) runs registered skills
        - artifacts.save(name, data) persists data across executions
        - artifacts.load(name) retrieves previously saved data
        - Variables persist across calls

        Args:
            code: Python code to execute

        Returns:
            String representation of the result or error message
        """
        try:
            with httpx.Client(timeout=timeout + 5) as client:
                response = client.post(
                    f"{session_url.rstrip('/')}/execute",
                    json={"code": code, "timeout": timeout},
                    headers={"X-Session-ID": _session_id},
                )
                response.raise_for_status()
                result = response.json()

            if result.get("error"):
                return f"Error: {result['error']}"

            output = str(result.get("value", "")) if result.get("value") is not None else ""
            if result.get("stdout"):
                output = f"{result['stdout']}\n{output}" if output else result["stdout"]
            return output

        except httpx.HTTPError as e:
            return f"Error: HTTP request failed: {e}"
        except Exception as e:
            return f"Error: {e}"

    return run_code


def get_tools_description(
    session_url: str | None = None, executor: CodeExecutor | None = None
) -> str:
    """Get a description of available tools for the system prompt.

    Args:
        session_url: URL of session server (for remote)
        executor: CodeExecutor instance (for local)

    Returns:
        Formatted string describing available tools
    """
    if session_url:
        import httpx

        try:
            with httpx.Client(timeout=10) as client:
                response = client.get(f"{session_url.rstrip('/')}/info")
                response.raise_for_status()
                info = response.json()
                tools = info.get("tools", [])
        except Exception:
            return "Tools available via tools.call()"
    elif executor and executor._registry:
        tools = []
        for ns, adapter in executor._registry._adapters.items():
            for tool in adapter.list_tools():
                tools.append({"name": f"{ns}.{tool.name}", "description": tool.description})
    else:
        return "Tools available via tools.call()"

    lines = ['Available tools (use via tools.call("name", {args})):']
    for t in tools:
        lines.append(f"  - {t['name']}: {t['description']}")
    return "\n".join(lines)
