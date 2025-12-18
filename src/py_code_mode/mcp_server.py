"""MCP server exposing py-code-mode executor to MCP clients.

Usage:
    # File backend (default)
    py-code-mode-mcp --tools ./tools --skills ./skills

    # Redis backend
    py-code-mode-mcp --backend redis --url redis://localhost:6379 --prefix my-agent

    # With Claude Code
    claude mcp add py-code-mode -- py-code-mode-mcp --tools ./tools --skills ./skills
"""

from __future__ import annotations

import argparse
import asyncio

from fastmcp import FastMCP

mcp = FastMCP("py-code-mode")

# Global executor - initialized in main() before mcp.run()
_executor = None


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
    result = await _executor.run(code)
    if result.error:
        return f"Error: {result.error}" + (
            f"\n\nStdout:\n{result.stdout}" if result.stdout else ""
        )

    output = str(result.value) if result.value is not None else ""
    if result.stdout:
        output = (
            f"{output}\n\nStdout:\n{result.stdout}" if output else f"Stdout:\n{result.stdout}"
        )
    return output or "(no output)"


@mcp.tool
async def list_tools() -> list[dict]:
    """List all available tools with their descriptions and parameters."""
    return _executor._namespace["tools"].list()


@mcp.tool
async def search_tools(query: str, limit: int = 10) -> list[dict]:
    """Search tools by intent using semantic search.

    Use natural language to describe what you want to accomplish.
    Example queries: "make HTTP requests", "process JSON data", "scan ports"

    Args:
        query: Natural language description of what you're trying to accomplish
        limit: Maximum number of results to return (default: 10)

    Returns matching tools with their descriptions and parameters.
    """
    tools = _executor._namespace["tools"].search(query, limit)
    return [{"name": t.name, "description": t.description, "parameters": t.parameters} for t in tools]


@mcp.tool
async def list_skills() -> list[dict]:
    """List all available skills with their descriptions."""
    return _executor._namespace["skills"].list()


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
    return _executor._namespace["skills"].search(query, limit)


async def create_executor(args: argparse.Namespace):
    """Create executor based on CLI args."""
    from py_code_mode import CodeExecutor

    if args.backend == "redis":
        # Redis backend for ALL storage
        from redis import Redis

        from py_code_mode import (
            RedisArtifactStore,
            RedisSkillStore,
            RedisToolStore,
            create_skill_library,
            registry_from_redis,
        )
        from py_code_mode.semantic import Embedder

        redis = Redis.from_url(args.url)
        prefix = args.prefix or "py-code-mode"

        # Embedder for semantic search
        embedder = Embedder(model_name=args.embedding_model)

        # Tools from Redis
        tool_store = RedisToolStore(redis, prefix=f"{prefix}:tools")
        registry = await registry_from_redis(tool_store, embedder=embedder)

        # Skills from Redis
        skill_store = RedisSkillStore(redis, prefix=f"{prefix}:skills")
        skill_library = create_skill_library(store=skill_store, embedder=embedder)

        # Artifacts from Redis
        artifacts = RedisArtifactStore(redis, prefix=f"{prefix}:artifacts")

        return CodeExecutor(
            registry=registry,
            skill_library=skill_library,
            artifact_store=artifacts,
        )
    else:
        # File backend (default)
        return await CodeExecutor.create(
            tools=args.tools,
            skills=args.skills,
            artifacts=args.artifacts or "./artifacts",
            embedding_model=args.embedding_model,
        )


def main():
    parser = argparse.ArgumentParser(
        description="MCP server for py-code-mode executor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # File backend with local tools/skills
  py-code-mode-mcp --tools ./tools --skills ./skills

  # Redis backend (tools/skills must be bootstrapped first)
  py-code-mode-mcp --backend redis --url redis://localhost:6379 --prefix my-agent

  # Add to Claude Code
  claude mcp add py-code-mode -- py-code-mode-mcp --tools ./tools --skills ./skills
        """,
    )

    # Backend selection
    parser.add_argument(
        "--backend",
        choices=["file", "redis"],
        default="file",
        help="Storage backend (default: file)",
    )

    # File backend options
    parser.add_argument("--tools", help="Path to tools directory (YAML files)")
    parser.add_argument("--skills", help="Path to skills directory (.py files)")
    parser.add_argument(
        "--artifacts", help="Path to artifacts directory (default: ./artifacts)"
    )

    # Redis backend options
    parser.add_argument("--url", help="Redis URL (required for redis backend)")
    parser.add_argument(
        "--prefix", help="Redis key prefix (default: py-code-mode)"
    )

    # Embedding model selection
    parser.add_argument(
        "--embedding-model",
        dest="embedding_model",
        help="Embedding model: bge-small (default), bge-base, granite, or full HuggingFace name",
    )

    args = parser.parse_args()

    # Validate args
    if args.backend == "redis" and not args.url:
        parser.error("--url is required for redis backend")

    # Initialize executor
    global _executor
    _executor = asyncio.run(create_executor(args))

    # Run MCP server (stdio transport by default)
    mcp.run()


if __name__ == "__main__":
    main()
