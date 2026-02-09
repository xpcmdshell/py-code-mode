#!/usr/bin/env python3
"""DenoSandboxExecutor example - Deno + Pyodide (WASM) sandbox.

Highlights:
- Python code executes inside Pyodide (WASM) within a Deno subprocess.
- In DenoSandboxExecutor, namespace calls are async-first:
  - use `await tools.*`, `await artifacts.*`, `await workflows.*`, `await deps.*`
- Tool execution is host-side: `tools.*` calls are RPC'd back to the host and
  executed by ToolAdapters with host permissions.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from py_code_mode import FileStorage, Session
from py_code_mode.execution import DenoSandboxConfig, DenoSandboxExecutor

HERE = Path(__file__).resolve().parent


async def main() -> None:
    if shutil.which("deno") is None:
        raise SystemExit(
            "deno not found on PATH. Install Deno to run this example: https://deno.com/"
        )

    storage = FileStorage(base_path=HERE / "data")
    deno_dir = HERE / ".deno-cache"
    tools_dir = HERE / "tools"

    config = DenoSandboxConfig(
        tools_path=tools_dir,
        deno_dir=deno_dir,
        # Start with no sandbox network access. (Tools still run host-side.)
        network_profile="none",
        default_timeout=60.0,
        ipc_timeout=120.0,
    )
    executor = DenoSandboxExecutor(config)

    async with Session(storage=storage, executor=executor) as session:
        print("Basic execution (sandboxed Python)...")
        r = await session.run("1 + 1")
        print("  1 + 1 =", r.value)

        print("\nTool call (HOST-SIDE, via RPC)...")
        r = await session.run("(await tools.echo.say(message='hello from host tool')).strip()")
        print("  tools.echo.say ->", r.value)

        print("\nArtifacts (stored via host storage backend)...")
        await session.run("await artifacts.save('hello.txt', 'hi', description='demo')")
        r = await session.run("await artifacts.load('hello.txt')")
        print("  artifacts.load('hello.txt') ->", r.value)

        print("\nWorkflows (stored in host storage; executed in sandbox)...")
        src = "async def run(x: int) -> int:\\n    return x * 2\\n"
        await session.run(f"await workflows.create('double', {src!r}, description='Multiply by 2')")
        r = await session.run("await workflows.invoke(workflow_name='double', x=21)")
        print("  workflows.invoke('double', x=21) ->", r.value)

        print("\nStdout capture...")
        r = await session.run('print("hello from sandbox stdout")\\n"done"')
        print("  value:", r.value)
        print("  stdout:", r.stdout.strip())


if __name__ == "__main__":
    asyncio.run(main())
