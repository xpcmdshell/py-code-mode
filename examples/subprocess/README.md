# SubprocessExecutor Example

Demonstrates Jupyter kernel-based isolated execution using `SubprocessExecutor`.

## What is SubprocessExecutor?

SubprocessExecutor runs code in an IPython kernel within a subprocess. It provides process isolation without requiring Docker.

**Capabilities:**
| Feature | Supported |
|---------|-----------|
| Timeout | Yes (via message wait timeout) |
| Process Isolation | Yes (code runs in subprocess) |
| Reset | Yes (kernel restart clears state) |
| Network Isolation | No |
| Filesystem Isolation | No |

## When to Use It

**Choose SubprocessExecutor when:**
- You need process isolation but Docker is unavailable or too heavy
- Development/testing where fast iteration matters
- CI environments without Docker access
- You need kernel restart capability to reset state

**Choose ContainerExecutor instead when:**
- You need filesystem or network isolation
- Running untrusted code in production
- You need reproducible environments across machines

**Choose InProcessExecutor when:**
- You trust the code completely
- Maximum performance is required
- You want simplest setup

## Prerequisites

- Python 3.11+
- `ipykernel` package (installed via dependencies)

## Setup

```bash
cd examples/subprocess
uv sync
```

## Run

```bash
uv run python example.py
```

## How It Works

```python
from pathlib import Path
from py_code_mode import FileStorage, Session
from py_code_mode.execution import SubprocessConfig, SubprocessExecutor

# Storage for skills and artifacts only
storage = FileStorage(base_path=Path("./data"))

# Executor with tools from config
config = SubprocessConfig(
    tools_path=Path("./tools"),  # Tools owned by executor
    python_version="3.11",
    default_timeout=60.0,
    startup_timeout=30.0,
    cleanup_venv_on_close=True,
)
executor = SubprocessExecutor(config=config)

async with Session(storage=storage, executor=executor) as session:
    result = await session.run("1 + 1")
    print(result.value)  # 2
```

The executor:
1. Creates a temporary virtualenv (or reuses existing)
2. Starts an IPython kernel in that environment
3. Executes code via Jupyter messaging protocol
4. Captures stdout, stderr, and return values
5. Optionally cleans up on session close
