"""MCP server exposing py-code-mode executor to MCP clients.

Usage:
    # Base directory (auto-discovers tools/, workflows/, artifacts/ subdirs)
    py-code-mode-mcp --base ~/.code-mode

    # Explicit storage + tools
    py-code-mode-mcp --storage ./data --tools ./project/tools

    # Redis storage
    py-code-mode-mcp --redis redis://localhost:6379 --prefix my-agent

    # Deno sandbox backend
    py-code-mode-mcp --base ~/.code-mode --executor deno-sandbox

    # With Claude Code
    claude mcp add py-code-mode -- py-code-mode-mcp --base ~/.code-mode

Note on execution:
    Execution backend is selectable via --executor. Default is SubprocessExecutor
    for process isolation and broad compatibility.

Note on architecture:
    Storage (--storage or --redis) holds workflows and artifacts.
    Tools are owned by the executor and loaded from --tools directory.
    The --base flag is a convenience that sets both: storage=base, tools=base/tools.

Most CLI flags are optional backend-specific overrides. For normal usage,
`--base` (or `--storage`) is sufficient.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastmcp import FastMCP

if TYPE_CHECKING:
    from py_code_mode import Session

EXECUTOR_CHOICES = ("subprocess", "in-process", "container", "deno-sandbox")
EXECUTOR_OPTION_ATTRS: dict[str, tuple[str, ...]] = {
    "subprocess": (
        "subprocess_python_version",
        "subprocess_venv_path",
        "subprocess_startup_timeout",
        "subprocess_ipc_timeout",
        "subprocess_no_cache_venv",
        "subprocess_cleanup_venv_on_close",
    ),
    "in-process": ("inprocess_ipc_timeout",),
    "container": (
        "container_image",
        "container_port",
        "container_host",
        "container_startup_timeout",
        "container_ipc_timeout",
        "container_remote_url",
        "container_no_auto_build",
        "container_keep_container",
        "container_auth_token",
        "container_auth_disabled",
    ),
    "deno-sandbox": (
        "deno_executable",
        "deno_runner_path",
        "deno_dir",
        "deno_network_profile",
        "deno_ipc_timeout",
        "deno_deps_timeout",
        "deno_deps_net_allowlist",
    ),
}

# Global session + parsed CLI args for MCP lifespan initialization.
_session: Session | None = None
_cli_args: argparse.Namespace | None = None


@asynccontextmanager
async def _mcp_lifespan(_server: Any) -> AsyncIterator[dict[str, Any]]:
    """Initialize and teardown Session on FastMCP's event loop."""
    global _session
    if _cli_args is None:
        raise RuntimeError("MCP session args not initialized")

    _session = await create_session(_cli_args)
    try:
        yield {}
    finally:
        if _session is not None:
            await _session.close()
            _session = None


mcp = FastMCP("py-code-mode", lifespan=_mcp_lifespan)


@mcp.tool
async def run_code(code: str) -> str:
    """Execute Python code with access to tools, workflows, and artifacts.

    WORKFLOW:
    1. First, use search_workflows to find existing solutions for your task
    2. If a workflow exists, invoke it: workflows.invoke("workflow_name", arg=value)
    3. If no workflow exists, solve the task ad-hoc using tools and Python
    4. Once solved, save reusable solutions as workflows for future use

    NAMESPACES:
    - tools.* - Call registered tools (use list_tools to see available)
      Example: tools.curl(url="https://api.example.com")

    - workflows.* - Work with workflows:
      - workflows.invoke("name", arg=val) - Run an existing workflow
      - workflows.search("query") - Find workflows (same as search_workflows tool)
      - workflows.create("name", code, "description") - Save a new workflow
      - workflows.list() - List all workflows
      - workflows.get("name") - Get workflow details

    - artifacts.* - Persist data across sessions:
      - artifacts.save("filename", data) - Save data
      - artifacts.load("filename") - Load data

    - deps.* - Manage Python dependencies:
      - deps.add("package") - Install a package
      - deps.list("package") - List configured dependencies
      - deps.remove("package") - Remove a dependency

    The namespace persists across calls - variables survive between run_code invocations.
    """
    if _session is None:
        return "Error: Session not initialized"

    result = await _session.run(code)
    if result.error:
        return f"Error: {result.error}" + (f"\n\nStdout:\n{result.stdout}" if result.stdout else "")

    output = str(result.value) if result.value is not None else ""
    if result.stdout:
        output = f"{output}\n\nStdout:\n{result.stdout}" if output else f"Stdout:\n{result.stdout}"
    return output or "(no output)"


@mcp.tool
async def list_tools() -> str:
    """List all available tools with their descriptions and parameters."""
    if _session is None:
        raise RuntimeError("Session not initialized")
    tools = await _session.list_tools()
    # Return JSON string for consistent MCP serialization
    # (FastMCP may not serialize empty lists correctly)
    return json.dumps(tools)


@mcp.tool
async def search_tools(query: str, limit: int = 10) -> str:
    """Search tools by intent using semantic search.

    Use natural language to describe what you want to accomplish.
    Example queries: "make HTTP requests", "process JSON data", "scan ports"

    Args:
        query: Natural language description of what you're trying to accomplish
        limit: Maximum number of results to return (default: 10)

    Returns matching tools with their descriptions and tags.
    """
    if _session is None:
        raise RuntimeError("Session not initialized")
    tools = await _session.search_tools(query, limit)
    return json.dumps(tools)


@mcp.tool
async def list_workflows() -> str:
    """List all available workflows with their descriptions."""
    if _session is None:
        raise RuntimeError("Session not initialized")
    workflows = await _session.list_workflows()
    return json.dumps(workflows)


@mcp.tool
async def search_workflows(query: str, limit: int = 5) -> str:
    """Search for existing workflows before solving a task from scratch.

    START HERE: Before writing code, search for workflows that might already solve
    your task. Workflows are reusable solutions that combine tools and logic.

    Args:
        query: Natural language description of what you're trying to accomplish
        limit: Maximum number of results to return (default: 5)

    Returns matching workflows with their descriptions and parameters.
    If no good match exists, use run_code to solve the task ad-hoc,
    then create a workflow for future reuse.
    """
    if _session is None:
        raise RuntimeError("Session not initialized")
    workflows = await _session.search_workflows(query, limit)
    return json.dumps(workflows)


@mcp.tool
async def list_artifacts() -> str:
    """List all stored artifacts with their metadata."""
    if _session is None:
        raise RuntimeError("Session not initialized")
    artifacts = await _session.list_artifacts()
    return json.dumps(artifacts)


@mcp.tool
async def create_workflow(name: str, source: str, description: str) -> dict:
    """Create a reusable workflow from Python source code.

    The source must contain a `def run(...)` function that will be executed
    when the workflow is invoked. The function can accept parameters and has
    access to tools, workflows, and artifacts namespaces.

    Example source:
        def run(url: str) -> str:
            return tools.curl.get(url=url)

    Args:
        name: Unique name for the workflow (used to invoke it later)
        source: Python source code containing a `def run(...)` function
        description: Human-readable description of what the workflow does

    Returns the created workflow's metadata.
    """
    if _session is None:
        raise RuntimeError("Session not initialized")
    return await _session.add_workflow(name, source, description)


@mcp.tool
async def delete_workflow(name: str) -> bool:
    """Delete a workflow by name.

    Args:
        name: Name of the workflow to delete

    Returns True if the workflow was deleted, False if it was not found.
    """
    if _session is None:
        raise RuntimeError("Session not initialized")
    return await _session.remove_workflow(name)


async def list_deps() -> list[str]:
    """List all configured dependencies."""
    if _session is None:
        return []
    return await _session.list_deps()


async def _list_deps_json() -> str:
    """List all configured dependencies (JSON-serialized for MCP).

    FastMCP doesn't create TextContent for empty lists, so we serialize
    to JSON string to ensure consistent MCP response format.
    """
    return json.dumps(await list_deps())


async def add_dep(package: str) -> dict:
    """Add and install a dependency.

    Args:
        package: Package name with optional version specifier (e.g., "pandas>=2.0")

    Returns:
        Dict with installation result (success, installed, failed, output)
    """
    if _session is None:
        return {"error": "Session not initialized"}
    try:
        return await _session.add_dep(package)
    except ValueError as e:
        return {"error": str(e)}


async def remove_dep(package: str) -> dict:
    """Remove a dependency from configuration and uninstall it.

    Args:
        package: Package name to remove

    Returns:
        Dict with removal result (removed, not_found, failed, removed_from_config)
    """
    if _session is None:
        return {"error": "Session not initialized"}
    try:
        return await _session.remove_dep(package)
    except ValueError as e:
        return {"error": str(e)}


# Register deps tools that are always available (list only)
# Use _list_deps_json for MCP to ensure TextContent is always created (FastMCP
# doesn't create TextContent for empty lists, which breaks MCP clients expecting
# result.content[0].text)
mcp.tool(_list_deps_json, name="list_deps", description="List all configured dependencies.")

# Note: add_dep and remove_dep are conditionally registered in register_runtime_dep_tools()
# based on --no-runtime-deps flag

# Track if runtime dep tools are registered (for testing)
_runtime_dep_tools_registered = False


def register_runtime_dep_tools(allow_runtime_deps: bool) -> None:
    """Register runtime dependency tools based on configuration.

    Args:
        allow_runtime_deps: If True, register add_dep and remove_dep tools.
                           If False, only list_deps is available.
    """
    global _runtime_dep_tools_registered
    if allow_runtime_deps and not _runtime_dep_tools_registered:
        mcp.tool(add_dep)
        mcp.tool(remove_dep)
        _runtime_dep_tools_registered = True


def _is_option_set(value: Any) -> bool:
    """Return True when a backend-specific CLI option was explicitly set."""
    if value is None:
        return False
    if value is False:
        return False
    if value == []:
        return False
    return True


def _validate_executor_specific_options(args: argparse.Namespace) -> None:
    """Validate backend-specific flags are used with matching --executor."""
    selected = getattr(args, "executor", "subprocess")
    for backend, attrs in EXECUTOR_OPTION_ATTRS.items():
        if backend == selected:
            continue
        for attr in attrs:
            if _is_option_set(getattr(args, attr, None)):
                flag = f"--{attr.replace('_', '-')}"
                raise ValueError(f"{flag} requires --executor {backend}")

    if (
        selected == "container"
        and getattr(args, "container_auth_token", None)
        and getattr(args, "container_auth_disabled", False)
    ):
        raise ValueError(
            "--container-auth-token and --container-auth-disabled cannot be used together"
        )


def _build_subprocess_executor(
    *,
    args: argparse.Namespace,
    no_runtime_deps: bool,
    timeout: float | None,
    tools_path: Path | None,
) -> Any:
    from py_code_mode.execution.subprocess import SubprocessConfig, SubprocessExecutor

    config_kwargs: dict[str, Any] = {
        "allow_runtime_deps": not no_runtime_deps,
        "default_timeout": timeout,
        "tools_path": tools_path,
    }
    if args.subprocess_python_version:
        config_kwargs["python_version"] = args.subprocess_python_version
    if args.subprocess_venv_path:
        config_kwargs["venv_path"] = Path(args.subprocess_venv_path)
    if args.subprocess_startup_timeout is not None:
        config_kwargs["startup_timeout"] = args.subprocess_startup_timeout
    if args.subprocess_ipc_timeout is not None:
        config_kwargs["ipc_timeout"] = args.subprocess_ipc_timeout
    if args.subprocess_no_cache_venv:
        config_kwargs["cache_venv"] = False
    if args.subprocess_cleanup_venv_on_close:
        config_kwargs["cleanup_venv_on_close"] = True

    return SubprocessExecutor(config=SubprocessConfig(**config_kwargs))


def _build_inprocess_executor(
    *,
    args: argparse.Namespace,
    no_runtime_deps: bool,
    timeout: float | None,
    tools_path: Path | None,
) -> Any:
    from py_code_mode.execution.in_process import InProcessConfig, InProcessExecutor

    config_kwargs: dict[str, Any] = {
        "allow_runtime_deps": not no_runtime_deps,
        "default_timeout": timeout,
        "tools_path": tools_path,
    }
    if args.inprocess_ipc_timeout is not None:
        config_kwargs["ipc_timeout"] = args.inprocess_ipc_timeout

    return InProcessExecutor(config=InProcessConfig(**config_kwargs))


def _build_container_executor(
    *,
    args: argparse.Namespace,
    no_runtime_deps: bool,
    timeout: float | None,
    tools_path: Path | None,
) -> Any:
    from py_code_mode.execution.container import ContainerConfig, ContainerExecutor

    config_kwargs: dict[str, Any] = {
        "allow_runtime_deps": not no_runtime_deps,
        "timeout": timeout if timeout is not None else 30.0,
        "tools_path": tools_path,
        # Keep local MCP usage ergonomic unless caller opts into auth token.
        "auth_disabled": True,
    }
    if args.container_image:
        config_kwargs["image"] = args.container_image
    if args.container_port is not None:
        config_kwargs["port"] = args.container_port
    if args.container_host:
        config_kwargs["host"] = args.container_host
    if args.container_startup_timeout is not None:
        config_kwargs["startup_timeout"] = args.container_startup_timeout
    if args.container_ipc_timeout is not None:
        config_kwargs["ipc_timeout"] = args.container_ipc_timeout
    if args.container_remote_url:
        config_kwargs["remote_url"] = args.container_remote_url
    if args.container_no_auto_build:
        config_kwargs["auto_build"] = False
    if args.container_keep_container:
        config_kwargs["remove_on_exit"] = False
    if args.container_auth_token:
        config_kwargs["auth_token"] = args.container_auth_token
        config_kwargs["auth_disabled"] = False
    elif args.container_auth_disabled:
        config_kwargs["auth_disabled"] = True

    return ContainerExecutor(config=ContainerConfig(**config_kwargs))


def _build_deno_executor(
    *,
    args: argparse.Namespace,
    no_runtime_deps: bool,
    timeout: float | None,
    tools_path: Path | None,
) -> Any:
    from py_code_mode.execution.deno_sandbox import DenoSandboxConfig, DenoSandboxExecutor

    config_kwargs: dict[str, Any] = {
        "allow_runtime_deps": not no_runtime_deps,
        "default_timeout": timeout,
        "tools_path": tools_path,
    }
    if args.deno_executable:
        config_kwargs["deno_executable"] = args.deno_executable
    if args.deno_runner_path:
        config_kwargs["runner_path"] = Path(args.deno_runner_path)
    if args.deno_dir:
        config_kwargs["deno_dir"] = Path(args.deno_dir)
    if args.deno_network_profile:
        config_kwargs["network_profile"] = args.deno_network_profile
    if args.deno_ipc_timeout is not None:
        config_kwargs["ipc_timeout"] = args.deno_ipc_timeout
    if args.deno_deps_timeout is not None:
        config_kwargs["deps_timeout"] = args.deno_deps_timeout
    if args.deno_deps_net_allowlist:
        config_kwargs["deps_net_allowlist"] = tuple(args.deno_deps_net_allowlist)

    return DenoSandboxExecutor(config=DenoSandboxConfig(**config_kwargs))


async def create_session(args: argparse.Namespace) -> Session:
    """Create session based on CLI args."""
    from py_code_mode import Session
    from py_code_mode.storage import StorageBackend

    _validate_executor_specific_options(args)

    storage: StorageBackend
    if args.redis:
        from py_code_mode import RedisStorage

        storage = RedisStorage(url=args.redis, prefix=args.prefix or "py-code-mode")
    else:
        from py_code_mode import FileStorage

        storage_path = Path(args.storage)
        storage_path.mkdir(parents=True, exist_ok=True)
        storage = FileStorage(base_path=storage_path)

    # Configure executor with runtime deps and timeout settings
    no_runtime_deps = getattr(args, "no_runtime_deps", False)
    timeout = getattr(args, "timeout", None)

    # Tools path from CLI arg (executor-owned, not storage)
    tools_path = Path(args.tools) if args.tools else None

    executor_name = getattr(args, "executor", "subprocess")
    if executor_name == "subprocess":
        executor = _build_subprocess_executor(
            args=args,
            no_runtime_deps=no_runtime_deps,
            timeout=timeout,
            tools_path=tools_path,
        )
    elif executor_name == "in-process":
        executor = _build_inprocess_executor(
            args=args,
            no_runtime_deps=no_runtime_deps,
            timeout=timeout,
            tools_path=tools_path,
        )
    elif executor_name == "container":
        executor = _build_container_executor(
            args=args,
            no_runtime_deps=no_runtime_deps,
            timeout=timeout,
            tools_path=tools_path,
        )
    elif executor_name == "deno-sandbox":
        executor = _build_deno_executor(
            args=args,
            no_runtime_deps=no_runtime_deps,
            timeout=timeout,
            tools_path=tools_path,
        )
    else:
        raise ValueError(f"Unsupported executor: {executor_name!r}")

    # Determine if we should sync deps on start (default: True)
    sync_deps = not getattr(args, "no_sync_deps", False)

    session = Session(storage=storage, executor=executor, sync_deps_on_start=sync_deps)
    await session.start()

    # Note: Tool registry pre-loading removed. In the new architecture,
    # tools are owned by executors (via config.tools_path), not storage.
    # MCP server tools are provided via executor config if needed.

    return session


def build_parser() -> argparse.ArgumentParser:
    """Build argument parser for py-code-mode MCP server."""
    parser = argparse.ArgumentParser(
        description="MCP server for py-code-mode executor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Base directory (auto-discovers tools/, workflows/, artifacts/)
  py-code-mode-mcp --base ~/.code-mode

  # Explicit storage + tools
  py-code-mode-mcp --storage ./data --tools ./project/tools

  # Redis storage
  py-code-mode-mcp --redis redis://localhost:6379 --prefix my-agent

  # Deno sandbox backend
  py-code-mode-mcp --base ~/.code-mode --executor deno-sandbox

  # Add to Claude Code
  claude mcp add py-code-mode -- py-code-mode-mcp --base ~/.code-mode
        """,
    )

    # Base directory (convenience: auto-discovers tools/, workflows/, artifacts/)
    parser.add_argument(
        "--base",
        help="Base directory with tools/, workflows/, artifacts/ subdirs (convenience shorthand)",
    )

    # File storage option
    parser.add_argument(
        "--storage",
        help="Path to storage directory (contains workflows/, artifacts/)",
    )

    # Tools path (separate from storage since tools are executor-owned)
    parser.add_argument(
        "--tools",
        help="Path to tools directory containing YAML tool definitions",
    )

    # Redis storage options
    parser.add_argument("--redis", help="Redis URL for storage")
    parser.add_argument("--prefix", help="Redis key prefix (default: py-code-mode)")

    parser.add_argument(
        "--executor",
        choices=EXECUTOR_CHOICES,
        default="subprocess",
        help="Execution backend (default: subprocess)",
    )

    subprocess_group = parser.add_argument_group("Subprocess backend options")
    subprocess_group.add_argument(
        "--subprocess-python-version",
        help="Python major.minor for venv (example: 3.12)",
    )
    subprocess_group.add_argument(
        "--subprocess-venv-path",
        help="Path to subprocess virtual environment",
    )
    subprocess_group.add_argument(
        "--subprocess-startup-timeout",
        type=float,
        default=None,
        help="Kernel startup timeout in seconds",
    )
    subprocess_group.add_argument(
        "--subprocess-ipc-timeout",
        type=float,
        default=None,
        help="Subprocess IPC timeout in seconds",
    )
    subprocess_group.add_argument(
        "--subprocess-no-cache-venv",
        action="store_true",
        help="Disable subprocess venv cache",
    )
    subprocess_group.add_argument(
        "--subprocess-cleanup-venv-on-close",
        action="store_true",
        help="Delete subprocess venv when session closes",
    )

    inprocess_group = parser.add_argument_group("In-process backend options")
    inprocess_group.add_argument(
        "--inprocess-ipc-timeout",
        type=float,
        default=None,
        help="In-process IPC timeout in seconds",
    )

    container_group = parser.add_argument_group("Container backend options")
    container_group.add_argument("--container-image", help="Container image tag")
    container_group.add_argument(
        "--container-port",
        type=int,
        default=None,
        help="Container API port on host (default: auto)",
    )
    container_group.add_argument(
        "--container-host",
        help="Host for container API connection (default: localhost)",
    )
    container_group.add_argument(
        "--container-startup-timeout",
        type=float,
        default=None,
        help="Container startup timeout in seconds",
    )
    container_group.add_argument(
        "--container-ipc-timeout",
        type=float,
        default=None,
        help="Container IPC timeout in seconds",
    )
    container_group.add_argument(
        "--container-remote-url",
        help="Connect to existing remote container session server URL",
    )
    container_group.add_argument(
        "--container-no-auto-build",
        action="store_true",
        help="Disable automatic image build if image is missing",
    )
    container_group.add_argument(
        "--container-keep-container",
        action="store_true",
        help="Do not remove container on exit",
    )
    container_group.add_argument(
        "--container-auth-token",
        help="Bearer token for container session server auth",
    )
    container_group.add_argument(
        "--container-auth-disabled",
        action="store_true",
        help="Disable container API auth (local development only)",
    )

    deno_group = parser.add_argument_group("Deno sandbox backend options")
    deno_group.add_argument(
        "--deno-executable",
        help="Deno executable path/name",
    )
    deno_group.add_argument(
        "--deno-runner-path",
        help="Path to Deno sandbox runner TypeScript entrypoint",
    )
    deno_group.add_argument(
        "--deno-dir",
        help="Directory for Deno module cache (DENO_DIR)",
    )
    deno_group.add_argument(
        "--deno-network-profile",
        choices=("none", "deps-only", "full"),
        default=None,
        help="Deno network profile",
    )
    deno_group.add_argument(
        "--deno-ipc-timeout",
        type=float,
        default=None,
        help="Deno RPC timeout in seconds",
    )
    deno_group.add_argument(
        "--deno-deps-timeout",
        type=float,
        default=None,
        help="Timeout for dependency installs in seconds",
    )
    deno_group.add_argument(
        "--deno-deps-net-allowlist",
        action="append",
        default=None,
        help="Allowed hostname for deps-only profile (repeatable)",
    )

    # Runtime deps control
    parser.add_argument(
        "--no-runtime-deps",
        action="store_true",
        help="Disable runtime dependency installation",
    )

    # Execution timeout
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Code execution timeout in seconds (default: backend-specific)",
    )

    # Dependency sync control
    parser.add_argument(
        "--no-sync-deps",
        action="store_true",
        help="Don't install pre-configured dependencies on startup (default: sync on start)",
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # Handle --base convenience flag
    if args.base:
        base_path = Path(args.base)
        # --base sets storage to base dir, tools to base/tools if it exists
        if not args.storage:
            args.storage = str(base_path)
        tools_subdir = base_path / "tools"
        if not args.tools and tools_subdir.is_dir():
            args.tools = str(tools_subdir)

    # Validate: need either --storage, --base, or --redis
    if not args.storage and not args.redis:
        parser.error("Either --base, --storage, or --redis is required")

    try:
        _validate_executor_specific_options(args)
    except ValueError as e:
        parser.error(str(e))

    # Conditionally register add_dep tool based on --no-runtime-deps flag
    no_runtime_deps = getattr(args, "no_runtime_deps", False)
    register_runtime_dep_tools(allow_runtime_deps=not no_runtime_deps)

    # FastMCP lifespan initializes session on the server event loop.
    global _cli_args
    _cli_args = args

    # Run MCP server (stdio transport by default)
    mcp.run()


if __name__ == "__main__":
    main()
