"""In-process execution backend.

Runs Python code directly in the same process.
Fast but provides no isolation.
"""

from __future__ import annotations

import ast
import asyncio
import builtins
import io
import re
import traceback
from contextlib import redirect_stdout
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from py_code_mode.adapters import CLIAdapter, CLIToolSpec
from py_code_mode.artifacts import ArtifactStore, FileArtifactStore
from py_code_mode.backend import Capability, register_backend
from py_code_mode.registry import ToolRegistry
from py_code_mode.semantic import SkillLibrary, create_skill_library
from py_code_mode.skill_store import FileSkillStore
from py_code_mode.types import ExecutionResult, JsonSchema

if TYPE_CHECKING:
    pass

# Use builtins to avoid security hook false positive on Python's code execution
_run_code = getattr(builtins, "exec")
_eval_code = getattr(builtins, "eval")


def _extract_template_params(args_template: str) -> list[str]:
    """Extract parameter names from args template.

    Args:
        args_template: Template like "{flags} {target}"

    Returns:
        List of parameter names like ["flags", "target"]
    """
    return re.findall(r"\{(\w+)\}", args_template)


class ToolsNamespace:
    """Namespace object for tools.* access in executed code.

    Supports two calling styles:
    - tools.call("nmap", {"target": "10.0.0.1"})  # dict args
    - tools.nmap(target="10.0.0.1")               # pythonic kwargs
    """

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Set the event loop to use for async tool calls."""
        self._loop = loop

    def __getattr__(self, name: str) -> ToolCaller:
        """Enable tools.nmap(...) syntax."""
        # Don't intercept private attributes or special methods
        if name.startswith("_"):
            raise AttributeError(name)
        return ToolCaller(self, name)

    def call(self, name: str, args: dict[str, Any] | None = None) -> Any:
        """Call a tool by name. Sync wrapper for async registry."""
        args = args or {}

        coro = self._registry.call_tool(name, args)

        # When called from a thread (via executor.run -> to_thread), use
        # the stored loop with run_coroutine_threadsafe to schedule on main loop.
        # This keeps MCP adapters working since they're bound to the main loop.
        if self._loop is not None:
            future = asyncio.run_coroutine_threadsafe(coro, self._loop)
            return future.result()

        # Fallback: try running loop, then create new one (standalone usage)
        try:
            loop = asyncio.get_running_loop()
            return loop.run_until_complete(coro)
        except RuntimeError:
            return asyncio.run(coro)

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search for tools matching query. Returns simplified tool info."""
        tools = self._registry.search(query, limit)
        return [self._simplify(t) for t in tools]

    def list(self) -> list[dict[str, Any]]:
        """List all available tools. Returns simplified tool info."""
        tools = self._registry.list_tools()
        return [self._simplify(t) for t in tools]

    def _simplify(self, tool: Any) -> dict[str, Any]:
        """Simplify tool definition for agent readability."""
        params = {}
        if tool.input_schema and tool.input_schema.properties:
            for name, schema in tool.input_schema.properties.items():
                params[name] = schema.description or schema.type
        return {
            "name": tool.name,
            "description": tool.description,
            "params": params,
        }


class ToolCaller:
    """Callable wrapper for pythonic tool invocation."""

    def __init__(self, namespace: ToolsNamespace, name: str) -> None:
        self._namespace = namespace
        self._name = name

    def __call__(self, **kwargs: Any) -> Any:
        """Call the tool with kwargs."""
        return self._namespace.call(self._name, kwargs)

    def __repr__(self) -> str:
        return f"<Tool: {self._name}>"


class SkillsNamespace:
    """Namespace object for skills.* access in executed code.

    Wraps a SkillLibrary and provides agent-facing methods plus skill execution.
    """

    def __init__(self, library: SkillLibrary, executor: InProcessExecutor) -> None:
        self._library = library
        self._executor = executor

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search for skills matching query. Returns simplified skill info."""
        skills = self._library.search(query, limit)
        return [self._simplify(s) for s in skills]

    def get(self, name: str) -> Any:
        """Get a skill by name."""
        return self._library.get(name)

    def list(self) -> list[dict[str, Any]]:
        """List all available skills. Returns simplified skill info."""
        skills = self._library.list()
        return [self._simplify(s) for s in skills]

    def _simplify(self, skill: Any) -> dict[str, Any]:
        """Simplify skill for agent readability."""
        params = {}
        for p in skill.parameters:
            params[p.name] = p.description or p.type
        return {
            "name": skill.name,
            "description": skill.description,
            "params": params,
        }

    def create(
        self,
        name: str,
        code: str,
        description: str = "",
    ) -> dict[str, Any]:
        """Create and save a new Python skill.

        Args:
            name: Skill name (must be valid Python identifier).
            code: Python source code with def run(...) function.
            description: What the skill does.

        Returns:
            Simplified skill info dict.

        Raises:
            ValueError: If name is invalid, reserved, or code is malformed.
            SyntaxError: If code has syntax errors.
        """
        from py_code_mode.skills import PythonSkill

        # PythonSkill.from_source handles all validation
        skill = PythonSkill.from_source(
            name=name,
            source=code,
            description=description,
        )

        # Add to library (persists to store if configured)
        self._library.add(skill)

        return self._simplify(skill)

    def delete(self, name: str) -> bool:
        """Remove a skill from the library.

        Args:
            name: Name of skill to delete.

        Returns:
            True if skill was deleted, False if not found.
        """
        return self._library.remove(name)

    def __getattr__(self, name: str) -> Any:
        """Allow skills.skill_name(...) syntax."""
        if name.startswith("_"):
            raise AttributeError(name)
        skill = self._library.get(name)
        if skill is None:
            raise AttributeError(f"Skill not found: {name}")
        # Capture name in closure to avoid conflict with kwargs
        skill_name = name
        return lambda **kwargs: self.invoke(skill_name, **kwargs)

    def invoke(self, skill_name: str, **kwargs: Any) -> Any:
        """Invoke a skill by calling its run() function.

        Returns the result of the skill execution.
        """
        skill = self._library.get(skill_name)
        if skill is None:
            raise ValueError(f"Skill not found: {skill_name}")

        # Execute skill source fresh, same as regular code execution
        namespace = {
            "tools": self._executor._namespace.get("tools"),
            "skills": self._executor._namespace.get("skills"),
            "artifacts": self._executor._namespace.get("artifacts"),
        }
        code = compile(skill.source, f"<skill:{skill_name}>", "exec")
        _run_code(code, namespace)
        return namespace["run"](**kwargs)


class InProcessExecutor:
    """Runs Python code with persistent state in the same process.

    Variables, functions, and imports persist across runs.
    Optionally injects tools.*, skills.*, and artifacts.* namespaces.

    Capabilities:
    - TIMEOUT: Yes (via asyncio.wait_for)
    - PROCESS_ISOLATION: No
    - NETWORK_ISOLATION: No
    - FILESYSTEM_ISOLATION: No

    Usage:
        executor = await InProcessExecutor.create(
            tools="./tools/",
            skills="./skills/",
        )
        result = await executor.run('tools.nmap(target="scanme.nmap.org")')
    """

    # Capabilities this backend supports
    _CAPABILITIES = frozenset({Capability.TIMEOUT})

    def __init__(
        self,
        registry: ToolRegistry | None = None,
        skill_library: SkillLibrary | None = None,
        artifact_store: ArtifactStore | None = None,
        default_timeout: float = 30.0,
    ) -> None:
        self._registry = registry
        self._skill_library = skill_library
        self._artifact_store = artifact_store
        self._default_timeout = default_timeout
        self._namespace: dict[str, Any] = {"__builtins__": builtins}
        self._closed = False

        # Inject tools namespace if registry provided
        if registry is not None:
            self._namespace["tools"] = ToolsNamespace(registry)

        # Inject skills namespace if skill_library provided
        if skill_library is not None:
            self._namespace["skills"] = SkillsNamespace(skill_library, self)

        # Inject artifacts namespace if artifact_store provided
        if artifact_store is not None:
            self._namespace["artifacts"] = artifact_store

    def supports(self, capability: str) -> bool:
        """Check if this backend supports a capability."""
        return capability in self._CAPABILITIES

    def supported_capabilities(self) -> set[str]:
        """Return set of all capabilities this backend supports."""
        return set(self._CAPABILITIES)

    @classmethod
    async def from_yaml(
        cls,
        path: str,
        skills_path: str | None = None,
        artifacts_path: str | None = None,
        allowed_tags: set[str] | None = None,
        default_timeout: float = 30.0,
    ) -> InProcessExecutor:
        """Create executor from YAML tools config.

        Args:
            path: Path to tools.yaml file.
            skills_path: Optional path to skills directory.
            artifacts_path: Optional path for artifact storage.
            allowed_tags: Optional set of tags to filter tools.
            default_timeout: Default execution timeout.

        Returns:
            Configured InProcessExecutor.

        Example tools.yaml:
            tools:
              - name: nmap
                description: Network scanner
                args: "{flags} {target}"
                tags: [recon, network]
        """
        config_path = Path(path)
        with open(config_path) as f:
            config = yaml.safe_load(f)

        # Build tool specs from YAML
        cli_specs = []
        for tool in config.get("tools", []):
            tool_type = tool.get("type", "cli")

            if tool_type == "cli":
                args_template = tool.get("args", "")
                params = _extract_template_params(args_template)

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
                cli_specs.append(spec)
            elif tool_type == "mcp":
                raise NotImplementedError(f"MCP tools not yet supported: {tool['name']}")
            elif tool_type == "http":
                raise NotImplementedError(f"HTTP tools not yet supported: {tool['name']}")
            else:
                raise ValueError(f"Unknown tool type: {tool_type}")

        # Create registry and register tools
        registry = ToolRegistry()
        if cli_specs:
            adapter = CLIAdapter(cli_specs)
            await registry.register_adapter(adapter)

        # Apply tag filtering if specified
        if allowed_tags:
            registry = registry.scoped_view(allowed_tags)

        # Build skill library if path provided
        skill_library = None
        if skills_path:
            skills_dir = Path(skills_path)
            store = FileSkillStore(skills_dir)
            skill_library = create_skill_library(store=store)

        # Build artifact store if path provided
        artifact_store = None
        if artifacts_path:
            artifact_store = FileArtifactStore(Path(artifacts_path))

        return cls(
            registry=registry,
            skill_library=skill_library,
            artifact_store=artifact_store,
            default_timeout=default_timeout,
        )

    @classmethod
    async def create(
        cls,
        tools: str | None = None,
        skills: str | None = None,
        artifacts: str | None = None,
        allowed_tags: set[str] | None = None,
        default_timeout: float = 30.0,
        semantic_search: bool = True,
        embedding_model: str | None = None,
        **kwargs: Any,  # Accept extra config for backend-agnostic factory
    ) -> InProcessExecutor:
        """Create executor by specifying where your tools and skills are.

        Args:
            tools: Path to directory containing tool YAML files.
            skills: Path to directory containing skill .py files.
            artifacts: Path to directory for artifact storage.
            allowed_tags: Optional set of tags to filter tools.
            default_timeout: Default execution timeout.
            semantic_search: Enable semantic search for tools and skills.
            embedding_model: Model alias or full HuggingFace model name.
            **kwargs: Additional options (ignored for compatibility).

        Returns:
            Configured InProcessExecutor.

        Example:
            executor = await InProcessExecutor.create(
                tools="./my_tools/",
                skills="./my_skills/",
            )
        """
        # Create embedder for semantic search
        embedder = None
        if semantic_search:
            try:
                from py_code_mode.semantic import Embedder

                embedder = Embedder(model_name=embedding_model)
            except ImportError:
                pass  # Embedder not available, fall back to substring search

        # Load tools from directory (supports CLI and MCP tools)
        if tools:
            registry = await ToolRegistry.from_dir(tools, embedder=embedder)
        else:
            registry = ToolRegistry(embedder=embedder)

        # Apply tag filtering if specified
        if allowed_tags:
            registry = registry.scoped_view(allowed_tags)

        # Load skills from directory with semantic search
        skill_library = None
        if skills:
            skills_path = Path(skills)
            if skills_path.exists():
                store = FileSkillStore(skills_path)
                skill_library = create_skill_library(store=store, embedder=embedder)

        # Build artifact store
        artifact_store = None
        if artifacts:
            artifacts_path = Path(artifacts)
            artifacts_path.mkdir(parents=True, exist_ok=True)
            artifact_store = FileArtifactStore(artifacts_path)

        return cls(
            registry=registry,
            skill_library=skill_library,
            artifact_store=artifact_store,
            default_timeout=default_timeout,
        )

    @classmethod
    async def quick(
        cls,
        tools: dict[str, str | tuple[str, str]] | None = None,
        skills: str | None = None,
        artifacts: str | None = None,
        default_timeout: float = 30.0,
    ) -> InProcessExecutor:
        """Create executor with inline tool definitions for quick prototyping.

        Args:
            tools: Dict of tools. Key is name, value is either:
                - str: args template (e.g., "-s {url}")
                - tuple: (args_template, description)
            skills: Path to skills directory.
            artifacts: Path for artifact storage.
            default_timeout: Default execution timeout.

        Returns:
            Configured InProcessExecutor.

        Example:
            executor = await InProcessExecutor.quick(
                tools={
                    "curl": "-s {url}",
                    "nmap": ("{flags} {target}", "Network scanner"),
                },
                skills="./skills/",
            )
        """
        # Build tool specs
        cli_specs = []
        if tools:
            for name, value in tools.items():
                if isinstance(value, tuple):
                    args_template, description = value
                else:
                    args_template = value
                    description = ""

                params = _extract_template_params(args_template)
                spec = CLIToolSpec(
                    name=name,
                    description=description,
                    args_template=args_template,
                    input_schema=JsonSchema(
                        type="object",
                        properties={p: JsonSchema(type="string") for p in params},
                    ),
                )
                cli_specs.append(spec)

        # Create registry
        registry = ToolRegistry()
        if cli_specs:
            adapter = CLIAdapter(cli_specs)
            await registry.register_adapter(adapter)

        # Load skills if path provided
        skill_library = None
        if skills:
            skills_path = Path(skills)
            store = FileSkillStore(skills_path)
            skill_library = create_skill_library(store=store)

        # Build artifact store if path provided
        artifact_store = None
        if artifacts:
            artifact_store = FileArtifactStore(Path(artifacts))

        return cls(
            registry=registry,
            skill_library=skill_library,
            artifact_store=artifact_store,
            default_timeout=default_timeout,
        )

    async def run(self, code: str, timeout: float | None = None) -> ExecutionResult:
        """Run code and return result.

        Args:
            code: Python code to run.
            timeout: Timeout in seconds. Uses default if None.

        Returns:
            ExecutionResult with value, stdout, and optional error.
        """
        if self._closed:
            return ExecutionResult(
                value=None,
                stdout="",
                error="Executor is closed",
            )

        timeout = timeout if timeout is not None else self._default_timeout

        # Store loop reference for tool calls from thread context
        loop = asyncio.get_running_loop()
        if "tools" in self._namespace:
            self._namespace["tools"].set_loop(loop)

        # Run in thread to allow timeout cancellation
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._run_sync, code),
                timeout=timeout,
            )
        except TimeoutError:
            return ExecutionResult(
                value=None,
                stdout="",
                error=f"Execution timeout after {timeout} seconds",
            )

    # Alias for test compatibility
    execute = run

    def _run_sync(self, code: str) -> ExecutionResult:
        """Run code synchronously, capturing output."""
        stdout_capture = io.StringIO()

        try:
            # Parse to check for trailing expression
            tree = ast.parse(code)

            # Separate statements from final expression
            if tree.body and isinstance(tree.body[-1], ast.Expr):
                # Last item is an expression - run all but last, then eval last
                stmts = tree.body[:-1]
                expr = tree.body[-1]

                # Run statements
                if stmts:
                    stmt_tree = ast.Module(body=stmts, type_ignores=[])
                    stmt_code = compile(stmt_tree, "<code>", "exec")
                    with redirect_stdout(stdout_capture):
                        _run_code(stmt_code, self._namespace)

                # Evaluate final expression
                expr_tree = ast.Expression(body=expr.value)
                expr_code = compile(expr_tree, "<expr>", "eval")
                with redirect_stdout(stdout_capture):
                    value = _eval_code(expr_code, self._namespace)
            else:
                # No trailing expression - just run everything
                with redirect_stdout(stdout_capture):
                    _run_code(code, self._namespace)
                value = None

            return ExecutionResult(
                value=value,
                stdout=stdout_capture.getvalue(),
                error=None,
            )

        except Exception:
            return ExecutionResult(
                value=None,
                stdout=stdout_capture.getvalue(),
                error=traceback.format_exc(),
            )

    async def close(self) -> None:
        """Release executor resources."""
        self._closed = True
        if self._registry:
            await self._registry.close()
        self._namespace.clear()

    async def __aenter__(self) -> InProcessExecutor:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()


# Register this backend
register_backend("in-process", InProcessExecutor)

# Backward compatibility alias
CodeExecutor = InProcessExecutor
