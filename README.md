# py-code-mode

[![CI](https://github.com/xpcmdshell/py-code-mode/actions/workflows/ci.yml/badge.svg)](https://github.com/xpcmdshell/py-code-mode/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Let AI agents write Python code that discovers and uses your tools.

## The Problem

Traditional agent frameworks require:
- **N tool calls** with LLM reasoning between each step
- **All tool schemas** dumped into context (even irrelevant ones)
- **No memory** of successful patterns between sessions

py-code-mode fixes this. Agents write Python code that searches for tools, composes multi-step workflows, and learns reusable skills.

## Installation

```bash
pip install py-code-mode
```

## Quick Start

### Claude Code (MCP)

```bash
claude mcp add py-code-mode -- uvx py-code-mode --tools ./tools --skills ./skills
```

Now Claude can search your tools, run skills, and create new ones.

### Python

```python
from pathlib import Path
from py_code_mode import Session, FileStorage

storage = FileStorage(base_path=Path("./data"))

async with Session(storage=storage) as session:
    result = await session.run('tools.nmap(target="scanme.nmap.org")')
    print(result.value)
```

## Why Code Mode?

**Search, don't dump**: Agent has 100 tools but discovers what it needs by intent. `tools.search("port scan")` returns relevant tools instead of 100 schemas in context.

**One execution, not N tool calls**:

```python
for target in targets:
    scan = tools.nmap(target=target, flags="-sV")
    if "open" in scan:
        content = tools.fetch(url=f"http://{target}")
        artifacts.save(f"{target}.md", content)
```

**Full Python ecosystem**: Agents write Python, so they can use pandas, BeautifulSoup, or any installed package.

**Skills accumulate**: Agent finds existing skill → uses it. No skill exists → creates one → available next time.

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

Skills are Python files with a `run()` function:

```python
# skills/analyze_url.py
"""Fetch a URL and summarize its content."""

def run(url: str, max_length: int = 500) -> dict:
    content = tools.fetch(url=url)
    summary = skills.summarize(text=content, max_length=max_length)
    return {"url": url, "word_count": len(content.split()), "summary": summary}
```

Skills have access to `tools`, `skills`, and `artifacts` automatically.

## API Overview

```python
# Tools
tools.search("network scanning")
tools.nmap(target="10.0.0.1")

# Skills
skills.search("analyze website")
skills.analyze_url(url="https://example.com")
skills.create(name="quick_scan", code="...", description="...")

# Artifacts
artifacts.save("results.json", data)
artifacts.load("results.json")
```

## Production

- **Redis storage**: Distributed tools, skills, and artifacts
- **Container isolation**: Execute untrusted code in Docker

```python
# Redis backend
from py_code_mode import Session, RedisStorage
storage = RedisStorage(redis=client, prefix="my-agent")

# Container execution
from py_code_mode.backends.container import ContainerExecutor, ContainerConfig
executor = ContainerExecutor(ContainerConfig(timeout=60.0))
async with Session(storage=storage, executor=executor) as session:
    ...
```

See [docs/](docs/) for detailed production guides.

## Examples

- **minimal/** - Simple agent in ~100 lines
- **autogen-direct/** - AutoGen integration
- **azure-container-apps/** - Production deployment

## License

MIT
