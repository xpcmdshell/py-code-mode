# py-code-mode Architecture

This document explains how tools, skills, and artifacts interact across different deployment scenarios.

## Core Concepts

| Component | Purpose | Format |
|-----------|---------|--------|
| **Tools** | CLI commands, MCP servers, HTTP APIs | YAML definitions |
| **Skills** | Reusable Python code recipes | `.py` files with `run()` function |
| **Artifacts** | Persistent data storage | Binary data with metadata |
| **Deps** | Python package dependencies | `requirements.txt` (file) or Redis keys |
| **VectorStore** | Cached skill embeddings for fast search | ChromaDB or Redis keys |

## Agent-Facing Namespaces

When code executes, agents access four main namespaces:

| Namespace | Purpose | Operations |
|-----------|---------|-----------|
| **tools.\*** | Call CLI commands, MCP servers, HTTP APIs | `call()`, `list()`, `search()` |
| **skills.\*** | Execute or manage reusable Python recipes | `invoke()`, `create()`, `delete()`, `list()`, `search()` |
| **artifacts.\*** | Save and retrieve persistent data | `save()`, `load()`, `delete()`, `list()` |
| **deps.\*** | Manage Python package dependencies | `add()`, `remove()`, `list()`, `sync()` |

All namespaces are automatically injected into code execution. Skills also have access to these namespaces.

---

## Storage Abstraction

Storage handles where skills and artifacts live. Tools and deps are owned by executors via config.

| Storage Type | Use Case | Skills | Artifacts |
|-------------|----------|--------|-----------|
| `FileStorage` | Local development | `.py` files | Binary files |
| `RedisStorage` | Distributed/production | Redis keys | Redis keys |

**Current API:**
```python
from pathlib import Path
from py_code_mode import Session, FileStorage, RedisStorage
from py_code_mode.execution import InProcessExecutor, InProcessConfig, ContainerExecutor, ContainerConfig

# File-based storage for skills and artifacts
storage = FileStorage(base_path=Path("./storage"))
# Creates: ./storage/skills/, ./storage/artifacts/

# Redis-based storage for skills and artifacts
storage = RedisStorage(url="redis://localhost:6379", prefix="myapp")
# Uses keys: myapp:skills:*, myapp:artifacts:*

# Configure executor with tools and deps (owned by executor, not storage)
config = InProcessConfig(
    tools_path=Path("./tools"),  # YAML tool definitions
    deps=["pandas>=2.0", "numpy"],  # Pre-configured dependencies
)
executor = InProcessExecutor(config=config)

# Session with storage and executor
async with Session(storage=storage, executor=executor) as session:
    result = await session.run('tools.curl(url="...")')

# Or with ContainerExecutor
config = ContainerConfig(
    tools_path=Path("./tools"),
    deps=["requests"],
    auth_disabled=True,  # For local dev
)
executor = ContainerExecutor(config=config)
async with Session(storage=storage, executor=executor) as session:
    result = await session.run('tools.curl(url="...")')
```

**Key design:**
- `Session` accepts typed `Executor` instances
- `FileStorage`/`RedisStorage` only handle skills and artifacts
- Tools and deps are configured via executor config (`tools_path`, `deps`, `deps_file`)
- Session uses `StorageBackend` protocol for skills and artifacts

## StorageBackend Protocol

The `StorageBackend` protocol provides a clean interface for storage backends:

```python
class StorageBackend(Protocol):
    """Protocol for unified storage backend.

    Provides skills and artifacts storage. Tools and deps are owned by executors.
    """

    def get_serializable_access(self) -> FileStorageAccess | RedisStorageAccess:
        """Return serializable access descriptor for cross-process communication.

        Used by executors that run in separate processes and need
        connection info rather than direct object references.
        """
        ...

    def get_skill_library(self) -> SkillLibrary:
        """Return SkillLibrary for in-process execution."""
        ...

    def get_artifact_store(self) -> ArtifactStoreProtocol:
        """Return artifact store for in-process execution."""
        ...
```

**Design rationale:**
- `get_serializable_access()`: Returns path/connection info that can be sent to other processes (containers, subprocesses)
- `get_skill_library()`, `get_artifact_store()`: Return live objects for in-process execution
- Tools and deps are owned by executors (via `config.tools_path`, `config.deps`)
- No wrapper layers or dict-like access - components are accessed directly

---

## Bootstrap Architecture

Cross-process executors (SubprocessExecutor, ContainerExecutor) need to reconstruct the `tools`, `skills`, `artifacts` namespaces in their isolated environment. The bootstrap pattern handles this:

```
Host Process                          Subprocess/Container
-----------                          --------------------
storage.to_bootstrap_config()
+ executor config (tools_path, deps)
        |
        v
    {                                 bootstrap_namespaces(config)
      "type": "file",                         |
      "base_path": "/path/to/storage",        v
    }                                    +-------------------+
    + tools_path from executor           | tools namespace   |
    + deps from executor                 | skills namespace  |
        |                                | artifacts namespace|
        +---- (serialized) ------------> +-------------------+
```

**Key functions:**

| Function | Location | Purpose |
|----------|----------|---------|
| `storage.to_bootstrap_config()` | `storage/backends.py` | Serialize storage config (skills, artifacts) |
| `executor.config.tools_path` | Executor config | Path to tool YAML definitions |
| `bootstrap_namespaces(config)` | `execution/bootstrap.py` | Reconstruct namespaces from config |

**FileStorage bootstrap config:**
```python
{
    "type": "file",
    "base_path": "/absolute/path/to/storage"
}
# Skills at base_path/skills/, artifacts at base_path/artifacts/
# Tools come from executor config.tools_path (separate from storage)
```

**RedisStorage bootstrap config:**
```python
{
    "type": "redis",
    "url": "redis://localhost:6379",
    "prefix": "myapp"
}
# Skills at myapp:skills:*, artifacts at myapp:artifacts:*
# Tools come from executor config.tools_path (separate from storage)
```

**Why this matters:**
- Subprocess needs to create its own ToolRegistry, SkillLibrary, ArtifactStore from scratch
- Cannot pass live Python objects across process boundaries
- Config dict is JSON-serializable and can be sent via IPC, HTTP, environment variables
- Tools path is passed separately from storage config (executor owns tools)
- `bootstrap_namespaces()` returns a dict with `tools`, `skills`, `artifacts` ready for code execution

## Session Architecture

Session orchestrates storage and execution:

```
Session(storage=StorageBackend, executor=Executor)
    |
    +-- Storage provides (skills and artifacts only):
    |       storage.get_skill_library()    -> SkillLibrary
    |       storage.get_artifact_store()   -> ArtifactStoreProtocol
    |
    +-- Executor provides (tools and deps):
    |       executor.config.tools_path     -> Path to YAML tool definitions
    |       executor.config.deps           -> Pre-configured dependencies
    |
    +-- For cross-process executors:
    |       storage.get_serializable_access() -> FileStorageAccess | RedisStorageAccess
    |
    +-- Executor implementations:
            +-- InProcessExecutor (default)
            |       Gets skills/artifacts from storage, tools from config
            |
            +-- ContainerExecutor (Docker)
            |       Receives serializable access + tools_path, reconstructs
            |
            +-- SubprocessExecutor (Jupyter kernel)
                    Receives serializable access + tools_path, reconstructs
```

**Key Flow:**
1. User creates `Session(storage=storage, executor=executor)`
2. Session starts executor with storage backend
3. Executor gets skills/artifacts from storage, tools from its own config
4. Cross-process executors serialize storage access + tools_path
5. Executor builds namespaces: `tools.*`, `skills.*`, `artifacts.*`
6. User calls `session.run(code)` which delegates to executor

---

## Dependency Management (Deps)

The `deps` namespace manages Python package dependencies for code execution:

```python
# Agent code can manage dependencies on demand
deps.add("pandas")        # Install pandas
deps.list()               # See configured dependencies
deps.remove("pandas")     # Remove from configuration
deps.sync()               # Ensure all configured deps are installed
```

**DepsStore Protocol:**

```python
class DepsStore(Protocol):
    """Protocol for dependency persistence."""

    def add(self, package: str) -> None:
        """Add a dependency to configuration."""
        ...

    def remove(self, package: str) -> bool:
        """Remove a dependency from configuration."""
        ...

    def list(self) -> list[str]:
        """List all configured dependencies."""
        ...

    def exists(self, package: str) -> bool:
        """Check if a dependency is configured."""
        ...
```

**Implementations:**

| Implementation | Storage | Format | Use Case |
|---|---|---|---|
| `FileDepsStore` | Local filesystem | `requirements.txt` | Local development |
| `RedisDepsStore` | Redis | JSON-serialized keys | Production/distributed |

**PackageInstaller:**

The `PackageInstaller` handles actual installation:

```python
class PackageInstaller(Protocol):
    """Protocol for installing packages."""

    async def install(self, packages: list[str]) -> InstallResult:
        """Install packages and return result with installed/failed lists."""
        ...
```

**Workflow:**

1. Agent calls `deps.add("package")`
2. `DepsStore` persists the dependency
3. `PackageInstaller` installs the package into the environment
4. Future code execution includes the package
5. `deps.sync()` ensures all configured deps are installed

**Deps via Executor Config:**

```python
from py_code_mode.execution import InProcessConfig, InProcessExecutor

# Pre-configure deps via executor config
config = InProcessConfig(
    deps=["pandas>=2.0", "numpy"],  # Inline list
    deps_file=Path("./requirements.txt"),  # Or from file
)
executor = InProcessExecutor(config=config)

async with Session(storage=storage, executor=executor) as session:
    # deps.list() returns pre-configured deps
    # deps.sync() installs them
    pass
```

**Runtime deps (when allowed):**

```python
# With allow_runtime_deps=True (default), agent code can manage deps
await session.run('deps.add("requests")')  # Adds and installs
await session.run('deps.list()')  # Shows all deps
await session.run('deps.remove("requests")')  # Removes
```

---

## SkillsNamespace Decoupling

`SkillsNamespace` is decoupled from executors and accepts a plain namespace dict:

```python
class SkillsNamespace:
    def __init__(self, library: SkillLibrary, namespace: dict[str, Any]) -> None:
        """Initialize SkillsNamespace.

        Args:
            library: The skill library for skill lookup and storage.
            namespace: Dict containing tools, skills, artifacts for skill execution.
                       Must be a plain dict, not an executor object.
        """
```

**Design rationale:**
- Any executor (InProcess, Container, Subprocess) can use `SkillsNamespace`
- No coupling to specific executor implementations
- Skills execute with `tools`, `skills`, `artifacts` from the namespace dict
- Explicit rejection of executor-like objects prevents accidental coupling

---

## ToolProxy Explicit Methods

`ToolProxy` provides explicit sync/async methods for predictable behavior:

```python
# Explicit methods (recommended for clarity)
result = await tools.curl.call_async(url="...")  # Always async
result = tools.curl.call_sync(url="...")          # Always sync, blocks

# Context-aware __call__ (backward compatible)
result = tools.curl(url="...")  # Sync in sync context, returns coroutine in async
```

**Methods:**
- `call_async(**kwargs)`: Always returns awaitable, use in async code
- `call_sync(**kwargs)`: Always blocks and returns result, use in sync code
- `__call__(**kwargs)`: Context-aware, detects if running in async context

**Same pattern applies to `CallableProxy`** for recipe invocations:
```python
result = await tools.curl.get.call_async(url="...")
result = tools.curl.get.call_sync(url="...")
```

---

## Scenario 1: Session with File Storage

**Best for:** Local development, single-machine deployments.

```
+------------------------------------------------------------------+
|                        Host Machine                              |
|                                                                  |
|   +----------------------------------------------------------+   |
|   |                     Your Agent                           |   |
|   |                                                          |   |
|   |   storage = FileStorage(base_path=Path("./storage"))     |   |
|   |   # Creates: skills/, artifacts/ subdirs                 |   |
|   |                                                          |   |
|   |   config = InProcessConfig(tools_path=Path("./tools"))   |   |
|   |   executor = InProcessExecutor(config=config)            |   |
|   |                                                          |   |
|   |   async with Session(storage=storage,                    |   |
|   |                      executor=executor) as session:      |   |
|   |       result = await session.run('tools.curl(...)')      |   |
|   +-------------------------+--------------------------------+   |
|                             |                                    |
|                             | runs in same process               |
|                             v                                    |
|   +-------------------------+--------------------------------+   |
|   |                InProcessExecutor                         |   |
|   |                                                          |   |
|   |   +-------------+ +-------------+ +------------------+   |   |
|   |   |ToolRegistry | |SkillLibrary | |FileArtifactStore |   |   |
|   |   |(from config)| | (storage)   | | (storage)        |   |   |
|   |   +------+------+ +------+------+ +--------+---------+   |   |
|   +----------|--------------+|-----------------+-------------+   |
|              |               |                 |                 |
|   +----------v------+ +------v------+ +--------v--------+        |
|   |  ./tools/       | |./storage/   | |./storage/       |        |
|   |  +-- curl.yaml  | |  skills/    | |  artifacts/     |        |
|   |  +-- nmap.yaml  | |  +-- *.py   | |  +-- *.bin      |        |
|   +-----------------+ +-------------+ +-----------------+        |
|                                                                  |
+------------------------------------------------------------------+
```

**Code:**
```python
from pathlib import Path
from py_code_mode import Session, FileStorage
from py_code_mode.execution import InProcessConfig, InProcessExecutor

# Storage for skills and artifacts
storage = FileStorage(base_path=Path("./storage"))

# Executor with tools path (separate from storage)
config = InProcessConfig(tools_path=Path("./tools"))
executor = InProcessExecutor(config=config)

async with Session(storage=storage, executor=executor) as session:
    result = await session.run('tools.curl(url="https://api.example.com")')
    print(result.value)
```

---

## Scenario 2: Session with Redis Storage

**Best for:** Distributed deployments, shared state across instances.

```
+------------------------------------------------------------------+
|                        Host Machine                              |
|                                                                  |
|   +----------------------------------------------------------+   |
|   |                     Your Agent                           |   |
|   |                                                          |   |
|   |   storage = RedisStorage(url="redis://localhost:6379",   |   |
|   |                          prefix="agent")                 |   |
|   |   # Uses agent:skills:*, agent:artifacts:*               |   |
|   |                                                          |   |
|   |   config = InProcessConfig(tools_path=Path("./tools"))   |   |
|   |   executor = InProcessExecutor(config=config)            |   |
|   |                                                          |   |
|   |   async with Session(storage=storage,                    |   |
|   |                      executor=executor) as session:      |   |
|   |       result = await session.run('tools.curl(...)')      |   |
|   +-------------------------+--------------------------------+   |
|                             |                                    |
|   +-------------------------v--------------------------------+   |
|   |                InProcessExecutor                         |   |
|   |                                                          |   |
|   |   +-------------+ +-------------+ +------------------+   |   |
|   |   |ToolRegistry | |SkillLibrary | |RedisArtifactStore|   |   |
|   |   |(from config)| | (Redis)     | | (Redis)          |   |   |
|   |   +------+------+ +------+------+ +--------+---------+   |   |
|   +----------|--------------+|-----------------+-------------+   |
|              |               |                 |                 |
|   +----------v------+        |                 |                 |
|   |  ./tools/       |        |                 |                 |
|   |  +-- curl.yaml  |        |                 |                 |
|   |  +-- nmap.yaml  |        |                 |                 |
|   +-----------------+        |                 |                 |
|                              |                 |                 |
+------------------------------|-----------------|------------------+
                               |                 |
    +--------------------------v-----------------v-----------+
    |                       Redis                            |
    |                                                        |
    |  agent:skills:*        |       agent:artifacts:*       |
    |  (python code)         |       (binary data)           |
    |                                                        |
    +--------------------------------------------------------+
```

**Code:**
```python
from pathlib import Path
from py_code_mode import Session, RedisStorage
from py_code_mode.execution import InProcessConfig, InProcessExecutor

# RedisStorage for skills and artifacts
storage = RedisStorage(url="redis://localhost:6379", prefix="agent")

# Executor with tools from local filesystem
config = InProcessConfig(tools_path=Path("./tools"))
executor = InProcessExecutor(config=config)

async with Session(storage=storage, executor=executor) as session:
    result = await session.run('tools.curl(url="https://api.example.com")')
    print(result.value)
```

**Provisioning skills to Redis:**
```bash
# Skills (provisioned to Redis for distributed access)
python -m py_code_mode.store bootstrap \
    --source ./skills \
    --target redis://localhost:6379 \
    --prefix agent-skills

# Tools stay on filesystem (executor loads from tools_path)
```

---

## Scenario 3: Container with File Storage (Volume Mounts)

**Best for:** Process isolation with local development.

**Note:** Container backend is used with Session by passing `ContainerExecutor` explicitly.
Tools come from executor config (mounted to container). Skills and artifacts from storage.

```
+------------------------------------------------------------------+
|                        Host Machine                              |
|                                                                  |
|   +----------------------------------------------------------+   |
|   |                     Your Agent                           |   |
|   |                                                          |   |
|   |   storage = FileStorage(base_path=Path("./storage"))     |   |
|   |                                                          |   |
|   |   config = ContainerConfig(                              |   |
|   |       tools_path=Path("./tools"),  # Mounted to container|   |
|   |       auth_disabled=True,  # Local dev                   |   |
|   |   )                                                      |   |
|   |   executor = ContainerExecutor(config=config)            |   |
|   |                                                          |   |
|   |   async with Session(storage=storage,                    |   |
|   |                      executor=executor) as session:      |   |
|   |       result = await session.run('tools.curl(...)')      |   |
|   +-------------------------+--------------------------------+   |
|                             | HTTP                               |
|                             v                                    |
|   +=========================================================+   |
|   ||               Docker Container                        ||   |
|   ||                                                       ||   |
|   ||   +-----------------------------------------------+   ||   |
|   ||   |            SessionServer (FastAPI)            |   ||   |
|   ||   |                                               |   ||   |
|   ||   |   +-------------+ +-------------+ +--------+  |   ||   |
|   ||   |   |ToolRegistry | |SkillLibrary | |FileArt.|  |   ||   |
|   ||   |   |(from config)| | (mounted)   | |(mount) |  |   ||   |
|   ||   |   +------+------+ +------+------+ +---+----+  |   ||   |
|   ||   +----------|--------------|-------------|-------+   ||   |
|   ||              |              |             |           ||   |
|   ||   +----------v------+ +-----v-----+ +-----v-------+   ||   |
|   ||   |/app/tools/      | |/app/      | |/workspace/  |   ||   |
|   ||   |(from config,    | | skills/   | |artifacts/   |   ||   |
|   ||   | volume mounted) | | (volume)  | |(volume)     |   ||   |
|   ||   +-----------------+ +-----^-----+ +------^------+   ||   |
|   +=============================|===============|==========+   |
|                                 |               |               |
|                         volume  |       volume  |               |
|                         mount   |       mount   |               |
|                                 |               |               |
|   +-----------------------------+--------------+-------------+  |
|   |                     Host Filesystem                      |  |
|   |                                                          |  |
|   |   ./tools/     ./storage/skills/  ./storage/artifacts/   |  |
|   |   +-- *.yaml   +-- *.py           +-- (files)            |  |
|   |                                                          |  |
|   +----------------------------------------------------------+  |
|                                                                  |
+------------------------------------------------------------------+
```

**Environment (container receives via mounts and env vars):**
```
TOOLS_PATH=/app/tools           # From config.tools_path (mounted)
SKILLS_PATH=/app/skills         # From storage (mounted)
ARTIFACTS_PATH=/workspace/artifacts  # From storage (mounted)
```

---

## Scenario 4: Container with Redis Storage

**Best for:** Cloud deployments, horizontal scaling, shared state.

**Note:** Container backend is used with Session by passing `ContainerExecutor` explicitly.
Tools still come from executor config (mounted). Skills and artifacts from Redis.

```
+------------------------------------------------------------------+
|                        Host / Cloud                              |
|                                                                  |
|   +----------------------------------------------------------+   |
|   |                     Your Agent                           |   |
|   |                                                          |   |
|   |   storage = RedisStorage(url="redis://redis:6379",       |   |
|   |                          prefix="agent")                 |   |
|   |                                                          |   |
|   |   config = ContainerConfig(                              |   |
|   |       tools_path=Path("./tools"),  # Mounted to container|   |
|   |       auth_token=os.environ["AUTH_TOKEN"],  # Production |   |
|   |   )                                                      |   |
|   |   executor = ContainerExecutor(config=config)            |   |
|   |                                                          |   |
|   |   async with Session(storage=storage,                    |   |
|   |                      executor=executor) as session:      |   |
|   |       result = await session.run('tools.curl(...)')      |   |
|   +-------------------------+--------------------------------+   |
|                             | HTTP                               |
|                             v                                    |
|   +=========================================================+   |
|   ||               Docker Container                        ||   |
|   ||                                                       ||   |
|   ||   +-----------------------------------------------+   ||   |
|   ||   |            SessionServer (FastAPI)            |   ||   |
|   ||   |                                               |   ||   |
|   ||   |   Receives:                                   |   ||   |
|   ||   |   - tools_path from config (mounted)          |   ||   |
|   ||   |   - RedisStorageAccess for skills/artifacts   |   ||   |
|   ||   |                                               |   ||   |
|   ||   |   +-------------+ +-------------+ +--------+  |   ||   |
|   ||   |   |ToolRegistry | |SkillLibrary | |RedisArt|  |   ||   |
|   ||   |   |(from config)| | (Redis)     | |(Redis) |  |   ||   |
|   ||   |   +------+------+ +------+------+ +---+----+  |   ||   |
|   ||   +----------|--------------|-------------|-------+   ||   |
|   ||              |              |             |           ||   |
|   ||   +----------v------+       |             |           ||   |
|   ||   |/app/tools/      |       |             |           ||   |
|   ||   |(volume mounted) |       |             |           ||   |
|   ||   +-----------------+       |             |           ||   |
|   +==============================|=============|===========+   |
|                                  |             |                |
+----------------------------------|-------------|----------------+
                                   |             |
         +-------------------------v-------------v----------+
         |                       Redis                      |
         |                                                  |
         |  agent:skills:*        |    agent:artifacts:*    |
         |  (python code)         |    (binary data)        |
         |                                                  |
         |  Provisioned via:                                |
         |  python -m py_code_mode.store bootstrap ...      |
         |                                                  |
         +--------------------------------------------------+
```

**Key flow:**
1. Session passes storage backend to `executor.start(storage=...)`
2. ContainerExecutor mounts tools_path from config
3. ContainerExecutor passes Redis connection details for skills/artifacts
4. SessionServer (in container) loads skills/artifacts from Redis, tools from mount

**Provisioning before deployment:**
```bash
# Bootstrap skills to Redis (tools stay on filesystem)
python -m py_code_mode.store bootstrap \
    --source ./skills \
    --target redis://redis:6379 \
    --prefix agent:skills

# Tools are mounted from config.tools_path (not in Redis)
```

---

## Storage Comparison Matrix

| Scenario | Storage | Tools Source | Skills Source | Artifacts Store |
|----------|---------|--------------|---------------|-----------------|
| Local dev | FileStorage | `config.tools_path/*.yaml` | `<base>/skills/*.py` | `<base>/artifacts/` |
| Distributed | RedisStorage | `config.tools_path/*.yaml` | `<prefix>:skills:*` | `<prefix>:artifacts:*` |
| Container + File | FileStorage | `config.tools_path` (mounted) | `<base>/skills/` (mounted) | `<base>/artifacts/` (mounted) |
| Container + Redis | RedisStorage | `config.tools_path` (mounted) | Redis keys | Redis keys |

**Key insight:** Tools always come from `config.tools_path` (executor owns tools). Only skills and artifacts vary by storage type.

**Decision tree:**

```
Choose storage backend (for skills and artifacts):
    |
    +-- Single machine, local dev?  -> FileStorage(base_path=Path("./storage"))
    +-- Distributed, production?    -> RedisStorage(url="redis://...", prefix="app")

Choose executor (with tools_path):
    |
    +-- Same-process execution?     -> InProcessExecutor(config=InProcessConfig(tools_path=...))
    +-- Docker isolation?           -> ContainerExecutor(config=ContainerConfig(tools_path=...))
    +-- Subprocess isolation?       -> SubprocessExecutor(config=SubprocessConfig(tools_path=...))

Combine:
    Session(storage=storage, executor=executor)
```

---

## Scenario 5: Subprocess Executor (Jupyter Kernel)

**Best for:** Process isolation without Docker overhead, development environments.

SubprocessExecutor runs code in an IPython/Jupyter kernel within a subprocess. It provides process isolation lighter than Docker but stronger than in-process execution.

**Capabilities:**
- TIMEOUT: Yes (via message wait timeout)
- PROCESS_ISOLATION: Yes (code runs in subprocess)
- RESET: Yes (kernel restart)
- NETWORK_ISOLATION: No
- FILESYSTEM_ISOLATION: No

```
+------------------------------------------------------------------+
|                        Host Machine                              |
|                                                                  |
|   +----------------------------------------------------------+   |
|   |                     Your Agent                           |   |
|   |                                                          |   |
|   |   storage = FileStorage(base_path=Path("./storage"))     |   |
|   |                                                          |   |
|   |   config = SubprocessConfig(                             |   |
|   |       tools_path=Path("./tools"),                        |   |
|   |       python_version="3.11",                             |   |
|   |       default_timeout=120.0,                             |   |
|   |   )                                                      |   |
|   |   executor = SubprocessExecutor(config=config)           |   |
|   |                                                          |   |
|   |   async with Session(storage=storage,                    |   |
|   |                      executor=executor) as session:      |   |
|   |       result = await session.run('tools.curl(...)')      |   |
|   +-------------------------+--------------------------------+   |
|                             | Jupyter client protocol            |
|                             v                                    |
|   +=========================================================+   |
|   ||           Subprocess (IPython Kernel)                 ||   |
|   ||                                                       ||   |
|   ||   +-----------------------------------------------+   ||   |
|   ||   |   tools.* skills.* artifacts.* namespaces     |   ||   |
|   ||   |   (tools from config, skills/artifacts from   |   ||   |
|   ||   |    storage, injected at kernel start)         |   ||   |
|   ||   +-----------------------------------------------+   ||   |
|   ||                                                       ||   |
|   ||   Virtual environment created with:                   ||   |
|   ||   - ipykernel                                         ||   |
|   ||   - py-code-mode (for namespace construction)         ||   |
|   ||                                                       ||   |
|   +=========================================================+   |
|                                                                  |
+------------------------------------------------------------------+
```

**Code:**
```python
from pathlib import Path
from py_code_mode import Session, FileStorage
from py_code_mode.execution import SubprocessExecutor, SubprocessConfig

storage = FileStorage(base_path=Path("./storage"))

# Configure subprocess executor with tools_path
config = SubprocessConfig(
    tools_path=Path("./tools"),  # Tools from executor config
    python_version="3.11",       # Python version for venv
    default_timeout=120.0,       # Execution timeout
    startup_timeout=30.0,        # Kernel ready timeout
    cleanup_venv_on_close=True,  # Delete temp venv on close
)
executor = SubprocessExecutor(config=config)

async with Session(storage=storage, executor=executor) as session:
    result = await session.run('tools.curl.get(url="https://api.example.com")')
    print(result.value)
```

**When to use SubprocessExecutor:**
- Need process isolation but Docker is unavailable or too heavy
- Development/testing where fast iteration matters
- CI environments without Docker access
- When you need kernel restart capability (reset state)

**When to use ContainerExecutor instead:**
- Need filesystem isolation
- Need network isolation
- Running untrusted code in production
- Reproducible environments across machines

---

## Data Flow

### Tool Execution

```
Agent writes: "tools.curl.get(url='...')"
        |
        v
+------------------------+
| ToolsNamespace         |
|                        |
| tools.curl(url=...)    |--> Escape hatch (direct invocation)
| tools.curl.get(...)    |--> Recipe invocation
| tools.search(...)      |                |
| tools.list()           |                v
+------------------------+         +--------------+
                                   | CLIAdapter   | -> subprocess
                                   | MCPAdapter   | -> MCP server
                                   | HTTPAdapter  | -> HTTP request
                                   +--------------+
```

### ToolProxy Methods

```
Agent writes: "tools.curl.get(url='...')"
        |
        v
+------------------------+
| ToolProxy              |
|                        |
| .call_async(**kwargs)  |--> Always returns awaitable
| .call_sync(**kwargs)   |--> Always blocks, returns result
| .__call__(**kwargs)    |--> Context-aware (sync/async detection)
+------------------------+
        |
        v
+------------------------+
| CallableProxy (recipe) |
|                        |
| .call_async(**kwargs)  |--> Always returns awaitable
| .call_sync(**kwargs)   |--> Always blocks, returns result
| .__call__(**kwargs)    |--> Context-aware (sync/async detection)
+------------------------+
```

### Skill Execution

```
Agent writes: "skills.analyze_repo(repo='...')"
        |
        v
+------------------------+
| SkillsNamespace        |  Agent-facing API:
|                        |
| skills.analyze_repo()  |  # Direct attribute access (preferred)
| skills.invoke("name")  |  # Explicit invocation
| skills.search("...")   |  # Semantic search
| skills.list()          |  # List all skills
| skills.create(...)     |  # Create new skill
| skills.delete("name")  |  # Delete skill
+------------------------+
        |
        | (internally calls SkillLibrary)
        v
+------------------------+
| SkillLibrary           |  Internal implementation:
|                        |
| .get("analyze_repo")   |  # Retrieve PythonSkill
| .search("query")       |  # Semantic search
| .list_all()            |  # All skills
+------------------------+
        |
        v
+------------------------+
| SkillStore (File/Redis)|
+------------------------+
        |
        v
+-----------------+
| compile(source) |
| exec(code)      |
| return run()    |
+-----------------+
        |
Skill has access to:
- tools (ToolsNamespace)
- skills (SkillsNamespace)
- artifacts (ArtifactStore)
```

### Artifact Storage

```
Agent writes: "artifacts.save('data.json', b'...', 'description')"
        |
        v
+------------------------+
| ArtifactStore          |
|                        |
| artifacts.save(...)    |--> FileArtifactStore.save()  -> disk
| artifacts.load(...)    |    or
| artifacts.list()       |    RedisArtifactStore.save() -> Redis
+------------------------+
```

---

## CLI Tool Interface

The unified CLI tool interface provides two invocation patterns:

| Pattern | Example | Use Case |
|---------|---------|----------|
| **Escape Hatch** | `tools.curl(silent=True, url="...")` | Full control over all options |
| **Recipe** | `tools.curl.get(url="...")` | Pre-configured for common use cases |

### Tool YAML Schema

```yaml
name: curl                        # Tool identifier
description: Make HTTP requests   # Human-readable description
command: curl                     # Actual CLI command
timeout: 60                       # Execution timeout in seconds
tags: [http]                      # Searchable tags

schema:
  options:                        # Named flags (--flag / -f)
    silent:
      type: boolean
      short: s                    # -s instead of --silent
      description: Silent mode
    header:
      type: array                 # Repeatable: -H val1 -H val2
      short: H
      description: HTTP headers
  positional:                     # Positional arguments
    - name: url
      type: string
      required: true

recipes:                          # Named presets
  get:
    description: Simple GET request
    preset:                       # Pre-filled options
      silent: true
      location: true
    params:                       # Exposed to agent
      url: {}
```

### Data Flow

```
                        DEVELOPER WRITES
--------------------------------------------------------------------------------

  tools/curl.yaml
  +------------------------------------------------------+
  | name: curl                                           |
  | command: curl                                        |
  | schema:                                              |
  |   options:                                           |
  |     silent: {type: boolean, short: s}                |
  |   positional:                                        |
  |     - {name: url, required: true}                    |
  | recipes:                                             |
  |   get:                                               |
  |     preset: {silent: true, location: true}           |
  |     params: {url: {}}                                |
  +------------------------------------------------------+
                          |
                          v
                     LOADING PHASE
--------------------------------------------------------------------------------

  cli_schema.py: parse_cli_tool_yaml()
  +------------------------------------------------------+
  | CLIToolDefinition(                                   |
  |   name="curl",                                       |
  |   command="curl",                                    |
  |   schema={options: {...}, positional: [...]},        |
  |   recipes={"get": {preset: ..., params: ...}}        |
  | )                                                    |
  +------------------------------------------------------+
                          |
                          v
  cli.py: CLIAdapter.list_tools()
  +------------------------------------------------------+
  | Tool(                                                |
  |   name="curl",                                       |
  |   description="Make HTTP requests",                  |
  |   callables=(                                        |
  |     ToolCallable(name="get", params=(...)),          |
  |     ToolCallable(name="post", params=(...)),         |
  |   )                                                  |
  | )                                                    |
  +------------------------------------------------------+

                       AGENT CALLS
--------------------------------------------------------------------------------

  tools.curl.get(url="https://example.com")
        |    |           |
        |    |           +--- kwargs passed to CallableProxy.__call__
        |    |
        |    +--- ToolProxy.__getattr__("get") -> CallableProxy
        |
        +--- ToolsNamespace.__getattr__("curl") -> ToolProxy

                          |
                          v
  CallableProxy.__call__(url="https://example.com")
        |
        +--- adapter.call_tool("curl", "get", {"url": "..."})
                          |
                          v
                    COMMAND BUILDING
--------------------------------------------------------------------------------

  CLICommandBuilder.build_recipe("get", {"url": "..."})
        |
        +--- 1. Get recipe preset: {silent: true, location: true}
        |
        +--- 2. Merge with user args: {silent: true, location: true,
        |                              url: "https://example.com"}
        |
        +--- 3. Build command array:
                 ["curl", "-s", "-L", "https://example.com"]
                          |
                          v
                       EXECUTION
--------------------------------------------------------------------------------

  asyncio.create_subprocess_exec(
    "curl", "-s", "-L", "https://example.com",
    stdout=PIPE, stderr=PIPE
  )
        |
        +--- Returns: stdout content (HTML/JSON response)
```

### Key Implementation Files

| File | Purpose |
|------|---------|
| `adapters/cli_schema.py` | YAML parsing, command building |
| `adapters/cli.py` | CLIAdapter with `call_tool()` execution |
| `namespace.py` | ToolsNamespace, ToolProxy, CallableProxy |
| `tool_types.py` | Tool, ToolCallable, ToolParameter dataclasses |

### Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Proxies use `__getattr__`** | Enables `tools.X.Y` syntax without pre-defining every method |
| **`frozen=True` dataclasses** | Immutable types are safer and can be cached/hashed |
| **Recipes merge presets + args** | Agent provides only what varies; preset handles boilerplate |
| **`asyncio.create_subprocess_exec`** | Avoids shell injection - args passed as list, not string |
| **Escape hatch (`ToolProxy.__call__`)** | Experts can bypass recipes when full control is needed |
| **Explicit `call_async`/`call_sync`** | Predictable behavior regardless of calling context |
| **No backward compatibility** | Clean interface, no legacy code paths to maintain |

---

## Deployment Checklist

### Local Development (Session + FileStorage + InProcessExecutor)
- [ ] Create base storage directory for skills and artifacts
- [ ] Add YAML tool definitions to separate tools directory
- [ ] Add Python skill files to `<base_path>/skills/`
- [ ] Configure executor: `InProcessConfig(tools_path=Path("./tools"))`
- [ ] Use `Session(storage=FileStorage(base_path=...), executor=InProcessExecutor(config))`

### Local with Container Isolation (Container + File)
- [ ] Build Docker image with py-code-mode installed
- [ ] Configure `ContainerConfig(tools_path=Path("./tools"))` - will be mounted
- [ ] Storage provides skills and artifacts directories (also mounted)
- [ ] Set `auth_disabled=True` for local development
- [ ] Use `Session(storage=FileStorage(...), executor=ContainerExecutor(config))`

### Production (Session + RedisStorage)
- [ ] Provision Redis instance
- [ ] Bootstrap skills: `python -m py_code_mode.store bootstrap --target redis://... --prefix myapp:skills`
- [ ] Tools stay on filesystem (via executor config)
- [ ] Create storage: `RedisStorage(url="redis://...", prefix="myapp")`
- [ ] Configure executor: `InProcessConfig(tools_path=Path("./tools"))`
- [ ] Use `Session(storage=storage, executor=executor)`

### Production with Container Isolation
- [ ] Provision Redis instance
- [ ] Bootstrap skills to Redis (as above)
- [ ] Tools on filesystem (mounted to container via `config.tools_path`)
- [ ] Create storage: `RedisStorage(url="redis://...", prefix="myapp")`
- [ ] Create executor: `ContainerExecutor(config=ContainerConfig(tools_path=..., auth_token=...))`
- [ ] Use `Session(storage=storage, executor=executor)`
