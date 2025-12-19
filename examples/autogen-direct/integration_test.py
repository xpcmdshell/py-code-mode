"""Integration test: Agent solves multi-tool task and saves skill.

This test verifies:
1. An AutoGen agent can solve a task requiring multiple steps
2. The agent can save a successful solution as a reusable skill
3. The skill persists to disk and can be invoked later

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
TEST_SKILLS_DIR = HERE / "test_skills"


SYSTEM_PROMPT = """You are a helpful assistant that writes Python code to accomplish tasks.

You have access to `tools`, `skills`, and `artifacts` namespaces in your code environment.

WORKFLOW:
1. For any nontrivial task, FIRST search skills: skills.search("relevant keywords")
2. If a skill exists, use it: skills.invoke("skill_name", arg=value)
3. If no skill matches, search tools: tools.search("keywords")
4. Script tools together: tools.name(arg=value)

DISCOVERY:
- skills.search("query") / skills.list() - find prebaked solutions
- tools.search("query") / tools.list() - find individual tools

ARTIFACTS (persistent storage):
- artifacts.save("name", data, description="...") - Save data for later
- artifacts.load("name") - Load previously saved data
- artifacts.list() - List saved artifacts

SKILL CREATION:
When you solve a multi-step task that could be reused, save it as a skill:

skills.create(
    name="descriptive_name",
    description="What this skill does",
    code='''
def run(param1: str, param2: int = default) -> dict:
    \"\"\"Docstring describing the skill.\"\"\"
    # Your solution here
    return result
'''
)

This lets you reuse the solution later via skills.invoke() or skills.name().

The skill code must:
- Define a `run()` function as the entrypoint
- Have parameters with type hints
- Return a value (not print)

Skills are reusable recipes that combine tools. Prefer them over scripting from scratch.

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

    # Create empty skills directory for testing skill creation
    skills_dir = test_base / "skills"
    skills_dir.mkdir(exist_ok=True)

    print("=" * 60)
    print("Integration Test: Agent Creates Skill from Task Solution")
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

        # Task: Multi-step problem that should result in a saved skill
        task = """
        Fetch the HackerNews front page (https://news.ycombinator.com/).
        Parse the HTML and extract the first 10 article titles.
        Return them as a list of strings.

        Once you have a working solution, save it as a reusable skill called
        'get_hn_headlines' that takes an optional 'count' parameter (default 10).
        """

        print(f"\nTask: {task.strip()}")
        print("-" * 60)

        result = await agent.run(task=task)

        print("\n" + "-" * 60)
        print("Agent response:")
        print(result.messages[-1].content)
        print("-" * 60)

        # Verify skill was created
        print("\n" + "=" * 60)
        print("Verification")
        print("=" * 60)

        # Check via storage API
        skill_info = storage.skills.get("get_hn_headlines")
        if skill_info is None:
            print("FAILED: Skill 'get_hn_headlines' was not created")
            return False

        print(f"Skill created: {skill_info['name']}")
        print(f"Description: {skill_info['description']}")

        # Verify skill file exists
        skill_file = skills_dir / "get_hn_headlines.py"
        if not skill_file.exists():
            print(f"FAILED: Skill file was not persisted to {skill_file}")
            return False

        print(f"Skill file persisted: {skill_file}")

        # Invoke the skill to verify it works
        print("\nInvoking skill to verify it works...")
        invoke_result = await session.run('skills.invoke("get_hn_headlines", count=5)')

        if not invoke_result.is_ok:
            print(f"FAILED: Skill invocation failed: {invoke_result.error}")
            return False

        print(f"Skill result: {invoke_result.value}")

    # Verify skill survives a fresh session (true persistence)
    print("\n" + "-" * 60)
    print("Testing persistence: loading skill in fresh session...")

    fresh_storage = FileStorage(base_path=test_base)
    async with Session(storage=fresh_storage) as fresh_session:
        skill_info = fresh_storage.skills.get("get_hn_headlines")
        if skill_info is None:
            print("FAILED: Skill not found in fresh session")
            return False

        print(f"Skill loaded from disk: {skill_info['name']}")

        result = await fresh_session.run("skills.get_hn_headlines(count=3)")
        if not result.is_ok:
            print(f"FAILED: Skill invocation failed: {result.error}")
            return False

        print(f"Fresh invocation result: {result.value}")

    print("\n" + "=" * 60)
    print("SUCCESS: All verifications passed!")
    print("=" * 60)
    return True


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
