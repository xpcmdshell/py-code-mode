# Artifacts

Artifacts provide persistent data storage across sessions. Use them to cache results, maintain state, or share data between workflows.

## Basic Usage

```python
# Save data
await artifacts.save("analysis_results", {
    "repos_analyzed": 42,
    "findings": [...]
})

# Load data
data = await artifacts.load("analysis_results")

# List all artifacts
all_artifacts = await artifacts.list()

# Delete an artifact
await artifacts.delete("old_data")
```

## Storage Formats

Artifacts automatically handle serialization based on data type:

```python
# JSON-serializable data (dicts, lists, primitives)
await artifacts.save("config", {"api_key": "...", "timeout": 30})

# Binary data
await artifacts.save("image", image_bytes)

# Text data
await artifacts.save("report", "Analysis results: ...")
```

## Use Cases

### Caching API Responses

```python
async def run(owner: str, repo: str) -> dict:
    cache_key = f"repo_{owner}_{repo}"

    # Check cache first
    cached = await artifacts.load(cache_key)
    if cached:
        return cached

    # Fetch fresh data
    data = await tools.curl.get(url=f"https://api.github.com/repos/{owner}/{repo}")

    # Cache for next time
    await artifacts.save(cache_key, data)
    return data
```

### Maintaining State

```python
async def run(url: str) -> dict:
    # Load previous crawl state
    state = await artifacts.load("crawl_state") or {"visited": [], "queue": []}

    if url in state["visited"]:
        return {"status": "already_crawled"}

    # Process URL
    content = await tools.fetch(url=url)
    state["visited"].append(url)

    # Save updated state
    await artifacts.save("crawl_state", state)
    return {"status": "success", "content": content}
```

### Sharing Data Between Workflows

```python
# Skill 1: Collect data
async def run(sources: list) -> dict:
    results = [fetch_source(s) for s in sources]
    await artifacts.save("collected_data", results)
    return {"count": len(results)}

# Skill 2: Analyze data
async def run() -> dict:
    data = await artifacts.load("collected_data")
    analysis = analyze(data)
    await artifacts.save("analysis_report", analysis)
    return analysis
```

## Storage Backends

Artifacts are stored according to your storage backend:

**FileStorage:**
- Stored in `{base_path}/artifacts/` directory
- Each artifact is a separate file
- JSON data stored as `.json`, binary as raw files

**RedisStorage:**
- Stored as Redis keys with configured prefix
- Automatic expiration support (if configured)
- Shared across all agent instances

## Best Practices

**Use descriptive names:**
```python
# Good
await artifacts.save("github_repos_2024_analysis", data)

# Bad
await artifacts.save("data1", data)
```

**Clean up old artifacts:**
```python
# Remove artifacts you no longer need
await artifacts.delete("temp_processing_results")
```

**Consider data size:**
- Artifacts are loaded into memory when accessed
- Large datasets may impact performance
- Consider pagination or chunking for large data

## Metadata

Artifacts automatically track metadata:

```python
artifacts_list = await artifacts.list()
for artifact in artifacts_list:
    print(f"{artifact['name']}: {artifact['created_at']}")
```

## Limitations

- No versioning (saving with same name overwrites)
- No automatic expiration (except with Redis TTL configuration)
- No search/filtering beyond list all
- No access control (all agents with same storage can access all artifacts)
