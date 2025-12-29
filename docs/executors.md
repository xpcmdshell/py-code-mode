# Executors

Executors determine where and how agent code runs. Three backends available: InProcess, Subprocess, and Container.

## InProcessExecutor (Default)

Code runs in the same Python process as your application. Fastest option, no isolation.

```python
from py_code_mode import Session, FileStorage
from pathlib import Path

storage = FileStorage(base_path=Path("./data"))

# InProcessExecutor is the default
async with Session(storage=storage) as session:
    result = await session.run(agent_code)
```

### Configuration

```python
from py_code_mode.execution import InProcessExecutor, InProcessConfig

config = InProcessConfig(
    default_timeout=30.0,  # Default execution timeout in seconds
    allow_runtime_deps=True  # Allow agents to install packages at runtime
)

executor = InProcessExecutor(config=config)

async with Session(storage=storage, executor=executor) as session:
    result = await session.run(agent_code)
```

### When to Use

- ✓ Development and prototyping
- ✓ Trusted agent code
- ✓ Performance-critical applications
- ✓ Simple deployment requirements

### When NOT to Use

- ✗ Untrusted agent code
- ✗ Need process isolation
- ✗ Multi-tenant environments
- ✗ Resource limiting requirements

---

## SubprocessExecutor

Code runs in a Jupyter kernel subprocess. Process-level isolation without Docker overhead.

```python
from py_code_mode.execution import SubprocessExecutor, SubprocessConfig

config = SubprocessConfig(
    python_version="3.11",  # Python version for the subprocess
    default_timeout=120.0,  # Execution timeout
    allow_runtime_deps=False  # Lock down dependency installation
)

executor = SubprocessExecutor(config)

async with Session(storage=storage, executor=executor) as session:
    result = await session.run(agent_code)
```

### Features

- **Process isolation** - Agent code runs in separate process
- **Clean environment** - Fresh venv created for each executor
- **Crash recovery** - Main process unaffected by agent crashes
- **Resource separation** - Subprocess can be monitored/limited separately

### Configuration Options

```python
SubprocessConfig(
    python_version="3.11",      # Python version (default: current version)
    default_timeout=120.0,      # Default timeout in seconds
    allow_runtime_deps=True,    # Allow runtime package installation
    venv_dir=None              # Custom venv directory (default: temp dir)
)
```

### When to Use

- ✓ Need isolation without Docker complexity
- ✓ Development on systems without Docker
- ✓ Moderate trust in agent code
- ✓ Want crash recovery without containers

### Limitations

- Process-level isolation only (not containerized)
- Subprocess shares host filesystem access
- No network isolation
- No resource limits beyond OS process limits

---

## ContainerExecutor

Code runs in a Docker container. Full isolation for untrusted code.

```python
from py_code_mode.execution import ContainerExecutor, ContainerConfig

config = ContainerConfig(
    timeout=60.0,  # Execution timeout
    allow_runtime_deps=False,  # Lock down deps for security
    auth_token="your-secret-token",  # API authentication (required for production)
)

executor = ContainerExecutor(config)

async with Session(storage=storage, executor=executor) as session:
    result = await session.run(agent_code)
```

For local development, you can disable auth:

```python
config = ContainerConfig(
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
    timeout=60.0,               # Execution timeout
    allow_runtime_deps=False,   # Lock down package installation
    auth_token="secret",        # Bearer token for API auth (production)
    auth_disabled=False,        # Set True for local dev only (no auth)
    network_disabled=False,     # Disable container network access
    memory_limit="512m",        # Container memory limit
    cpu_quota=None             # CPU quota (default: no limit)
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

- ✓ Untrusted agent code
- ✓ Production deployments
- ✓ Multi-tenant environments
- ✓ Need resource isolation
- ✓ Compliance/security requirements

### Limitations

- Requires Docker daemon
- Slower startup than subprocess
- More complex deployment
- Container image must be kept up-to-date with code changes

---

## Choosing an Executor

| Requirement | InProcess | Subprocess | Container |
|-------------|-----------|------------|-----------|
| Fastest execution | ✓ | | |
| Process isolation | | ✓ | ✓ |
| Container isolation | | | ✓ |
| No Docker required | ✓ | ✓ | |
| Crash recovery | | ✓ | ✓ |
| Resource limits | | Partial | ✓ |
| Untrusted code | | | ✓ |
| Simple deployment | ✓ | ✓ | |

## Switching Executors

Executors are interchangeable - same code works with any executor:

```python
# Development: InProcess for speed
async with Session(storage=storage) as session:
    result = await session.run(code)

# Testing: Subprocess for isolation
executor = SubprocessExecutor(SubprocessConfig())
async with Session(storage=storage, executor=executor) as session:
    result = await session.run(code)

# Production: Container for security (with auth)
executor = ContainerExecutor(ContainerConfig(auth_token=os.getenv("AUTH_TOKEN")))
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
- Use InProcessExecutor for fast iteration
- Switch to SubprocessExecutor when testing isolation

**Production:**
- Use ContainerExecutor for untrusted code
- Pre-configure dependencies with `allow_runtime_deps=False`
- Set appropriate timeouts based on expected workload
- Monitor executor health and resource usage

**Testing:**
- Test with all executors to ensure compatibility
- Use SubprocessExecutor for integration tests
- Use ContainerExecutor to validate production behavior
