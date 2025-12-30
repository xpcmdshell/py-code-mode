# Storage

Storage backends determine where tools, skills, artifacts, and dependencies persist.

## FileStorage

Stores data in local directories. Good for development and single-instance deployments.

```python
from pathlib import Path
from py_code_mode import FileStorage

storage = FileStorage(base_path=Path("./data"))
```

### Directory Structure

```
./data/
├── tools/          # Tool YAML definitions
├── skills/         # Skill .py files
├── artifacts/      # Saved data
└── requirements.txt  # Dependencies
```

### When to Use

- ✓ Local development
- ✓ Single-agent deployments
- ✓ Simple setup with no external dependencies
- ✓ Version control integration (commit skills to git)

### Limitations

- Single-instance only (no skill sharing between agents)
- No automatic backup
- Manual synchronization if running multiple instances

---

## RedisStorage

Stores data in Redis. Enables skill sharing across multiple agent instances.

```python
from py_code_mode import RedisStorage

storage = RedisStorage(url="redis://localhost:6379", prefix="my-agents")
```

### Key Structure

```
{prefix}:tools:{name}          # Tool definitions
{prefix}:skills:{name}         # Skill source code
{prefix}:artifacts:{name}      # Artifact data
{prefix}:deps                  # Dependency list
```

### When to Use

- ✓ Multi-instance deployments
- ✓ Skill sharing across agents
- ✓ Cloud deployments
- ✓ Need centralized skill library

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

---

## One Agent Learns, All Agents Benefit

**The power of RedisStorage:** When one agent creates a skill, it's immediately available to all other agents sharing the same Redis storage.

```python
# Agent Instance 1
async with Session(storage=redis_storage) as session:
    await session.run('''
skills.create(
    name="analyze_sentiment",
    source="""def run(text: str) -> dict:
        # Implementation
        return {"sentiment": "positive", "score": 0.9}
    """,
    description="Analyze sentiment of text"
)
''')

# Agent Instance 2 (different process, different machine)
async with Session(storage=redis_storage) as session:
    # Skill is already available!
    result = await session.run('skills.invoke("analyze_sentiment", text="Great product!")')
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

---

## Migrating Between Storage Backends

### File to Redis

```python
from pathlib import Path
from py_code_mode import FileStorage, RedisStorage

# Load from file storage
file_storage = FileStorage(base_path=Path("./data"))
file_skill_store = file_storage.get_skill_store()
skills = file_skill_store.list_all()

# Save to Redis storage
redis_storage = RedisStorage(url="redis://localhost:6379", prefix="production")
redis_skill_store = redis_storage.get_skill_store()

for skill in skills:
    redis_skill_store.save(skill)
```

### Redis to File

```python
from pathlib import Path
from py_code_mode import FileStorage, RedisStorage

# Load from Redis
redis_storage = RedisStorage(url="redis://localhost:6379", prefix="production")
redis_skill_store = redis_storage.get_skill_store()
skills = redis_skill_store.list_all()

# Save to file storage
file_storage = FileStorage(base_path=Path("./backup"))
file_skill_store = file_storage.get_skill_store()

for skill in skills:
    file_skill_store.save(skill)
```

---

## CLI Tools for Storage Management

Bootstrap skills from file to Redis:

```bash
python -m py_code_mode.store bootstrap \
  --source ./skills \
  --target redis://localhost:6379 \
  --prefix production
```

Pull skills from Redis to file:

```bash
python -m py_code_mode.store pull \
  --target redis://localhost:6379 \
  --prefix production \
  --dest ./skills-review
```

Compare file and Redis storage:

```bash
python -m py_code_mode.store diff \
  --source ./skills \
  --target redis://localhost:6379 \
  --prefix production
```

---

## Best Practices

### Development

- Use FileStorage for local development
- Commit skills to version control
- Use feature branches for experimental skills

### Production

- Use RedisStorage for multi-instance deployments
- Set appropriate TTLs if skills should expire
- Use prefixes to isolate environments (dev/staging/prod)
- Regular backups to file storage

### Multi-Tenant

- Use separate prefix per tenant
- Consider separate Redis instances for hard isolation
- Monitor Redis memory usage

### Skill Lifecycle

```python
# Development: Create skills in file storage
file_storage = FileStorage(base_path=Path("./skills"))

# Review: Pull skills for code review
# (use CLI tools)

# Promotion: Push vetted skills to production
redis_storage = RedisStorage(url="redis://prod-redis:6379", prefix="prod")
# (use CLI tools to bootstrap)
```

---

## Storage Abstraction

Storage backends implement a common protocol, making them interchangeable:

```python
def create_session(storage_type: str):
    if storage_type == "file":
        storage = FileStorage(base_path=Path("./data"))
    elif storage_type == "redis":
        storage = RedisStorage(url="redis://localhost:6379", prefix="app")

    return Session(storage=storage)
```

All session features work with any storage backend - the choice only affects where data persists.
