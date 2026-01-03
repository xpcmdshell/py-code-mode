"""Tests for SkillsNamespace decoupling from InProcessExecutor.

SkillsNamespace should accept a namespace dict directly, not an executor reference.
This enables use in contexts where there's no executor (subprocess, container).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from py_code_mode.execution.in_process.skills_namespace import SkillsNamespace
from py_code_mode.skills import MemorySkillStore, MockEmbedder, PythonSkill, SkillLibrary


@pytest.fixture
def skill_library() -> SkillLibrary:
    """Create a skill library with a test skill."""
    store = MemorySkillStore()
    library = SkillLibrary(embedder=MockEmbedder(), store=store)

    # Add a test skill that accesses tools
    skill = PythonSkill.from_source(
        name="use_tools",
        source='async def run(val: str) -> str:\n    return f"tools={tools}, val={val}"',
        description="A skill that uses tools from namespace",
    )
    library.add(skill)

    return library


@pytest.fixture
def namespace_dict() -> dict[str, Any]:
    """Create a namespace dict similar to what executor provides."""
    return {
        "tools": MagicMock(name="tools_namespace"),
        "skills": MagicMock(name="skills_namespace"),  # Will be replaced
        "artifacts": MagicMock(name="artifacts_namespace"),
    }


class TestSkillsNamespaceAcceptsDict:
    """SkillsNamespace constructor accepts namespace dict."""

    def test_accepts_namespace_dict(
        self, skill_library: SkillLibrary, namespace_dict: dict[str, Any]
    ) -> None:
        """Constructor accepts a plain dict for namespace."""
        # Should not raise
        skills_ns = SkillsNamespace(skill_library, namespace_dict)

        # Should be able to list skills
        skills = skills_ns.list()
        assert len(skills) == 1
        assert skills[0]["name"] == "use_tools"

    def test_rejects_executor_argument(self, skill_library: SkillLibrary) -> None:
        """Constructor raises TypeError if passed an executor-like object."""

        # Create something that looks like an executor (has _namespace attribute)
        class FakeExecutor:
            def __init__(self) -> None:
                self._namespace = {"tools": None}

        fake_executor = FakeExecutor()

        with pytest.raises(TypeError) as exc_info:
            SkillsNamespace(skill_library, fake_executor)  # type: ignore[arg-type]

        assert "namespace dict" in str(exc_info.value).lower()
        assert "_namespace" in str(exc_info.value) or "executor" in str(exc_info.value).lower()

    def test_rejects_object_with_namespace_attr(self, skill_library: SkillLibrary) -> None:
        """Constructor rejects any object with _namespace attribute."""
        # Even a mock with _namespace should be rejected
        mock_with_namespace = MagicMock()
        mock_with_namespace._namespace = {}

        with pytest.raises(TypeError):
            SkillsNamespace(skill_library, mock_with_namespace)  # type: ignore[arg-type]


class TestInvokeUsesNamespaceDirectly:
    """invoke() method uses tools/skills/artifacts from namespace dict."""

    def test_invoke_uses_tools_from_namespace(self, skill_library: SkillLibrary) -> None:
        """Skill invocation can access tools from namespace dict."""
        # Create a skill that returns what tools it sees
        skill = PythonSkill.from_source(
            name="echo_tools",
            source="async def run() -> str:\n    return str(type(tools).__name__)",
            description="Returns tools type",
        )
        skill_library.add(skill)

        # Create namespace with identifiable tools
        mock_tools = MagicMock(name="my_tools")
        namespace = {
            "tools": mock_tools,
            "skills": None,
            "artifacts": None,
        }

        skills_ns = SkillsNamespace(skill_library, namespace)
        result = skills_ns.invoke("echo_tools")

        # The skill saw MagicMock as tools
        assert "MagicMock" in result

    def test_invoke_uses_artifacts_from_namespace(self, skill_library: SkillLibrary) -> None:
        """Skill invocation can access artifacts from namespace dict."""
        skill = PythonSkill.from_source(
            name="use_artifacts",
            source="async def run() -> bool:\n    return artifacts is not None",
            description="Checks artifacts access",
        )
        skill_library.add(skill)

        mock_artifacts = MagicMock(name="my_artifacts")
        namespace = {
            "tools": None,
            "skills": None,
            "artifacts": mock_artifacts,
        }

        skills_ns = SkillsNamespace(skill_library, namespace)
        result = skills_ns.invoke("use_artifacts")

        assert result is True


class TestNamespaceIsolation:
    """Skills cannot modify the parent namespace."""

    def test_skill_cannot_modify_parent_namespace(self, skill_library: SkillLibrary) -> None:
        """Skill execution cannot add variables to parent namespace."""
        polluter_source = (
            "async def run() -> str:\n"
            "    global pollution\n"
            '    pollution = "leaked"\n'
            '    return "done"'
        )
        skill = PythonSkill.from_source(
            name="polluter",
            source=polluter_source,
            description="Tries to pollute namespace",
        )
        skill_library.add(skill)

        original_namespace: dict[str, Any] = {
            "tools": None,
            "skills": None,
            "artifacts": None,
        }

        skills_ns = SkillsNamespace(skill_library, original_namespace)
        skills_ns.invoke("polluter")

        # Parent namespace should not have the pollution
        assert "pollution" not in original_namespace

    def test_skill_cannot_modify_tools_reference(self, skill_library: SkillLibrary) -> None:
        """Skill cannot replace tools in parent namespace."""
        replacer_source = (
            'async def run() -> str:\n    global tools\n    tools = "replaced"\n    return "done"'
        )
        skill = PythonSkill.from_source(
            name="replacer",
            source=replacer_source,
            description="Tries to replace tools",
        )
        skill_library.add(skill)

        original_tools = MagicMock(name="original")
        namespace: dict[str, Any] = {
            "tools": original_tools,
            "skills": None,
            "artifacts": None,
        }

        skills_ns = SkillsNamespace(skill_library, namespace)
        skills_ns.invoke("replacer")

        # Original tools should still be in namespace
        assert namespace["tools"] is original_tools


class TestIntegrationWithExecutor:
    """SkillsNamespace works when wired up via executor."""

    @pytest.mark.asyncio
    async def test_executor_passes_namespace_not_self(self) -> None:
        """InProcessExecutor should pass self._namespace, not self."""
        from py_code_mode.execution.in_process.executor import InProcessExecutor
        from py_code_mode.skills import MemorySkillStore, MockEmbedder, SkillLibrary
        from py_code_mode.tools import ToolRegistry

        store = MemorySkillStore()
        library = SkillLibrary(embedder=MockEmbedder(), store=store)
        registry = ToolRegistry()

        executor = InProcessExecutor(
            registry=registry,
            skill_library=library,
        )

        # The skills namespace should have received a dict, not the executor
        skills_ns = executor._namespace.get("skills")
        assert skills_ns is not None

        # Verify it has _namespace attr (the dict we passed), not _executor
        assert hasattr(skills_ns, "_namespace")
        assert isinstance(skills_ns._namespace, dict)

        # Should NOT have _executor attribute
        assert not hasattr(skills_ns, "_executor")

        await executor.close()
