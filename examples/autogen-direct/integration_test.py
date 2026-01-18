"""Integration test: Agent solves multi-tool task and saves workflow.

This test verifies:
1. An AutoGen agent can solve a task requiring multiple steps
2. The agent can save a successful solution as a reusable workflow
3. The workflow persists to disk and can be invoked later

Run:
    cd examples/autogen
    uv run python integration_test.py
"""

import asyncio
import shutil
from pathlib import Path

from autogen_agentchat.agents import AssistantAgent
from autogen_ext.models.anthropic import AnthropicChatCompletionClient
from dotenv import load_dotenv

from py_code_mode import FileStorage, Session
from py_code_mode.integrations.autogen import create_run_code_tool

# Load .env file
load_dotenv()

# Paths
HERE = Path(__file__).parent
SHARED = HERE.parent / "shared"
TEST_WORKFLOWS_DIR = HERE / "test_workflows"


SYSTEM_PROMPT = """You are a helpful assistant that writes Python code to accomplish tasks.

You have access to `tools`, `workflows`, and `artifacts` namespaces in your code environment.

WORKFLOW:
1. For any nontrivial task, FIRST search workflows: workflows.search("relevant keywords")
2. If a workflow exists, use it: workflows.invoke("workflow_name", arg=value)
3. If no workflow matches, search tools: tools.search("keywords")
4. Script tools together: tools.name(arg=value)

DISCOVERY:
- workflows.search("query") / workflows.list() - find prebaked solutions
- tools.search("query") / tools.list() - find individual tools

ARTIFACTS (persistent storage):
- artifacts.save("name", data, description="...") - Save data for later
- artifacts.load("name") - Load previously saved data
- artifacts.list() - List saved artifacts

WORKFLOW CREATION:
When you solve a multi-step task that could be reused, save it as a workflow:

workflows.create(
    name="descriptive_name",
    description="What this workflow does",
    code='''
def run(param1: str, param2: int = default) -> dict:
    \"\"\"Docstring describing the workflow.\"\"\"
    # Your solution here
    return result
'''
)

This lets you reuse the solution later via workflows.invoke() or workflows.name().

The workflow code must:
- Define a `run()` function as the entrypoint
- Have parameters with type hints
- Return a value (not print)

Workflows are reusable recipes that combine tools. Prefer them over scripting from scratch.


Always wrap your code in ```python blocks."""


async def main():
    # Clean up previous test runs
    test_base = HERE / "test_storage"
    if test_base.exists():
        shutil.rmtree(test_base)
    test_base.mkdir(parents=True, exist_ok=True)

    # Copy tools from SHARED to test directory
    tools_dir = test_base / "tools"
    shutil.copytree(SHARED / "tools", tools_dir)

    # Create empty workflows directory for testing workflow creation
    workflows_dir = test_base / "workflows"
    workflows_dir.mkdir(exist_ok=True)

    print("=" * 60)
    print("Integration Test: Agent Creates Workflow from Task Solution")
    print("=" * 60)

    # Create storage with test directory
    storage = FileStorage(base_path=test_base)

    async with Session(storage=storage) as session:
        run_code = create_run_code_tool(session)

        model = AnthropicChatCompletionClient(model="claude-sonnet-4-20250514")
        agent = AssistantAgent(
            name="assistant",
            model_client=model,
            tools=[run_code],
            system_message=SYSTEM_PROMPT,
            reflect_on_tool_use=True,
            max_tool_iterations=20,
        )

        # Task: Multi-step problem that should result in a saved workflow
        task = """
        Fetch the HackerNews front page (https://news.ycombinator.com/).
        Parse the HTML and extract the first 10 article titles.
        Return them as a list of strings.

        Once you have a working solution, save it as a reusable workflow called
        'get_hn_headlines' that takes an optional 'count' parameter (default 10).
        """

        print(f"\nTask: {task.strip()}")
        print("-" * 60)

        result = await agent.run(task=task)

        print("\n" + "-" * 60)
        print("Agent response:")
        print(result.messages[-1].content)
        print("-" * 60)

        # Verify workflow was created
        print("\n" + "=" * 60)
        print("Verification")
        print("=" * 60)

        # Check via storage API
        workflow_info = storage.workflows.get("get_hn_headlines")
        if workflow_info is None:
            print("FAILED: Workflow 'get_hn_headlines' was not created")
            return False

        print(f"Workflow created: {workflow_info['name']}")
        print(f"Description: {workflow_info['description']}")

        # Verify workflow file exists
        workflow_file = workflows_dir / "get_hn_headlines.py"
        if not workflow_file.exists():
            print(f"FAILED: Workflow file was not persisted to {workflow_file}")
            return False

        print(f"Workflow file persisted: {workflow_file}")

        # Invoke the workflow to verify it works
        print("\nInvoking workflow to verify it works...")
        invoke_result = await session.run('workflows.invoke("get_hn_headlines", count=5)')

        if not invoke_result.is_ok:
            print(f"FAILED: Workflow invocation failed: {invoke_result.error}")
            return False

        print(f"Workflow result: {invoke_result.value}")

    # Verify workflow survives a fresh session (true persistence)
    print("\n" + "-" * 60)
    print("Testing persistence: loading workflow in fresh session...")

    fresh_storage = FileStorage(base_path=test_base)
    async with Session(storage=fresh_storage) as fresh_session:
        workflow_info = fresh_storage.workflows.get("get_hn_headlines")
        if workflow_info is None:
            print("FAILED: Workflow not found in fresh session")
            return False

        print(f"Workflow loaded from disk: {workflow_info['name']}")

        result = await fresh_session.run("workflows.get_hn_headlines(count=3)")
        if not result.is_ok:
            print(f"FAILED: Workflow invocation failed: {result.error}")
            return False

        print(f"Fresh invocation result: {result.value}")

    print("\n" + "=" * 60)
    print("SUCCESS: All verifications passed!")
    print("=" * 60)
    return True


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
