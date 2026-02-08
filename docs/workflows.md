# Workflows

Workflows are reusable Python workflows that persist across sessions. Agents create workflows when they solve problems, then invoke them later instead of re-solving from scratch.

## Core Concept

When an agent successfully completes a multi-step workflow, they save it as a workflow. Next time they need that capability, they search for and invoke the workflow directly—no re-planning required.

Over time, the workflow library grows. Simple workflows become building blocks for more complex workflows.

## Creating Workflows

Workflows are async Python functions with an `async def run()` entry point:

```python
# workflows/fetch_json.py
"""Fetch and parse JSON from a URL."""

async def run(url: str, headers: dict = None) -> dict:
    """Fetch JSON data from a URL.

    Args:
        url: The URL to fetch
        headers: Optional HTTP headers

    Returns:
        Parsed JSON response

    Raises:
        RuntimeError: If request fails or response isn't valid JSON
    """
    import json
    try:
        response = await tools.curl.get(url=url)
        return json.loads(response)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Invalid JSON from {url}: {e}") from e
```

> **Note:** All workflows must use `async def run()`. Synchronous `def run()` is not supported.

### Runtime Creation

Agents can create workflows dynamically:

```python
await workflows.create(
    name="fetch_json",
    source='''async def run(url: str) -> dict:
    """Fetch and parse JSON from a URL."""
    import json
    response = await tools.curl.get(url=url)
    return json.loads(response)
''',
    description="Fetch JSON from URL and parse response"
)
```

## Workflow Discovery

Workflows support semantic search based on descriptions:

```python
# Search by intent
results = await workflows.search("fetch github repository data")
# Returns workflows ranked by relevance to the query

# List all workflows
all_workflows = await workflows.list()

# Get specific workflow details
workflow = await workflows.get("fetch_json")
```

The search uses embedding-based similarity, so it understands intent even if the exact words don't match.

## Invoking Workflows

```python
# Direct invocation
data = await workflows.invoke("fetch_json", url="https://api.github.com/repos/owner/repo")

# With keyword arguments
analysis = await workflows.invoke(
    "analyze_repo",
    owner="anthropics",
    repo="anthropic-sdk-python"
)
```

## Composing Workflows

Workflows can invoke other workflows, enabling layered workflows:

### Layer 1: Base Workflows (Building Blocks)

```python
# workflows/fetch_json.py
async def run(url: str) -> dict:
    """Fetch and parse JSON from a URL."""
    import json
    response = await tools.curl.get(url=url)
    return json.loads(response)
```

### Layer 2: Domain Workflows (Compositions)

```python
# workflows/get_repo_metadata.py
async def run(owner: str, repo: str) -> dict:
    """Get GitHub repository metadata."""
    # Uses the fetch_json workflow
    data = await workflows.invoke(
        "fetch_json",
        url=f"https://api.github.com/repos/{owner}/{repo}",
    )

    return {
        "name": data["name"],
        "stars": data["stargazers_count"],
        "language": data["language"],
        "description": data.get("description", "")
    }
```

### Layer 3: Workflow Workflows (Orchestration)

```python
# workflows/analyze_multiple_repos.py
async def run(repos: list) -> dict:
    """Analyze multiple GitHub repositories."""
    summaries = []
    for repo in repos:
        owner, name = repo.split('/')
        # Uses the get_repo_metadata workflow
        metadata = await workflows.invoke("get_repo_metadata", owner=owner, repo=name)
        summaries.append(metadata)

    # Aggregate results
    total_stars = sum(r["stars"] for r in summaries)
    languages = list(set(r["language"] for r in summaries if r["language"]))

    return {
        "total_repos": len(summaries),
        "total_stars": total_stars,
        "languages": languages,
        "repos": summaries
    }
```

**Simple workflows become building blocks for complex workflows.** As the library grows, agents accomplish more by composing existing capabilities.

## Quality Standards

Workflows should follow these standards for reliability and maintainability:

### Type Hints

```python
# Good: Full type hints
async def run(url: str, timeout: int = 30) -> dict:
    ...

# Bad: No type hints
async def run(url, timeout=30):
    ...
```

### Docstrings

```python
# Good: Complete docstring
async def run(owner: str, repo: str) -> dict:
    """Get GitHub repository metadata.

    Args:
        owner: Repository owner username
        repo: Repository name

    Returns:
        Dictionary with repo metadata (name, stars, language)

    Raises:
        RuntimeError: If API request fails
    """
    ...

# Bad: No docstring
async def run(owner: str, repo: str) -> dict:
    ...
```

### Error Handling

```python
# Good: Explicit error handling
async def run(url: str) -> dict:
    import json
    try:
        response = tools.curl.get(url=url)
        return json.loads(response)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Invalid JSON from {url}: {e}") from e
    except Exception as e:
        raise RuntimeError(f"Failed to fetch {url}: {e}") from e

# Bad: Silent failure
async def run(url: str) -> dict:
    try:
        response = tools.curl.get(url=url)
        return json.loads(response)
    except:
        return {}  # Hides what went wrong!
```

### Clear Parameter Names

```python
# Good: Descriptive names
async def run(repository_url: str, include_contributors: bool = False) -> dict:
    ...

# Bad: Cryptic abbreviations
async def run(repo_url: str, incl_contrib: bool = False) -> dict:
    ...
```

## Managing Workflows

### Deleting Workflows

```python
# Delete a workflow by name
await workflows.delete("old_workflow_name")
```

### Updating Workflows

Workflows are immutable. To update, delete and recreate:

```python
# Delete old version
await workflows.delete("fetch_json")

# Create new version
await workflows.create(
    name="fetch_json",
    source='''async def run(url: str, timeout: int = 30) -> dict:
    # Updated implementation with timeout
    ...
''',
    description="Fetch JSON with configurable timeout"
)
```

## Seeding Workflows

You can pre-author workflows for agents to discover:

### File-based (Recommended)

Create `.py` files in the workflows directory:

```python
# workflows/fetch_and_summarize.py
"""Fetch a URL and extract key information."""

async def run(url: str) -> dict:
    content = await tools.fetch(url=url)
    paragraphs = [p for p in content.split("\n\n") if p.strip()]
    return {
        "url": url,
        "summary": paragraphs[0] if paragraphs else "",
        "word_count": len(content.split())
    }
```

### Programmatic

Use `session.add_workflow()` for runtime workflow creation (recommended):

```python
async with Session(storage=storage) as session:
    await session.add_workflow(
        name="greet",
        source='''async def run(name: str = "World") -> str:
    return f"Hello, {name}!"
''',
        description="Generate a greeting message"
    )
```

For advanced use cases where you need to create workflows outside of agent code execution, use `session.add_workflow()`:

```python
async with Session(storage=storage, executor=executor) as session:
    await session.add_workflow(
        name="greet",
        source='''async def run(name: str = "World") -> str:
    return f"Hello, {name}!"
''',
        description="Generate a greeting message"
    )
```

## Best Practices

**When to create workflows:**
- You'll need this operation again (or similar variants)
- It's more than 5 lines of meaningful logic
- It has clear inputs and outputs
- It could be composed into higher-level workflows

**When NOT to create workflows:**
- One-off operations you won't repeat
- Simple wrappers around single tool calls
- Exploration or debugging code

**Workflow composition guidelines:**
- Start with simple, focused workflows (single responsibility)
- Build higher-level workflows by composing simpler ones
- Use semantic search to find existing workflows before creating new ones
- Name workflows descriptively (what they do, not how they do it)

## Examples

See [examples/](../examples/) for complete workflow libraries in working agent applications.
