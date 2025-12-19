# py-code-mode

[![CI](https://github.com/xpcmdshell/py-code-mode/actions/workflows/ci.yml/badge.svg)](https://github.com/xpcmdshell/py-code-mode/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Tools your agents can search, compose, and learn from.

Give your agents:
- **Tools** they can discover via semantic search (not schema dumps)
- **Skills** - reusable recipes they can find, use, and create
- **Artifacts** - persistent storage across sessions

Works with Claude Code (MCP), AutoGen, LangChain, or any Python agent.

## Installation

```bash
pip install py-code-mode
```

## Quick Start

### Claude Code (MCP)

Add py-code-mode to Claude Code:

```bash
claude mcp add py-code-mode -- uvx py-code-mode --tools ./tools --skills ./skills
```

Now Claude can:
- **Search and call your tools**: "find a tool for network scanning" → uses nmap
- **Find and run skills**: "analyze this website" → finds and runs analyze_url skill
- **Create new skills**: "save this as a reusable skill" → persists for next time

### Agent Frameworks (Python)

```python
from pathlib import Path
from py_code_mode import Session, FileStorage

storage = FileStorage(base_path=Path("./configs"))

async with Session(storage=storage) as session:
    # Agent writes code, session runs it
    result = await session.run('''
        # Search for relevant tools
        tools.search("web search")

        # Call tools
        results = tools.brave_search(query="python async patterns")

        # Fetch and analyze a result
        content = tools.fetch(url=results[0]["url"])

        # Use existing skills
        skills.summarize(text=content)
    ''')
```

## Why Code Mode?

**Progressive disclosure**: Your agent has 100 tools available, but searches by intent instead of seeing all schemas dumped in context. `tools.search("network scan")` returns the relevant subset.

**Composition**: Multi-tool workflows in one execution:

```python
for target in targets:
    scan = tools.nmap(target=target, flags="-sV")
    if "open" in scan:
        content = tools.fetch(url=f"http://{target}")
        artifacts.save(f"{target}.md", content)
```

vs N separate tool calls with LLM reasoning between each.

**Python ecosystem**: Agent writes Python, so it can use any installed package - pandas for data analysis, BeautifulSoup for parsing, whatever you need.

**Learning**: Agent finds existing skill → uses it. No skill exists → creates one → available next time. Skills accumulate as institutional knowledge.

## Concepts

### Tools

External commands wrapped as callable functions. Three adapter types:

- **CLI** - Shell commands (nmap, ffmpeg, git, etc.) - wrap tools Python can't easily replace
- **MCP** - Model Context Protocol servers - AI-native tools like web search and content extraction
- **HTTP** - REST API endpoints

Agents call tools via `tools.nmap(target="10.0.0.1")` or `tools.call("nmap", {...})`.

### Skills

Reusable Python recipes that compose tools. Skills are:

- **Searchable** - Semantic search finds relevant skills by description
- **Inspectable** - Agents can read skill source to understand or adapt them
- **Persistent** - Store in files (dev) or Redis (production)
- **Composable** - Skills can call other skills and tools

### Artifacts

Persistent storage for data across sessions:

```python
artifacts.save("results.json", data, description="Scan results")
data = artifacts.load("results.json")
artifacts.list()  # See all saved artifacts
```

## Defining Tools

Tools are YAML files in your `tools/` directory.

**CLI tools** - wrap existing commands:

```yaml
# tools/nmap.yaml
name: nmap
type: cli
args: "{flags} {target}"
description: Network scanner for port scanning and service detection
timeout: 300
```

**MCP tools via stdio** - connect to MCP servers:

```yaml
# tools/brave_search.yaml
name: brave_search
type: mcp
transport: stdio
command: npx
args: ["-y", "@anthropic/mcp-brave-search"]
description: Web search via Brave Search API
```

**MCP tools via SSE** - connect to remote MCP servers:

```yaml
# tools/fetch.yaml
name: fetch
type: mcp
transport: sse
url: http://localhost:8080/mcp
description: Fetch URL content as clean markdown
```

## Writing Skills

Skills are Python files with a `run()` function. They have access to `tools`, `skills`, and `artifacts`.

```python
# skills/analyze_url.py
"""Fetch a URL and summarize its content."""

def run(url: str, max_length: int = 500) -> dict:
    # Fetch content as markdown
    content = tools.fetch(url=url)

    # Use Python libraries
    word_count = len(content.split())

    # Call other skills
    summary = skills.summarize(text=content, max_length=max_length)

    return {
        "url": url,
        "word_count": word_count,
        "summary": summary,
    }
```

Skills can be:
- **Invoked**: `skills.analyze_url(url="https://example.com")`
- **Searched**: `skills.search("analyze website content")`
- **Inspected**: `skills.get("analyze_url").source`
- **Created at runtime**: `skills.create(name="...", code="...", description="...")`

## API Reference

### Session

The main entry point. Create with storage and optional executor:

```python
from pathlib import Path
from py_code_mode import Session, FileStorage

# File-based storage (creates tools/, skills/, artifacts/ subdirs)
storage = FileStorage(base_path=Path("./data"))

async with Session(storage=storage) as session:
    result = await session.run('tools.list()')
```

### Tool Operations

```python
# Call a tool
tools.nmap(target="10.0.0.1", flags="-sV")
tools.call("nmap", {"target": "10.0.0.1", "flags": "-sV"})

# Search tools by intent
tools.search("network scanning")

# List all tools
tools.list()
```

### Skill Operations

```python
# Invoke a skill
skills.analyze_url(url="https://example.com")
skills.invoke("analyze_url", url="https://example.com")

# Search skills by intent
skills.search("analyze website", limit=5)

# List all skills
skills.list()

# Get skill details
skill = skills.get("analyze_url")
print(skill.source)
print(skill.parameters)

# Create new skill at runtime
skills.create(
    name="quick_scan",
    code='def run(target: str): return tools.nmap(target=target, flags="-F")',
    description="Fast port scan"
)
```

### Typed Executors

Session accepts typed executor instances for different isolation levels:

```python
from py_code_mode import Session, FileStorage
from py_code_mode.backends.in_process import InProcessExecutor
from py_code_mode.backends.container import ContainerExecutor, ContainerConfig

storage = FileStorage(base_path=Path("./data"))

# In-process execution (default when executor omitted)
async with Session(storage=storage, executor=InProcessExecutor()) as session:
    result = await session.run('2 + 2')

# Container isolation for production
config = ContainerConfig(image="py-code-mode:latest", timeout=60.0)
async with Session(storage=storage, executor=ContainerExecutor(config)) as session:
    result = await session.run('tools.nmap(target="10.0.0.1")')
```

## Configuration

### Embedding Model

Semantic search uses BGE-small by default. You can specify a different model:

```bash
# MCP server with custom model
py-code-mode-mcp --tools ./tools --skills ./skills --embedding-model bge-base

# Or any HuggingFace model
py-code-mode-mcp --tools ./tools --skills ./skills --embedding-model intfloat/e5-large-v2
```

Built-in aliases:
- `bge-small` (default) - BAAI/bge-small-en-v1.5, fast, good quality
- `bge-base` - BAAI/bge-base-en-v1.5, slightly better quality, slower
- `granite` - ibm-granite/granite-embedding-small-english-r2

Python API:

```python
from py_code_mode import Session, FileStorage

# Embedding model configured via environment or storage options
storage = FileStorage(base_path=Path("./data"))

async with Session(storage=storage) as session:
    # Semantic search uses configured embedding model
    result = await session.run('tools.search("network scanning")')
```

## Production

### Redis Backend

For distributed deployments, use Redis for tools, skills, and artifacts:

```python
import redis as redis_lib
from py_code_mode import Session, RedisStorage

client = redis_lib.from_url("redis://localhost:6379")
storage = RedisStorage(redis=client, prefix="my-agent")

async with Session(storage=storage) as session:
    result = await session.run('tools.list()')
```

MCP server with Redis:

```bash
py-code-mode-mcp --backend redis --url redis://localhost:6379 --prefix my-agent
```

### Container Isolation

For production, use ContainerExecutor with Docker:

```python
from py_code_mode import Session, FileStorage
from py_code_mode.backends.container import ContainerExecutor, ContainerConfig

storage = FileStorage(base_path=Path("./data"))
config = ContainerConfig(image="py-code-mode:latest", timeout=60.0)

async with Session(storage=storage, executor=ContainerExecutor(config)) as session:
    result = await session.run('tools.nmap(target="scanme.nmap.org")')
```

Build the container image:

```bash
docker build -f docker/Dockerfile.tools -t py-code-mode:latest .
```

## Examples

See `examples/` for complete examples:

- **minimal/** - Simple agent in ~100 lines, no framework
- **autogen-direct/** - AutoGen with py-code-mode wired directly (more control)
- **autogen-mcp/** - AutoGen connecting via MCP protocol (simpler setup)
- **azure-container-apps/** - Production deployment on Azure

## License

MIT
