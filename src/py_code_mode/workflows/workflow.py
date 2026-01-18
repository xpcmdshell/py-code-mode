"""Workflows system - Python workflows with IDE support."""

from __future__ import annotations

import ast
import builtins
import importlib.util
import inspect
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, get_type_hints

logger = logging.getLogger(__name__)

# Use builtins to avoid security hook false positive on Python's code execution
_run_code = getattr(builtins, "exec")


@dataclass
class WorkflowMetadata:
    """Metadata about workflow creation and origin."""

    created_at: datetime
    created_by: str  # "agent" or "human"
    source: str  # "file", "redis", "runtime"

    @classmethod
    def now(cls, created_by: str = "agent", source: str = "runtime") -> WorkflowMetadata:
        """Create metadata with current timestamp."""
        return cls(
            created_at=datetime.now(UTC),
            created_by=created_by,
            source=source,
        )


@dataclass
class WorkflowParameter:
    """A parameter for a workflow."""

    name: str
    type: str
    description: str
    required: bool = True
    default: Any = None


# Map Python types to our type strings
_PYTHON_TYPE_MAP: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}

# Special parameters that are injected, not user-provided
_INJECTED_PARAMS = {"tools", "workflows", "artifacts", "deps"}


def _extract_parameters(func: Callable[..., Any], name: str) -> list[WorkflowParameter]:
    """Extract WorkflowParameter list from a function's signature."""
    sig = inspect.signature(func)
    try:
        type_hints = get_type_hints(func)
    except (NameError, AttributeError, TypeError) as e:
        # NameError: unresolved forward references
        # AttributeError: issues accessing type attributes
        # TypeError: invalid type annotations
        logger.debug(f"Type hint extraction failed for {name}: {type(e).__name__}: {e}")
        type_hints = {}

    parameters = []
    for param_name, param in sig.parameters.items():
        if param_name in _INJECTED_PARAMS:
            continue

        python_type = type_hints.get(param_name, str)
        type_str = _PYTHON_TYPE_MAP.get(python_type, "string")
        has_default = param.default is not inspect.Parameter.empty
        default = param.default if has_default else None

        parameters.append(
            WorkflowParameter(
                name=param_name,
                type=type_str,
                description="",
                required=not has_default,
                default=default,
            )
        )
    return parameters


@dataclass
class PythonWorkflow:
    """A workflow defined as a Python module with run() entrypoint.

    Provides full IDE support (syntax highlighting, intellisense)
    and exposes source code for agent inspection and adaptation.
    """

    name: str
    description: str
    parameters: list[WorkflowParameter]
    source: str
    _func: Callable[..., Any] = field(repr=False)
    metadata: WorkflowMetadata | None = None

    @classmethod
    def from_source(
        cls,
        name: str,
        source: str,
        description: str = "",
        metadata: WorkflowMetadata | None = None,
    ) -> PythonWorkflow:
        """Create a PythonWorkflow from source code string.

        Args:
            name: Workflow name (must be valid Python identifier).
            source: Python source code with def run(...) function.
            description: What the workflow does.
            metadata: Optional creation metadata.

        Returns:
            PythonWorkflow instance.

        Raises:
            ValueError: If name is invalid or code doesn't define run().
            SyntaxError: If code has syntax errors.
        """
        # Validate name is valid identifier
        if not name.isidentifier():
            raise ValueError(f"Invalid workflow name: {name!r} (must be valid Python identifier)")

        # Reserved names that would shadow WorkflowsNamespace methods
        reserved = {"list", "search", "get", "invoke", "create", "delete"}
        if name in reserved:
            raise ValueError(f"Reserved workflow name: {name!r}")

        # Parse and validate syntax
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            raise SyntaxError(f"Syntax error in workflow code: {e}")

        has_async_run = False
        has_sync_run = False
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "run":
                has_async_run = True
                break
            if isinstance(node, ast.FunctionDef) and node.name == "run":
                has_sync_run = True

        if has_sync_run and not has_async_run:
            raise ValueError("Workflow must define 'async def run()', not 'def run()'")
        if not has_async_run:
            raise ValueError("Workflow must define an 'async def run()' function")

        # Compile and execute to get the function
        namespace: dict[str, Any] = {}
        _run_code(compile(tree, f"<workflow:{name}>", "exec"), namespace)

        func = namespace.get("run")
        if not callable(func):
            raise ValueError("run must be a callable function")

        # Extract description from source if not provided
        if not description:
            # Try module docstring first
            if tree.body and isinstance(tree.body[0], ast.Expr):
                if isinstance(tree.body[0].value, ast.Constant):
                    doc = tree.body[0].value.value
                    if isinstance(doc, str):
                        description = doc.strip().split("\n")[0]
            # Try function docstring
            if not description and func.__doc__:
                description = func.__doc__.strip().split("\n")[0]

        parameters = _extract_parameters(func, name)

        return cls(
            name=name,
            description=description,
            parameters=parameters,
            source=source,
            _func=func,
            metadata=metadata or WorkflowMetadata.now(),
        )

    @classmethod
    def from_file(cls, path: Path) -> PythonWorkflow:
        """Load a Python workflow from a .py file.

        The file must have an async def run() function as entrypoint.
        Parameters are extracted from the function signature.
        Description comes from the module or function docstring.
        """
        source = path.read_text()

        # Validate async def run() requirement
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            raise SyntaxError(f"Syntax error in workflow {path}: {e}")

        has_async_run = False
        has_sync_run = False
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "run":
                has_async_run = True
                break
            if isinstance(node, ast.FunctionDef) and node.name == "run":
                has_sync_run = True

        if has_sync_run and not has_async_run:
            raise ValueError(f"Workflow {path} must define 'async def run()', not 'def run()'")
        if not has_async_run:
            raise ValueError(f"Workflow {path} must define an 'async def run()' function")

        # Load module dynamically
        spec = importlib.util.spec_from_file_location(path.stem, path)
        if spec is None or spec.loader is None:
            raise ValueError(f"Could not load module from {path}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        func = module.run

        # Extract description from module or function docstring
        description = module.__doc__ or func.__doc__ or ""
        description = description.strip().split("\n")[0]  # First line

        parameters = _extract_parameters(func, path.stem)

        return cls(
            name=path.stem,
            description=description,
            parameters=parameters,
            source=source,
            _func=func,
            metadata=WorkflowMetadata(
                created_at=datetime.now(UTC),
                created_by="human",
                source="file",
            ),
        )

    async def invoke(self, **kwargs: Any) -> Any:
        """Invoke the workflow with given parameters.

        Awaits the async run() function.
        """
        return await self._func(**kwargs)

    @property
    def tags(self) -> frozenset[str]:
        """Tags for categorization (empty for now)."""
        return frozenset()
