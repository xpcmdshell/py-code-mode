# Session API Reference

Complete reference for the Session class - the primary interface for py-code-mode.

## Overview

Session wraps a storage backend and executor, providing a unified API for code execution with tools, skills, and artifacts.

```python
from pathlib import Path
from py_code_mode import Session, FileStorage
from py_code_mode.execution import SubprocessExecutor, SubprocessConfig

storage = FileStorage(base_path=Path("./data"))
config = SubprocessConfig(tools_path=Path("./tools"))
executor = SubprocessExecutor(config=config)

async with Session(storage=storage, executor=executor) as session:
    result = await session.run("tools.curl.get(url='https://api.github.com')")
```

---

## Constructor

```python
Session(
    storage: StorageBackend,
    executor: Executor | None = None,
    sync_deps_on_start: bool = False,
)
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `storage` | `StorageBackend` | Required. FileStorage or RedisStorage instance. |
| `executor` | `Executor` | Optional. Defaults to SubprocessExecutor if not provided. |
| `sync_deps_on_start` | `bool` | If True, install pre-configured deps when session starts. |

---

## Lifecycle Methods

### start()

Initialize the executor and prepare for code execution.

```python
async def start(self) -> None
```

Called automatically when using `async with`. Only call manually if not using context manager.

### close()

Release session resources.

```python
async def close(self) -> None
```

Called automatically when exiting `async with`. Only call manually if not using context manager.

### reset()

Reset the execution environment, clearing user-defined variables while preserving namespaces.

```python
async def reset(self) -> None
```

**Example:**

```python
async with Session(storage=storage, executor=executor) as session:
    await session.run("x = 42")
    await session.reset()
    result = await session.run("x")  # Error: x is not defined
```

---

## Code Execution

### run()

Execute Python code and return the result.

```python
async def run(
    self,
    code: str,
    timeout: float | None = None
) -> ExecutionResult
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `code` | `str` | Python code to execute |
| `timeout` | `float` | Optional timeout in seconds (overrides default) |

**Returns:** `ExecutionResult` with:
- `value` - Return value of the last expression
- `stdout` - Captured stdout
- `error` - Error message if execution failed
- `is_ok` - True if no error

**Example:**

```python
result = await session.run('''
import json
data = tools.curl.get(url="https://api.github.com/users/octocat")
json.loads(data)["public_repos"]
''')

if result.is_ok:
    print(f"Repos: {result.value}")
else:
    print(f"Error: {result.error}")
```

---

## Capability Query

### supports()

Check if the session supports a specific capability.

```python
def supports(self, capability: str) -> bool
```

**Example:**

```python
if session.supports("timeout"):
    result = await session.run(code, timeout=30.0)
```

### supported_capabilities()

Get all capabilities supported by the current executor.

```python
def supported_capabilities(self) -> set[str]
```

**Example:**

```python
caps = session.supported_capabilities()
# {'timeout', 'process_isolation', 'reset', ...}
```

**Available capabilities:**

| Capability | Description |
|------------|-------------|
| `timeout` | Supports execution timeout |
| `process_isolation` | Code runs in separate process |
| `container_isolation` | Code runs in container |
| `network_isolation` | Can disable network access |
| `reset` | Supports environment reset |
| `deps_install` | Can install dependencies |

---

## Tools Methods

### list_tools()

List all available tools.

```python
async def list_tools(self) -> list[dict[str, Any]]
```

**Returns:** List of tool info dicts with `name`, `description`, `tags`.

**Example:**

```python
tools = await session.list_tools()
for tool in tools:
    print(f"{tool['name']}: {tool['description']}")
```

### search_tools()

Search tools by keyword or semantic similarity.

```python
async def search_tools(
    self,
    query: str,
    limit: int = 10
) -> list[dict[str, Any]]
```

**Example:**

```python
http_tools = await session.search_tools("make HTTP requests")
```

---

## Skills Methods

### list_skills()

List all available skills.

```python
async def list_skills(self) -> list[dict[str, Any]]
```

**Returns:** List of skill summaries (name, description, parameters - no source).

### search_skills()

Search skills by semantic similarity.

```python
async def search_skills(
    self,
    query: str,
    limit: int = 5
) -> list[dict[str, Any]]
```

**Example:**

```python
skills = await session.search_skills("fetch GitHub repository data")
```

### get_skill()

Get a specific skill by name, including source code.

```python
async def get_skill(self, name: str) -> dict[str, Any] | None
```

**Returns:** Skill dict with `name`, `description`, `parameters`, `source`, or None if not found.

**Example:**

```python
skill = await session.get_skill("fetch_json")
if skill:
    print(skill["source"])
```

### add_skill()

Create and persist a new skill.

```python
async def add_skill(
    self,
    name: str,
    source: str,
    description: str
) -> dict[str, Any]
```

**Example:**

```python
await session.add_skill(
    name="fetch_json",
    source='''def run(url: str) -> dict:
    import json
    response = tools.curl.get(url=url)
    return json.loads(response)
''',
    description="Fetch and parse JSON from a URL"
)
```

### remove_skill()

Remove a skill by name.

```python
async def remove_skill(self, name: str) -> bool
```

**Returns:** True if removed, False if not found.

---

## Artifacts Methods

### list_artifacts()

List all stored artifacts.

```python
async def list_artifacts(self) -> list[dict[str, Any]]
```

**Returns:** List of artifact info with `name`, `path`, `description`, `metadata`, `created_at`.

### save_artifact()

Save data as an artifact.

```python
async def save_artifact(
    self,
    name: str,
    data: Any,
    description: str = "",
    metadata: dict[str, Any] | None = None
) -> dict[str, Any]
```

**Example:**

```python
await session.save_artifact(
    name="analysis_results",
    data={"repos": 42, "stars": 1000},
    description="GitHub analysis results"
)
```

### load_artifact()

Load artifact data by name.

```python
async def load_artifact(self, name: str) -> Any
```

**Example:**

```python
data = await session.load_artifact("analysis_results")
```

### delete_artifact()

Delete an artifact.

```python
async def delete_artifact(self, name: str) -> None
```

---

## Dependencies Methods

### list_deps()

List configured dependencies.

```python
async def list_deps(self) -> list[str]
```

### add_dep()

Add and install a dependency.

```python
async def add_dep(self, package: str) -> dict[str, Any]
```

**Returns:** Dict with `installed`, `already_present`, `failed` keys.

**Example:**

```python
result = await session.add_dep("pandas>=2.0")
if result.get("installed"):
    print("pandas installed")
```

### remove_dep()

Remove a dependency.

```python
async def remove_dep(self, package: str) -> dict[str, Any]
```

**Returns:** Dict with `removed`, `not_found`, `failed`, `removed_from_config` keys.

### sync_deps()

Install all pre-configured dependencies.

```python
async def sync_deps(self) -> dict[str, Any]
```

**Returns:** Dict with `installed`, `already_present`, `failed` keys.

**Example:**

```python
# Manually sync deps (alternative to sync_deps_on_start=True)
result = await session.sync_deps()
print(f"Installed: {result['installed']}")
```

---

## Properties

### storage

Access the underlying storage backend.

```python
@property
def storage(self) -> StorageBackend
```

**Example:**

```python
# Access storage for advanced operations
skill_library = session.storage.get_skill_library()
```

---

## Context Manager

Session implements async context manager for automatic lifecycle management:

```python
async with Session(storage=storage, executor=executor) as session:
    # session.start() called automatically
    result = await session.run(code)
    # session.close() called automatically on exit
```

This is the recommended pattern. Manual lifecycle management:

```python
session = Session(storage=storage, executor=executor)
await session.start()
try:
    result = await session.run(code)
finally:
    await session.close()
```
