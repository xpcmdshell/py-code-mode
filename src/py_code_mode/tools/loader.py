"""Tool loading utilities.

Provides functions to load tools from filesystem paths.
"""

from __future__ import annotations

from pathlib import Path

from py_code_mode.tools.registry import ToolRegistry


async def load_tools_from_path(path: Path) -> ToolRegistry:
    """Load all tool YAML files from path into a registry.

    This function wraps ToolRegistry.from_dir() and provides the
    executor-side entry point for tool loading from config.tools_path.

    Supports both CLI and MCP tools:
    - CLI tools: YAML files with type: cli (or no type, defaults to cli)
    - MCP tools: YAML files with type: mcp and transport configuration

    Args:
        path: Path to directory containing tool YAML files.

    Returns:
        ToolRegistry with all tools loaded from the directory.

    Example:
        registry = await load_tools_from_path(Path("./tools"))
        tools = registry.list_tools()
    """
    return await ToolRegistry.from_dir(str(path))
