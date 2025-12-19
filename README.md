# py-code-mode

[![CI](https://github.com/xpcmdshell/py-code-mode/actions/workflows/ci.yml/badge.svg)](https://github.com/xpcmdshell/py-code-mode/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Make your agents' tool orchestration more robust over time.

## The Problem

Complex workflows with LLMs are fragile. Each step is an LLM call that can hallucinate, pick the wrong tool, or lose context. A 5-tool workflow = 5 chances to fail.

## The Solution

Let agents write Python that orchestrates tools in a single execution. When a workflow succeeds, save it as a skill. Next time, call the skill directly - no multi-step reasoning required.

```python
# First time: agent searches for an existing skill
results = skills.search("research topic from multiple sources")

if not results:
    # No skill exists - compose tools to solve it
    search_results = tools.web_search(query=topic)
    sources = []
    for r in search_results[:3]:
        content = tools.fetch(url=r["url"])
        sources.append({"url": r["url"], "content": content})

    # Save the working solution as a reusable skill
    skills.create(
        name="multi_source_research",
        code='''
def run(topic: str, num_sources: int = 3) -> dict:
    results = tools.web_search(query=topic)
    sources = []
    for r in results[:num_sources]:
        content = tools.fetch(url=r["url"])
        sources.append({"url": r["url"], "content": content})
    return {"topic": topic, "sources": sources}
''',
        description="Research a topic by fetching and combining multiple web sources"
    )

# Next time: one call, no multi-step reasoning
research = skills.multi_source_research(topic="Python async patterns", num_sources=5)
```

Skills accumulate. Your agents get more reliable over time.

## Installation

```bash
uv add git+https://github.com/xpcmdshell/py-code-mode.git
```

## Quick Start

### Claude Code (MCP)

```bash
claude mcp add py-code-mode -- uvx py-code-mode --tools ./tools --skills ./skills
```

### Python

```python
from pathlib import Path
from py_code_mode import Session, FileStorage

storage = FileStorage(base_path=Path("./data"))

async with Session(storage=storage) as session:
    # Agent code runs with tools, skills, artifacts available
    result = await session.run('skills.search("research")')
```

## What Agents Get

Three namespaces injected into their execution environment:

- **tools** - Your CLI commands, MCP servers, and APIs wrapped as functions
- **skills** - Reusable workflows (agent-created or human-authored)
- **artifacts** - Persistent storage across sessions

## Defining Tools

Wrap external capabilities as YAML:

```yaml
# tools/web_search.yaml
name: web_search
type: mcp
transport: stdio
command: npx
args: ["-y", "@modelcontextprotocol/server-brave-search"]
description: Search the web and return results with URLs
```

```yaml
# tools/fetch.yaml
name: fetch
type: mcp
transport: stdio
command: npx
args: ["-y", "@modelcontextprotocol/server-fetch"]
description: Fetch a URL and return content as markdown
```

## Seeding Skills

Pre-author skills for agents to find:

```python
# skills/fetch_and_summarize.py
"""Fetch a URL and extract key information."""

def run(url: str) -> dict:
    content = tools.fetch(url=url)
    # Extract first paragraph as summary
    paragraphs = [p for p in content.split("\n\n") if p.strip()]
    return {"url": url, "summary": paragraphs[0] if paragraphs else "", "word_count": len(content.split())}
```

Or let agents create them at runtime via `skills.create()`.

## Production

- **Redis storage** - One agent learns, all agents benefit
- **Container isolation** - Execute untrusted agent code safely

```python
from py_code_mode import Session, RedisStorage
from py_code_mode.backends.container import ContainerExecutor, ContainerConfig

storage = RedisStorage(redis=client, prefix="my-agents")
executor = ContainerExecutor(ContainerConfig(timeout=60.0))

async with Session(storage=storage, executor=executor) as session:
    result = await session.run(agent_code)
```

## Examples

- **minimal/** - Simple agent in ~100 lines
- **autogen-direct/** - AutoGen integration
- **azure-container-apps/** - Production deployment

## License

MIT
