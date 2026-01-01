"""MCP server exposing py-code-mode executor to MCP clients.

Usage:
    # File storage
    py-code-mode-mcp --storage ./data

    # Redis storage
    py-code-mode-mcp --redis redis://localhost:6379 --prefix my-agent

    # With Claude Code
    claude mcp add py-code-mode -- py-code-mode-mcp --storage ~/.code-mode

Note on execution:
    Code runs in an isolated subprocess with its own virtual environment and
    IPython kernel (SubprocessExecutor). This provides process isolation while
    still allowing access to CLI tools on your system.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING

from fastmcp import FastMCP

if TYPE_CHECKING:
    from py_code_mode import Session

mcp = FastMCP("py-code-mode")

# Global session - initialized in main() before mcp.run()
_session: Session | None = None


@mcp.tool
async def run_code(code: str) -> str:
    """Execute Python code with access to tools, skills, and artifacts.

    WORKFLOW:
    1. First, use search_skills to find existing solutions for your task
    2. If a skill exists, invoke it: skills.invoke("skill_name", arg=value)
    3. If no skill exists, solve the task ad-hoc using tools and Python
    4. Once solved, save reusable solutions as skills for future use

    NAMESPACES:
    - tools.* - Call registered tools (use list_tools to see available)
      Example: tools.curl(url="https://api.example.com")

    - skills.* - Work with skills:
      - skills.invoke("name", arg=val) - Run an existing skill
      - skills.search("query") - Find skills (same as search_skills tool)
      - skills.create("name", code, "description") - Save a new skill
      - skills.list() - List all skills
      - skills.get("name") - Get skill details

    - artifacts.* - Persist data across sessions:
      - artifacts.save("filename", data) - Save data
      - artifacts.load("filename") - Load data

    - deps.* - Manage Python dependencies:
      - deps.add("package") - Install a package
      - deps.list() - List configured dependencies
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
async def list_skills() -> str:
    """List all available skills with their descriptions."""
    if _session is None:
        raise RuntimeError("Session not initialized")
    skills = await _session.list_skills()
    return json.dumps(skills)


@mcp.tool
async def search_skills(query: str, limit: int = 5) -> str:
    """Search for existing skills before solving a task from scratch.

    START HERE: Before writing code, search for skills that might already solve
    your task. Skills are reusable solutions that combine tools and logic.

    Args:
        query: Natural language description of what you're trying to accomplish
        limit: Maximum number of results to return (default: 5)

    Returns matching skills with their descriptions and parameters.
    If no good match exists, use run_code to solve the task ad-hoc,
    then create a skill for future reuse.
    """
    if _session is None:
        raise RuntimeError("Session not initialized")
    skills = await _session.search_skills(query, limit)
    return json.dumps(skills)


@mcp.tool
async def list_artifacts() -> str:
    """List all stored artifacts with their metadata."""
    if _session is None:
        raise RuntimeError("Session not initialized")
    artifacts = await _session.list_artifacts()
    return json.dumps(artifacts)


@mcp.tool
async def create_skill(name: str, source: str, description: str) -> dict:
    """Create a reusable skill from Python source code.

    The source must contain a `def run(...)` function that will be executed
    when the skill is invoked. The function can accept parameters and has
    access to tools, skills, and artifacts namespaces.

    Example source:
        def run(url: str) -> str:
            return tools.curl.get(url=url)

    Args:
        name: Unique name for the skill (used to invoke it later)
        source: Python source code containing a `def run(...)` function
        description: Human-readable description of what the skill does

    Returns the created skill's metadata.
    """
    if _session is None:
        raise RuntimeError("Session not initialized")
    return await _session.add_skill(name, source, description)


@mcp.tool
async def delete_skill(name: str) -> bool:
    """Delete a skill by name.

    Args:
        name: Name of the skill to delete

    Returns True if the skill was deleted, False if it was not found.
    """
    if _session is None:
        raise RuntimeError("Session not initialized")
    return await _session.remove_skill(name)


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


async def create_session(args: argparse.Namespace) -> Session:
    """Create session based on CLI args."""
    from py_code_mode import Session
    from py_code_mode.execution.subprocess import SubprocessConfig, SubprocessExecutor

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

    # Use persistent venv alongside storage for faster restarts
    # For file storage: ./data/.venv/
    # For redis: ~/.cache/py-code-mode/<prefix>/.venv/
    if args.redis:
        prefix = args.prefix or "py-code-mode"
        venv_path = Path.home() / ".cache" / "py-code-mode" / prefix / ".venv"
    else:
        venv_path = storage_path / ".venv"

    config = SubprocessConfig(
        allow_runtime_deps=not no_runtime_deps,
        default_timeout=timeout,
        venv_path=venv_path,
        cleanup_venv_on_close=False,  # Persist for faster restarts
        tools_path=tools_path,  # Tools from CLI arg
    )
    executor = SubprocessExecutor(config=config)

    # Determine if we should sync deps on start (default: True)
    sync_deps = not getattr(args, "no_sync_deps", False)

    session = Session(storage=storage, executor=executor, sync_deps_on_start=sync_deps)
    await session.start()

    # Note: Tool registry pre-loading removed. In the new architecture,
    # tools are owned by executors (via config.tools_path), not storage.
    # MCP server tools are provided via executor config if needed.

    return session


def main() -> None:
    parser = argparse.ArgumentParser(
        description="MCP server for py-code-mode executor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # File storage
  py-code-mode-mcp --storage ./data

  # Redis storage
  py-code-mode-mcp --redis redis://localhost:6379 --prefix my-agent

  # Add to Claude Code
  claude mcp add py-code-mode -- py-code-mode-mcp --storage ~/.code-mode
        """,
    )

    # File storage option
    parser.add_argument(
        "--storage",
        help="Path to storage directory (contains skills/, artifacts/)",
    )

    # Tools path (separate from storage since tools are executor-owned)
    parser.add_argument(
        "--tools",
        help="Path to tools directory containing YAML tool definitions",
    )

    # Redis storage options
    parser.add_argument("--redis", help="Redis URL for storage")
    parser.add_argument("--prefix", help="Redis key prefix (default: py-code-mode)")

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
        help="Code execution timeout in seconds (default: unlimited)",
    )

    # Dependency sync control
    parser.add_argument(
        "--no-sync-deps",
        action="store_true",
        help="Don't install pre-configured dependencies on startup (default: sync on start)",
    )

    args = parser.parse_args()

    # Validate: need either --storage or --redis
    if not args.storage and not args.redis:
        parser.error("Either --storage or --redis is required")

    # Conditionally register add_dep tool based on --no-runtime-deps flag
    no_runtime_deps = getattr(args, "no_runtime_deps", False)
    register_runtime_dep_tools(allow_runtime_deps=not no_runtime_deps)

    # Initialize session
    global _session
    _session = asyncio.run(create_session(args))

    # Run MCP server (stdio transport by default)
    mcp.run()


if __name__ == "__main__":
    main()
