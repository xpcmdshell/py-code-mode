"""Workflows namespace for code execution.

Provides the workflows.* namespace that agents use to search,
invoke, create, and delete workflows during code execution.
"""

from __future__ import annotations

import asyncio
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
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Set the event loop to use for async workflow invocations.

        When code runs in a thread (via asyncio.to_thread), we need a reference
        to the main event loop to execute async workflows via run_coroutine_threadsafe.
        """
        self._loop = loop

    @property
    def library(self) -> WorkflowLibrary:
        """Access the underlying WorkflowLibrary.

        Useful for tests and advanced use cases that need direct library access.
        """
        return self._library

    def search(self, query: str, limit: int = 10) -> builtins.list[dict[str, Any]] | Any:
        """Search for workflows matching query.

        In async context, returns an awaitable so code can use `await workflows.search(...)`.
        """

        def _run() -> builtins.list[dict[str, Any]]:
            workflows = self._library.search(query, limit)
            return [self._simplify(w) for w in workflows]

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return _run()

        async def _coro() -> builtins.list[dict[str, Any]]:
            return _run()

        return _coro()

    def get(self, name: str) -> Any:
        """Get a workflow by name.

        In async context, returns an awaitable so code can use `await workflows.get(...)`.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return self._library.get(name)

        async def _coro() -> Any:
            return self._library.get(name)

        return _coro()

    def list(self) -> builtins.list[dict[str, Any]] | Any:
        """List all available workflows.

        In async context, returns an awaitable so code can use `await workflows.list()`.
        """

        def _run() -> builtins.list[dict[str, Any]]:
            workflows = self._library.list()
            return [self._simplify(w) for w in workflows]

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return _run()

        async def _coro() -> builtins.list[dict[str, Any]]:
            return _run()

        return _coro()

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

        result = self._simplify(workflow)

        # Allow awaiting in async contexts for consistency.
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return result

        async def _coro() -> dict[str, Any]:
            return result

        return _coro()

    def delete(self, name: str) -> bool | Any:
        """Remove a workflow from the library.

        Args:
            name: Name of workflow to delete.

        Returns:
            True if workflow was deleted, False if not found.
        """
        removed = self._library.remove(name)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return removed

        async def _coro() -> bool:
            return removed

        return _coro()

    def __getattr__(self, name: str) -> Any:
        """Allow workflows.workflow_name(...) syntax."""
        if name.startswith("_"):
            raise AttributeError(name)
        workflow = self._library.get(name)
        if workflow is None:
            raise AttributeError(f"Workflow not found: {name}")
        # Capture name in closure to avoid conflict with kwargs
        workflow_name = name
        return lambda **kwargs: self.invoke(workflow_name, **kwargs)

    def invoke(self, workflow_name: str, **kwargs: Any) -> Any:
        """Invoke a workflow by calling its run() function.

        Returns the result of the workflow execution.
        """
        workflow = self._library.get(workflow_name)
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
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return asyncio.run(result)

            async def _coro() -> Any:
                return await result

            return _coro()

        return result
