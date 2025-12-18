"""AutoGen agent with py-code-mode tools and skills.

This example shows:
- CLI tools (curl, jq)
- MCP tools via uvx (fetch, time)
- A skill that combines tools
- Optional Redis backend for distributed skill/artifact storage

Run (file-based, default):
    cd examples/autogen
    uv run python agent.py

Run with Redis backend:
    # Start Redis (using Docker)
    docker run -d --name redis -p 6379:6379 redis:alpine

    # Bootstrap skills to Redis (one-time)
    uv run python -m py_code_mode.store bootstrap \
        --source ../shared/skills \
        --target redis://localhost:6379 \
        --prefix agent-skills

    # Run agent with Redis
    REDIS_URL=redis://localhost:6379 uv run python agent.py
"""

import asyncio
import os
import sys
from pathlib import Path

import redis as redis_lib
from dotenv import load_dotenv

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.ui import Console
from autogen_ext.models.anthropic import AnthropicChatCompletionClient

from py_code_mode import (
    CodeExecutor,
    RedisArtifactStore,
    RedisSkillStore,
    RedisToolStore,
    ToolRegistry,
    registry_from_redis,
    create_skill_library,
)
from py_code_mode.integrations.autogen import create_run_code_tool

# Load .env file
load_dotenv()

# Directory containing this file
HERE = Path(__file__).parent
SHARED = HERE.parent / "shared"


async def create_executor():
    """Create executor with appropriate storage backend.

    When REDIS_URL is set:
    - Skills are loaded from Redis (provisioned via store CLI)
    - Artifacts are stored in Redis (persistent across restarts)

    Without REDIS_URL:
    - Skills are loaded from shared/skills directory
    - Artifacts are stored in local files
    """
    redis_url = os.environ.get("REDIS_URL")

    if redis_url:
        # Redis mode: everything from Redis (provisioned separately)
        r = redis_lib.from_url(redis_url)

        # Connect to existing Redis stores
        # Provisioned via: python -m py_code_mode.store bootstrap
        skill_store = RedisSkillStore(r, prefix="agent-skills")
        skill_library = create_skill_library(store=skill_store)

        tool_store = RedisToolStore(r, prefix="agent-tools")
        registry = await registry_from_redis(tool_store)

        artifact_store = RedisArtifactStore(r, prefix="agent-artifacts")

        print(f"Using Redis backend: {redis_url}")
        print(f"  Tools in Redis: {len(tool_store)}")
        print(f"  Skills in Redis: {len(list(skill_store.list_all()))}")

        return CodeExecutor(
            registry=registry,
            skill_library=skill_library,
            artifact_store=artifact_store,
        )
    else:
        # File mode: load directly from shared/
        print("Using file-based backend (set REDIS_URL for Redis mode)")
        return await CodeExecutor.create(
            tools=str(SHARED / "tools"),
            skills=str(SHARED / "skills"),
            artifacts=str(HERE / "artifacts"),
        )


async def main():
    # Use async context manager for proper lifecycle management
    async with await create_executor() as executor:
        # Create the run_code tool for AutoGen
        run_code = create_run_code_tool(executor=executor)

        system_prompt = """You are a helpful assistant that writes Python code to accomplish tasks.

You have access to `tools`, `skills`, and `artifacts` namespaces in your code environment.

WORKFLOW:
1. For any nontrivial task, FIRST search skills: skills.search("relevant keywords")
2. If a skill exists, use it: skills.invoke("name", arg=value)
3. If no skill matches, search tools: tools.search("keywords")
4. Script tools together: tools.name(arg=value)

DISCOVERY:
- skills.search("query") / skills.list() - find prebaked solutions
- tools.search("query") / tools.list() - find individual tools

ARTIFACTS (persistent storage):
- artifacts.save("name", data, description="...") - Save data for later
- artifacts.load("name") - Load previously saved data
- artifacts.list() - List saved artifacts

Skills are reusable recipes that combine tools. Prefer them over scripting from scratch.

Always wrap your code in ```python blocks."""

        # Create Claude client (uses ANTHROPIC_API_KEY from .env)
        model = AnthropicChatCompletionClient(model="claude-sonnet-4-20250514")

        # Create agent
        agent = AssistantAgent(
            name="assistant",
            model_client=model,
            tools=[run_code],
            system_message=system_prompt,
            reflect_on_tool_use=True,  # Continue after tool calls
            max_tool_iterations=5,     # Allow multiple tool call rounds
        )

        # Check for command line argument
        if len(sys.argv) > 1:
            query = " ".join(sys.argv[1:])
            await Console(agent.run_stream(task=query))
            return

        # Interactive loop
        print("Assistant ready. Type your request (or 'quit' to exit).\n")

        while True:
            try:
                user_input = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                break

            if not user_input:
                continue
            if user_input.lower() in ("quit", "exit", "q"):
                break

            # Run agent
            result = await agent.run(task=user_input)

            # Print response
            print(f"\nAssistant: {result.messages[-1].content}\n")


if __name__ == "__main__":
    asyncio.run(main())
