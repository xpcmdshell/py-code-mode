"""AutoGen agent connecting to py-code-mode via MCP.

This example shows how to use py-code-mode as an MCP server with AutoGen.
Much simpler than direct integration - just point McpWorkbench at the server.

Run:
    cd examples/autogen-mcp
    uv run python agent.py
"""

import asyncio
import sys
from pathlib import Path

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.ui import Console
from autogen_ext.models.anthropic import AnthropicChatCompletionClient
from autogen_ext.tools.mcp import McpWorkbench, StdioServerParams
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# Directory containing this file
HERE = Path(__file__).parent
SHARED = HERE.parent / "shared"


async def main():
    # Configure py-code-mode MCP server
    server_params = StdioServerParams(
        command="uv",
        args=[
            "--directory",
            str(HERE.parent.parent),  # py-code-mode root
            "run",
            "py-code-mode-mcp",
            "--tools",
            str(SHARED / "tools"),
            "--skills",
            str(SHARED / "skills"),
            "--artifacts",
            str(HERE / "artifacts"),
        ],
        read_timeout_seconds=120,
    )

    # Connect to py-code-mode via MCP
    async with McpWorkbench(server_params) as workbench:
        # Create Claude client (uses ANTHROPIC_API_KEY from .env)
        model = AnthropicChatCompletionClient(model="claude-sonnet-4-20250514")

        # Create agent with MCP workbench
        agent = AssistantAgent(
            name="assistant",
            model_client=model,
            workbench=workbench,
            reflect_on_tool_use=True,
            max_tool_iterations=5,
        )

        # Check for command line argument
        if len(sys.argv) > 1:
            query = " ".join(sys.argv[1:])
            await Console(agent.run_stream(task=query))
            return

        # Interactive loop
        print("Assistant ready. Type your request (or 'quit' to exit).")
        print("Tools available via MCP: run_code, list_tools, list_skills, search_skills\n")

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
