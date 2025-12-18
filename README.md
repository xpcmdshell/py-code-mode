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

### Explicit objects

For more control, use registries directly:

```python
from py_code_mode import CodeExecutor, ToolRegistry, SkillRegistry

executor = CodeExecutor(
    registry=await ToolRegistry.from_dir("./tools/"),
    skill_registry=SkillRegistry.from_dir("./skills/"),
)
```

### Tool syntax

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
- `examples/azure-container-apps/` - Production deployment on Azure

## License

MIT
