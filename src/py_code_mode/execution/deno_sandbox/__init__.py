"""Deno sandbox execution backend.

This backend runs Python inside Pyodide (WASM) hosted by a Deno subprocess.
It is intended to provide a sandboxed runtime without requiring Docker.
"""

from py_code_mode.execution.deno_sandbox.config import DenoSandboxConfig
from py_code_mode.execution.deno_sandbox.executor import DenoSandboxExecutor

__all__ = ["DenoSandboxConfig", "DenoSandboxExecutor"]
