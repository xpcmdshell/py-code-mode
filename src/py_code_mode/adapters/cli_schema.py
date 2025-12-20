"""CLI schema parsing and command building for unified tool interface."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass
class CLIToolDefinition:
    """Definition of a CLI tool with schema and recipes."""

    name: str
    command: str
    schema: dict[str, Any]
    recipes: dict[str, Any]
    timeout: float = 60.0
    description: str = ""


def parse_cli_tool_dict(data: dict[str, Any]) -> CLIToolDefinition:
    """Parse a CLI tool config dict into CLIToolDefinition.

    Args:
        data: Tool configuration dict (same format as YAML data).

    Returns:
        CLIToolDefinition with parsed schema and recipes.
    """
    name = data["name"]
    command = data.get("command", name)
    schema = data.get("schema", {})
    timeout = data.get("timeout", 60.0)
    description = data.get("description", "")

    recipes = data.get("recipes", {})

    if not recipes:
        raise ValueError(
            f"Tool '{name}' has no recipes defined. "
            "Old-format YAML with 'args' template is no longer supported. "
            "Use schema + recipes format."
        )

    return CLIToolDefinition(
        name=name,
        command=command,
        schema=schema,
        recipes=recipes,
        timeout=timeout,
        description=description,
    )


def parse_cli_tool_yaml(path: Path) -> CLIToolDefinition:
    """Parse a CLI tool YAML file into CLIToolDefinition.

    Args:
        path: Path to YAML file.

    Returns:
        CLIToolDefinition with parsed schema and recipes.
    """
    with open(path) as f:
        data = yaml.safe_load(f)

    return parse_cli_tool_dict(data)


class CLICommandBuilder:
    """Build command arrays from CLI tool schema + arguments.

    Handles:
    - Boolean flags (true -> include flag, false -> omit)
    - String options (-p value)
    - Array options (--exclude val1 --exclude val2)
    - Positional arguments
    - Recipe presets and defaults
    """

    def __init__(self, tool_def: CLIToolDefinition) -> None:
        self.tool_def = tool_def
        self.schema = tool_def.schema

    def build(self, args: dict[str, Any]) -> list[str]:
        """Build command array from arguments.

        Args:
            args: Arguments dictionary.

        Returns:
            Command array ready for subprocess.

        Raises:
            ValueError: If required parameters are missing.
        """
        cmd = [self.tool_def.command]

        # Validate required positional arguments
        positional = self.schema.get("positional", [])
        for pos in positional:
            if pos.get("required", False) and pos["name"] not in args:
                raise ValueError(f"Required parameter '{pos['name']}' is missing")

        # Add options first
        options = self.schema.get("options", {})
        for opt_name, opt_spec in options.items():
            if opt_name not in args:
                continue

            value = args[opt_name]
            opt_type = opt_spec.get("type", "string")

            # Determine flag format: use short if specified, otherwise long form
            short = opt_spec.get("short")
            flag = f"-{short}" if short else f"--{opt_name}"

            if opt_type == "boolean":
                # Only add flag if true
                if value:
                    cmd.append(flag)
            elif opt_type == "array":
                # Repeat flag for each array element
                for item in value:
                    cmd.extend([flag, str(item)])
            elif opt_type == "integer":
                cmd.extend([flag, str(value)])
            else:  # string
                cmd.extend([flag, str(value)])

        # Add positional arguments last
        for pos in positional:
            if pos["name"] in args:
                cmd.append(str(args[pos["name"]]))

        return cmd

    def build_recipe(self, recipe_name: str, args: dict[str, Any]) -> list[str]:
        """Build command from a recipe.

        Applies preset values first, then user args (which override presets).
        Applies recipe parameter defaults for missing args.

        Args:
            recipe_name: Name of the recipe to use.
            args: User-provided arguments (override presets).

        Returns:
            Command array.

        Raises:
            ValueError: If recipe not found or required params missing.
        """
        if recipe_name not in self.tool_def.recipes:
            raise ValueError(f"Recipe '{recipe_name}' not found")

        recipe = self.tool_def.recipes[recipe_name]

        # Start with preset values
        merged_args = dict(recipe.get("preset", {}))

        # Apply recipe parameter defaults for missing args
        recipe_params = recipe.get("params", {})
        for param_name, param_spec in recipe_params.items():
            if param_name not in merged_args and param_name not in args:
                if "default" in param_spec:
                    merged_args[param_name] = param_spec["default"]

        # User args override everything
        merged_args.update(args)

        return self.build(merged_args)
