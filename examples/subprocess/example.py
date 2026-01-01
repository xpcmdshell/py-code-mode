#!/usr/bin/env python3
"""SubprocessExecutor example - Jupyter kernel-based isolated execution.

This example demonstrates using SubprocessExecutor which runs code in an
IPython kernel within a subprocess. It provides process isolation without
requiring Docker.

Capabilities:
- TIMEOUT: Yes (via message wait timeout)
- PROCESS_ISOLATION: Yes (code runs in subprocess)
- RESET: Yes (kernel restart clears state)
- NETWORK_ISOLATION: No
- FILESYSTEM_ISOLATION: No

Use SubprocessExecutor when:
- You need process isolation but Docker is unavailable or too heavy
- Development/testing where fast iteration matters
- CI environments without Docker access
- You need kernel restart capability to reset state

Use ContainerExecutor instead when:
- You need filesystem or network isolation
- Running untrusted code in production
- You need reproducible environments across machines
"""

import asyncio
from pathlib import Path

from py_code_mode import FileStorage, Session
from py_code_mode.execution import SubprocessConfig, SubprocessExecutor

# Shared tools and skills directory
HERE = Path(__file__).parent
SHARED = HERE.parent / "shared"


async def main() -> None:
    # Storage for skills and artifacts only
    storage = FileStorage(base_path=SHARED)

    # Configure subprocess executor with tools from config
    config = SubprocessConfig(
        # Tools owned by executor
        tools_path=SHARED / "tools",
        # Python version for venv (defaults to current if not specified)
        python_version="3.11",
        # Execution timeout in seconds
        default_timeout=60.0,
        # Kernel startup timeout
        startup_timeout=30.0,
        # Delete temp venv on close (set False to reuse across runs)
        cleanup_venv_on_close=True,
    )
    executor = SubprocessExecutor(config=config)

    async with Session(storage=storage, executor=executor) as session:
        # Basic execution
        print("Running basic code...")
        result = await session.run("1 + 1")
        print(f"  Result: {result.value}")

        # Variables persist across calls within the same session
        print("\nVariable persistence...")
        await session.run("x = 42")
        result = await session.run("x * 2")
        print(f"  x * 2 = {result.value}")

        # Using tools (if available in shared directory)
        print("\nSearching for tools...")
        result = await session.run("tools.list()")
        print(f"  Available tools: {result.value}")

        # Searching for skills
        print("\nSearching for skills...")
        result = await session.run('skills.search("fetch")')
        print(f"  Found skills: {result.value}")

        # Demonstrate stdout capture
        print("\nStdout capture...")
        result = await session.run('print("Hello from subprocess!")')
        print(f"  Captured stdout: {result.stdout!r}")


if __name__ == "__main__":
    asyncio.run(main())
