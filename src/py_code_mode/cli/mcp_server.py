"""MCP server exposing py-code-mode executor to MCP clients.

Usage:
    # File storage
    py-code-mode-mcp --storage ./data

    # Redis storage
    py-code-mode-mcp --redis redis://localhost:6379 --prefix my-agent

    # With Claude Code
    claude mcp add py-code-mode -- py-code-mode-mcp --storage ~/.code-mode

Note on execution isolation:
    Currently, code runs in-process (no isolation). Container-based execution
    with Docker is supported by the library (ContainerExecutor), but automatic
    Docker configuration for Claude Code MCP integration is not yet implemented.

    For now, the MCP server uses InProcessExecutor which provides the simplest
    "just works" experience - no Docker setup required, tools are CLI commands
    on your system. Container isolation will be added when we solve the tool
    discovery/management UX for containerized environments.
"""

from __future__ import annotations

import argparse
import asyncio
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
async def list_tools() -> list[dict]:
    """List all available tools with their descriptions and parameters."""
    if _session is None or _session._executor is None:
        return []
    return _session._executor._namespace["tools"].list()


@mcp.tool
async def search_tools(query: str, limit: int = 10) -> list[dict]:
    """Search tools by intent using semantic search.

    Use natural language to describe what you want to accomplish.
    Example queries: "make HTTP requests", "process JSON data", "scan ports"

    Args:
        query: Natural language description of what you're trying to accomplish
        limit: Maximum number of results to return (default: 10)

    Returns matching tools with their descriptions and callables.
    """
    if _session is None or _session._executor is None:
        return []
    tools = _session._executor._namespace["tools"].search(query, limit)
    return [
        {
            "name": t.name,
            "description": t.description,
            "callables": [c.signature() for c in t.callables],
        }
        for t in tools
    ]


@mcp.tool
async def list_skills() -> list[dict]:
    """List all available skills with their descriptions."""
    if _session is None or _session._executor is None:
        return []
    return _session._executor._namespace["skills"].list()


@mcp.tool
async def search_skills(query: str, limit: int = 5) -> list[dict]:
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
    if _session is None or _session._executor is None:
        return []
    return _session._executor._namespace["skills"].search(query, limit)


@mcp.tool
async def list_artifacts() -> list[dict]:
    """List all stored artifacts with their metadata."""
    if _session is None or _session._executor is None:
        return []
    return _session._executor._namespace["artifacts"].list()


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
    if _session is None or _session._executor is None:
        return {"error": "Session not initialized"}
    return _session._executor._namespace["skills"].create(name, source, description)


@mcp.tool
async def delete_skill(name: str) -> bool:
    """Delete a skill by name.

    Args:
        name: Name of the skill to delete

    Returns True if the skill was deleted, False if it was not found.
    """
    if _session is None or _session._executor is None:
        return False
    return _session._executor._namespace["skills"].delete(name)


async def create_session(args: argparse.Namespace) -> Session:
    """Create session based on CLI args."""
    from py_code_mode import Session

    if args.redis:
        from redis import Redis

        from py_code_mode import RedisStorage

        redis = Redis.from_url(args.redis)
        storage = RedisStorage(redis=redis, prefix=args.prefix or "py-code-mode")
    else:
        from py_code_mode import FileStorage

        storage_path = Path(args.storage)
        storage_path.mkdir(parents=True, exist_ok=True)
        storage = FileStorage(base_path=storage_path)

    session = Session(storage=storage)
    await session.start()
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
        help="Path to storage directory (contains tools/, skills/, artifacts/)",
    )

    # Redis storage options
    parser.add_argument("--redis", help="Redis URL for storage")
    parser.add_argument("--prefix", help="Redis key prefix (default: py-code-mode)")

    args = parser.parse_args()

    # Validate: need either --storage or --redis
    if not args.storage and not args.redis:
        parser.error("Either --storage or --redis is required")

    # Initialize session
    global _session
    _session = asyncio.run(create_session(args))

    # Run MCP server (stdio transport by default)
    mcp.run()


if __name__ == "__main__":
    main()
