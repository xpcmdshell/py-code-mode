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

Tools are defined in YAML files that describe how to invoke CLI commands:

```yaml
# configs/tools/curl.yaml
name: curl
type: cli
description: HTTP client for making requests
args: "-s {url}"
```

### 2. Storage + Session

Tools and skills are loaded via storage abstraction:

```python
from pathlib import Path
from py_code_mode import Session, FileStorage

# File-based storage
storage = FileStorage(base_path=Path("./configs"))

# Create session (defaults to in-process execution)
async with Session(storage=storage) as session:
    result = await session.run('tools.curl(url="...")')
```

Or with Redis:

```python
import redis
from py_code_mode import Session, RedisStorage

r = redis.from_url("redis://localhost:6379")
storage = RedisStorage(redis=r, prefix="myapp")

async with Session(storage=storage) as session:
    result = await session.run('tools.curl(url="...")')
```

### 3. Agent Code Execution

When the agent writes code, it has access to `tools`:

```python
# Pythonic style (recommended)
response = tools.curl(url="https://api.example.com")

# Or dict-based style
response = tools.call("curl", {"url": "https://api.example.com"})

import json
data = json.loads(response)
data["field"]
```

The executor runs the code and returns the result of the last expression.

### 4. Persistent State

Variables persist across executions within the same session, so the agent can build up state:

```python
# First execution
users = []

# Second execution (users still exists)
users.append({"name": "Alice"})
```

Artifacts provide persistence across sessions:

```python
# Save data
artifacts.save("users.json", json.dumps(users).encode(), "User list")

# Load in another session
users_json = artifacts.load("users.json")
users = json.loads(users_json.decode())
```

## Customization

### Add More Tools

Create additional YAML files in your tools directory:

```yaml
# configs/tools/dig.yaml
name: dig
type: cli
description: DNS lookup
args: "+short {domain}"
```

```yaml
# configs/tools/whois.yaml
name: whois
type: cli
description: Domain info
args: "{domain}"
```

### Load Tools from YAML

Instead of defining tools in code, create individual YAML files per tool:

```yaml
# configs/tools/curl.yaml
name: curl
type: cli
description: HTTP client
args: "-s {url}"
```

```python
from pathlib import Path
from py_code_mode import Session, FileStorage

# Tools automatically loaded from configs/tools/ directory
storage = FileStorage(base_path=Path("./configs"))

async with Session(storage=storage) as session:
    result = await session.run('tools.curl(url="...")')
```

### Add Skills (Code Recipes)

Skills are reusable code snippets the agent can invoke:

```python
# configs/skills/fetch_json.py
def run(url: str) -> dict:
    """Fetch JSON from a URL and parse it."""
    import json
    response = tools.curl(url=url)
    return json.loads(response)
```

Skills are automatically loaded from the directory when using `FileStorage`:

```python
from pathlib import Path
from py_code_mode import Session, FileStorage

# Skills loaded from configs/skills/
storage = FileStorage(base_path=Path("./configs"))

async with Session(storage=storage) as session:
    # Agent can use: skills.fetch_json(url="...")
    result = await session.run('skills.fetch_json(url="https://api.example.com")')
```

## Next Steps

- See `examples/azure-container-apps/` for production deployment with Docker isolation
- Read the main README for full API documentation
