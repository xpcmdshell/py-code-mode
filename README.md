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
# First time: agent reasons through the problem
results = skills.search("security assessment")

if not results:
    # Compose tools to solve it
    dns = tools.dig(target=target)
    ports = tools.nmap(target=target, flags="-sV")
    vulns = tools.nikto(target=target)

    # Save the working solution
    skills.create(
        name="security_assessment",
        code='''
def run(target: str) -> dict:
    dns = tools.dig(target=target)
    ports = tools.nmap(target=target, flags="-sV")
    vulns = tools.nikto(target=target)
    return {"dns": dns, "ports": ports, "vulns": vulns}
''',
        description="DNS, port scan, and vulnerability scan on a target"
    )

# Next time: one call, no reasoning
report = skills.security_assessment(target="example.com")
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
    result = await session.run('skills.search("recon")')
```

## What Agents Get

Three namespaces injected into their execution environment:

- **tools** - Your CLI commands, MCP servers, and APIs wrapped as functions
- **skills** - Reusable workflows (agent-created or human-authored)
- **artifacts** - Persistent storage across sessions

## Defining Tools

Wrap external capabilities as YAML:

```yaml
# tools/nmap.yaml
name: nmap
type: cli
args: "{flags} {target}"
description: Network scanner for port discovery
```

```yaml
# tools/brave_search.yaml
name: brave_search
type: mcp
transport: stdio
command: npx
args: ["-y", "@anthropic/mcp-brave-search"]
description: Web search via Brave
```

## Seeding Skills

Pre-author skills for agents to find:

```python
# skills/analyze_url.py
"""Fetch a URL and analyze its content."""

def run(url: str) -> dict:
    content = tools.fetch(url=url)
    return {"url": url, "word_count": len(content.split())}
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
