# Dependency Management Example

Demonstrates runtime dependency management using the `deps` namespace.

## What It Does

The `deps` namespace allows agents to install Python packages at runtime:

```python
# Add a package
deps.add("requests")

# Use it immediately
import requests
response = requests.get("https://example.com")

# List installed deps
deps.list()  # ["requests"]

# Remove a package
deps.remove("requests")
```

## Features

- **Runtime installation**: Install packages without restarting the session
- **Version specifiers**: `deps.add("requests>=2.28")`
- **Persistence**: Dependencies persist across sessions via storage
- **Sync on startup**: `deps.sync()` ensures all stored deps are installed

## Prerequisites

- Python 3.11+

## Setup

```bash
cd examples/deps
uv sync
```

## Run

```bash
uv run python demo.py
```

## How It Works

1. `deps.add(package)` installs via pip and records in storage
2. `deps.list()` returns all tracked dependencies
3. `deps.remove(package)` uninstalls and removes from storage
4. `deps.sync()` ensures all stored deps are installed (useful after session restart)

Dependencies are stored in `{storage}/deps/requirements.txt` when using FileStorage.
