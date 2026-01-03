# Framework Integrations

py-code-mode integrates with agent frameworks via two approaches: MCP protocol or direct SDK.

## Integration Approaches

| Approach | Best For | Complexity |
|----------|----------|------------|
| **MCP** | Any MCP-capable framework, quick setup | Low |
| **Direct SDK** | Custom control, lower latency | Medium |

---

## MCP Integration

The MCP server exposes py-code-mode as a standard Model Context Protocol server. Any MCP-capable framework can connect.

### Setup

```bash
# Install and run MCP server
py-code-mode-mcp --base ~/.code-mode
```

### Available Tools

The MCP server exposes these tools:

| Tool | Purpose |
|------|---------|
| `run_code` | Execute Python with access to tools/skills/artifacts |
| `list_tools` / `search_tools` | Discover available tools |
| `list_skills` / `search_skills` | Discover available skills |
| `create_skill` / `delete_skill` | Manage skills |
| `list_artifacts` | List saved data |
| `list_deps` / `add_dep` / `remove_dep` | Manage dependencies |

### Framework Examples

#### Claude Code

```bash
claude mcp add py-code-mode -- uvx --from git+https://github.com/xpcmdshell/py-code-mode.git@v0.10.0 py-code-mode-mcp --base ~/.code-mode
```

#### Generic MCP Client

```python
import subprocess
import json

# Start MCP server as subprocess
proc = subprocess.Popen(
    ["py-code-mode-mcp", "--base", "~/.code-mode"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
)

# Send MCP messages via stdio
# (Use your framework's MCP client library for proper protocol handling)
```

---

## Direct SDK Integration

For frameworks that don't support MCP or need lower latency, use the Session API directly.

### Basic Pattern

```python
from pathlib import Path
from py_code_mode import Session, FileStorage
from py_code_mode.execution import SubprocessExecutor, SubprocessConfig

# Create session
storage = FileStorage(base_path=Path("./data"))
config = SubprocessConfig(tools_path=Path("./tools"))
executor = SubprocessExecutor(config=config)

async def execute_agent_code(code: str) -> str:
    """Execute code from your agent framework."""
    async with Session(storage=storage, executor=executor) as session:
        result = await session.run(code)
        
        if result.is_ok:
            output = str(result.value) if result.value is not None else ""
            if result.stdout:
                output = f"{result.stdout}\n{output}" if output else result.stdout
            return output
        else:
            return f"Error: {result.error}"
```

### Persistent Session Pattern

For agents that make multiple code execution calls, keep the session open:

```python
class CodeExecutionTool:
    """Reusable code execution tool for agent frameworks."""
    
    def __init__(self, storage_path: Path, tools_path: Path):
        self.storage = FileStorage(base_path=storage_path)
        config = SubprocessConfig(tools_path=tools_path)
        self.executor = SubprocessExecutor(config=config)
        self.session: Session | None = None
    
    async def start(self):
        """Initialize session. Call before agent loop."""
        self.session = Session(storage=self.storage, executor=self.executor)
        await self.session.start()
    
    async def stop(self):
        """Cleanup. Call after agent loop."""
        if self.session:
            await self.session.close()
            self.session = None
    
    async def run(self, code: str, timeout: float = 30.0) -> str:
        """Execute code. Variables persist across calls."""
        if not self.session:
            raise RuntimeError("Call start() first")
        
        result = await self.session.run(code, timeout=timeout)
        
        if result.is_ok:
            output = str(result.value) if result.value is not None else ""
            if result.stdout:
                output = f"{result.stdout}\n{output}" if output else result.stdout
            return output or "(no output)"
        else:
            return f"Error: {result.error}"
    
    async def __aenter__(self):
        await self.start()
        return self
    
    async def __aexit__(self, *args):
        await self.stop()
```

**Usage:**

```python
async with CodeExecutionTool(Path("./data"), Path("./tools")) as tool:
    # Variables persist across calls
    await tool.run("x = 42")
    result = await tool.run("x * 2")  # Returns "84"
```

### Tool Definition for LLM

When registering with your framework, provide a clear tool description:

```python
TOOL_DESCRIPTION = """Execute Python code with access to tools, skills, and artifacts.

NAMESPACES:
- tools.* - Call registered tools (e.g., tools.curl.get(url="..."))
- skills.* - Invoke reusable workflows (e.g., skills.invoke("fetch_json", url="..."))
- artifacts.* - Persist data (e.g., artifacts.save("key", data))
- deps.* - Manage packages (e.g., deps.add("pandas"))

Variables persist across calls within the same session.

WORKFLOW:
1. Search for existing skills: skills.search("your task")
2. If found, invoke it: skills.invoke("skill_name", arg=value)
3. Otherwise, write code using tools
4. Save successful workflows as skills for reuse
"""
```

---

## Redis Backend for Multi-Agent

When running multiple agent instances, use Redis for shared skill library:

```python
from py_code_mode import Session, RedisStorage
from py_code_mode.execution import SubprocessExecutor, SubprocessConfig

# All instances share skills via Redis
storage = RedisStorage(url="redis://localhost:6379", prefix="my-agents")
config = SubprocessConfig(tools_path=Path("./tools"))
executor = SubprocessExecutor(config=config)

async with Session(storage=storage, executor=executor) as session:
    # Skills created by any agent are available to all
    result = await session.run(code)
```

---

## Production Patterns

### Container Isolation

For untrusted agent code, use ContainerExecutor:

```python
from py_code_mode.execution import ContainerExecutor, ContainerConfig

config = ContainerConfig(
    tools_path=Path("./tools"),
    auth_token=os.getenv("CONTAINER_AUTH_TOKEN"),
    timeout=60.0,
    allow_runtime_deps=False,
)
executor = ContainerExecutor(config)
```

### Timeout Handling

```python
async def safe_execute(session: Session, code: str) -> str:
    try:
        result = await session.run(code, timeout=30.0)
        if result.is_ok:
            return str(result.value)
        return f"Error: {result.error}"
    except TimeoutError:
        return "Error: Execution timed out"
```

### Error Recovery

```python
async def execute_with_retry(session: Session, code: str, retries: int = 2) -> str:
    for attempt in range(retries + 1):
        result = await session.run(code)
        if result.is_ok:
            return str(result.value)
        
        # Reset on failure to clear potentially corrupted state
        if attempt < retries:
            await session.reset()
    
    return f"Error after {retries + 1} attempts: {result.error}"
```

---

## Examples

See working integration examples:

- **[examples/minimal/](../examples/minimal/)** - Simple agent (~100 lines)
- **[examples/subprocess/](../examples/subprocess/)** - SubprocessExecutor usage
- **[examples/azure-container-apps/](../examples/azure-container-apps/)** - Production deployment
