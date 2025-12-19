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

**New API** (recommended):
```python
from py_code_mode import Session, FileStorage, RedisStorage

# File-based
storage = FileStorage(
    tools_path=Path("./tools"),
    skills_path=Path("./skills"),
    artifacts_path=Path("./artifacts"),
)

# Redis-based
storage = RedisStorage(
    redis_url="redis://localhost:6379",
    tools_prefix="myapp:tools",
    skills_prefix="myapp:skills",
    artifacts_prefix="myapp:artifacts",
)

async with Session(storage=storage) as session:
    result = await session.run('tools.curl(url="...")')
```

**Legacy API** (for container backend):
- `create_executor(backend="in-process", tools=..., skills=...)`
- `create_executor(backend="container")` (with SessionServer)

ContainerExecutor support in Session is pending.

## Deployment Scenarios

Storage and execution are now separate concerns:

```
Session(storage=..., executor=...)
    │
    ├─ Storage (where data lives):
    │   ├─ FileStorage(tools_path, skills_path, artifacts_path)
    │   └─ RedisStorage(redis_url, prefixes...)
    │
    └─ Executor (where code runs):
        ├─ InProcessExecutor (default, same process)
        └─ ContainerExecutor (Docker isolation, pending)
```

**Current state:**
- `Session` API supports FileStorage and RedisStorage
- `Session` defaults to InProcessExecutor
- ContainerExecutor integration pending (use legacy `create_executor(backend="container")`)

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
│   │       tools_path=Path("./tools"),                     │     │
│   │       skills_path=Path("./skills"),                   │     │
│   │       artifacts_path=Path("./artifacts"),             │     │
│   │   )                                                   │     │
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

storage = FileStorage(
    tools_path=Path("./tools"),
    skills_path=Path("./skills"),
    artifacts_path=Path("./artifacts"),
)

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
│   │   storage = RedisStorage(                             │     │
│   │       redis_url="redis://localhost:6379",             │     │
│   │       tools_prefix="agent:tools",                     │     │
│   │       skills_prefix="agent:skills",                   │     │
│   │       artifacts_prefix="agent:artifacts",             │     │
│   │   )                                                   │     │
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
from py_code_mode import Session, RedisStorage

storage = RedisStorage(
    redis_url="redis://localhost:6379",
    tools_prefix="agent:tools",
    skills_prefix="agent:skills",
    artifacts_prefix="agent:artifacts",
)

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

> **Note:** ContainerExecutor support in Session is pending.
> Use the legacy `create_executor(backend="container")` API for now.
> The `tools` parameter is **ignored** by the container backend.
> Tools must be provided via `TOOLS_CONFIG` environment variable pointing
> to a YAML file (baked into the image or volume mounted).

```
┌─────────────────────────────────────────────────────────────────┐
│                        Host Machine                             │
│                                                                 │
│   ┌───────────────────────────────────────────────────────┐     │
│   │                     Your Agent                        │     │
│   │                                                       │     │
│   │   executor = await create_executor(                   │     │
│   │       backend="container",                            │     │
│   │       # NOTE: tools= is IGNORED by container backend  │     │
│   │       artifacts="./artifacts/",   ─────────┐          │     │
│   │       skills="./skills/",         ───────┐ │          │     │
│   │   )                                      │ │          │     │
│   └───────────────────────┬──────────────────┼─┼──────────┘     │
│                           │ HTTP             │ │                │
│                           │                  │ │                │
│   ╔═══════════════════════▼══════════════════▼═▼══════════════╗ │
│   ║               Docker Container                            ║ │
│   ║               (no REDIS_URL set)                          ║ │
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

> **Note:** ContainerExecutor support in Session is pending.
> Use the legacy `create_executor(backend="container")` API for now.

```
┌─────────────────────────────────────────────────────────────────┐
│                        Host / Cloud                             │
│                                                                 │
│   ┌───────────────────────────────────────────────────────┐     │
│   │                     Your Agent                        │     │
│   │                                                       │     │
│   │   executor = await create_executor(                   │     │
│   │       backend="container",                            │     │
│   │   )                                                   │     │
│   │                                                       │     │
│   │   # Container receives REDIS_URL env var              │     │
│   └───────────────────────┬───────────────────────────────┘     │
│                           │ HTTP                                │
│                           │                                     │
│   ╔═══════════════════════▼═══════════════════════════════════╗ │
│   ║               Docker Container                            ║ │
│   ║               REDIS_URL=redis://redis:6379                ║ │
│   ║                                                           ║ │
│   ║   ┌─────────────────────────────────────────────────┐     ║ │
│   ║   │            SessionServer (FastAPI)              │     ║ │
│   ║   │                                                 │     ║ │
│   ║   │   When REDIS_URL is set:                        │     ║ │
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

**Key insight:** When `REDIS_URL` is set in the container environment, the SessionServer automatically loads **everything** from Redis:
- Tools via `registry_from_redis()`
- Skills via `RedisSkillStore`
- Artifacts via `RedisArtifactStore`

**Container environment:**
```
REDIS_URL=redis://redis:6379
# That's it! No volume mounts needed.
```

**Provisioning before deployment:**
```bash
# Bootstrap tools to Redis
python -m py_code_mode.store bootstrap \
    --source ./tools \
    --target redis://redis:6379 \
    --prefix agent-tools \
    --type tools

# Bootstrap skills to Redis
python -m py_code_mode.store bootstrap \
    --source ./skills \
    --target redis://redis:6379 \
    --prefix agent-skills
```

---

## Storage Comparison Matrix

| Storage Type | API | Tools Source | Skills Source | Artifacts Store |
|--------------|-----|--------------|---------------|-----------------|
| FileStorage | `Session(storage=FileStorage(...))` | `./tools/*.yaml` | `./skills/*.py` | `./artifacts/` |
| RedisStorage | `Session(storage=RedisStorage(...))` | Redis keys | Redis keys | Redis keys |
| Container + File (legacy) | `create_executor(backend="container")` | `TOOLS_CONFIG` yaml | Volume mount | Volume mount |
| Container + Redis (legacy) | `create_executor(backend="container")` with `REDIS_URL` | Redis | Redis | Redis |

**Decision tree:**

```
Do you need process isolation (Docker)?
    │
    ├─ No  → Session API
    │         │
    │         ├─ Single machine?  → FileStorage
    │         └─ Distributed?     → RedisStorage
    │
    └─ Yes → Legacy create_executor(backend="container")
              │
              ├─ Local dev?       → Volume mounts (no REDIS_URL)
              └─ Production?      → Redis storage (set REDIS_URL)

              (ContainerExecutor support in Session pending)
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
- [ ] Create `./tools/` with YAML tool definitions
- [ ] Create `./skills/` with Python skill files
- [ ] Create `./artifacts/` for output storage
- [ ] Use `Session(storage=FileStorage(tools_path=..., skills_path=..., artifacts_path=...))`

### Local with Container Isolation (Container + File)
- [ ] Build Docker image with py-code-mode and tools installed
- [ ] Configure `TOOLS_CONFIG` in image or mount tools directory
- [ ] Mount skills directory: `-v ./skills:/app/skills:ro`
- [ ] Mount artifacts directory: `-v ./artifacts:/workspace/artifacts:rw`
- [ ] Use `create_executor(backend="container", ...)`

### Production (Session + RedisStorage)
- [ ] Provision Redis instance
- [ ] Bootstrap tools: `python -m py_code_mode.store bootstrap --type tools --target redis://... --prefix myapp:tools`
- [ ] Bootstrap skills: `python -m py_code_mode.store bootstrap --target redis://... --prefix myapp:skills`
- [ ] Use `Session(storage=RedisStorage(redis_url=..., tools_prefix=..., skills_prefix=..., artifacts_prefix=...))`

### Production (Legacy Container + Redis)
- [ ] Provision Redis instance
- [ ] Bootstrap tools and skills to Redis (as above)
- [ ] Set `REDIS_URL` environment variable in container
- [ ] Deploy container (no volume mounts needed)
- [ ] Container automatically loads everything from Redis
- [ ] Use `create_executor(backend="container")` (legacy API)
