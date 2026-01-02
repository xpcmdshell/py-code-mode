# Skills

Skills are reusable Python workflows that persist across sessions. Agents create skills when they solve problems, then invoke them later instead of re-solving from scratch.

## Core Concept

When an agent successfully completes a multi-step workflow, they save it as a skill. Next time they need that capability, they search for and invoke the skill directly—no re-planning required.

Over time, the skill library grows. Simple skills become building blocks for more complex workflows.

## Creating Skills

Skills are Python functions with a `run()` entry point:

```python
# skills/fetch_json.py
"""Fetch and parse JSON from a URL."""

def run(url: str, headers: dict = None) -> dict:
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
        response = tools.curl.get(url=url)
        return json.loads(response)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Invalid JSON from {url}: {e}") from e
```

### Runtime Creation

Agents can create skills dynamically:

```python
skills.create(
    name="fetch_json",
    source='''def run(url: str) -> dict:
    """Fetch and parse JSON from a URL."""
    import json
    response = tools.curl.get(url=url)
    return json.loads(response)
''',
    description="Fetch JSON from URL and parse response"
)
```

## Skill Discovery

Skills support semantic search based on descriptions:

```python
# Search by intent
results = skills.search("fetch github repository data")
# Returns skills ranked by relevance to the query

# List all skills
all_skills = skills.list()

# Get specific skill details
skill = skills.get("fetch_json")
```

The search uses embedding-based similarity, so it understands intent even if the exact words don't match.

## Invoking Skills

```python
# Direct invocation
data = skills.invoke("fetch_json", url="https://api.github.com/repos/owner/repo")

# With keyword arguments
analysis = skills.invoke(
    "analyze_repo",
    owner="anthropics",
    repo="anthropic-sdk-python"
)
```

## Composing Skills

Skills can invoke other skills, enabling layered workflows:

### Layer 1: Base Skills (Building Blocks)

```python
# skills/fetch_json.py
def run(url: str) -> dict:
    """Fetch and parse JSON from a URL."""
    import json
    response = tools.curl.get(url=url)
    return json.loads(response)
```

### Layer 2: Domain Skills (Compositions)

```python
# skills/get_repo_metadata.py
def run(owner: str, repo: str) -> dict:
    """Get GitHub repository metadata."""
    # Uses the fetch_json skill
    data = skills.invoke("fetch_json",
                         url=f"https://api.github.com/repos/{owner}/{repo}")

    return {
        "name": data["name"],
        "stars": data["stargazers_count"],
        "language": data["language"],
        "description": data.get("description", "")
    }
```

### Layer 3: Workflow Skills (Orchestration)

```python
# skills/analyze_multiple_repos.py
def run(repos: list) -> dict:
    """Analyze multiple GitHub repositories."""
    summaries = []
    for repo in repos:
        owner, name = repo.split('/')
        # Uses the get_repo_metadata skill
        metadata = skills.invoke("get_repo_metadata", owner=owner, repo=name)
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

**Simple skills become building blocks for complex workflows.** As the library grows, agents accomplish more by composing existing capabilities.

## Quality Standards

Skills should follow these standards for reliability and maintainability:

### Type Hints

```python
# Good: Full type hints
def run(url: str, timeout: int = 30) -> dict:
    ...

# Bad: No type hints
def run(url, timeout=30):
    ...
```

### Docstrings

```python
# Good: Complete docstring
def run(owner: str, repo: str) -> dict:
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
def run(owner: str, repo: str) -> dict:
    ...
```

### Error Handling

```python
# Good: Explicit error handling
def run(url: str) -> dict:
    import json
    try:
        response = tools.curl.get(url=url)
        return json.loads(response)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Invalid JSON from {url}: {e}") from e
    except Exception as e:
        raise RuntimeError(f"Failed to fetch {url}: {e}") from e

# Bad: Silent failure
def run(url: str) -> dict:
    try:
        response = tools.curl.get(url=url)
        return json.loads(response)
    except:
        return {}  # Hides what went wrong!
```

### Clear Parameter Names

```python
# Good: Descriptive names
def run(repository_url: str, include_contributors: bool = False) -> dict:
    ...

# Bad: Cryptic abbreviations
def run(repo_url: str, incl_contrib: bool = False) -> dict:
    ...
```

## Managing Skills

### Deleting Skills

```python
# Delete a skill by name
skills.delete("old_skill_name")
```

### Updating Skills

Skills are immutable. To update, delete and recreate:

```python
# Delete old version
skills.delete("fetch_json")

# Create new version
skills.create(
    name="fetch_json",
    source='''def run(url: str, timeout: int = 30) -> dict:
    # Updated implementation with timeout
    ...
''',
    description="Fetch JSON with configurable timeout"
)
```

## Seeding Skills

You can pre-author skills for agents to discover:

### File-based (Recommended)

Create `.py` files in the skills directory:

```python
# skills/fetch_and_summarize.py
"""Fetch a URL and extract key information."""

def run(url: str) -> dict:
    content = tools.fetch(url=url)
    paragraphs = [p for p in content.split("\n\n") if p.strip()]
    return {
        "url": url,
        "summary": paragraphs[0] if paragraphs else "",
        "word_count": len(content.split())
    }
```

### Programmatic

Use `session.add_skill()` for runtime skill creation (recommended):

```python
async with Session(storage=storage) as session:
    await session.add_skill(
        name="greet",
        source='''def run(name: str = "World") -> str:
    return f"Hello, {name}!"
''',
        description="Generate a greeting message"
    )
```

For advanced use cases where you need to create skills outside of agent code execution, use `session.add_skill()`:

```python
async with Session(storage=storage, executor=executor) as session:
    await session.add_skill(
        name="greet",
        source='''def run(name: str = "World") -> str:
    return f"Hello, {name}!"
''',
        description="Generate a greeting message"
    )
```

## Best Practices

**When to create skills:**
- You'll need this operation again (or similar variants)
- It's more than 5 lines of meaningful logic
- It has clear inputs and outputs
- It could be composed into higher-level workflows

**When NOT to create skills:**
- One-off operations you won't repeat
- Simple wrappers around single tool calls
- Exploration or debugging code

**Skill composition guidelines:**
- Start with simple, focused skills (single responsibility)
- Build higher-level skills by composing simpler ones
- Use semantic search to find existing skills before creating new ones
- Name skills descriptively (what they do, not how they do it)

## Examples

See [examples/](../examples/) for complete skill libraries in working agent applications.
