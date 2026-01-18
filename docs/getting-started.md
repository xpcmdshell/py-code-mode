# Getting Started

This guide walks through installing py-code-mode and running your first agent session.

## Installation

### As a Python Library

```bash
uv add git+https://github.com/xpcmdshell/py-code-mode.git@v0.10.0
```

### For Claude Code (MCP Server)

**Global installation** (available in all directories):

```bash
claude mcp add -s user py-code-mode \
  -- uvx --from git+https://github.com/xpcmdshell/py-code-mode.git@v0.10.0 \
  py-code-mode-mcp --base ~/.code-mode
```

**Project-scoped installation** (only in the current project):

```bash
claude mcp add -s project py-code-mode \
  -- uvx --from git+https://github.com/xpcmdshell/py-code-mode.git@v0.10.0 \
  py-code-mode-mcp --base ./.code-mode
```

> **Note:** Without `-s user` or `-s project`, `claude mcp add` defaults to project scope based on your current directory. If you install from `~` without a scope flag, the server only works in that directory.

**Verify installation:**

```bash
claude mcp list
```

The base directory will contain `workflows/`, `artifacts/`, and optionally `tools/` subdirectories.

## Your First Session

### As a Python Library

```python
from py_code_mode import Session

# One line setup - auto-discovers tools/, workflows/, artifacts/, requirements.txt
async with Session.from_base("./data") as session:
    result = await session.run('''
# Search for existing workflows
results = workflows.search("data processing")

# List available tools
all_tools = tools.list()

# Create a simple workflow
workflows.create(
    name="hello_world",
    source="""async def run(name: str = "World") -> str:
    return f"Hello, {name}!"
    """,
    description="Simple greeting function"
)

# Invoke the workflow
greeting = workflows.invoke("hello_world", name="Python")
print(greeting)
''')

    print(f"Result: {result.value}")
```

**Need process isolation?**

```python
async with Session.subprocess("~/.code-mode") as session:
    ...
```

### With Claude Code (MCP)

Once installed, the MCP server provides these tools to Claude:

- `run_code` - Execute Python code with `tools`, `workflows`, `artifacts`, `deps` namespaces
- `list_tools`, `search_tools` - Discover available tools
- `list_workflows`, `search_workflows`, `create_workflow`, `delete_workflow` - Manage workflows
- `list_artifacts` - View stored data
- `list_deps`, `add_dep`, `remove_dep` - Manage dependencies

Just ask Claude to use py-code-mode:

```
Can you search for workflows related to GitHub analysis?
```

Claude will use the `search_workflows` MCP tool automatically.

## Basic Workflow

1. **Search for existing workflows** - Always check if someone already solved this
2. **Invoke if found** - Reuse existing workflows
3. **Script if not found** - Write code to solve the problem
4. **Create workflow if reusable** - Save successful workflows for future use

```python
# 1. Search
results = workflows.search("fetch json from url")

# 2. Invoke if found
if results:
    data = workflows.invoke(results[0]["name"], url="https://api.example.com/data")
else:
    # 3. Script the solution
    import json
    response = tools.curl.get(url="https://api.example.com/data")
    data = json.loads(response)

    # 4. Save as workflow
    workflows.create(
        name="fetch_json",
        source='''async def run(url: str) -> dict:
    import json
    response = tools.curl.get(url=url)
    return json.loads(response)
''',
        description="Fetch and parse JSON from a URL"
    )
```

## Next Steps

- **[Tools](./tools.md)** - Learn how to add CLI, MCP, and REST API adapters
- **[Workflows](./workflows.md)** - Deep dive on creating and composing workflows
- **[Artifacts](./artifacts.md)** - Persist data across sessions
- **[Examples](../examples/)** - See complete agent implementations
