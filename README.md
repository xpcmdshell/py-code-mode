# py-code-mode

[![CI](https://github.com/xpcmdshell/py-code-mode/actions/workflows/ci.yml/badge.svg)](https://github.com/xpcmdshell/py-code-mode/actions/workflows/ci.yml)
[![Version](https://img.shields.io/github/v/tag/xpcmdshell/py-code-mode)](https://github.com/xpcmdshell/py-code-mode/tags)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> **Note:** This project is new and under active development. Expect breaking changes.

Make your agents' tool orchestration more robust over time.

## The Problem

Complex workflows with LLMs are fragile. Each step is an LLM call that can hallucinate, pick the wrong tool, or lose context. A 5-tool workflow = 5 chances to fail.

## The Solution

Agents write Python code strings. You execute them with `tools`, `skills`, and `artifacts` available:

```python
await session.run(agent_code)  # agent_code is a string the LLM generated
```

When a workflow succeeds, the agent saves it as a skill. Next time, it calls the skill directly - no multi-step reasoning required.

Here's what the agent's code looks like:

```python
# First time: agent needs to scrape Hacker News
results = skills.search("scrape hacker news")
# returns: []  (no matching skills yet)

# Agent iterates to figure out the structure
content = tools.fetch(url="https://news.ycombinator.com")

import re
# Attempt 1: try to find links
matches = re.findall(r'<a href="([^"]+)"', content)  # too many results, includes nav links

# Attempt 2: look for title pattern
matches = re.findall(r'class="title".*?href="([^"]+)"', content)  # wrong class name

# Attempt 3: inspect more carefully, find the right selector
matches = re.findall(r'class="titleline"><a href="([^"]+)".*?>([^<]+)</a>', content)  # works!

# Now save the working solution
skills.create(
    name="scrape_hn_stories",
    source='''
def run(num_stories: int = 30) -> list:
    import re
    content = tools.fetch(url="https://news.ycombinator.com")
    matches = re.findall(r'class="titleline"><a href="([^"]+)".*?>([^<]+)</a>', content)
    return [{"url": url, "title": title} for url, title in matches[:num_stories]]
''',
    description="Extract top stories from Hacker News"
)

```

Next time the agent needs this:

```python
# Agent searches for a relevant skill
results = skills.search("scrape hacker news")
# returns: [{"name": "scrape_hn_stories", "description": "Extract top stories from Hacker News", "params": {"num_stories": "int"}}]

# Found one - just call it, no iteration needed
stories = skills.scrape_hn_stories(num_stories=10)
```

Skills accumulate. Your agents get more reliable over time.

## Installation

```bash
uv add git+https://github.com/xpcmdshell/py-code-mode.git@v0.3.0
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

Wrap external capabilities as YAML. Three types supported:

**CLI tools** - wrap command-line programs with schema + recipes:

```yaml
# tools/curl.yaml
name: curl
description: Make HTTP requests
command: curl
timeout: 60

schema:
  options:
    silent:
      type: boolean
      short: s
      description: Silent mode
    location:
      type: boolean
      short: L
      description: Follow redirects
    header:
      type: array
      short: H
      description: HTTP headers
    data:
      type: string
      short: d
      description: POST data
  positional:
    - name: url
      type: string
      required: true

recipes:
  get:
    description: Simple GET request
    preset:
      silent: true
      location: true
    params:
      url: {}

  post:
    description: POST request with data
    preset:
      silent: true
      location: true
    params:
      url: {}
      data: {}
```

Agent invocation:

```python
# Recipe invocation (recommended)
tools.curl.get(url="https://example.com")
tools.curl.post(url="https://api.example.com/data", data='{"key": "value"}')

# Escape hatch - raw tool invocation (all options available)
tools.curl(url="https://example.com", silent=True, location=True, header=["Accept: application/json"])

# Discovery
tools.list()                    # List all tools
tools.search("http")            # Search tools by name/description
tools.curl.list()               # List recipes for a tool
```

**MCP tools** - connect to MCP servers:

```yaml
# tools/fetch.yaml
name: fetch
type: mcp
transport: stdio
command: uvx
args: ["mcp-server-fetch"]
description: Fetch web pages with full content extraction
```

**HTTP tools** - wrap REST APIs (defined in Python):

```python
from py_code_mode.tools.adapters import HTTPAdapter, Endpoint

adapter = HTTPAdapter(base_url="https://api.example.com")
adapter.add_endpoint(Endpoint(
    name="get_user",
    method="GET",
    path="/users/{user_id}",
    description="Get user by ID"
))
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

**Managing skills:**

```python
# Delete a skill
skills.delete("scrape_hn_stories")
```

## Artifacts

Store and retrieve data across sessions:

```python
# Save data
artifacts.save("research_results", {"findings": [...], "sources": [...]})

# Load data
data = artifacts.load("research_results")

# List all artifacts
artifacts.list()

# Delete an artifact
artifacts.delete("research_results")
```

## Production

- **Redis storage** - One agent learns, all agents benefit
- **Container isolation** - Execute untrusted agent code safely

```python
from py_code_mode import Session, RedisStorage
from py_code_mode.execution import ContainerExecutor, ContainerConfig

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
