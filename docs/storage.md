# Storage

Storage backends determine where workflows and artifacts persist. Tools and dependencies are now owned by executors (via config).

## FileStorage

Stores workflows and artifacts in local directories. Good for development and single-instance deployments.

```python
from pathlib import Path
from py_code_mode import FileStorage

storage = FileStorage(base_path=Path("./data"))
```

### Directory Structure

```
./data/
├── workflows/         # Workflow .py files
├── artifacts/      # Saved data
└── vectors/        # Embedding cache (if chromadb installed)
```

**Note:** Tools are loaded from executor config (`config.tools_path`), not storage.

### When to Use

- ✓ Local development
- ✓ Single-agent deployments
- ✓ Simple setup with no external dependencies
- ✓ Version control integration (commit workflows to git)

### Limitations

- Single-instance only (no workflow sharing between agents)
- No automatic backup
- Manual synchronization if running multiple instances

---

## RedisStorage

Stores data in Redis. Enables workflow sharing across multiple agent instances.

```python
from py_code_mode import RedisStorage

storage = RedisStorage(url="redis://localhost:6379", prefix="my-agents")
```

### Key Structure

```
{prefix}:workflows:{name}         # Workflow source code
{prefix}:artifacts:{name}      # Artifact data
{prefix}:vectors:*             # Embedding cache (if RediSearch available)
```

**Note:** Tools are loaded from executor config (`config.tools_path`), not storage. Dependencies are also configured via executor config.

### When to Use

- ✓ Multi-instance deployments
- ✓ Workflow sharing across agents
- ✓ Cloud deployments
- ✓ Need centralized workflow library

### Configuration

```python
RedisStorage(
    url="redis://localhost:6379",  # Redis URL (preferred)
    prefix="production",           # Key prefix for isolation
)

# Or with pre-constructed client (advanced use cases)
RedisStorage(
    redis=redis_client,     # Redis client instance
    prefix="production",
)
```

### Workspace Scoping

Both storage backends accept an optional `workspace_id`:

```python
from pathlib import Path

from py_code_mode import FileStorage, RedisStorage

file_storage = FileStorage(base_path=Path("./data"), workspace_id="client-a")
redis_storage = RedisStorage(
    url="redis://localhost:6379",
    prefix="production",
    workspace_id="client-a",
)
```

When `workspace_id` is set, workflows, artifacts, and vector caches are scoped to that
workspace and shared by other sessions using the same ID.

When `workspace_id` is omitted, storage uses the legacy unscoped namespace. This is one
shared default namespace, **not** access to all workspaces.

---

## One Agent Learns, All Agents Benefit

**The power of RedisStorage:** When one agent creates a workflow, it's immediately available to all other agents sharing the same Redis storage.

```python
# Agent Instance 1
async with Session(storage=redis_storage) as session:
    await session.run('''
workflows.create(
    name="analyze_sentiment",
    source="""async def run(text: str) -> dict:
        # Implementation
        return {"sentiment": "positive", "score": 0.9}
    """,
    description="Analyze sentiment of text"
)
''')

# Agent Instance 2 (different process, different machine)
async with Session(storage=redis_storage) as session:
    # Workflow is already available!
    result = await session.run('workflows.invoke("analyze_sentiment", text="Great product!")')
```

---

## Storage Isolation

Use different prefixes to isolate storage for different environments:

```python
# Development environment
dev_storage = RedisStorage(url="redis://localhost:6379", prefix="dev")

# Production environment
prod_storage = RedisStorage(url="redis://prod-redis:6379", prefix="prod")

# Multi-tenant isolation
tenant_a_storage = RedisStorage(url="redis://localhost:6379", prefix="tenant-a")
tenant_b_storage = RedisStorage(url="redis://localhost:6379", prefix="tenant-b")
```

For multi-tenant systems inside one environment, prefer a stable app-level prefix plus
per-session `workspace_id` values:

```python
storage = RedisStorage(
    url="redis://localhost:6379",
    prefix="production",
    workspace_id="client-a",
)
```

---

## Migrating Between Storage Backends

Use the CLI tools for migration (recommended):

### File to Redis

```bash
python -m py_code_mode.store bootstrap \
  --source ./workflows \
  --target redis://localhost:6379 \
  --prefix production
```

### Redis to File

```bash
python -m py_code_mode.store pull \
  --target redis://localhost:6379 \
  --prefix production \
  --dest ./workflows-backup
```

---

## CLI Tools for Storage Management

Bootstrap workflows from file to Redis:

```bash
python -m py_code_mode.store bootstrap \
  --source ./workflows \
  --target redis://localhost:6379 \
  --prefix production
```

Pull workflows from Redis to file:

```bash
python -m py_code_mode.store pull \
  --target redis://localhost:6379 \
  --prefix production \
  --dest ./workflows-review
```

Compare file and Redis storage:

```bash
python -m py_code_mode.store diff \
  --source ./workflows \
  --target redis://localhost:6379 \
  --prefix production
```

---

## Best Practices

### Development

- Use FileStorage for local development
- Commit workflows to version control
- Use feature branches for experimental workflows

### Production

- Use RedisStorage for multi-instance deployments
- Set appropriate TTLs if workflows should expire
- Use prefixes to isolate environments (dev/staging/prod)
- Regular backups to file storage

### Multi-Tenant

- Use a stable environment prefix (for example `prod`) plus `workspace_id` per tenant or campaign
- Consider separate Redis instances for hard isolation
- Monitor Redis memory usage

### Remote Session Servers

When using `ContainerExecutor(remote_url=...)`, the host storage object and the remote
session server must point at the same logical backing store:

- file-backed remote mode: host `FileStorage(...)` should correspond to the server's
  `storage_base_path`
- Redis-backed remote mode: host `RedisStorage(prefix=..., workspace_id=...)` should
  correspond to the server's `storage_prefix`

For true remote deployments, `RedisStorage` is usually the simplest and safest option
because both the host process and the remote session server can share the same Redis
namespace directly.

### Workflow Lifecycle

```python
# Development: Create workflows in file storage
file_storage = FileStorage(base_path=Path("./workflows"))

# Review: Pull workflows for code review
# (use CLI tools)

# Promotion: Push vetted workflows to production
redis_storage = RedisStorage(url="redis://prod-redis:6379", prefix="prod")
# (use CLI tools to bootstrap)
```

---

## Storage Abstraction

Storage backends implement a common protocol, making them interchangeable:

```python
from pathlib import Path
from py_code_mode import Session, FileStorage, RedisStorage
from py_code_mode.execution import SubprocessConfig, SubprocessExecutor

def create_session(storage_type: str, tools_path: Path):
    # Choose storage based on environment
    if storage_type == "file":
        storage = FileStorage(base_path=Path("./data"))
    elif storage_type == "redis":
        storage = RedisStorage(url="redis://localhost:6379", prefix="app")

    # Executor config is the same for both storage types
    config = SubprocessConfig(tools_path=tools_path)
    executor = SubprocessExecutor(config=config)

    return Session(storage=storage, executor=executor)
```

All session features work with any storage backend - the choice only affects where workflows and artifacts persist. Tools and deps come from executor config.
