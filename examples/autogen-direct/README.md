# AutoGen Direct Integration

Local AutoGen agent with py-code-mode wired directly into the agent.

**When to use:** Deep customization, lower latency, single-framework projects.

See also: `../autogen-mcp/` for MCP-based integration (simpler setup, standard protocol).

## Setup

```bash
cd examples/autogen-direct
uv sync
```

Create a `.env` file with your API key:
```
ANTHROPIC_API_KEY=sk-ant-...
```

## Run (File-Based)

Default mode loads workflows from disk:

```bash
uv run python agent.py
```

## Run (Redis Backend)

For distributed deployments or persistent storage, use Redis:

### 1. Start Redis

```bash
docker run -d --name redis -p 6379:6379 redis:alpine
```

### 2. Bootstrap Tools and Workflows to Redis

Load tools and workflows from disk into Redis (one-time setup):

```bash
# Bootstrap tools
uv run python -m py_code_mode.store bootstrap \
  --source ../shared/tools \
  --target redis://localhost:6379 \
  --prefix agent-tools \
  --type tools

# Bootstrap workflows
uv run python -m py_code_mode.store bootstrap \
  --source ../shared/workflows \
  --target redis://localhost:6379 \
  --prefix agent-workflows
```

### 3. Run with Redis

```bash
REDIS_URL=redis://localhost:6379 uv run python agent.py
```

You should see:
```
Using Redis backend: redis://localhost:6379
  Tools in Redis: 4
  Workflows in Redis: 1
```

### Managing Workflows

```bash
# List workflows in Redis
uv run python -m py_code_mode.store list --target redis://localhost:6379 --prefix agent-workflows

# Compare local vs Redis
uv run python -m py_code_mode.store diff \
  --source ../shared/workflows \
  --target redis://localhost:6379 \
  --prefix agent-workflows

# Pull workflows from Redis to local (for review)
uv run python -m py_code_mode.store pull \
  --target redis://localhost:6379 \
  --prefix agent-workflows \
  --dest ./workflows-from-redis
```

## What's Included

### CLI Tools (`../shared/tools/`)

- `curl.yaml` - HTTP requests
- `jq.yaml` - JSON processing

### MCP Tools (`../shared/mcp-tools/`)

- `fetch.yaml` - Web page fetching via `mcp-server-fetch`
- `time.yaml` - Timezone queries via `mcp-server-time`

MCP tools are launched via `uvx` (no pre-installation needed). They live in a separate directory from CLI tools because they use a different adapter.

### Workflows (`../shared/workflows/`)

- `check_api.py` - Fetches an API and optionally filters with jq

## Example Prompts

```
You: What time is it in Tokyo?

You: Fetch the GitHub API and tell me how many public repos octocat has

You: Use the check_api workflow to fetch https://api.github.com/users/torvalds and extract the name
```

## Architecture

```
                    ┌─────────────────────────────────────────────┐
                    │                  agent.py                   │
                    │                                             │
                    │  REDIS_URL set?                             │
                    │    Yes → Redis backend                      │
                    │    No  → File backend                       │
                    └─────────────────────────────────────────────┘
                                        │
              ┌─────────────────────────┴─────────────────────────┐
              │                                                   │
              ▼                                                   ▼
    ┌──────────────────┐                             ┌──────────────────┐
    │  File Backend    │                             │  Redis Backend   │
    │                  │                             │                  │
    │  Workflows: disk    │                             │  Workflows: Redis   │
    │  Artifacts: disk │                             │  Artifacts: Redis│
    │  Tools: disk     │                             │  Tools: disk     │
    └──────────────────┘                             └──────────────────┘
```

## Adding Tools

Create a YAML file in `../shared/tools/`:

```yaml
# tools/my_tool.yaml
name: my_tool
type: cli
args: "{input}"
description: What it does
```

For MCP tools:

```yaml
# tools/my_mcp.yaml
name: my_mcp
type: mcp
transport: stdio
command: uvx
args: ["mcp-server-whatever"]
```

## Adding Workflows

Create a Python file in `../shared/workflows/` with an `async def run()` function:

```python
# workflows/my_workflow.py
"""What this workflow does."""

async def run(param1: str, param2: int = 10) -> str:
    result = tools.some_tool(input=param1)
    return f"Processed: {result}"
```

Then bootstrap to Redis if using Redis mode:

```bash
uv run python -m py_code_mode.store bootstrap \
  --source ../shared/workflows \
  --target redis://localhost:6379 \
  --prefix agent-workflows
```
