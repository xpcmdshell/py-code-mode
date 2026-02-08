"""Deno + Pyodide execution backend.

This backend runs Python inside Pyodide (WASM) hosted by a Deno subprocess.
It is intended to provide a sandboxed runtime without requiring Docker.
"""

from py_code_mode.execution.deno_pyodide.config import DenoPyodideConfig
from py_code_mode.execution.deno_pyodide.executor import DenoPyodideExecutor

# Friendly public names. These describe the execution style (sandboxed via Deno
# permissions + Pyodide), not the implementation internals.
DenoSandboxConfig = DenoPyodideConfig
DenoSandboxExecutor = DenoPyodideExecutor

__all__ = [
    "DenoPyodideConfig",
    "DenoPyodideExecutor",
    "DenoSandboxConfig",
    "DenoSandboxExecutor",
]
