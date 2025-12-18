"""CLI adapter for wrapping command-line tools."""

import asyncio
import json
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from py_code_mode.errors import ToolCallError, ToolNotFoundError, ToolTimeoutError
from py_code_mode.types import JsonSchema, ToolDefinition


@dataclass
class CLIToolSpec:
    """Specification for a CLI tool.

    Defines how to invoke a command-line tool and parse its output.
    """

    name: str
    description: str = ""  # Auto-generated if empty
    command: str | None = None  # Defaults to name if not specified
    args_template: str = ""  # Template with {arg_name} placeholders
    input_schema: JsonSchema = field(default_factory=lambda: JsonSchema(type="object"))
    output_schema: JsonSchema | None = None
    tags: frozenset[str] = field(default_factory=frozenset)
    timeout_seconds: float = 60.0
    parse_json: bool = False  # Whether to parse stdout as JSON
    working_dir: str | None = None
    env: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Apply defaults after initialization."""
        if self.command is None:
            object.__setattr__(self, "command", self.name)
        if not self.description:
            object.__setattr__(self, "description", f"Run {self.name} command")


class CLIAdapter:
    """Adapter for command-line tools.

    Wraps CLI tools and runs them via subprocess, capturing output.

    Usage:
        specs = [
            CLIToolSpec(
                name="grep",
                description="Search for pattern in files",
                command="grep",
                args_template="-r {pattern} {path}",
                input_schema=JsonSchema(
                    type="object",
                    properties={
                        "pattern": JsonSchema(type="string", description="Search pattern"),
                        "path": JsonSchema(type="string", description="Path to search"),
                    },
                    required=["pattern", "path"],
                ),
                tags=frozenset({"search", "text"}),
            ),
        ]
        adapter = CLIAdapter(specs)
        result = await adapter.call_tool("grep", {"pattern": "error", "path": "."})
    """

    def __init__(self, specs: list[CLIToolSpec]) -> None:
        """Initialize with tool specifications.

        Args:
            specs: List of CLI tool specifications.
        """
        self._specs: dict[str, CLIToolSpec] = {spec.name: spec for spec in specs}
        self._tools: dict[str, ToolDefinition] = {}

        for spec in specs:
            self._tools[spec.name] = ToolDefinition(
                name=spec.name,
                description=spec.description,
                input_schema=spec.input_schema,
                output_schema=spec.output_schema,
                tags=spec.tags,
                timeout_seconds=spec.timeout_seconds,
            )

    @classmethod
    def from_dir(cls, path: str) -> "CLIAdapter":
        """Load CLI tools from a directory of YAML files.

        Each *.yaml file defines one tool:
            # nmap.yaml
            name: nmap
            args: "{flags} {target}"
            description: Network scanner
            tags: [recon, network]
            timeout: 300

        Args:
            path: Path to directory containing tool YAML files.

        Returns:
            CLIAdapter with loaded tools.
        """
        specs = []
        tools_path = Path(path)

        if not tools_path.exists():
            return cls([])

        for tool_file in sorted(tools_path.glob("*.yaml")):
            with open(tool_file) as f:
                tool = yaml.safe_load(f)
                if not tool or not tool.get("name"):
                    continue

            # Skip non-CLI tools (mcp, http, etc.)
            tool_type = tool.get("type", "cli")
            if tool_type != "cli":
                continue

            args_template = tool.get("args", "")
            params = re.findall(r"\{(\w+)\}", args_template)

            spec = CLIToolSpec(
                name=tool["name"],
                description=tool.get("description", ""),
                command=tool.get("command"),
                args_template=args_template,
                input_schema=JsonSchema(
                    type="object",
                    properties={p: JsonSchema(type="string") for p in params},
                ),
                tags=frozenset(tool.get("tags", [])),
                timeout_seconds=tool.get("timeout", 60.0),
            )
            specs.append(spec)

        return cls(specs)

    async def list_tools(self) -> list[ToolDefinition]:
        """List all CLI tools."""
        return list(self._tools.values())

    async def call_tool(self, name: str, args: dict[str, Any]) -> Any:
        """Run a CLI tool.

        Args:
            name: Tool name.
            args: Arguments to pass to the tool.

        Returns:
            Tool output as string (or parsed JSON if parse_json=True).

        Raises:
            ToolNotFoundError: If tool not found.
            ToolCallError: If command fails.
            ToolTimeoutError: If command exceeds timeout.
        """
        if name not in self._specs:
            raise ToolNotFoundError(name, list(self._specs.keys()))

        spec = self._specs[name]

        # Build command
        cmd = self._build_command(spec, args)

        try:
            result = await self._run_subprocess(
                cmd,
                timeout=spec.timeout_seconds,
                cwd=spec.working_dir,
                env=spec.env if spec.env else None,
            )

            if spec.parse_json:
                try:
                    return json.loads(result)
                except json.JSONDecodeError as e:
                    raise ToolCallError(
                        name, tool_args=args, cause=ValueError(f"Invalid JSON output: {e}")
                    ) from e

            return result

        except TimeoutError:
            raise ToolTimeoutError(name, spec.timeout_seconds)
        except Exception as e:
            if isinstance(e, (ToolCallError, ToolTimeoutError)):
                raise
            raise ToolCallError(name, tool_args=args, cause=e) from e

    def _build_command(self, spec: CLIToolSpec, args: dict[str, Any]) -> list[str]:
        """Build command list from spec and arguments."""
        # Start with base command
        cmd_parts = shlex.split(spec.command)

        if spec.args_template:
            # Substitute arguments into template
            try:
                formatted = spec.args_template.format(**args)
                cmd_parts.extend(shlex.split(formatted))
            except KeyError as e:
                raise ValueError(f"Missing required argument: {e}")
        else:
            # No template - pass args as --key=value or positional
            for key, value in args.items():
                if isinstance(value, bool):
                    if value:
                        cmd_parts.append(f"--{key}")
                elif isinstance(value, list):
                    for item in value:
                        cmd_parts.append(str(item))
                else:
                    cmd_parts.append(f"--{key}={value}")

        return cmd_parts

    async def _run_subprocess(
        self,
        cmd: list[str],
        timeout: float,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> str:
        """Run a subprocess and return its output."""
        import os

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
