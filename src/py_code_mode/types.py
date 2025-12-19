"""Core type definitions for py-code-mode."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class JsonSchema:
    """JSON Schema representation for tool input/output schemas.

    Simplified subset of JSON Schema sufficient for tool definitions.
    """

    type: str = "object"
    description: str | None = None
    properties: dict[str, JsonSchema] = field(default_factory=dict)
    required: list[str] = field(default_factory=list)
    items: JsonSchema | None = None  # For array types
    enum: list[Any] = field(default_factory=list)  # For enum types
    default: Any = None
    additional_properties: bool | JsonSchema = True

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON Schema dict representation."""
        result: dict[str, Any] = {"type": self.type}

        if self.description:
            result["description"] = self.description

        if self.properties:
            result["properties"] = {k: v.to_dict() for k, v in self.properties.items()}

        if self.required:
            result["required"] = self.required

        if self.items:
            result["items"] = self.items.to_dict()

        if self.enum:
            result["enum"] = self.enum

        if self.default is not None:
            result["default"] = self.default

        if self.additional_properties is not True:
            if isinstance(self.additional_properties, JsonSchema):
                result["additionalProperties"] = self.additional_properties.to_dict()
            else:
                result["additionalProperties"] = self.additional_properties

        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JsonSchema:
        """Create JsonSchema from dict representation."""
        properties = {}
        if "properties" in data:
            properties = {k: cls.from_dict(v) for k, v in data["properties"].items()}

        items = None
        if "items" in data:
            items = cls.from_dict(data["items"])

        additional_properties: bool | JsonSchema = data.get("additionalProperties", True)
        if isinstance(additional_properties, dict):
            additional_properties = cls.from_dict(additional_properties)

        return cls(
            type=data.get("type", "object"),
            description=data.get("description"),
            properties=properties,
            required=data.get("required", []),
            items=items,
            enum=data.get("enum", []),
            default=data.get("default"),
            additional_properties=additional_properties,
        )


@dataclass(frozen=True)
class ToolDefinition:
    """Definition of a tool available for agent use.

    Contains all metadata needed to:
    - Generate TypedDict interfaces for the agent
    - Call the tool at runtime
    - Filter/scope tools by tags
    """

    name: str
    description: str
    input_schema: JsonSchema
    output_schema: JsonSchema | None = None
    tags: frozenset[str] = field(default_factory=frozenset)
    python_deps: tuple[str, ...] = field(default_factory=tuple)
    timeout_seconds: float = 60.0

    def matches_scope(self, scope: set[str]) -> bool:
        """Check if this tool matches the given scope (tag filter).

        A tool matches if any of its tags are in the scope.
        """
        if not scope:
            return False
        return bool(self.tags & scope)


@dataclass
class ExecutionResult:
    """Result from executing code in any backend.

    Unified result type for all execution backends.
    """

    value: Any
    stdout: str
    error: str | None
    execution_time_ms: float | None = None
    backend_info: dict[str, Any] = field(default_factory=dict)

    @property
    def is_ok(self) -> bool:
        """True if execution succeeded (no error)."""
        return self.error is None


@dataclass
class ExecutorConfig:
    """Base configuration for all execution backends.

    Security policies are accepted by all backends, but backends
    will ignore policies they don't support.
    """

    # Common
    default_timeout: float = 30.0
    tools_path: str | None = None
    skills_path: str | None = None
    artifacts_path: str | None = None

    # Security policies (backends ignore if unsupported)
    network_policy: str = "allow"  # "allow", "deny", "filtered"
    allowed_hosts: list[str] = field(default_factory=list)
    filesystem_policy: str = "allow"  # "allow", "deny", "readonly"
    allowed_paths: list[str] = field(default_factory=list)

    # Resource limits
    memory_limit_mb: int | None = None
    cpu_limit: float | None = None
