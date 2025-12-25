# py-code-mode

[![CI](https://github.com/xpcmdshell/py-code-mode/actions/workflows/ci.yml/badge.svg)](https://github.com/xpcmdshell/py-code-mode/actions/workflows/ci.yml)
[![Version](https://img.shields.io/github/v/tag/xpcmdshell/py-code-mode)](https://github.com/xpcmdshell/py-code-mode/tags)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Give your AI agents code execution with persistent skills and tool integration.

## The Core Idea

Multi-step agent workflows are fragile. Each step requires a new LLM call that can hallucinate, pick the wrong tool, or lose context.

**py-code-mode takes a different approach:** Agents write Python code. When a workflow succeeds, they save it as a **skill**. Next time they need that capability, they invoke the skill directly—no re-planning required.

```
First time:  Problem → Iterate → Success → Save as Skill
Next time:   Search Skills → Found! → Invoke (no iteration needed)
Later:       Skill A + Skill B → Compose into Skill C
```

Over time, agents build a library of reliable capabilities. Simple skills become building blocks for complex workflows.

## Quick Start

```python
from pathlib import Path
from py_code_mode import Session, FileStorage

storage = FileStorage(base_path=Path("./data"))

async with Session(storage=storage) as session:
    # Agent writes code with tools, skills, and artifacts available
    result = await session.run('''
# Search for existing skills
results = skills.search("github analysis")

# Or create a new workflow
import json
repo_data = tools.curl.get(url="https://api.github.com/repos/anthropics/anthropic-sdk-python")
parsed = json.loads(repo_data)

# Save successful workflows as skills
skills.create(
    name="fetch_repo_stars",
    source="""def run(owner: str, repo: str) -> int:
    import json
    data = tools.curl.get(url=f"https://api.github.com/repos/{owner}/{repo}")
    return json.loads(data)["stargazers_count"]
    """,
    description="Get GitHub repository star count"
)
''')
```

**Also ships as an MCP server for Claude Code:**

```bash
claude mcp add py-code-mode -- uvx --from git+https://github.com/xpcmdshell/py-code-mode.git@v0.5.1 py-code-mode-mcp
```

## Three Namespaces

When agents write code, three namespaces are available:

**tools**: CLI commands, MCP servers, and REST APIs wrapped as callable functions
**skills**: Reusable Python workflows with semantic search
**artifacts**: Persistent data storage across sessions

```python
# Tools: external capabilities
tools.curl.get(url="https://api.example.com/data")
tools.jq.query(filter=".key", input=json_data)

# Skills: reusable workflows
analysis = skills.invoke("analyze_repo", owner="anthropics", repo="anthropic-sdk-python")

# Skills can build on other skills
def run(repos: list) -> dict:
    summaries = [skills.invoke("analyze_repo", **parse_repo(r)) for r in repos]
    return {"total": len(summaries), "results": summaries}

# Artifacts: persistent storage
artifacts.save("results", data)
cached = artifacts.load("results")
```

For programmatic access without code strings, Session also provides facade methods:

```python
# Direct API access (useful for MCP servers, framework integrations)
tools = await session.list_tools()
skills = await session.search_skills("github analysis")
await session.save_artifact("data", {"key": "value"})
```

## Installation

```bash
uv add git+https://github.com/xpcmdshell/py-code-mode.git@v0.5.1
```

For MCP server installation, see [Getting Started](./docs/getting-started.md).

## Documentation

- **[Getting Started](./docs/getting-started.md)** - Installation, first session, basic usage
- **[Tools](./docs/tools.md)** - CLI, MCP, and REST API adapters
- **[Skills](./docs/skills.md)** - Creating, composing, and managing workflows
- **[Artifacts](./docs/artifacts.md)** - Persistent data storage patterns
- **[Dependencies](./docs/dependencies.md)** - Managing Python packages
- **[Executors](./docs/executors.md)** - InProcess, Subprocess, Container execution
- **[Storage](./docs/storage.md)** - File vs Redis storage backends
- **[Production](./docs/production.md)** - Deployment and scaling patterns
- **[Architecture](./docs/ARCHITECTURE.md)** - System design and separation of concerns

## Examples

- **[minimal/](./examples/minimal/)** - Simple agent implementation (~100 lines)
- **[subprocess/](./examples/subprocess/)** - Process isolation without Docker
- **[autogen-direct/](./examples/autogen-direct/)** - AutoGen framework integration
- **[azure-container-apps/](./examples/azure-container-apps/)** - Production deployment

## License

MIT
