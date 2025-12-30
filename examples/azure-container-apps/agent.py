"""Azure Container Apps agent with py-code-mode.

This example shows:
- Same agent pattern as the autogen example
- Deployed to Azure Container Apps with Claude via Azure AI Foundry
- Uses Redis for both skills and artifacts when REDIS_URL is set
- CLI tools (curl, jq) and MCP tools (fetch, time)
- Multi-tool skill (analyze_repo.py)

Run locally (with ANTHROPIC_API_KEY):
    cd examples/azure-container-apps
    uv run python agent.py

Run with Redis backend:
    # First, provision skills to Redis (one-time or deploy-time)
    python -m py_code_mode.store bootstrap \
        --source ../shared/skills \
        --target redis://localhost:6379 \
        --prefix agent-skills

    # Then run the agent
    REDIS_URL=redis://localhost:6379 uv run python agent.py

Deploy to Azure:
    See deploy/README.md
"""

import asyncio
import os
from pathlib import Path

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.ui import Console
from dotenv import load_dotenv

from py_code_mode import FileStorage, RedisStorage, Session
from py_code_mode.integrations.autogen import create_run_code_tool

# Load .env file for local development
load_dotenv()

# Directory paths
HERE = Path(__file__).parent
SHARED = HERE.parent / "shared"


def get_model_client():
    """Get model client - Azure AI Foundry in cloud, Anthropic API locally."""
    azure_endpoint = os.environ.get("AZURE_AI_ENDPOINT")

    if azure_endpoint:
        # Running in Azure - use Azure AI Foundry with managed identity
        from autogen_ext.models.azure import AzureAIChatCompletionClient
        from azure.identity import DefaultAzureCredential

        return AzureAIChatCompletionClient(
            model="claude-sonnet-4-20250514",
            endpoint=azure_endpoint,
            credential=DefaultAzureCredential(),
        )
    else:
        # Running locally - use Anthropic API directly
        from autogen_ext.models.anthropic import AnthropicChatCompletionClient

        return AnthropicChatCompletionClient(model="claude-sonnet-4-20250514")


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
    # Create storage and session
    storage = create_storage()
    async with Session(storage=storage) as session:
        # Create the run_code tool for AutoGen
        run_code = create_run_code_tool(session=session)

        system_prompt = """You are a helpful assistant that writes Python code to accomplish tasks.

You have access to `tools` and `skills` namespaces in your code environment.

WORKFLOW:
1. For any nontrivial task, FIRST search skills: skills.search("relevant keywords")
2. If a skill exists, use it: skills.invoke("name", arg=value)
3. If no skill matches, search tools: tools.search("keywords")
4. Script tools together: tools.name(arg=value)

DISCOVERY:
- skills.search("query") / skills.list() - find prebaked solutions
- tools.search("query") / tools.list() - find individual tools

Skills are reusable recipes that combine tools. Prefer them over scripting from scratch.

ARTIFACTS (persistent storage):
- artifacts.save("name", data, description="...") - Save data for later
- artifacts.load("name") - Load previously saved data
- artifacts.list() - List saved artifacts

Always wrap your code in ```python blocks."""

        # Get appropriate model client for environment
        model = get_model_client()

        # Create agent
        agent = AssistantAgent(
            name="assistant",
            model_client=model,
            tools=[run_code],
            system_message=system_prompt,
            reflect_on_tool_use=True,
            max_tool_iterations=5,
        )

        # Check for command line argument
        import sys

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
