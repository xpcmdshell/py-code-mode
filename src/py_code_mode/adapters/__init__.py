"""Tool adapters for py-code-mode.

Adapters connect to different tool sources: CLI, MCP servers, HTTP APIs, etc.
"""

from py_code_mode.adapters.base import ToolAdapter
from py_code_mode.adapters.cli import CLIAdapter, CLIToolSpec

__all__ = ["ToolAdapter", "CLIAdapter", "CLIToolSpec"]
