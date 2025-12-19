# py-code-mode Architecture

This document explains how tools, skills, and artifacts interact across different deployment scenarios.

## Core Concepts

| Component | Purpose | Format |
|-----------|---------|--------|
| **Tools** | CLI commands, MCP servers, HTTP APIs | YAML definitions |
| **Skills** | Reusable Python code recipes | `.py` files with `run()` function |
| **Artifacts** | Persistent data storage | Binary data with metadata |

## Storage Abstraction

Storage handles where tools, skills, and artifacts live. Two implementations:

| Storage Type | Use Case | Implementation |
|-------------|----------|----------------|
| `FileStorage` | Local development | Directories for tools, skills, artifacts |
| `RedisStorage` | Distributed/production | Redis keys with prefixes |

**Current API:**
```python
from pathlib import Path
from redis import Redis
from py_code_mode import Session, FileStorage, RedisStorage
from py_code_mode.backends.in_process import InProcessExecutor
from py_code_mode.backends.container import ContainerExecutor, ContainerConfig

# File-based storage (single base_path creates subdirs)
storage = FileStorage(base_path=Path("./storage"))
# Creates: ./storage/tools/, ./storage/skills/, ./storage/artifacts/

# Redis-based storage (client instance + prefix)
redis_client = Redis.from_url("redis://localhost:6379")
storage = RedisStorage(redis=redis_client, prefix="myapp")
# Uses keys: myapp:tools:*, myapp:skills:*, myapp:artifacts:*

# Session with default in-process executor
async with Session(storage=storage) as session:
    result = await session.run('tools.curl(url="...")')

# Session with explicit executor
executor = ContainerExecutor(config=ContainerConfig(...))
async with Session(storage=storage, executor=executor) as session:
    result = await session.run('tools.curl(url="...")')
```

**Key changes from legacy API:**
- `Session` accepts typed `Executor` instances, not `backend="container"` strings
- `FileStorage` takes single `base_path`, creates subdirs automatically
- `RedisStorage` takes Redis client instance and prefix, not separate URL/prefix params
- Session derives `StorageAccess` from storage backend, passes to `executor.start()`

## Session Architecture

Session orchestrates storage and execution:

```
Session(storage=StorageBackend, executor=Executor)
    │
    ├─ Storage (where data lives):
    │   ├─ FileStorage(base_path) → creates tools/, skills/, artifacts/
    │   └─ RedisStorage(redis, prefix) → keys with prefix:tools:*, etc.
    │
    ├─ Storage Access Pattern:
    │   │
    │   ├─ Session._derive_storage_access() converts:
    │   │   │
    │   │   ├─ FileStorage → FileStorageAccess(tools_path, skills_path, artifacts_path)
    │   │   └─ RedisStorage → RedisStorageAccess(redis_url, tools_prefix, skills_prefix, artifacts_prefix)
    │   │
    │   └─ Passed to executor.start(storage_access=...) during session startup
    │
    └─ Executor (where code runs):
        │
        ├─ InProcessExecutor (default, same process)
        │   └─ start(storage_access) loads tools/skills/artifacts from paths or Redis
        │
        └─ ContainerExecutor (Docker isolation)
            └─ start(storage_access) configures container environment

```

**Key Flow:**
1. User creates `Session(storage=storage, executor=executor)`
2. Session calls `executor.start(storage_access=derived_access)`
3. Executor loads tools, skills, artifacts from storage_access descriptor
4. Executor injects namespaces: `tools.*`, `skills.*`, `artifacts.*`
5. User calls `session.run(code)` which delegates to executor

**Current state:**
- `Session` API fully supports FileStorage and RedisStorage
- `Session` defaults to InProcessExecutor if executor not specified
- ContainerExecutor works with Session when explicitly passed

---

## Scenario 1: Session with File Storage

**Best for:** Local development, single-machine deployments.

```
┌─────────────────────────────────────────────────────────────────┐
│                        Host Machine                             │
│                                                                 │
│   ┌───────────────────────────────────────────────────────┐     │
│   │                     Your Agent                        │     │
│   │                                                       │     │
│   │   storage = FileStorage(                              │     │
│   │       base_path=Path("./storage")                    │     │
│   │   )  # Creates tools/, skills/, artifacts/ subdirs   │     │
│   │                                                       │     │
│   │   async with Session(storage=storage) as session:     │     │
│   │       result = await session.run('tools.curl(...)')   │     │
│   └───────────────────────┬───────────────────────────────┘     │
│                           │                                     │
│                           │ runs in same process                │
│                           │                                     │
│   ┌───────────────────────▼───────────────────────────────┐     │
│   │                InProcessExecutor                      │     │
│   │                                                       │     │
│   │   ┌─────────────┐ ┌─────────────┐ ┌───────────────┐   │     │
│   │   │ ToolRegistry│ │SkillLibrary│ │FileArtifactStore  │     │
│   │   │ (file)      │ │ (file)     │ │ (file)        │   │     │
│   │   └──────┬──────┘ └──────┬──────┘ └───────┬───────┘   │     │
│   └──────────┼───────────────┼────────────────┼───────────┘     │
│              │               │                │                 │
│   ┌──────────▼──────┐ ┌──────▼──────┐ ┌───────▼───────┐         │
│   │  ./tools/       │ │  ./skills/  │ │  ./artifacts/ │         │
│   │  ├─ curl.yaml   │ │  └─ *.py    │ │  └─ *.bin     │         │
│   │  └─ nmap.yaml   │ │             │ │               │         │
│   └─────────────────┘ └─────────────┘ └───────────────┘         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Code:**
```python
from pathlib import Path
from py_code_mode import Session, FileStorage

# FileStorage creates tools/, skills/, artifacts/ subdirs automatically
storage = FileStorage(base_path=Path("./storage"))

async with Session(storage=storage) as session:
    result = await session.run('tools.curl(url="https://api.example.com")')
    print(result.value)
```

---

## Scenario 2: Session with Redis Storage

**Best for:** Distributed deployments, shared state across instances.

```
┌─────────────────────────────────────────────────────────────────┐
│                        Host Machine                             │
│                                                                 │
│   ┌───────────────────────────────────────────────────────┐     │
│   │                     Your Agent                        │     │
│   │                                                       │     │
│   │   from redis import Redis                             │     │
│   │   redis = Redis.from_url("redis://localhost:6379")   │     │
│   │   storage = RedisStorage(                             │     │
│   │       redis=redis,                                    │     │
│   │       prefix="agent"                                  │     │
│   │   )  # Uses agent:tools:*, agent:skills:*, etc.      │     │
│   │                                                       │     │
│   │   async with Session(storage=storage) as session:     │     │
│   │       result = await session.run('tools.curl(...)')   │     │
│   └───────────────────────┬───────────────────────────────┘     │
│                           │                                     │
│   ┌───────────────────────▼───────────────────────────────┐     │
│   │                InProcessExecutor                      │     │
│   │                                                       │     │
│   │   ┌─────────────┐ ┌─────────────┐ ┌───────────────┐   │     │
│   │   │ ToolRegistry│ │SkillLibrary│ │RedisArtifactStore │     │
│   │   │ (Redis)     │ │ (Redis)    │ │ (Redis)       │   │     │
│   │   └──────┬──────┘ └──────┬──────┘ └───────┬───────┘   │     │
│   └──────────┼───────────────┼────────────────┼───────────┘     │
│              │               │                │                 │
└──────────────┼───────────────┼────────────────┼─────────────────┘
               │               │                │
    ┌──────────▼───────────────▼────────────────▼──────────┐
    │                       Redis                          │
    │                                                      │
    │  agent:tools:*  │  agent:skills:*  │ agent:artifacts:*│
    │  (yaml configs) │  (python code)   │ (binary data)   │
    │                                                      │
    └──────────────────────────────────────────────────────┘
```

**Code:**
```python
from redis import Redis
from py_code_mode import Session, RedisStorage

# RedisStorage takes client instance and prefix
redis_client = Redis.from_url("redis://localhost:6379")
storage = RedisStorage(redis=redis_client, prefix="agent")
# Creates keys: agent:tools:*, agent:skills:*, agent:artifacts:*

async with Session(storage=storage) as session:
    result = await session.run('tools.curl(url="https://api.example.com")')
    print(result.value)
```

**Provisioning to Redis:**
```bash
# Tools
python -m py_code_mode.store bootstrap \
    --source ./tools \
    --target redis://localhost:6379 \
    --prefix agent-tools \
    --type tools

# Skills
python -m py_code_mode.store bootstrap \
    --source ./skills \
    --target redis://localhost:6379 \
    --prefix agent-skills
```

---

## Scenario 3: Container with File Storage (Volume Mounts)

**Best for:** Process isolation with local development.

**Note:** Container backend can be used with Session by passing `ContainerExecutor` explicitly.
Storage is provided via volume mounts for tools, skills, and artifacts.

```
┌─────────────────────────────────────────────────────────────────┐
│                        Host Machine                             │
│                                                                 │
│   ┌───────────────────────────────────────────────────────┐     │
│   │                     Your Agent                        │     │
│   │                                                       │     │
│   │   from py_code_mode.backends.container import (       │     │
│   │       ContainerExecutor, ContainerConfig              │     │
│   │   )                                                   │     │
│   │                                                       │     │
│   │   storage = FileStorage(base_path=Path("./storage")) │     │
│   │   executor = ContainerExecutor(config=ContainerConfig(│     │
│   │       image="py-code-mode:latest",                    │     │
│   │       # Storage access derived by Session             │     │
│   │   ))                                                  │     │
│   │                                                       │     │
│   │   async with Session(storage=storage,                 │     │
│   │                      executor=executor) as session:   │     │
│   │       result = await session.run('tools.curl(...)')   │     │
│   └───────────────────────┬───────────────────────────────┘     │
│                           │ HTTP                                │
│                           │                                     │
│   ╔═══════════════════════▼═══════════════════════════════════╗ │
│   ║               Docker Container                            ║ │
│   ║               (FileStorageAccess passed via Session)      ║ │
│   ║                                                           ║ │
│   ║   ┌─────────────────────────────────────────────────┐     ║ │
│   ║   │            SessionServer (FastAPI)              │     ║ │
│   ║   │                                                 │     ║ │
│   ║   │   ┌─────────────┐ ┌─────────────┐ ┌──────────┐  │     ║ │
│   ║   │   │ ToolRegistry│ │SkillLibrary│ │FileArtifact  │     ║ │
│   ║   │   │ (from       │ │ (mounted)  │ │(mounted) │  │     ║ │
│   ║   │   │ TOOLS_CONFIG│ │             │ │          │  │     ║ │
│   ║   │   └──────┬──────┘ └──────┬──────┘ └────┬─────┘  │     ║ │
│   ║   └──────────┼───────────────┼─────────────┼────────┘     ║ │
│   ║              │               │             │              ║ │
│   ║   ┌──────────▼──────┐ ┌──────▼──────┐ ┌────▼────────┐     ║ │
│   ║   │TOOLS_CONFIG yaml│ │ /app/skills/│ │/workspace/  │     ║ │
│   ║   │(in container or │ │ (volume)    │ │artifacts/   │     ║ │
│   ║   │ mounted)        │ │             │ │(volume)     │     ║ │
│   ║   └─────────────────┘ └──────▲──────┘ └─────▲───────┘     ║ │
│   ╚══════════════════════════════╬══════════════╬═════════════╝ │
│                                  │              │               │
│                         volume   │     volume   │               │
│                         mount    │     mount    │               │
│                                  │              │               │
│   ┌──────────────────────────────┴──────────────┴─────────────┐ │
│   │                     Host Filesystem                       │ │
│   │                                                           │ │
│   │   ./skills/              ./artifacts/                     │ │
│   │   └─ *.py                └─ (agent-created files)         │ │
│   │                                                           │ │
│   └───────────────────────────────────────────────────────────┘ │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Environment:**
```
# No REDIS_URL = file-based mode
TOOLS_CONFIG=/app/tools/tools.yaml    # Can be in image or mounted
SKILLS_PATH=/app/skills               # Volume mounted from host
ARTIFACTS_PATH=/workspace/artifacts   # Volume mounted from host
```

---

## Scenario 4: Container with Redis Storage

**Best for:** Cloud deployments, horizontal scaling, shared state.

**Note:** Container backend can be used with Session by passing `ContainerExecutor` explicitly.
Session derives RedisStorageAccess from RedisStorage and passes to container.

```
┌─────────────────────────────────────────────────────────────────┐
│                        Host / Cloud                             │
│                                                                 │
│   ┌───────────────────────────────────────────────────────┐     │
│   │                     Your Agent                        │     │
│   │                                                       │     │
│   │   from redis import Redis                             │     │
│   │   from py_code_mode.backends.container import (       │     │
│   │       ContainerExecutor, ContainerConfig              │     │
│   │   )                                                   │     │
│   │                                                       │     │
│   │   redis = Redis.from_url("redis://redis:6379")        │     │
│   │   storage = RedisStorage(redis=redis, prefix="agent") │     │
│   │   executor = ContainerExecutor(config=ContainerConfig(│     │
│   │       image="py-code-mode:latest"                     │     │
│   │   ))                                                  │     │
│   │                                                       │     │
│   │   async with Session(storage=storage,                 │     │
│   │                      executor=executor) as session:   │     │
│   │       result = await session.run('tools.curl(...)')   │     │
│   └───────────────────────┬───────────────────────────────┘     │
│                           │ HTTP                                │
│                           │                                     │
│   ╔═══════════════════════▼═══════════════════════════════════╗ │
│   ║               Docker Container                            ║ │
│   ║               (RedisStorageAccess passed via Session)     ║ │
│   ║                                                           ║ │
│   ║   ┌─────────────────────────────────────────────────┐     ║ │
│   ║   │            SessionServer (FastAPI)              │     ║ │
│   ║   │                                                 │     ║ │
│   ║   │   Receives RedisStorageAccess from Session:     │     ║ │
│   ║   │   - redis_url: connection string                │     ║ │
│   ║   │   - tools_prefix, skills_prefix, artifacts_prefix   ║ │
│   ║   │                                                 │     ║ │
│   ║   │   Loads from Redis:                             │     ║ │
│   ║   │   - registry = registry_from_redis(tool_store)  │     ║ │
│   ║   │   - skill_library from RedisSkillStore          │     ║ │
│   ║   │   - artifact_store = RedisArtifactStore         │     ║ │
│   ║   │                                                 │     ║ │
│   ║   │   ┌─────────────┐ ┌─────────────┐ ┌──────────┐  │     ║ │
│   ║   │   │ ToolRegistry│ │SkillLibrary│ │RedisArtifact │     ║ │
│   ║   │   │ (Redis)     │ │ (Redis)    │ │ (Redis)  │  │     ║ │
│   ║   │   └──────┬──────┘ └──────┬──────┘ └────┬─────┘  │     ║ │
│   ║   └──────────┼───────────────┼─────────────┼────────┘     ║ │
│   ╚══════════════╬═══════════════╬═════════════╬══════════════╝ │
│                  │               │             │                │
└──────────────────┼───────────────┼─────────────┼────────────────┘
                   │               │             │
        ┌──────────▼───────────────▼─────────────▼──────────┐
        │                       Redis                       │
        │                                                   │
        │   agent-tools:*  │  agent-skills:*  │  agent-artifacts:*
        │   (yaml configs) │  (python code)   │  (binary data)
        │                                                   │
        │   Provisioned via:                                │
        │   python -m py_code_mode.store bootstrap ...      │
        │                                                   │
        └───────────────────────────────────────────────────┘
```

**Key flow:**
1. Session derives `RedisStorageAccess` from `RedisStorage`
2. Session passes `RedisStorageAccess` to `executor.start(storage_access=...)`
3. ContainerExecutor configures container with Redis connection details
4. SessionServer (in container) loads everything from Redis using provided prefixes

**No volume mounts needed** - all data comes from Redis.

**Provisioning before deployment:**
```bash
# Bootstrap tools to Redis
python -m py_code_mode.store bootstrap \
    --source ./tools \
    --target redis://redis:6379 \
    --prefix agent:tools \
    --type tools

# Bootstrap skills to Redis
python -m py_code_mode.store bootstrap \
    --source ./skills \
    --target redis://redis:6379 \
    --prefix agent:skills
```

---

## Storage Comparison Matrix

| Storage Type | API | Tools Source | Skills Source | Artifacts Store |
|--------------|-----|--------------|---------------|-----------------|
| FileStorage | `Session(storage=FileStorage(base_path=...))` | `<base>/tools/*.yaml` | `<base>/skills/*.py` | `<base>/artifacts/` |
| RedisStorage | `Session(storage=RedisStorage(redis=client, prefix=...))` | `<prefix>:tools:*` | `<prefix>:skills:*` | `<prefix>:artifacts:*` |
| Container + File | `Session(storage=FileStorage(...), executor=ContainerExecutor(...))` | Volume mounted | Volume mounted | Volume mounted |
| Container + Redis | `Session(storage=RedisStorage(...), executor=ContainerExecutor(...))` | Redis keys | Redis keys | Redis keys |

**Decision tree:**

```
Choose storage backend:
    │
    ├─ Single machine, local dev?  → FileStorage(base_path=Path("./storage"))
    └─ Distributed, production?    → RedisStorage(redis=client, prefix="app")

Choose executor:
    │
    ├─ Same-process execution?     → InProcessExecutor() (default)
    └─ Process isolation needed?   → ContainerExecutor(config=ContainerConfig(...))

Combine:
    Session(storage=storage, executor=executor)  # or omit executor for default
```

---

## Data Flow

### Tool Execution

```
Agent writes: "tools.curl(url='...')"
        │
        ▼
┌───────────────────────┐
│ ToolsNamespace        │
│                       │
│ tools.curl(url=...)   │──▶ ToolRegistry.call_tool("curl", {...})
│ tools.call("curl",...)│                │
│ tools.search(...)     │                ▼
│ tools.list()          │         ┌────────────┐
└───────────────────────┘         │ CLIAdapter │ → subprocess
                                  │ MCPAdapter │ → MCP server
                                  │ HTTPAdapter│ → HTTP request
                                  └────────────┘
```

### Skill Execution

```
Agent writes: "skills.analyze_repo(repo='...')"
        │
        ▼
┌───────────────────────┐
│ SkillsNamespace       │
│                       │
│ skills.invoke("name") │──▶ SkillLibrary.get("analyze_repo")
│ skills.analyze_repo() │                │
│ skills.search("...")  │                ▼
│ skills.list()         │         ┌─────────────┐
└───────────────────────┘         │ SkillStore  │
                                  │ (File/Redis)│
                                  └──────┬──────┘
                                         │
                                         ▼
                                  ┌─────────────────┐
                                  │ compile(source) │
                                  │ exec(code)      │
                                  │ return run()    │
                                  └─────────────────┘
```

### Artifact Storage

```
Agent writes: "artifacts.save('data.json', b'...', 'description')"
        │
        ▼
┌───────────────────────┐
│ ArtifactStore         │
│                       │
│ artifacts.save(...)   │──▶ FileArtifactStore.save()  → disk
│ artifacts.load(...)   │    or
│ artifacts.list()      │    RedisArtifactStore.save() → Redis
└───────────────────────┘
```

---

## Deployment Checklist

### Local Development (Session + FileStorage)
- [ ] Create base storage directory
- [ ] Add YAML tool definitions to `<base_path>/tools/`
- [ ] Add Python skill files to `<base_path>/skills/`
- [ ] Use `Session(storage=FileStorage(base_path=Path("./storage")))`

### Local with Container Isolation (Container + File)
- [ ] Build Docker image with py-code-mode and tools installed
- [ ] Configure `TOOLS_CONFIG` in image or mount tools directory
- [ ] Mount skills directory: `-v ./skills:/app/skills:ro`
- [ ] Mount artifacts directory: `-v ./artifacts:/workspace/artifacts:rw`
- [ ] Use `Session(storage=FileStorage(...), executor=ContainerExecutor(config))`

### Production (Session + RedisStorage)
- [ ] Provision Redis instance
- [ ] Bootstrap tools: `python -m py_code_mode.store bootstrap --type tools --target redis://... --prefix myapp:tools`
- [ ] Bootstrap skills: `python -m py_code_mode.store bootstrap --target redis://... --prefix myapp:skills`
- [ ] Create storage: `RedisStorage(redis=Redis.from_url("redis://..."), prefix="myapp")`
- [ ] Use `Session(storage=storage)`

### Production with Container Isolation
- [ ] Provision Redis instance
- [ ] Bootstrap tools and skills to Redis (as above)
- [ ] Create storage: `RedisStorage(redis=redis_client, prefix="myapp")`
- [ ] Create executor: `ContainerExecutor(config=ContainerConfig(...))`
- [ ] Use `Session(storage=storage, executor=executor)`
