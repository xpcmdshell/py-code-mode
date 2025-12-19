# py-code-mode

[![CI](https://github.com/xpcmdshell/py-code-mode/actions/workflows/ci.yml/badge.svg)](https://github.com/xpcmdshell/py-code-mode/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A scripting engine for AI agents. Write skills your agents can use, or let agents create their own.

## How It Works

You give agents a Python execution environment with three namespaces:

- **tools** - CLI commands, MCP servers, and APIs wrapped as functions
- **skills** - Reusable Python recipes (you write them, or agents create them)
- **artifacts** - Persistent storage across sessions

Agents write Python code. The engine runs it.

```python
# Agent searches for a skill, finds one, uses it
analysis = skills.analyze_url(url="https://example.com")

# No skill exists? Agent creates one for next time
skills.create(
    name="quick_recon",
    code='def run(target): return tools.nmap(target=target, flags="-F")',
    description="Fast port scan on a target"
)
```

Skills accumulate as institutional knowledge. Your agents get smarter over time.

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
    result = await session.run('tools.nmap(target="scanme.nmap.org")')
    print(result.value)
```

## Defining Tools

Tools are YAML files wrapping CLI commands, MCP servers, or HTTP APIs:

```yaml
# tools/nmap.yaml
name: nmap
type: cli
args: "{flags} {target}"
description: Network scanner for port discovery
timeout: 300
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

## Writing Skills

Skills are Python files with a `run()` function. They have access to `tools`, `skills`, and `artifacts`:

```python
# skills/analyze_url.py
"""Fetch a URL and summarize its content."""

def run(url: str, max_length: int = 500) -> dict:
    content = tools.fetch(url=url)
    summary = skills.summarize(text=content, max_length=max_length)
    return {"url": url, "word_count": len(content.split()), "summary": summary}
```

Or agents create skills at runtime:

```python
skills.create(
    name="quick_scan",
    code='def run(target: str): return tools.nmap(target=target, flags="-F")',
    description="Fast port scan"
)
```

## Production

- **Redis storage** - Share tools, skills, and artifacts across agents
- **Container isolation** - Execute untrusted agent code in Docker

```python
from py_code_mode import Session, RedisStorage
from py_code_mode.backends.container import ContainerExecutor, ContainerConfig

storage = RedisStorage(redis=client, prefix="my-agent")
executor = ContainerExecutor(ContainerConfig(timeout=60.0))

async with Session(storage=storage, executor=executor) as session:
    result = await session.run(agent_code)
```

## Examples

See `examples/` for complete integrations:

- **minimal/** - Simple agent in ~100 lines
- **autogen-direct/** - AutoGen integration
- **azure-container-apps/** - Production deployment

## License

MIT
