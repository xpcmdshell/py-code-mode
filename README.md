# py-code-mode

Python library enabling "code mode" for LLM agents - agents write Python code, executor runs it with injected namespaces for tools, skills, and artifacts.

## Installation

```bash
pip install py-code-mode

# With container support
pip install py-code-mode[container]
```

## Quick Start

**1. Create your tools directory:**

```
my_agent/
  tools/
    nmap.yaml
    curl.yaml
  skills/
    scan_ports.py
```

**2. Define tools as YAML files:**

```yaml
# tools/nmap.yaml
name: nmap
args: "{flags} {target}"
description: Network scanner
tags: [recon]
timeout: 300
```

```yaml
# tools/curl.yaml
name: curl
args: "-s {url}"
description: HTTP client
```

**3. Write skills as Python files:**

```python
# skills/scan_ports.py
"""Scan common ports on a target."""

def run(target: str, ports: list[int] = [22, 80, 443]) -> dict:
    results = {}
    for port in ports:
        output = tools.nmap(target=target, flags=f"-p {port}")
        results[port] = "open" in output
    return results
```

**4. Create executor and run code:**

```python
from py_code_mode import CodeExecutor

executor = await CodeExecutor.create(
    tools="./my_agent/tools/",
    skills="./my_agent/skills/",
)

# Agent writes Python code
result = await executor.run('''
    scan = tools.nmap(target="10.0.0.1", flags="-sV")
    skills.invoke("scan_ports", target="10.0.0.1")
''')

print(result.value)
```

## Architecture

```
Agent (LLM)
    |
    | writes Python code string
    v
+---------------------------------------------------------------+
|                        CodeExecutor                           |
|                                                               |
|   Namespaces available in executed code:                      |
|                                                               |
|   tools.*          skills.*             artifacts.*           |
|       |                |                     |                |
|       v                v                     v                |
|   ToolRegistry    SkillsNamespace      ArtifactStore          |
|       |                |                     |                |
|       v                v                     v                |
|   Adapters        SkillLibrary          File/Redis            |
|   +-- CLI         (semantic search)                           |
|   +-- MCP              |                                      |
|   +-- HTTP        SkillStore                                  |
|                   +-- Memory                                  |
|                   +-- File                                    |
|                   +-- Redis                                   |
+---------------------------------------------------------------+
```

## Concepts

### Tools

External commands wrapped as callable functions. Three adapter types:

- **CLI** - Shell commands (nmap, curl, dig, etc.)
- **MCP** - Model Context Protocol servers (stdio or SSE transport)
- **HTTP** - REST API endpoints

Agents call tools via `tools.nmap(target="10.0.0.1")` or `tools.call("nmap", {...})`.

### Skills

Reusable Python code recipes that can use tools. Skills are:

- **Searchable** - Semantic search finds relevant skills by description
- **Inspectable** - Agents can read skill source code to understand or adapt them
- **Persistent** - Store in files (dev) or Redis (production)

Agents invoke skills via `skills.invoke("scan_ports", target="10.0.0.1")` or `skills.scan_ports(target="10.0.0.1")`.

### Artifacts

Persistent storage for saving/loading data across sessions:

```python
artifacts.save("results.json", data, description="Scan results")
data = artifacts.load("results.json")
artifacts.list()  # See all saved artifacts
```

## Tool Types

All tools go in the same `tools/` directory. The `type` field determines how they're executed:

**CLI tools (default):**
```yaml
# tools/nmap.yaml
name: nmap
type: cli
args: "{flags} {target}"
description: Network scanner
```

**MCP tools via stdio:**
```yaml
# tools/brave_search.yaml
name: brave_search
type: mcp
transport: stdio
command: npx
args: ["-y", "@anthropic/mcp-brave-search"]
```

**MCP tools via SSE:**
```yaml
# tools/weather.yaml
name: weather
type: mcp
transport: sse
url: http://localhost:8080/mcp
```

## API

### CodeExecutor.create()

The main way to create an executor:

```python
executor = await CodeExecutor.create(
    tools="./tools/",       # Directory of tool YAML files
    skills="./skills/",     # Directory of skill .py files
    artifacts="./data/",    # Directory for persistent storage
)
```

### Explicit Components

For more control, construct components directly:

```python
from pathlib import Path
from py_code_mode import (
    CodeExecutor,
    ToolRegistry,
    FileSkillStore,
    FileArtifactStore,
    create_skill_library,
)

# Tools (loads CLI and MCP tools from YAML files)
registry = await ToolRegistry.from_dir("./tools/")

# Skills with semantic search
store = FileSkillStore(Path("./skills"))
skill_library = create_skill_library(store=store)

# Artifacts
artifacts = FileArtifactStore(Path("./data"))

# Executor
executor = CodeExecutor(
    registry=registry,
    skill_library=skill_library,
    artifact_store=artifacts,
)
```

### Redis Backend (Production)

For distributed deployments, use Redis for skills and artifacts:

```python
from redis import Redis
from py_code_mode import RedisSkillStore, RedisArtifactStore, create_skill_library

redis = Redis.from_url("redis://localhost:6379")

# Skills
store = RedisSkillStore(redis, prefix="my-agent")
skill_library = create_skill_library(store=store)

# Artifacts
artifacts = RedisArtifactStore(redis, prefix="my-agent")

executor = CodeExecutor(
    registry=registry,
    skill_library=skill_library,
    artifact_store=artifacts,
)
```

### Tool Syntax

Agents can call tools either way:

```python
# Pythonic (recommended)
tools.nmap(target="10.0.0.1", flags="-sV")

# Dict-based
tools.call("nmap", {"target": "10.0.0.1", "flags": "-sV"})

# Discovery
tools.list()
tools.search("network")
```

### Skill Operations

```python
# Invoke a skill
skills.invoke("scan_ports", target="10.0.0.1")
skills.scan_ports(target="10.0.0.1")  # Attribute syntax

# Search for skills
skills.search("port scanning", limit=5)

# List all skills
skills.list()

# Get skill details (including source)
skill = skills.get("scan_ports")
print(skill.source)

# Create new skill at runtime
skills.create(
    name="quick_scan",
    code='def run(target: str): return tools.nmap(target=target, flags="-F")',
    description="Fast port scan"
)
```

## Container Isolation

For production, run in Docker with multi-session support:

```python
from py_code_mode.container import SessionClient

async with SessionClient("http://localhost:8080") as client:
    result = await client.execute('tools.nmap(target="scanme.nmap.org")')
    print(result.value)
```

Build and run:

```bash
docker build -f docker/Dockerfile.tools -t py-code-mode-tools .
docker run -p 8080:8080 -v $(pwd)/tools:/workspace/tools py-code-mode-tools
```

## Framework Integration

Pre-built AutoGen integration:

```python
from py_code_mode.integrations.autogen import create_run_code_tool
from autogen_agentchat.agents import AssistantAgent

# Create tool for agent
run_code = create_run_code_tool(session_url="http://session-server:8080")

# Use with AutoGen
agent = AssistantAgent(name="analyst", model_client=model, tools=[run_code])
```

## Examples

See `examples/` for complete examples:

- `examples/minimal/` - Simple agent in ~100 lines, no framework
- `examples/autogen-direct/` - AutoGen with py-code-mode wired directly (more control)
- `examples/autogen-mcp/` - AutoGen connecting via MCP protocol (simpler setup)
- `examples/azure-container-apps/` - Production deployment on Azure

### MCP Server

py-code-mode can run as an MCP server, allowing any MCP-capable agent to use it:

```bash
# Add to Claude Code
claude mcp add py-code-mode -- py-code-mode-mcp --tools ./tools --skills ./skills

# Or with any MCP client
py-code-mode-mcp --tools ./tools --skills ./skills --artifacts ./artifacts
```

This exposes `run_code`, `list_tools`, `list_skills`, and `search_skills` as MCP tools.

## License

MIT
