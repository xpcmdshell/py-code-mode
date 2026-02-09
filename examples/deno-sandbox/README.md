# DenoSandboxExecutor Example

Demonstrates sandboxed Python execution using `DenoSandboxExecutor` (Deno + Pyodide).

## What Is DenoSandboxExecutor?

`DenoSandboxExecutor` runs Python in **Pyodide (WASM)** inside a **Deno** subprocess and uses Deno permissions to sandbox the Python runtime.

Important: **tools execute host-side**. Any `tools.*` call is sent over RPC to the host Python process and executed by ToolAdapters with host permissions.

## Prerequisites

- Python 3.12+
- Deno installed and on PATH

## Setup

```bash
cd examples/deno-sandbox
uv sync
```

## Run

```bash
uv run python example.py
```

## Notes

- In `DenoSandboxExecutor`, namespace calls are async-first: use `await tools.*`, `await artifacts.*`, `await workflows.*`, `await deps.*`.
- `DenoSandboxConfig.network_profile` controls *sandbox* network access:
  - `none`: deny sandbox network (no runtime `micropip` installs)
  - `deps-only`: allow typical PyPI/CDN hosts for `micropip`
  - `full`: allow all sandbox network

