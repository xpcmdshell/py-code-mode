"""Python code to inject into kernel for RPC setup.

This module provides the KERNEL_INIT_CODE constant - a Python code string that
is executed in the kernel subprocess to set up the RPC mechanism and proxy
namespaces for tools, skills, artifacts, and deps.

The proxies forward all namespace operations to the host via the stdin channel,
which allows the host to control access to storage and tools while maintaining
process isolation.
"""

from __future__ import annotations


def get_kernel_init_code(ipc_timeout: float = 30.0) -> str:
    """Generate kernel initialization code with configurable timeout.

    Args:
        ipc_timeout: Timeout for RPC calls in seconds. Default: 30.0.

    Returns:
        Python code string to execute in the kernel.
    """
    return f'''# Auto-generated RPC setup for SubprocessExecutor
# This code sets up proxy namespaces that forward calls to the host via stdin channel.

from __future__ import annotations

import json
import threading
import uuid
from typing import Any, NamedTuple

import zmq
from IPython import get_ipython

# Disable colored tracebacks - MCP clients don't render ANSI codes
_ip = get_ipython()
if _ip is not None:
    _ip.colors = "NoColor"

# Threading lock to prevent concurrent RPC corruption
_rpc_lock = threading.Lock()

# Configurable timeout for RPC calls
_RPC_TIMEOUT = {ipc_timeout}


# =============================================================================
# RPC Error Hierarchy (mirrors py_code_mode.errors)
# =============================================================================

class RPCError(Exception):
    """Base for all RPC-related errors."""
    pass


class RPCTransportError(RPCError):
    """RPC plumbing failed (JSON parse, timeout, channel broken, protocol violation)."""
    pass


class NamespaceError(RPCError):
    """Base for namespace operation failures.

    Provides structured context about which namespace, operation, and
    original exception type caused the failure.
    """
    def __init__(
        self,
        namespace: str,
        operation: str,
        message: str,
        original_type: str = "RuntimeError",
    ) -> None:
        self.namespace = namespace
        self.operation = operation
        self.original_type = original_type
        super().__init__(f"{{namespace}}.{{operation}}: [{{original_type}}] {{message}}")


class SkillError(NamespaceError):
    """Error in skills namespace operation."""
    def __init__(
        self, operation: str, message: str, original_type: str = "RuntimeError"
    ) -> None:
        super().__init__("skills", operation, message, original_type)


class ToolError(NamespaceError):
    """Error in tools namespace operation."""
    def __init__(
        self, operation: str, message: str, original_type: str = "RuntimeError"
    ) -> None:
        super().__init__("tools", operation, message, original_type)


class ArtifactError(NamespaceError):
    """Error in artifacts namespace operation."""
    def __init__(
        self, operation: str, message: str, original_type: str = "RuntimeError"
    ) -> None:
        super().__init__("artifacts", operation, message, original_type)


class DepsError(NamespaceError):
    """Error in deps namespace operation."""
    def __init__(
        self, operation: str, message: str, original_type: str = "RuntimeError"
    ) -> None:
        super().__init__("deps", operation, message, original_type)


# =============================================================================
# Lightweight types that mirror host-side types for API compatibility
# =============================================================================

class Tool(NamedTuple):
    """Lightweight Tool for kernel-side use.

    Mirrors py_code_mode.tools.types.Tool structure.
    """
    name: str
    description: str
    tags: tuple[str, ...]


class SyncResult(NamedTuple):
    """Lightweight SyncResult for kernel-side use.

    Mirrors py_code_mode.deps.installer.SyncResult structure.
    """
    installed: tuple[str, ...]
    already_present: tuple[str, ...]
    failed: tuple[str, ...]


class Skill(NamedTuple):
    """Lightweight Skill for kernel-side use.

    Mirrors py_code_mode.skills.skill.PythonSkill structure.
    """
    name: str
    description: str
    params: dict[str, str]


class ArtifactMeta(NamedTuple):
    """Lightweight artifact metadata for kernel-side use."""
    name: str
    path: str
    description: str
    created_at: str


def _rpc_call(method: str, **params) -> Any:
    """Make an RPC call using stdin channel - works during execution.

    This function sends an RPC request to the host via input_request and
    waits for the response via input_reply. The host processes the request
    and returns the result.

    Args:
        method: The RPC method name.
        **params: Method parameters.

    Returns:
        The result from the host.

    Raises:
        RuntimeError: If stdin is disabled, RPC fails, or response is malformed.
        TimeoutError: If the RPC call times out.
    """
    with _rpc_lock:
        kernel = get_ipython().kernel

        if not kernel._allow_stdin:
            raise RuntimeError("RPC requires stdin to be enabled")

        request_id = str(uuid.uuid4())
        request = {{
            "type": "rpc_request",
            "id": request_id,
            "method": method,
            "params": params,
        }}

        # Get parent context for stdin routing
        parent_ident = kernel._get_shell_context_var(kernel._shell_parent_ident)
        parent = kernel.get_parent("shell")

        # Flush stdout/stderr to ensure output ordering
        import sys
        if sys.stdout is not None:
            sys.stdout.flush()
        if sys.stderr is not None:
            sys.stderr.flush()

        # Flush stale stdin replies that might be lingering
        while True:
            try:
                kernel.stdin_socket.recv_multipart(zmq.NOBLOCK)
            except zmq.ZMQError as e:
                if e.errno == zmq.EAGAIN:
                    break
                raise

        # Send RPC request as input_request with JSON in prompt field
        content = {{
            "prompt": json.dumps(request),
            "password": False,
        }}
        kernel.session.send(
            kernel.stdin_socket,
            "input_request",
            content,
            parent,
            ident=parent_ident,
        )

        # Wait for response with timeout
        timeout_seconds = _RPC_TIMEOUT
        elapsed = 0.0
        poll_interval = 0.01

        while elapsed < timeout_seconds:
            try:
                rlist, _, xlist = zmq.select(
                    [kernel.stdin_socket], [], [kernel.stdin_socket], poll_interval
                )
                if rlist or xlist:
                    ident, reply = kernel.session.recv(kernel.stdin_socket)
                    if (ident, reply) != (None, None):
                        break
            except KeyboardInterrupt:
                raise KeyboardInterrupt("RPC call interrupted") from None
            except zmq.ZMQError:
                pass  # Timeout or socket error, continue polling
            elapsed += poll_interval
        else:
            raise TimeoutError(f"RPC call {{method}} timed out after {{timeout_seconds}}s")

        # Parse response
        try:
            response_str = reply["content"]["value"]
            response = json.loads(response_str)
        except Exception as e:
            raise RuntimeError(f"Failed to parse RPC response: {{e}}")

        if response.get("error"):
            err = response["error"]
            if isinstance(err, dict):
                # Validate required keys
                required_keys = {{"namespace", "operation", "message", "type"}}
                if not required_keys.issubset(err.keys()):
                    raise RPCTransportError(f"Malformed RPC error dict (missing keys): {{err!r}}")

                # Structured error from host
                namespace = err["namespace"]
                operation = err["operation"]
                message = err["message"]
                error_type = err["type"]

                # Map namespace to error class
                if namespace == "skills":
                    raise SkillError(operation, message, error_type)
                elif namespace == "tools":
                    raise ToolError(operation, message, error_type)
                elif namespace == "artifacts":
                    raise ArtifactError(operation, message, error_type)
                elif namespace == "deps":
                    raise DepsError(operation, message, error_type)
                else:
                    raise RPCError(f"{{namespace}}.{{operation}}: [{{error_type}}] {{message}}")
            else:
                # Non-dict error is a protocol violation
                raise RPCTransportError(f"Host sent non-dict error (protocol violation): {{err!r}}")

        return response.get("result")


class _ToolRecipeProxy:
    """Proxy for a tool recipe - enables tools.curl.get(...)."""

    def __init__(self, tool_name: str, recipe_name: str):
        self._tool_name = tool_name
        self._recipe_name = recipe_name

    def __call__(self, **kwargs) -> Any:
        """Invoke the recipe with given arguments."""
        # Recipe invocation: name is "tool.recipe"
        return _rpc_call(
            "tools.call",
            name=f"{{self._tool_name}}.{{self._recipe_name}}",
            args=kwargs,
        )


class _ToolProxy:
    """Proxy for a single tool - enables tools.curl(...) and tools.curl.get(...)."""

    def __init__(self, name: str, validated: bool = False):
        self._name = name
        self._validated = validated

    def __call__(self, **kwargs) -> Any:
        """Direct tool invocation (escape hatch)."""
        return _rpc_call("tools.call", name=self._name, args=kwargs)

    def __getattr__(self, recipe_name: str) -> _ToolRecipeProxy:
        """Get a recipe proxy for tools.tool.recipe(...) syntax."""
        if recipe_name.startswith("_"):
            raise AttributeError(recipe_name)
        return _ToolRecipeProxy(self._name, recipe_name)

    def list(self) -> list[dict[str, Any]]:
        """List recipes for this tool."""
        return _rpc_call("tools.list_recipes", name=self._name)


# Cache for valid tool names to avoid repeated RPC calls
_known_tools: set[str] | None = None


def _get_known_tools() -> set[str]:
    """Get set of known tool names, caching result."""
    global _known_tools
    if _known_tools is None:
        result = _rpc_call("tools.list")
        _known_tools = {{t["name"] for t in result}}
    return _known_tools


def _invalidate_tools_cache() -> None:
    """Invalidate the tools cache (called when tools may have changed)."""
    global _known_tools
    _known_tools = None


class ToolsProxy:
    """Proxy for calling host tools.

    Supports both direct invocation and recipe-style access:
    - tools.curl(url="...") - direct invocation
    - tools.curl.get(url="...") - recipe invocation
    - tools.list() - list all tools
    - tools.search("query") - search tools
    """

    def __getattr__(self, name: str) -> _ToolProxy:
        """Return a tool proxy for the named tool.

        Raises AttributeError if the tool is not registered.
        """
        if name.startswith("_"):
            raise AttributeError(name)

        # Validate tool exists
        known = _get_known_tools()
        if name not in known:
            available = ', '.join(sorted(known)[:5])
            raise AttributeError(f"Tool '{{name}}' not found. Available: {{available}}")

        return _ToolProxy(name, validated=True)

    def list(self) -> list[dict[str, Any]]:
        """List all available tools.

        Returns:
            List of dicts with name, description, and tags keys.
        """
        # Return raw dicts (not NamedTuples) so they serialize cleanly through IPython
        return _rpc_call("tools.list")

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search tools by query.

        Returns:
            List of dicts matching the query.
        """
        # Return raw dicts (not NamedTuples) so they serialize cleanly through IPython
        return _rpc_call("tools.search", query=query, limit=limit)


class SkillsProxy:
    """Proxy for invoking host skills.

    Supports:
    - skills.invoke("name", arg=value) - invoke a skill
    - skills.search("query") - search for skills
    - skills.list() - list all skills
    - skills.get("name") - get skill details
    - skills.create("name", source, description) - create a skill
    - skills.skill_name(arg=value) - direct invocation syntax
    """

    def invoke(self, skill_name: str, **kwargs) -> Any:
        """Invoke a skill by name.

        Args:
            skill_name: Name of the skill to invoke.
            **kwargs: Arguments to pass to the skill's run() function.

        Note: Uses skill_name (not name) to avoid collision with skills
        that have a 'name' parameter.
        """
        return _rpc_call("skills.invoke", name=skill_name, args=kwargs)

    def search(self, query: str, limit: int = 5) -> list[Skill]:
        """Search for skills matching query.

        Returns:
            List of Skill objects matching the query.
        """
        result = _rpc_call("skills.search", query=query, limit=limit)
        return [
            Skill(
                name=s["name"],
                description=s.get("description", ""),
                params=s.get("params", {{}}),
            )
            for s in result
        ]

    def list(self) -> list[Skill]:
        """List all available skills.

        Returns:
            List of Skill objects.
        """
        result = _rpc_call("skills.list")
        return [
            Skill(
                name=s["name"],
                description=s.get("description", ""),
                params=s.get("params", {{}}),
            )
            for s in result
        ]

    def get(self, name: str) -> dict[str, Any] | None:
        """Get a skill by name.

        Returns full skill details including source.
        """
        return _rpc_call("skills.get", name=name)

    def create(self, name: str, source: str, description: str = "") -> Skill:
        """Create and save a new skill.

        Returns:
            Skill object for the created skill.
        """
        result = _rpc_call("skills.create", name=name, source=source, description=description)
        return Skill(
            name=result["name"],
            description=result.get("description", ""),
            params=result.get("params", {{}}),
        )

    def delete(self, name: str) -> bool:
        """Delete a skill."""
        return _rpc_call("skills.delete", name=name)

    def __getattr__(self, name: str) -> Any:
        """Allow skills.skill_name(...) syntax."""
        if name.startswith("_"):
            raise AttributeError(name)
        # Return a callable that invokes the skill
        return lambda **kwargs: self.invoke(name, **kwargs)


class ArtifactsProxy:
    """Proxy for accessing host artifacts.

    Supports:
    - artifacts.save("name", data) - save an artifact
    - artifacts.load("name") - load an artifact
    - artifacts.list() - list all artifacts
    - artifacts.delete("name") - delete an artifact
    """

    def load(self, name: str) -> Any:
        """Load an artifact by name."""
        return _rpc_call("artifacts.load", name=name)

    def save(self, name: str, data: Any, description: str = "") -> ArtifactMeta:
        """Save an artifact.

        Returns:
            ArtifactMeta with name, path, description, created_at.
        """
        result = _rpc_call("artifacts.save", name=name, data=data, description=description)
        return ArtifactMeta(
            name=result["name"],
            path=result.get("path", ""),
            description=result.get("description", ""),
            created_at=result.get("created_at", ""),
        )

    def list(self) -> list[ArtifactMeta]:
        """List all artifacts.

        Returns:
            List of ArtifactMeta objects.
        """
        result = _rpc_call("artifacts.list")
        return [
            ArtifactMeta(
                name=a["name"],
                path=a.get("path", ""),
                description=a.get("description", ""),
                created_at=a.get("created_at", ""),
            )
            for a in result
        ]

    def delete(self, name: str) -> None:
        """Delete an artifact."""
        return _rpc_call("artifacts.delete", name=name)

    def exists(self, name: str) -> bool:
        """Check if an artifact exists."""
        return _rpc_call("artifacts.exists", name=name)

    def get(self, name: str) -> ArtifactMeta | None:
        """Get artifact metadata."""
        result = _rpc_call("artifacts.get", name=name)
        if result is None:
            return None
        return ArtifactMeta(
            name=result["name"],
            path=result.get("path", ""),
            description=result.get("description", ""),
            created_at=result.get("created_at", ""),
        )


class DepsProxy:
    """Proxy for managing dependencies.

    Supports:
    - deps.add("package") - add and install a package
    - deps.remove("package") - remove a package
    - deps.list() - list configured packages
    - deps.sync() - install all configured packages

    When allow_runtime_deps=False, add() and remove() raise errors.
    list() and sync() always work.
    """

    def add(self, package: str) -> SyncResult:
        """Add and install a package.

        Returns:
            SyncResult with installed, already_present, and failed tuples.
        """
        result = _rpc_call("deps.add", package=package)
        return SyncResult(
            installed=tuple(result.get("installed", [])),
            already_present=tuple(result.get("already_present", [])),
            failed=tuple(result.get("failed", [])),
        )

    def remove(self, package: str) -> bool:
        """Remove a package from configuration."""
        return _rpc_call("deps.remove", package=package)

    def list(self) -> list[str]:
        """List configured packages."""
        return _rpc_call("deps.list")

    def sync(self) -> SyncResult:
        """Install all configured packages.

        Returns:
            SyncResult with installed, already_present, and failed tuples.
        """
        result = _rpc_call("deps.sync")
        return SyncResult(
            installed=tuple(result.get("installed", [])),
            already_present=tuple(result.get("already_present", [])),
            failed=tuple(result.get("failed", [])),
        )

    def __repr__(self) -> str:
        """String representation showing it's a DepsNamespace."""
        try:
            packages = self.list()
            return f"<DepsNamespace: {{len(packages)}} packages configured>"
        except Exception:
            return "<DepsNamespace: runtime deps via RPC>"


# Inject proxies as globals
tools = ToolsProxy()
skills = SkillsProxy()
artifacts = ArtifactsProxy()
deps = DepsProxy()

print("RPC initialized: tools, skills, artifacts, deps are available (via stdin channel)")
'''


# For backward compatibility, provide the raw code string
KERNEL_INIT_CODE = get_kernel_init_code(ipc_timeout=30.0)
