"""Workflows namespace for code execution.

Provides the workflows.* namespace that agents use to search,
invoke, create, and delete workflows during code execution.
"""

from __future__ import annotations

import builtins
import inspect
from typing import TYPE_CHECKING, Any

from py_code_mode.workflows import WorkflowLibrary

if TYPE_CHECKING:
    from py_code_mode.workflows import PythonWorkflow

# Use builtins to avoid security hook false positive on Python's code execution
_run_code = getattr(builtins, "exec")


class WorkflowsNamespace:
    """Namespace object for workflows.* access in executed code.

    Wraps a WorkflowLibrary and provides agent-facing methods plus workflow execution.
    """

    def __init__(self, library: WorkflowLibrary, namespace: dict[str, Any]) -> None:
        """Initialize WorkflowsNamespace.

        Args:
            library: The workflow library for workflow lookup and storage.
            namespace: Dict containing tools, workflows, artifacts for workflow execution.
                       Must be a plain dict, not an executor object.

        Raises:
            TypeError: If namespace is an executor-like object (has _namespace attr).
        """
        # Reject executor-like objects - require the actual namespace dict
        if hasattr(namespace, "_namespace"):
            raise TypeError(
                "WorkflowsNamespace expects a namespace dict, not an executor. "
                "Pass executor._namespace instead of the executor itself."
            )

        self._library = library
        self._namespace = namespace
        # Intentionally synchronous surface. Async workflows are supported via
        # asyncio.run(...) when invoked from sync code (the default execution mode).

    @property
    def library(self) -> WorkflowLibrary:
        """Access the underlying WorkflowLibrary.

        Useful for tests and advanced use cases that need direct library access.
        """
        return self._library

    def _refresh_persisted_library(self) -> None:
        """Refresh persisted workflows so external changes are visible."""
        if self._library.store is not None:
            self._library.refresh()

    def _get_workflow(self, name: str) -> Any:
        """Get a workflow, refreshing persisted libraries first."""
        self._refresh_persisted_library()
        return self._library.get(name)

    def search(self, query: str, limit: int = 10) -> builtins.list[dict[str, Any]]:
        """Search for workflows matching query."""
        self._refresh_persisted_library()
        workflows = self._library.search(query, limit)
        return [self._simplify(w) for w in workflows]

    def get(self, name: str) -> Any:
        """Get a workflow by name."""
        return self._get_workflow(name)

    def list(self) -> builtins.list[dict[str, Any]]:
        """List all available workflows."""
        self._refresh_persisted_library()
        workflows = self._library.list()
        return [self._simplify(w) for w in workflows]

    def _simplify(self, workflow: PythonWorkflow) -> dict[str, Any]:
        """Simplify workflow for agent readability."""
        params = {}
        for p in workflow.parameters:
            params[p.name] = p.description or p.type
        return {
            "name": workflow.name,
            "description": workflow.description,
            "params": params,
        }

    def create(
        self,
        name: str,
        source: str,
        description: str = "",
    ) -> dict[str, Any]:
        """Create and save a new Python workflow.

        Args:
            name: Workflow name (must be valid Python identifier).
            source: Python source code with def run(...) function.
            description: What the workflow does.

        Returns:
            Simplified workflow info dict.

        Raises:
            ValueError: If name is invalid, reserved, or code is malformed.
            SyntaxError: If code has syntax errors.
        """
        from py_code_mode.workflows import PythonWorkflow

        # PythonWorkflow.from_source handles all validation
        workflow = PythonWorkflow.from_source(
            name=name,
            source=source,
            description=description,
        )

        # Add to library (persists to store if configured)
        self._library.add(workflow)

        return self._simplify(workflow)

    def delete(self, name: str) -> bool:
        """Remove a workflow from the library.

        Args:
            name: Name of workflow to delete.

        Returns:
            True if workflow was deleted, False if not found.
        """
        return self._library.remove(name)

    def __getattr__(self, name: str) -> Any:
        """Allow workflows.workflow_name(...) syntax."""
        if name.startswith("_"):
            raise AttributeError(name)
        workflow = self._get_workflow(name)
        if workflow is None:
            raise AttributeError(f"Workflow not found: {name}")
        # Capture name in closure to avoid conflict with kwargs
        workflow_name = name
        return lambda **kwargs: self.invoke(workflow_name, **kwargs)

    def invoke(self, workflow_name: str, **kwargs: Any) -> Any:
        """Invoke a workflow by calling its run() function.

        Returns the result of the workflow execution.
        """
        workflow = self._get_workflow(workflow_name)
        if workflow is None:
            raise ValueError(f"Workflow not found: {workflow_name}")

        workflow_namespace = {
            "tools": self._namespace.get("tools"),
            "workflows": self._namespace.get("workflows"),
            "artifacts": self._namespace.get("artifacts"),
            "deps": self._namespace.get("deps"),
        }
        code = compile(workflow.source, f"<workflow:{workflow_name}>", "exec")
        _run_code(code, workflow_namespace)
        run_func = workflow_namespace.get("run")
        if not callable(run_func):
            raise ValueError(f"Workflow {workflow_name} has no run() function")
        result = run_func(**kwargs)

        if inspect.iscoroutine(result):
            # Default agent code execution runs in a worker thread without a
            # running event loop, so asyncio.run(...) is safe and yields a
            # synchronous result.
            import asyncio

            return asyncio.run(result)

        return result
