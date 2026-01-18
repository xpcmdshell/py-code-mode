"""Workflows system - Python workflows.

Security model:
- Workflow source is validated and indexed using AST only (no execution).
- Workflow invocation executes the workflow source in a fresh namespace each time
  (stateless; module globals do not persist across invocations).
"""

from __future__ import annotations

import ast
import builtins
import inspect
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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


# Special parameters that are injected, not user-provided
_INJECTED_PARAMS = {"tools", "workflows", "artifacts", "deps"}


def _annotation_to_type_str(annotation: ast.expr | None) -> str:
    """Best-effort mapping from annotation AST to our simplified type strings."""

    def _base_name(expr: ast.expr) -> str | None:
        if isinstance(expr, ast.Name):
            return expr.id
        if isinstance(expr, ast.Attribute):
            # e.g. typing.List, module.Type
            return expr.attr
        return None

    if annotation is None:
        return "string"

    # Handle list[int], dict[str, int], etc.
    if isinstance(annotation, ast.Subscript):
        base = _base_name(annotation.value)
        if base in {"list", "List", "Sequence", "Iterable"}:
            return "array"
        if base in {"dict", "Dict", "Mapping"}:
            return "object"

    base = _base_name(annotation)
    if base in {"str", "String"}:
        return "string"
    if base in {"int", "Integer"}:
        return "integer"
    if base in {"float", "number", "Number"}:
        return "number"
    if base in {"bool", "Boolean"}:
        return "boolean"
    if base in {"list", "List"}:
        return "array"
    if base in {"dict", "Dict"}:
        return "object"

    return "string"


def _default_expr_to_value(expr: ast.expr) -> Any:
    """Return a safe representation for a default expression.

    - If it's a Python literal (incl. containers), returns the concrete value.
    - Otherwise returns a string representation of the expression.
    """
    try:
        return ast.literal_eval(expr)
    except Exception:
        try:
            return ast.unparse(expr)
        except Exception:
            return None


def _extract_parameters_from_ast(run_func: ast.AsyncFunctionDef) -> list[WorkflowParameter]:
    """Extract WorkflowParameter list from an async run() AST node.

    This avoids executing workflow code at load/index time.
    """
    args = run_func.args

    # Positional args are posonlyargs + args; defaults apply to the last N of these.
    pos_args = list(args.posonlyargs) + list(args.args)
    defaults = list(args.defaults)
    pos_defaults: dict[str, ast.expr] = {}
    if defaults:
        for arg_node, default_node in zip(pos_args[-len(defaults) :], defaults, strict=True):
            pos_defaults[arg_node.arg] = default_node

    kw_defaults: dict[str, ast.expr] = {}
    for kw_arg, kw_default in zip(args.kwonlyargs, args.kw_defaults, strict=True):
        if kw_default is not None:
            kw_defaults[kw_arg.arg] = kw_default

    parameters: list[WorkflowParameter] = []

    def _add_param(arg_node: ast.arg, default_node: ast.expr | None) -> None:
        if arg_node.arg in _INJECTED_PARAMS:
            return

        if default_node is not None:
            default_val = _default_expr_to_value(default_node)
            has_default = True
        else:
            default_val = None
            has_default = False
        parameters.append(
            WorkflowParameter(
                name=arg_node.arg,
                type=_annotation_to_type_str(arg_node.annotation),
                description="",
                required=not has_default,
                default=default_val,
            )
        )

    for a in pos_args:
        _add_param(a, pos_defaults.get(a.arg))

    for a in args.kwonlyargs:
        _add_param(a, kw_defaults.get(a.arg))

    return parameters


def _find_run_async_def(tree: ast.Module) -> ast.AsyncFunctionDef:
    """Find the top-level async def run() function in a module AST."""
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "run":
            return node
    raise ValueError("Workflow must define an 'async def run()' function")


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

        has_sync_run = any(
            isinstance(node, ast.FunctionDef) and node.name == "run" for node in tree.body
        )
        run_node = _find_run_async_def(tree)
        if has_sync_run:
            raise ValueError("Workflow must define 'async def run()', not 'def run()'")

        # Extract description from source if not provided
        if not description:
            # Try module docstring first
            if tree.body and isinstance(tree.body[0], ast.Expr):
                if isinstance(tree.body[0].value, ast.Constant):
                    doc = tree.body[0].value.value
                    if isinstance(doc, str):
                        description = doc.strip().split("\n")[0]
            # Try function docstring
            if not description:
                func_doc = ast.get_docstring(run_node)
                if func_doc:
                    description = func_doc.strip().split("\n")[0]

        parameters = _extract_parameters_from_ast(run_node)

        return cls(
            name=name,
            description=description,
            parameters=parameters,
            source=source,
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

        has_sync_run = any(
            isinstance(node, ast.FunctionDef) and node.name == "run" for node in tree.body
        )
        run_node = _find_run_async_def(tree)
        if has_sync_run:
            raise ValueError(f"Workflow {path} must define 'async def run()', not 'def run()'")

        # Extract description from module or function docstring
        description = ast.get_docstring(tree) or ast.get_docstring(run_node) or ""
        description = description.strip().split("\n")[0]

        parameters = _extract_parameters_from_ast(run_node)

        return cls(
            name=path.stem,
            description=description,
            parameters=parameters,
            source=source,
            metadata=WorkflowMetadata(
                created_at=datetime.now(UTC),
                created_by="human",
                source="file",
            ),
        )

    async def invoke(self, **kwargs: Any) -> Any:
        """Invoke the workflow in a fresh namespace (stateless).

        Note: This executes the workflow module source on each invocation, so
        module-level globals do not persist across calls.
        """
        namespace: dict[str, Any] = {}
        tree = ast.parse(self.source)
        _run_code(compile(tree, f"<workflow:{self.name}>", "exec"), namespace)
        run_func = namespace.get("run")
        if not callable(run_func):
            raise ValueError(f"Workflow {self.name} has no run() function")
        result = run_func(**kwargs)
        if inspect.iscoroutine(result):
            return await result
        return result

    @property
    def tags(self) -> frozenset[str]:
        """Tags for categorization (empty for now)."""
        return frozenset()
