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
from typing import TYPE_CHECKING, Any

from py_code_mode.artifacts import ArtifactStore
from py_code_mode.backend import (
    Capability,
    register_backend,
)
from py_code_mode.registry import ToolRegistry
from py_code_mode.semantic import SkillLibrary
from py_code_mode.types import ExecutionResult

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
        source: str,
        description: str = "",
    ) -> dict[str, Any]:
        """Create and save a new Python skill.

        Args:
            name: Skill name (must be valid Python identifier).
            source: Python source code with def run(...) function.
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
            source=source,
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
    _CAPABILITIES = frozenset({Capability.TIMEOUT, Capability.RESET})

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

    async def reset(self) -> None:
        """Reset session state.

        Clears all user-defined variables but preserves tools, skills, artifacts namespaces.
        """
        # Store namespace items we want to preserve
        preserved = {
            "__builtins__": self._namespace.get("__builtins__"),
            "tools": self._namespace.get("tools"),
            "skills": self._namespace.get("skills"),
            "artifacts": self._namespace.get("artifacts"),
        }

        # Clear everything
        self._namespace.clear()

        # Restore preserved items
        for key, value in preserved.items():
            if value is not None:
                self._namespace[key] = value

    async def start(
        self,
        storage_access: StorageAccess | None = None,
    ) -> None:
        """Start executor and configure from storage access.

        Args:
            storage_access: Optional storage access descriptor.
                           If provided, loads tools/skills/artifacts from paths.
                           If None, uses whatever was passed to __init__.
        """
        from py_code_mode.backend import FileStorageAccess, RedisStorageAccess

        if storage_access is None:
            return  # Use __init__ configuration

        if isinstance(storage_access, FileStorageAccess):
            # Load from file paths
            # Always inject tools namespace (empty if no path/directory)
            if storage_access.tools_path and storage_access.tools_path.exists():
                self._registry = await ToolRegistry.from_dir(
                    str(storage_access.tools_path)
                )
            else:
                self._registry = ToolRegistry()
            self._namespace["tools"] = ToolsNamespace(self._registry)

            # Always inject skills namespace
            if storage_access.skills_path:
                from py_code_mode.semantic import create_skill_library
                from py_code_mode.skill_store import FileSkillStore

                # Create directory if it doesn't exist (same as artifacts behavior)
                storage_access.skills_path.mkdir(parents=True, exist_ok=True)
                store = FileSkillStore(storage_access.skills_path)
                self._skill_library = create_skill_library(store=store)
            else:
                # Only use memory store if NO path configured (explicit choice)
                from py_code_mode.semantic import MockEmbedder, SkillLibrary
                from py_code_mode.skill_store import MemorySkillStore

                self._skill_library = SkillLibrary(
                    embedder=MockEmbedder(), store=MemorySkillStore()
                )
            self._namespace["skills"] = SkillsNamespace(self._skill_library, self)

            # Always inject artifacts namespace
            if storage_access.artifacts_path:
                from py_code_mode.artifacts import FileArtifactStore

                storage_access.artifacts_path.mkdir(parents=True, exist_ok=True)
                self._artifact_store = FileArtifactStore(storage_access.artifacts_path)
                self._namespace["artifacts"] = self._artifact_store

        elif isinstance(storage_access, RedisStorageAccess):
            # Load from Redis
            try:
                import redis
            except ImportError as e:
                raise ImportError(
                    "redis required for RedisStorageAccess. Install with: pip install redis"
                ) from e

            client = redis.from_url(storage_access.redis_url)

            # TODO: Load tools from Redis (not yet implemented)

            from py_code_mode.semantic import create_skill_library
            from py_code_mode.skill_store import RedisSkillStore

            skill_store = RedisSkillStore(client, prefix=storage_access.skills_prefix)
            self._skill_library = create_skill_library(store=skill_store)
            self._namespace["skills"] = SkillsNamespace(self._skill_library, self)

            from py_code_mode.redis_artifacts import RedisArtifactStore

            self._artifact_store = RedisArtifactStore(
                client, prefix=storage_access.artifacts_prefix
            )
            self._namespace["artifacts"] = self._artifact_store

    async def __aenter__(self) -> InProcessExecutor:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()


# Register this backend
register_backend("in-process", InProcessExecutor)

# Backward compatibility alias
CodeExecutor = InProcessExecutor
