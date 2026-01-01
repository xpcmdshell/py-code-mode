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

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.ui import Console
from autogen_ext.models.anthropic import AnthropicChatCompletionClient
from dotenv import load_dotenv

from py_code_mode import FileStorage, RedisStorage, Session
from py_code_mode.execution import InProcessConfig, InProcessExecutor
from py_code_mode.integrations.autogen import create_run_code_tool

# Load .env file
load_dotenv()

# Directory containing this file
HERE = Path(__file__).parent
SHARED = HERE.parent / "shared"


def create_storage():
    """Create storage backend.

    When REDIS_URL is set:
    - Tools, skills, and artifacts are loaded from Redis

    Without REDIS_URL:
    - Tools, skills, and artifacts are loaded from shared/ directory
    """
    redis_url = os.environ.get("REDIS_URL")

    if redis_url:
        # Redis mode: everything from Redis (provisioned separately)
        print(f"Using Redis backend: {redis_url}")

        return RedisStorage(url=redis_url, prefix="agent")
    else:
        # File mode: load directly from shared/
        print("Using file-based backend (set REDIS_URL for Redis mode)")
        return FileStorage(base_path=SHARED)


async def main():
    # Create storage (for skills and artifacts only)
    storage = create_storage()

    # Executor with tools from config
    config = InProcessConfig(tools_path=SHARED / "tools")
    executor = InProcessExecutor(config=config)

    async with Session(storage=storage, executor=executor) as session:
        # Create the run_code tool for AutoGen
        run_code = create_run_code_tool(session=session)

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
            max_tool_iterations=5,  # Allow multiple tool call rounds
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
