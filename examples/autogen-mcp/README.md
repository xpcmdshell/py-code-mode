# AutoGen MCP Integration

AutoGen agent connecting to py-code-mode via MCP protocol.

**When to use:** Quick setup, standard protocol, works with any MCP-capable framework.

See also: `../autogen-direct/` for direct integration (more control, lower latency).

## Setup

```bash
cd examples/autogen-mcp
uv sync
```

Create a `.env` file with your API key:
```
ANTHROPIC_API_KEY=sk-ant-...
```

## Run

```bash
uv run python agent.py
```

This starts py-code-mode as an MCP server subprocess and connects AutoGen to it.

## Architecture

```
┌─────────────────┐
│  AutoGen Agent  │
│  (MCP client)   │
└────────┬────────┘
         │ MCP (stdio)
         ▼
┌─────────────────┐
│  py-code-mode   │  ← Started as subprocess
│  MCP server     │
└────────┬────────┘
         │ CLI, MCP, REST
         ▼
┌─────────────────┐
│  Tools          │
│  (curl, fetch,  │
│   time, etc.)   │
└─────────────────┘
```

## How It Works

1. AutoGen's `McpWorkbench` spawns `py-code-mode-mcp` as a subprocess
2. py-code-mode exposes 4 MCP tools: `run_code`, `list_tools`, `list_skills`, `search_skills`
3. The agent uses these tools to execute Python code with access to tools/skills/artifacts
4. No custom integration code needed - just standard MCP

## Comparison with Direct Integration

| Aspect | MCP | Direct |
|--------|-----|--------|
| Setup complexity | Lower | Higher |
| Latency | Slightly higher (IPC) | Lower |
| Customization | Standard MCP tools | Full API access |
| Multi-framework | Yes (any MCP client) | No (AutoGen-specific) |
| Code size | ~20 lines | ~100 lines |

## Example Prompts

```
You: What time is it in Tokyo?

You: Fetch the GitHub API and tell me how many public repos octocat has

You: Search for skills related to API checking, then use one if it exists
```
