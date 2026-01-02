# Tools

Tools wrap external capabilities as callable functions. Three adapter types supported: CLI, MCP, and HTTP.

**When to add tools:** When external capabilities lack good Python libraries. Don't wrap what `requests`, `subprocess`, or the stdlib already handle well.

## CLI Tools

Define command-line tools with YAML schema + recipes.

### Schema Definition

```yaml
# tools/curl.yaml
name: curl
description: Make HTTP requests
command: curl
timeout: 60
tags: [http, network]

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
      description: URL to request
```

**Schema fields:**
- `options` - Named flags/options with types: `boolean`, `string`, `array`, `integer`
- `positional` - Positional arguments in order
- `short` - Single-character flag alias (e.g., `-s` for `silent`)
- `tags` - Keywords for discovery (optional)

### Recipes

Recipes are pre-configured tool invocations for common patterns:

```yaml
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

  json:
    description: GET with JSON Accept header
    preset:
      silent: true
      location: true
      header: ["Accept: application/json"]
    params:
      url: {}
```

**Recipe fields:**
- `preset` - Default values baked into the recipe
- `params` - Parameters exposed to the agent (can have `default`)
- `description` - What this recipe does

### Agent Usage

```python
# Recipe invocation (recommended)
tools.curl.get(url="https://api.github.com/repos/owner/repo")
tools.curl.post(url="https://api.example.com/data", data='{"key": "value"}')

# Escape hatch - raw tool invocation (full control)
tools.curl(
    url="https://example.com",
    silent=True,
    location=True,
    header=["Accept: application/json", "User-Agent: MyAgent"]
)

# Discovery
tools.list()                    # All tools
tools.search("http")            # Search by name/description/tags
tools.curl.list()               # Recipes for a specific tool
```

## MCP Tools

Connect to Model Context Protocol servers:

```yaml
# tools/fetch.yaml
name: fetch
type: mcp
transport: stdio
command: uvx
args: ["mcp-server-fetch"]
description: Fetch web pages with full content extraction
```

**Configuration:**
- `type: mcp` - Identifies this as an MCP adapter
- `transport` - Currently only `stdio` supported
- `command` - Command to launch the MCP server
- `args` - Arguments passed to the command

### Agent Usage

MCP tools are namespaced by their YAML `name` field:

```python
# Use tools as defined by the MCP server
content = tools.web.fetch(url="https://example.com")
```

**Namespace naming:** Choose names that describe the capability domain, not the tool name. For example, use `web` instead of `fetch` (avoids `tools.fetch.fetch()`), or `datetime` instead of `time`.

## HTTP Tools

Wrap REST APIs (defined in Python):

```python
from py_code_mode.tools.adapters import HTTPAdapter, Endpoint
from py_code_mode.tools import ToolRegistry

# Create adapter
adapter = HTTPAdapter(base_url="https://api.github.com")

# Add endpoints
adapter.add_endpoint(Endpoint(
    name="get_repo",
    method="GET",
    path="/repos/{owner}/{repo}",
    description="Get repository metadata"
))

adapter.add_endpoint(Endpoint(
    name="list_issues",
    method="GET",
    path="/repos/{owner}/{repo}/issues",
    description="List repository issues"
))

# Create registry and add adapter
registry = ToolRegistry()
registry.add_adapter(adapter)

# Registry is passed to executor (typically via custom integration)
```

### Agent Usage

```python
# Path parameters are function arguments
repo = tools.github.get_repo(owner="anthropics", repo="anthropic-sdk-python")

# Query parameters passed as dict
issues = tools.github.list_issues(
    owner="anthropics",
    repo="anthropic-sdk-python",
    query_params={"state": "open", "labels": "bug"}
)
```

## Tool Discovery

Agents can discover and search tools:

```python
# List all available tools
all_tools = tools.list()
# Returns: [Tool(name="curl", description="...", callables=[...]), ...]

# Search by keyword
http_tools = tools.search("http")
# Searches tool names, descriptions, and tags

# List recipes for a tool
curl_recipes = tools.curl.list()
# Returns: [{"name": "get", "description": "...", "params": {...}}, ...]
```

## Registering Tools

### Via Executor Config (Recommended)

Tools are loaded from the `tools_path` configured on the executor:

```python
from pathlib import Path
from py_code_mode import Session, FileStorage
from py_code_mode.execution import InProcessConfig, InProcessExecutor

# Storage for skills and artifacts
storage = FileStorage(base_path=Path("./storage"))

# Executor loads tools from tools_path
config = InProcessConfig(tools_path=Path("./tools"))
executor = InProcessExecutor(config=config)

async with Session(storage=storage, executor=executor) as session:
    # Tools are available from config.tools_path
    result = await session.run('tools.curl.get(url="...")')
```

### File Layout

Place YAML tool definitions in your tools directory:

```
./tools/
  curl.yaml
  jq.yaml
  nmap.yaml
```

Each YAML file defines one tool with its schema and recipes.

## Best Practices

**Do add tools for:**
- External commands with no good Python library (nmap, jq)
- MCP servers providing specialized capabilities
- Internal REST APIs your agents need to call

**Don't add tools for:**
- Operations well-handled by Python stdlib (file I/O, JSON parsing)
- Operations well-handled by popular libraries (HTTP via requests)
- One-off operations that won't be reused

**Recipe design:**
- Create recipes for common workflows, not every possible flag combination
- Use descriptive names: `get`, `post`, `json_post` not `recipe1`, `recipe2`
- Preset sensible defaults (silent mode, follow redirects)
- Expose only the parameters that vary between invocations

## Examples

See [examples/](../examples/) for complete tool configurations in working agent applications.
