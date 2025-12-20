"""CLI adapter for wrapping command-line tools."""

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

import yaml

from py_code_mode.adapters.cli_schema import (
    CLICommandBuilder,
    CLIToolDefinition,
    parse_cli_tool_dict,
    parse_cli_tool_yaml,
)
from py_code_mode.errors import ToolCallError, ToolNotFoundError, ToolTimeoutError
from py_code_mode.tool_types import Tool, ToolCallable, ToolParameter

logger = logging.getLogger(__name__)


class CLIAdapter:
    """Adapter for command-line tools.

    Wraps CLI tools and runs them via subprocess, capturing output.

    Usage:
        # Load tools from YAML directory (schema + recipes format)
        adapter = CLIAdapter(tools_path=Path("./tools"))

        # Call a recipe
        result = await adapter.call_tool("grep", "search", {"pattern": "error", "path": "."})

        # Escape hatch - direct call without recipe
        result = await adapter.call_tool("grep", None, {"pattern": "error", "path": "."})
    """

    def __init__(self, tools_path: Path | str | None = None) -> None:
        """Initialize adapter with unified tools.

        Args:
            tools_path: Path to directory containing tool YAML files.
                       If None, creates an empty adapter.
        """
        self._unified_tools: dict[str, CLIToolDefinition] = {}
        self._builders: dict[str, CLICommandBuilder] = {}

        if tools_path is not None:
            self._load_from_path(Path(tools_path))

    def _load_from_path(self, tools_path: Path) -> None:
        """Load tools from a directory path.

        Args:
            tools_path: Path to directory containing tool YAML files.
        """
        if not tools_path.exists():
            logger.warning("Tools path does not exist: %s", tools_path)
            return

        for tool_file in sorted(tools_path.glob("*.yaml")):
            try:
                tool_def = parse_cli_tool_yaml(tool_file)
                self._unified_tools[tool_def.name] = tool_def
                self._builders[tool_def.name] = CLICommandBuilder(tool_def)
            except (OSError, yaml.YAMLError, KeyError, ValueError) as e:
                logger.warning("Failed to load tool file %s: %s", tool_file, e)

    @classmethod
    def from_configs(cls, configs: list[dict[str, Any]]) -> "CLIAdapter":
        """Create adapter from a list of tool configuration dicts.

        Args:
            configs: List of tool config dicts (same format as YAML files).
                    Each must have 'name', 'schema', and 'recipes' keys.

        Returns:
            CLIAdapter with loaded tools.
        """
        adapter = cls()
        for config in configs:
            try:
                tool_def = parse_cli_tool_dict(config)
                adapter._unified_tools[tool_def.name] = tool_def
                adapter._builders[tool_def.name] = CLICommandBuilder(tool_def)
            except (KeyError, ValueError) as e:
                logger.warning("Failed to load tool config '%s': %s", config.get("name", "?"), e)
        return adapter

    def list_tools(self) -> list[Tool]:
        """List tools as Tool objects with callables.

        Returns:
            List of Tool objects with ToolCallable entries.
        """
        tools = []

        for name, tool_def in self._unified_tools.items():
            callables = []

            # Add callables from recipes
            for recipe_name, recipe_spec in tool_def.recipes.items():
                params = []

                # Get parameters from recipe, fall back to schema if not specified
                recipe_params = recipe_spec.get("params", {})

                # If recipe params is empty, inherit from schema
                if not recipe_params:
                    # Build params from schema positional and options
                    schema = tool_def.schema

                    # Add positional parameters
                    for pos_param in schema.get("positional", []):
                        params.append(
                            ToolParameter(
                                name=pos_param["name"],
                                type=pos_param.get("type", "str"),
                                required=pos_param.get("required", False),
                                default=pos_param.get("default"),
                                description=pos_param.get("description", ""),
                            )
                        )

                    # Add option parameters
                    for opt_name, opt_spec in schema.get("options", {}).items():
                        params.append(
                            ToolParameter(
                                name=opt_name,
                                type=opt_spec.get("type", "str"),
                                required=opt_spec.get("required", False),
                                default=opt_spec.get("default"),
                                description=opt_spec.get("description", ""),
                            )
                        )
                else:
                    # Use recipe-specified params
                    for param_name, param_spec in recipe_params.items():
                        params.append(
                            ToolParameter(
                                name=param_name,
                                type=param_spec.get("type", "str"),
                                required=param_spec.get("required", False),
                                default=param_spec.get("default"),
                                description=param_spec.get("description", ""),
                            )
                        )

                callables.append(
                    ToolCallable(
                        name=recipe_name,
                        description=recipe_spec.get("description", ""),
                        parameters=tuple(params),
                    )
                )

            if callables:
                tools.append(
                    Tool(
                        name=name,
                        description=tool_def.description,
                        callables=tuple(callables),
                    )
                )

        return tools

    async def call_tool(
        self,
        name: str,
        callable_name: str | None,
        args: dict[str, Any],
    ) -> Any:
        """Run a CLI tool with specific callable (recipe).

        Args:
            name: Tool name.
            callable_name: Callable name (recipe) or None for escape hatch.
            args: Arguments for the callable.

        Returns:
            Tool output as string.

        Raises:
            ToolNotFoundError: If tool not found.
            ToolCallError: If command fails.
            ToolTimeoutError: If command exceeds timeout.
        """
        if name not in self._unified_tools:
            raise ToolNotFoundError(name, list(self._unified_tools.keys()))

        tool_def = self._unified_tools[name]
        builder = self._builders[name]

        # Build command - either recipe or direct
        try:
            if callable_name is None:
                # Escape hatch - check if there's a default recipe with tool's name
                if name in tool_def.recipes:
                    cmd = builder.build_recipe(name, args)
                else:
                    # True escape hatch - direct invocation without recipe
                    cmd = builder.build(args)
            else:
                # Normal recipe invocation
                cmd = builder.build_recipe(callable_name, args)
        except ValueError as e:
            raise ToolCallError(name, tool_args=args, cause=e) from e

        # Execute command
        try:
            result = await self._run_subprocess(
                cmd,
                timeout=tool_def.timeout,
            )
            return result

        except TimeoutError:
            raise ToolTimeoutError(name, tool_def.timeout)
        except (OSError, RuntimeError) as e:
            raise ToolCallError(name, tool_args=args, cause=e) from e

    async def describe(self, tool_name: str, callable_name: str) -> dict[str, str]:
        """Get parameter descriptions for a callable.

        Args:
            tool_name: Name of the tool.
            callable_name: Name of the callable.

        Returns:
            Dict mapping parameter names to descriptions.

        Raises:
            ToolNotFoundError: If tool or callable not found.
        """
        if tool_name not in self._unified_tools:
            raise ToolNotFoundError(tool_name, list(self._unified_tools.keys()))

        tool_def = self._unified_tools[tool_name]

        if callable_name not in tool_def.recipes:
            available = list(tool_def.recipes.keys())
            raise ValueError(
                f"Callable '{callable_name}' not found in tool '{tool_name}'. "
                f"Available: {available}"
            )

        recipe = tool_def.recipes[callable_name]
        params = recipe.get("params", {})

        descriptions = {}
        for param_name, param_spec in params.items():
            descriptions[param_name] = param_spec.get("description", "")

        return descriptions

    async def _run_subprocess(
        self,
        cmd: list[str],
        timeout: float,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> str:
        """Run a subprocess and return its output."""
        # Merge with current environment if env is provided
        full_env = None
        if env:
            full_env = os.environ.copy()
            full_env.update(env)

        # Use create_subprocess_exec for safe argument passing (no shell injection)
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=full_env,
        )

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except TimeoutError:
            process.kill()
            await process.wait()
            raise

        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else f"Exit code {process.returncode}"
            raise RuntimeError(f"Command failed: {error_msg}")

        return stdout.decode()

    async def close(self) -> None:
        """Clean up (no-op for CLI adapter)."""
        pass
