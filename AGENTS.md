# Agent Instructions

## Branch Policy

**The `main` branch is protected.** You cannot push directly to main.

**ALWAYS create a feature branch before making changes:**

```bash
git checkout -b feature/description-of-work
# ... make changes ...
git push -u origin feature/description-of-work
# Then create a PR
```

---

## Project Overview

**py-code-mode** gives AI agents code execution with persistent skills and tool integration.

The core idea: Agents write Python code. When a workflow succeeds, they save it as a **skill**. Next time, they invoke the skill directly - no re-planning required.

**Python version:** 3.12+ (see `pyproject.toml`)

---

## Directory Structure

```
src/py_code_mode/
  cli/              # MCP server and store CLI commands
  execution/        # Executors: InProcess, Subprocess, Container
    subprocess/     # Jupyter kernel-based subprocess executor
    container/      # Docker container executor
    in_process/     # Same-process executor
  skills/           # Skill storage, library, and vector stores
  tools/            # Tool adapters: CLI, MCP, HTTP
    adapters/       # CLI, MCP, HTTP adapter implementations
  artifacts/        # Artifact storage (file, redis)
  deps/             # Dependency management (installer, store)
  storage/          # Storage backends (FileStorage, RedisStorage)
  integrations/     # Framework integrations (autogen)

tests/              # All tests (pytest)
  container/        # Container-specific tests

docs/               # Documentation
examples/           # Example implementations
```

---

## Key Concepts

### Four Namespaces

When agents write code, four namespaces are available:

| Namespace | Purpose |
|-----------|---------|
| `tools.*` | CLI commands, MCP servers, HTTP APIs |
| `skills.*` | Reusable Python workflows with semantic search |
| `artifacts.*` | Persistent data storage across sessions |
| `deps.*` | Runtime Python package management |

### Storage vs Executor

- **Storage** (FileStorage, RedisStorage): Owns skills and artifacts
- **Executor** (InProcess, Subprocess, Container): Owns tools and deps via config

### Executors

| Executor | Use Case |
|----------|----------|
| SubprocessExecutor | Recommended default. Process isolation via Jupyter kernel. |
| ContainerExecutor | Docker isolation for untrusted code. |
| InProcessExecutor | Maximum speed for trusted code. |

---

## Development Commands

### Testing

```bash
# Run all tests (parallel by default via pytest-xdist)
uv run pytest

# Run specific test file
uv run pytest tests/test_skills.py

# Run with verbose output
uv run pytest -v

# Run tests matching pattern
uv run pytest -k "test_skill"

# Run without parallelism (for debugging)
uv run pytest -n 0
```

### Linting and Type Checking

```bash
# Ruff linting
uv run ruff check .

# Ruff with auto-fix
uv run ruff check --fix .

# Type checking
uv run mypy src/

# Run all pre-commit hooks
uv run pre-commit run --all-files
```

### Test Coverage

```bash
# Run tests with coverage report
uv run pytest --cov=src/py_code_mode --cov-report=term

# Coverage threshold is 60% (configured in pyproject.toml)
```

### Running the MCP Server

```bash
# Local development
uv run py-code-mode-mcp --base ~/.code-mode

# With specific storage
uv run py-code-mode-mcp --base ~/.code-mode --redis redis://localhost:6379
```

---

## Architecture Notes

### StorageBackend Protocol

Storage backends implement `StorageBackend` protocol:
- `get_serializable_access()` - For cross-process communication
- `get_skill_library()` - Returns SkillLibrary
- `get_artifact_store()` - Returns ArtifactStore

### Bootstrap Pattern

Cross-process executors (Subprocess, Container) use bootstrap configs to reconstruct namespaces:

```python
# Host process serializes config
storage.get_serializable_access()  # -> FileStorageAccess | RedisStorageAccess

# Subprocess/Container reconstructs via bootstrap_namespaces()
```

### Tool Definitions

Tools are defined in YAML files. Key patterns:
- **Escape hatch**: `tools.curl(url="...")` - Full control
- **Recipe**: `tools.curl.get(url="...")` - Pre-configured preset

---

## Common Tasks

### Adding a New Tool Adapter

1. Create adapter in `src/py_code_mode/tools/adapters/`
2. Implement `ToolAdapter` protocol (see `base.py`)
3. Register in `loader.py`

### Adding a New Storage Backend

1. Implement `StorageBackend` protocol in `src/py_code_mode/storage/`
2. Implement serializable access type for cross-process support

### Adding a New Executor

1. Create executor in `src/py_code_mode/execution/`
2. Implement `Executor` protocol (see `protocol.py`)
3. Handle namespace construction via bootstrap

---

## Testing Guidelines

- Use `pytest.mark.asyncio` for async tests (auto mode enabled)
- Container tests are in `tests/container/` - require Docker
- Use `@pytest.mark.xdist_group("group_name")` for tests that need isolation
- Redis tests use testcontainers - spin up automatically

---

## Important Files

| File | Purpose |
|------|---------|
| `src/py_code_mode/session.py` | Main Session API |
| `src/py_code_mode/bootstrap.py` | Namespace reconstruction for subprocesses |
| `src/py_code_mode/execution/protocol.py` | Executor protocol definition |
| `src/py_code_mode/storage/backends.py` | Storage backend implementations |
| `src/py_code_mode/tools/namespace.py` | ToolsNamespace, ToolProxy |
| `src/py_code_mode/skills/library.py` | SkillLibrary implementation |
