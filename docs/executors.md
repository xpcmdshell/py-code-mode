# Executors

Executors determine where and how agent code runs. Three backends are available: Subprocess, Container, and InProcess.

## Quick Decision Guide

```
Which executor should I use?

Start here: SubprocessExecutor (recommended default)
  - Process isolation, crash recovery, clean environments
  - No Docker required
  - Used by the MCP server

Need stronger isolation? → ContainerExecutor
  - Untrusted code, production, multi-tenant
  - Filesystem and network isolation
  - Requires Docker

Need maximum speed AND trust the code completely? → InProcessExecutor
  - No isolation (runs in your process)
  - Only for trusted code you control
```

| Requirement | Subprocess | Container | InProcess |
|-------------|------------|-----------|-----------|
| **Recommended for most users** | **Yes** | | |
| Process isolation | Yes | Yes | No |
| Crash recovery | Yes | Yes | No |
| Container isolation | No | Yes | No |
| No Docker required | Yes | No | Yes |
| Resource limits | Partial | Full | No |
| Untrusted code | No | Yes | No |

---

## SubprocessExecutor (Recommended)

Code runs in a Jupyter kernel subprocess. Process-level isolation without Docker overhead. **This is the recommended starting point for most users.**

```python
from pathlib import Path
from py_code_mode import Session, FileStorage
from py_code_mode.execution import SubprocessExecutor, SubprocessConfig

storage = FileStorage(base_path=Path("./data"))

config = SubprocessConfig(
    tools_path=Path("./tools"),  # Path to YAML tool definitions
    default_timeout=120.0,       # Execution timeout
)

executor = SubprocessExecutor(config)

async with Session(storage=storage, executor=executor) as session:
    result = await session.run(agent_code)
```

### Why SubprocessExecutor is the Default Choice

- **Crash recovery** - If agent code crashes, your main process continues running
- **Clean environment** - Fresh virtual environment for predictable behavior
- **Process isolation** - Agent code can't interfere with your application state
- **No Docker required** - Works everywhere Python runs
- **Production-ready** - Used by the MCP server for Claude Code integration

### Configuration Options

```python
SubprocessConfig(
    tools_path=Path("./tools"),  # Path to YAML tool definitions
    deps=["pandas", "numpy"],    # Pre-configured dependencies
    python_version="3.11",       # Python version (default: current version)
    default_timeout=120.0,       # Default timeout in seconds
    allow_runtime_deps=True,     # Allow runtime package installation
    venv_dir=None                # Custom venv directory (default: temp dir)
)
```

### When to Use

- **Development and prototyping** - Isolated environment prevents accidents
- **MCP server deployments** - Default for Claude Code integration
- **CI/CD pipelines** - No Docker dependency
- **Any situation where you want safety without complexity**

### Limitations

- Process-level isolation only (not containerized)
- Subprocess shares host filesystem access
- No network isolation
- No resource limits beyond OS process limits

---

## ContainerExecutor

Code runs in a Docker container. Full isolation for untrusted code and production deployments.

```python
from pathlib import Path
import os
from py_code_mode import Session, FileStorage
from py_code_mode.execution import ContainerExecutor, ContainerConfig

storage = FileStorage(base_path=Path("./data"))

config = ContainerConfig(
    tools_path=Path("./tools"),  # Path to YAML tool definitions (mounted into container)
    deps=["requests"],           # Pre-configured dependencies
    timeout=60.0,                # Execution timeout
    allow_runtime_deps=False,    # Lock down deps for security
    auth_token=os.getenv("CONTAINER_AUTH_TOKEN"),  # Required for production
)

executor = ContainerExecutor(config)

async with Session(storage=storage, executor=executor) as session:
    result = await session.run(agent_code)
```

For local development, you can disable auth:

```python
config = ContainerConfig(
    tools_path=Path("./tools"),
    auth_disabled=True,  # Only for local development!
)
```

### Features

- **Full isolation** - Container-level sandboxing
- **Network control** - Can disable network access
- **Resource limits** - CPU, memory, disk quotas
- **Clean state** - Each execution in fresh container

### Configuration Options

```python
ContainerConfig(
    tools_path=Path("./tools"),  # Path to YAML tool definitions (mounted)
    deps=["requests"],           # Pre-configured dependencies
    timeout=60.0,                # Execution timeout
    allow_runtime_deps=False,    # Lock down package installation
    auth_token="secret",         # Bearer token for API auth (production)
    auth_disabled=False,         # Set True for local dev only (no auth)
    network_disabled=False,      # Disable container network access
    memory_limit="512m",         # Container memory limit
    cpu_quota=None               # CPU quota (default: no limit)
)
```

### Authentication

The container HTTP API requires authentication by default (fail-closed design):

| Setting | Behavior |
|---------|----------|
| `auth_token="secret"` | Requests must include `Authorization: Bearer secret` |
| `auth_disabled=True` | No authentication required (local dev only) |
| Neither set | Container refuses to start |

**Important:** Always use `auth_token` in production. The `auth_disabled` option is only for local development convenience.

### Container Images

Container executor requires Docker images:

```bash
# Build base image (includes Python + core dependencies)
docker build -t py-code-mode:base -f docker/Dockerfile.base .

# Build tools image (includes additional tools if needed)
docker build -t py-code-mode:tools -f docker/Dockerfile.tools .
```

### When to Use

- **Untrusted agent code** - Users you don't control
- **Production deployments** - Maximum security
- **Multi-tenant environments** - Tenant isolation
- **Compliance requirements** - Audit-friendly isolation

### Limitations

- Requires Docker daemon
- Slower startup than subprocess
- More complex deployment
- Container image must be kept up-to-date with code changes

---

## InProcessExecutor

Code runs in the same Python process as your application. Fastest option, but provides **no isolation**.

> **Warning:** InProcessExecutor runs agent code directly in your process. A crash in agent code crashes your application. Only use this when you fully trust the code and need maximum performance.

```python
from pathlib import Path
from py_code_mode import Session, FileStorage
from py_code_mode.execution import InProcessExecutor, InProcessConfig

storage = FileStorage(base_path=Path("./data"))

config = InProcessConfig(
    tools_path=Path("./tools"),  # Path to YAML tool definitions
    deps=["pandas>=2.0", "numpy"],  # Pre-configured dependencies
    default_timeout=30.0,        # Default execution timeout in seconds
    allow_runtime_deps=True      # Allow agents to install packages at runtime
)

executor = InProcessExecutor(config)

async with Session(storage=storage, executor=executor) as session:
    result = await session.run(agent_code)
```

### Configuration Options

```python
InProcessConfig(
    tools_path=Path("./tools"),  # Path to YAML tool definitions
    deps=["pandas>=2.0", "numpy"],  # Pre-configured dependencies
    default_timeout=30.0,        # Default execution timeout in seconds
    allow_runtime_deps=True      # Allow agents to install packages at runtime
)
```

### When to Use

- **Trusted code only** - Code you wrote or fully control
- **Performance-critical** - When subprocess overhead matters
- **Debugging** - Easier to debug in single process
- **Simple scripts** - Quick experiments where isolation doesn't matter

### When NOT to Use

- **Untrusted agent code** - Use ContainerExecutor instead
- **Production with user-generated code** - Use ContainerExecutor
- **Long-running services** - Crashes take down your app
- **Multi-tenant** - No isolation between tenants

### Risks

| Risk | Consequence |
|------|-------------|
| Agent code crashes | Your entire application crashes |
| Agent code hangs | Your application may hang |
| Agent installs malicious package | Package runs in your process |
| Agent modifies global state | Affects your application state |

---

## Switching Executors

Executors are interchangeable - the same Session code works with any executor:

```python
from pathlib import Path
import os
from py_code_mode import Session, FileStorage
from py_code_mode.execution import (
    SubprocessExecutor, SubprocessConfig,
    ContainerExecutor, ContainerConfig,
    InProcessExecutor, InProcessConfig,
)

storage = FileStorage(base_path=Path("./data"))
tools_path = Path("./tools")

# Development: Subprocess for safety (recommended)
config = SubprocessConfig(tools_path=tools_path)
executor = SubprocessExecutor(config)
async with Session(storage=storage, executor=executor) as session:
    result = await session.run(code)

# Production: Container for maximum security
config = ContainerConfig(tools_path=tools_path, auth_token=os.getenv("AUTH_TOKEN"))
executor = ContainerExecutor(config)
async with Session(storage=storage, executor=executor) as session:
    result = await session.run(code)

# Trusted code only: InProcess for speed
config = InProcessConfig(tools_path=tools_path)
executor = InProcessExecutor(config)
async with Session(storage=storage, executor=executor) as session:
    result = await session.run(code)
```

## Executor Lifecycle

All executors follow the same lifecycle:

```python
# Initialization
executor = SubprocessExecutor(config)

# Session creation (executor starts)
async with Session(storage=storage, executor=executor) as session:
    # Execute code
    result = await session.run(code)
    # Session cleanup (executor stops)

# Executor is cleaned up after session ends
```

For ContainerExecutor and SubprocessExecutor, cleanup includes:
- Stopping the subprocess/container
- Cleaning up temporary resources
- Removing the isolated environment

## Best Practices

**Development:**
- Use SubprocessExecutor for safe iteration with crash recovery
- Switch to InProcessExecutor only if debugging requires it

**Production:**
- Use ContainerExecutor for untrusted code
- Use SubprocessExecutor for trusted internal agents
- Pre-configure dependencies with `allow_runtime_deps=False`
- Set appropriate timeouts based on expected workload
- Monitor executor health and resource usage

**Testing:**
- Test with SubprocessExecutor to catch isolation issues early
- Use ContainerExecutor to validate production behavior
