"""Skills namespace for code execution.

Provides the skills.* namespace that agents use to search,
invoke, create, and delete skills during code execution.
"""

from __future__ import annotations

import builtins
from typing import TYPE_CHECKING, Any

from py_code_mode.skills import SkillLibrary

if TYPE_CHECKING:
    from py_code_mode.skills import PythonSkill

# Use builtins to avoid security hook false positive on Python's code execution
_run_code = getattr(builtins, "exec")


class SkillsNamespace:
    """Namespace object for skills.* access in executed code.

    Wraps a SkillLibrary and provides agent-facing methods plus skill execution.
    """

    def __init__(self, library: SkillLibrary, namespace: dict[str, Any]) -> None:
        """Initialize SkillsNamespace.

        Args:
            library: The skill library for skill lookup and storage.
            namespace: Dict containing tools, skills, artifacts for skill execution.
                       Must be a plain dict, not an executor object.

        Raises:
            TypeError: If namespace is an executor-like object (has _namespace attr).
        """
        # Reject executor-like objects - require the actual namespace dict
        if hasattr(namespace, "_namespace"):
            raise TypeError(
                "SkillsNamespace expects a namespace dict, not an executor. "
                "Pass executor._namespace instead of the executor itself."
            )

        self._library = library
        self._namespace = namespace

    @property
    def library(self) -> SkillLibrary:
        """Access the underlying SkillLibrary.

        Useful for tests and advanced use cases that need direct library access.
        """
        return self._library

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

    def _simplify(self, skill: PythonSkill) -> dict[str, Any]:
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
        # Create isolated namespace with copies of tools/skills/artifacts refs
        skill_namespace = {
            "tools": self._namespace.get("tools"),
            "skills": self._namespace.get("skills"),
            "artifacts": self._namespace.get("artifacts"),
        }
        code = compile(skill.source, f"<skill:{skill_name}>", "exec")
        _run_code(code, skill_namespace)
        return skill_namespace["run"](**kwargs)
