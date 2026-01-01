#!/usr/bin/env python3
"""Minimal Claude agent with py-code-mode code execution.

This example shows:
1. Loading tools and skills from the shared directory
2. Creating a Session with FileStorage
3. Running an agent loop with raw Claude API

The agent can write Python code that calls tools via the tools.* namespace
and invoke skills via the skills.* namespace.
"""

import asyncio
import re
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from py_code_mode import FileStorage, Session
from py_code_mode.execution import InProcessConfig, InProcessExecutor

# Load .env file (for ANTHROPIC_API_KEY)
load_dotenv()

# Shared tools and skills directory
HERE = Path(__file__).parent
SHARED = HERE.parent / "shared"

SYSTEM_PROMPT = """You are a helpful assistant with tools and skills via Python code execution.

Write Python code in ```python blocks. The code runs in an environment with
`tools` and `skills` namespaces.

WORKFLOW:
1. For any nontrivial task, FIRST search skills: skills.search("relevant keywords")
2. If a skill exists, use it: skills.invoke("name", arg=value)
3. If no skill matches, search tools: tools.search("keywords")
4. Script tools together: tools.name(arg=value)

DISCOVERY:
- skills.search("query") / skills.list() - find prebaked solutions
- tools.search("query") / tools.list() - find individual tools

Skills are reusable recipes that combine tools. Prefer them over scripting from scratch.

EXAMPLE:
```python
# First check for existing skills
skills.search("analyze repo")
```

```python
# If skill exists, use it
skills.invoke("analyze_repo", repo="anthropics/claude-code")
```

```python
# Or script tools directly
response = tools.curl(url="https://api.github.com/users/octocat")
import json
data = json.loads(response)
f"Found {data['public_repos']} repos"
```

Variables persist between code blocks. When done, respond in plain text.
"""


def extract_code(text: str) -> str | None:
    """Extract Python code from markdown code block."""
    match = re.search(r"```python\n(.*?)```", text, re.DOTALL)
    return match.group(1).strip() if match else None


async def main() -> None:
    # Storage for skills and artifacts only
    storage = FileStorage(base_path=SHARED)

    # Executor with tools from config
    config = InProcessConfig(tools_path=SHARED / "tools")
    executor = InProcessExecutor(config=config)

    async with Session(storage=storage, executor=executor) as session:
        # Initialize Claude client
        client = anthropic.Anthropic()
        messages: list[dict] = []

        # Agent loop
        print("Agent ready. Type your request (or 'quit' to exit):\n")

        while True:
            user_input = input("You: ").strip()
            if user_input.lower() in ("quit", "exit", "q"):
                break
            if not user_input:
                continue

            messages.append({"role": "user", "content": user_input})

            # Keep running until agent gives final answer (no code block)
            while True:
                response = client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=2048,
                    system=SYSTEM_PROMPT,
                    messages=messages,
                )

                assistant_text = response.content[0].text
                code = extract_code(assistant_text)

                if code:
                    # Execute the code
                    print("\nAgent is executing code...")
                    result = await session.run(code)

                    if result.is_ok:
                        result_text = f"Result: {result.value}"
                        if result.stdout:
                            result_text += f"\nStdout: {result.stdout}"
                    else:
                        result_text = f"Error: {result.error}"

                    print(f"  {result_text}\n")

                    # Add to conversation
                    messages.append({"role": "assistant", "content": assistant_text})
                    messages.append({"role": "user", "content": result_text})
                else:
                    # Final answer - print and break inner loop
                    print(f"\nAgent: {assistant_text}\n")
                    messages.append({"role": "assistant", "content": assistant_text})
                    break


if __name__ == "__main__":
    asyncio.run(main())
