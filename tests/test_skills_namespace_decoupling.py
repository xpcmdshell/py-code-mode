"""Tests for WorkflowsNamespace decoupling from InProcessExecutor.

WorkflowsNamespace should accept a namespace dict directly, not an executor reference.
This enables use in contexts where there's no executor (subprocess, container).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from py_code_mode.execution.in_process.workflows_namespace import WorkflowsNamespace
from py_code_mode.workflows import (
    MemoryWorkflowStore,
    MockEmbedder,
    PythonWorkflow,
    WorkflowLibrary,
)


@pytest.fixture
def workflow_library() -> WorkflowLibrary:
    """Create a workflow library with a test workflow."""
    store = MemoryWorkflowStore()
    library = WorkflowLibrary(embedder=MockEmbedder(), store=store)

    # Add a test workflow that accesses tools
    workflow = PythonWorkflow.from_source(
        name="use_tools",
        source='async def run(val: str) -> str:\n    return f"tools={tools}, val={val}"',
        description="A workflow that uses tools from namespace",
    )
    library.add(workflow)

    return library


@pytest.fixture
def namespace_dict() -> dict[str, Any]:
    """Create a namespace dict similar to what executor provides."""
    return {
        "tools": MagicMock(name="tools_namespace"),
        "workflows": MagicMock(name="workflows_namespace"),  # Will be replaced
        "artifacts": MagicMock(name="artifacts_namespace"),
    }


class TestWorkflowsNamespaceAcceptsDict:
    """WorkflowsNamespace constructor accepts namespace dict."""

    def test_accepts_namespace_dict(
        self, workflow_library: WorkflowLibrary, namespace_dict: dict[str, Any]
    ) -> None:
        """Constructor accepts a plain dict for namespace."""
        # Should not raise
        workflows_ns = WorkflowsNamespace(workflow_library, namespace_dict)

        # Should be able to list workflows
        workflows = workflows_ns.list()
        assert len(workflows) == 1
        assert workflows[0]["name"] == "use_tools"

    def test_rejects_executor_argument(self, workflow_library: WorkflowLibrary) -> None:
        """Constructor raises TypeError if passed an executor-like object."""

        # Create something that looks like an executor (has _namespace attribute)
        class FakeExecutor:
            def __init__(self) -> None:
                self._namespace = {"tools": None}

        fake_executor = FakeExecutor()

        with pytest.raises(TypeError) as exc_info:
            WorkflowsNamespace(workflow_library, fake_executor)  # type: ignore[arg-type]

        assert "namespace dict" in str(exc_info.value).lower()
        assert "_namespace" in str(exc_info.value) or "executor" in str(exc_info.value).lower()

    def test_rejects_object_with_namespace_attr(self, workflow_library: WorkflowLibrary) -> None:
        """Constructor rejects any object with _namespace attribute."""
        # Even a mock with _namespace should be rejected
        mock_with_namespace = MagicMock()
        mock_with_namespace._namespace = {}

        with pytest.raises(TypeError):
            WorkflowsNamespace(workflow_library, mock_with_namespace)  # type: ignore[arg-type]


class TestInvokeUsesNamespaceDirectly:
    """invoke() method uses tools/workflows/artifacts from namespace dict."""

    def test_invoke_uses_tools_from_namespace(self, workflow_library: WorkflowLibrary) -> None:
        """Workflow invocation can access tools from namespace dict."""
        # Create a workflow that returns what tools it sees
        workflow = PythonWorkflow.from_source(
            name="echo_tools",
            source="async def run() -> str:\n    return str(type(tools).__name__)",
            description="Returns tools type",
        )
        workflow_library.add(workflow)

        # Create namespace with identifiable tools
        mock_tools = MagicMock(name="my_tools")
        namespace = {
            "tools": mock_tools,
            "workflows": None,
            "artifacts": None,
        }

        workflows_ns = WorkflowsNamespace(workflow_library, namespace)
        result = workflows_ns.invoke("echo_tools")

        # The workflow saw MagicMock as tools
        assert "MagicMock" in result

    def test_invoke_uses_artifacts_from_namespace(self, workflow_library: WorkflowLibrary) -> None:
        """Workflow invocation can access artifacts from namespace dict."""
        workflow = PythonWorkflow.from_source(
            name="use_artifacts",
            source="async def run() -> bool:\n    return artifacts is not None",
            description="Checks artifacts access",
        )
        workflow_library.add(workflow)

        mock_artifacts = MagicMock(name="my_artifacts")
        namespace = {
            "tools": None,
            "workflows": None,
            "artifacts": mock_artifacts,
        }

        workflows_ns = WorkflowsNamespace(workflow_library, namespace)
        result = workflows_ns.invoke("use_artifacts")

        assert result is True

    def test_invoke_uses_deps_from_namespace(self, workflow_library: WorkflowLibrary) -> None:
        """Workflow invocation can access deps from namespace dict."""
        workflow = PythonWorkflow.from_source(
            name="use_deps",
            source="async def run() -> str:\n    return str(deps)",
            description="Checks deps access",
        )
        workflow_library.add(workflow)

        mock_deps = MagicMock(name="my_deps")
        namespace = {
            "tools": None,
            "workflows": None,
            "artifacts": None,
            "deps": mock_deps,
        }

        workflows_ns = WorkflowsNamespace(workflow_library, namespace)
        result = workflows_ns.invoke("use_deps")

        assert "MagicMock" in result


class TestNamespaceIsolation:
    """Workflows cannot modify the parent namespace."""

    def test_workflow_cannot_modify_parent_namespace(
        self, workflow_library: WorkflowLibrary
    ) -> None:
        """Workflow execution cannot add variables to parent namespace."""
        polluter_source = (
            "async def run() -> str:\n"
            "    global pollution\n"
            '    pollution = "leaked"\n'
            '    return "done"'
        )
        workflow = PythonWorkflow.from_source(
            name="polluter",
            source=polluter_source,
            description="Tries to pollute namespace",
        )
        workflow_library.add(workflow)

        original_namespace: dict[str, Any] = {
            "tools": None,
            "workflows": None,
            "artifacts": None,
        }

        workflows_ns = WorkflowsNamespace(workflow_library, original_namespace)
        workflows_ns.invoke("polluter")

        # Parent namespace should not have the pollution
        assert "pollution" not in original_namespace

    def test_workflow_cannot_modify_tools_reference(
        self, workflow_library: WorkflowLibrary
    ) -> None:
        """Workflow cannot replace tools in parent namespace."""
        replacer_source = (
            'async def run() -> str:\n    global tools\n    tools = "replaced"\n    return "done"'
        )
        workflow = PythonWorkflow.from_source(
            name="replacer",
            source=replacer_source,
            description="Tries to replace tools",
        )
        workflow_library.add(workflow)

        original_tools = MagicMock(name="original")
        namespace: dict[str, Any] = {
            "tools": original_tools,
            "workflows": None,
            "artifacts": None,
        }

        workflows_ns = WorkflowsNamespace(workflow_library, namespace)
        workflows_ns.invoke("replacer")

        # Original tools should still be in namespace
        assert namespace["tools"] is original_tools


class TestIntegrationWithExecutor:
    """WorkflowsNamespace works when wired up via executor."""

    @pytest.mark.asyncio
    async def test_executor_passes_namespace_not_self(self) -> None:
        """InProcessExecutor should pass self._namespace, not self."""
        from py_code_mode.execution.in_process.executor import InProcessExecutor
        from py_code_mode.workflows import MemoryWorkflowStore, MockEmbedder, WorkflowLibrary
        from py_code_mode.tools import ToolRegistry

        store = MemoryWorkflowStore()
        library = WorkflowLibrary(embedder=MockEmbedder(), store=store)
        registry = ToolRegistry()

        executor = InProcessExecutor(
            registry=registry,
            workflow_library=library,
        )

        # The workflows namespace should have received a dict, not the executor
        workflows_ns = executor._namespace.get("workflows")
        assert workflows_ns is not None

        # Verify it has _namespace attr (the dict we passed), not _executor
        assert hasattr(workflows_ns, "_namespace")
        assert isinstance(workflows_ns._namespace, dict)

        # Should NOT have _executor attribute
        assert not hasattr(workflows_ns, "_executor")

        await executor.close()
