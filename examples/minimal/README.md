# Minimal Agent Example

A simple Claude-powered agent with CLI tool execution. Shows the core py-code-mode value proposition in ~100 lines.

## What It Does

The agent can:
1. Receive a task from you
2. Write Python code to accomplish it
3. Execute code with access to CLI tools via `tools.call()`
4. Iterate on results until it has an answer

## Prerequisites

- Python 3.11+
- `curl` and `jq` installed (most systems have these)
- `ANTHROPIC_API_KEY` environment variable set

## Setup

```bash
# From the py-code-mode repository root
cd examples/minimal

# Install dependencies (using uv)
uv pip install anthropic py-code-mode

# Or with pip
pip install anthropic py-code-mode
```

## Run

```bash
python agent.py
```

## Example Session

```
Agent ready. Type your request (or 'quit' to exit):

You: How many public repos does the octocat user have on GitHub?

Agent is executing code...
  Result: Found 8 repos

Agent: The GitHub user "octocat" has 8 public repositories.
```

## How It Works

### 1. Tool Definition

Tools are defined as `CLIToolSpec` objects that describe how to invoke CLI commands:

```python
CLIToolSpec(
    name="curl",
    description="HTTP client for making requests",
    command="curl",
    args_template="-s {url}",  # {placeholders} filled from args dict
)
```

### 2. Registry + Executor

Tools are registered with a namespace, then passed to the executor:

```python
registry = ToolRegistry()
await registry.register("cli", cli_adapter)

executor = CodeExecutor(registry=registry)
```

### 3. Agent Code Execution

When the agent writes code, it has access to `tools.call()`:

```python
# Agent writes this
response = tools.call("cli.curl", {"url": "https://api.example.com"})
import json
data = json.loads(response)
data["field"]
```

The executor runs the code and returns the result of the last expression.

### 4. Persistent State

Variables persist across executions, so the agent can build up state:

```python
# First execution
users = []

# Second execution (users still exists)
users.append({"name": "Alice"})
```

## Customization

### Add More Tools

```python
cli = CLIAdapter([
    CLIToolSpec(name="curl", description="...", command="curl", args_template="-s {url}"),
    CLIToolSpec(name="dig", description="DNS lookup", command="dig", args_template="+short {domain}"),
    CLIToolSpec(name="whois", description="Domain info", command="whois", args_template="{domain}"),
])
```

### Load Tools from YAML

Instead of defining tools in code, you can load from YAML:

```yaml
# tools.yaml
cli_tools:
  - name: curl
    description: HTTP client
    command: curl
    args_template: "-s {url}"
```

```python
from py_code_mode.backends.container.config import SessionConfig

config = SessionConfig.from_yaml("tools.yaml")
# config.cli_tools contains the parsed specs
```

### Add Skills (Code Recipes)

Skills are reusable code snippets the agent can invoke:

```python
# skills/fetch_json.py
def run(url: str) -> dict:
    """Fetch JSON from a URL and parse it."""
    import json
    response = tools.curl(url=url)
    return json.loads(response)
```

```python
from py_code_mode import CodeExecutor
from py_code_mode.semantic import create_skill_library
from py_code_mode.skill_store import FileSkillStore

store = FileSkillStore("skills/")
skill_library = create_skill_library(store=store)

executor = CodeExecutor(registry=registry, skill_library=skill_library)
```

Agent can then use: `skills.fetch_json(url="https://api.example.com")`

## Next Steps

- See `examples/azure-container-apps/` for production deployment with Docker isolation
- Read the main README for full API documentation
