# py-code-mode

[![CI](https://github.com/xpcmdshell/py-code-mode/actions/workflows/ci.yml/badge.svg)](https://github.com/xpcmdshell/py-code-mode/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A scripting engine for AI agents that learns. Skills accumulate as institutional knowledge.

## How Agents Use It

```python
# 1. Agent searches for a skill that matches the task
results = skills.search("analyze website for vulnerabilities")

# 2. Found one? Use it
if results:
    report = skills.web_vuln_scan(url="https://target.com")

# 3. No skill exists? Compose tools to solve the task
else:
    content = tools.fetch(url="https://target.com")
    headers = tools.curl(url="https://target.com", flags="-I")
    scan = tools.nikto(target="target.com")

    # 4. Save the recipe as a reusable skill
    skills.create(
        name="web_vuln_scan",
        code='''
def run(url: str) -> dict:
    content = tools.fetch(url=url)
    headers = tools.curl(url=url, flags="-I")
    scan = tools.nikto(target=url)
    return {"content": content, "headers": headers, "scan": scan}
''',
        description="Fetch content, headers, and run nikto scan on a URL"
    )
```

Next time any agent needs this capability, the skill already exists.

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
    result = await session.run('skills.search("port scanning")')
    print(result.value)
```

## Three Namespaces

Agents get access to:

- **tools** - CLI commands, MCP servers, and APIs you've wrapped
- **skills** - Reusable recipes (agent-created or human-authored)
- **artifacts** - Persistent storage across sessions

## Defining Tools

Tools are YAML files wrapping external capabilities:

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

## Writing Skills

You can seed skills for agents to find:

```python
# skills/analyze_url.py
"""Fetch a URL and summarize its content."""

def run(url: str) -> dict:
    content = tools.fetch(url=url)
    return {"url": url, "word_count": len(content.split()), "content": content}
```

Or let agents create them at runtime via `skills.create()`.

## Production

- **Redis storage** - Share skills across agents (one agent learns, all benefit)
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

- **minimal/** - Simple agent in ~100 lines
- **autogen-direct/** - AutoGen integration
- **azure-container-apps/** - Production deployment

## License

MIT
