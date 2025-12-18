"""Tests for type definitions."""

import pytest

from py_code_mode import JsonSchema, ToolDefinition


class TestJsonSchema:
    """Tests for JsonSchema dataclass."""

    def test_basic_string_schema(self) -> None:
        schema = JsonSchema(type="string", description="A name")
        assert schema.type == "string"
        assert schema.description == "A name"

    def test_to_dict(self) -> None:
        schema = JsonSchema(
            type="object",
            description="User input",
            properties={
                "name": JsonSchema(type="string"),
                "age": JsonSchema(type="integer"),
            },
            required=["name"],
        )

        result = schema.to_dict()

        assert result["type"] == "object"
        assert result["description"] == "User input"
        assert "properties" in result
        assert result["properties"]["name"]["type"] == "string"
        assert result["required"] == ["name"]

    def test_from_dict(self) -> None:
        data = {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        }

        schema = JsonSchema.from_dict(data)

        assert schema.type == "object"
        assert "query" in schema.properties
        assert schema.properties["query"].type == "string"
        assert schema.required == ["query"]

    def test_array_schema(self) -> None:
        schema = JsonSchema(
            type="array",
            items=JsonSchema(type="string"),
        )

        result = schema.to_dict()
        assert result["type"] == "array"
        assert result["items"]["type"] == "string"

    def test_enum_schema(self) -> None:
        schema = JsonSchema(
            type="string",
            enum=["red", "green", "blue"],
        )

        result = schema.to_dict()
        assert result["enum"] == ["red", "green", "blue"]

    def test_roundtrip(self) -> None:
        original = JsonSchema(
            type="object",
            description="Complex schema",
            properties={
                "items": JsonSchema(
                    type="array",
                    items=JsonSchema(
                        type="object",
                        properties={
                            "id": JsonSchema(type="integer"),
                            "name": JsonSchema(type="string"),
                        },
                    ),
                ),
                "status": JsonSchema(type="string", enum=["active", "inactive"]),
            },
            required=["items"],
        )

        as_dict = original.to_dict()
        restored = JsonSchema.from_dict(as_dict)

        assert restored.type == original.type
        assert restored.description == original.description
        assert "items" in restored.properties


class TestToolDefinition:
    """Tests for ToolDefinition dataclass."""

    def test_basic_creation(self) -> None:
        tool = ToolDefinition(
            name="test_tool",
            description="A test tool",
            input_schema=JsonSchema(type="object"),
        )

        assert tool.name == "test_tool"
        assert tool.description == "A test tool"
        assert tool.tags == frozenset()
        assert tool.timeout_seconds == 60.0

    def test_with_tags(self) -> None:
        tool = ToolDefinition(
            name="nmap",
            description="Network scanner",
            input_schema=JsonSchema(type="object"),
            tags=frozenset({"network", "recon", "scanning"}),
        )

        assert "network" in tool.tags
        assert "recon" in tool.tags

    def test_immutable(self) -> None:
        tool = ToolDefinition(
            name="test",
            description="Test",
            input_schema=JsonSchema(type="object"),
        )

        with pytest.raises(AttributeError):
            tool.name = "changed"  # type: ignore

    def test_matches_scope_with_matching_tag(self) -> None:
        tool = ToolDefinition(
            name="nmap",
            description="Scanner",
            input_schema=JsonSchema(type="object"),
            tags=frozenset({"network", "recon"}),
        )

        assert tool.matches_scope({"network"})
        assert tool.matches_scope({"recon"})
        assert tool.matches_scope({"network", "web"})  # Any match is enough

    def test_matches_scope_no_match(self) -> None:
        tool = ToolDefinition(
            name="nmap",
            description="Scanner",
            input_schema=JsonSchema(type="object"),
            tags=frozenset({"network", "recon"}),
        )

        assert not tool.matches_scope({"web"})
        assert not tool.matches_scope({"http", "api"})

    def test_matches_scope_empty_scope(self) -> None:
        tool = ToolDefinition(
            name="nmap",
            description="Scanner",
            input_schema=JsonSchema(type="object"),
            tags=frozenset({"network"}),
        )

        # Empty scope matches nothing
        assert not tool.matches_scope(set())

    def test_matches_scope_tool_no_tags(self) -> None:
        tool = ToolDefinition(
            name="generic",
            description="Generic tool",
            input_schema=JsonSchema(type="object"),
            tags=frozenset(),  # No tags
        )

        # Tool with no tags matches nothing
        assert not tool.matches_scope({"network"})
        assert not tool.matches_scope(set())

    def test_python_deps(self) -> None:
        tool = ToolDefinition(
            name="nmap",
            description="Scanner",
            input_schema=JsonSchema(type="object"),
            python_deps=("python-nmap>=0.7.0", "requests"),
        )

        assert "python-nmap>=0.7.0" in tool.python_deps
        assert len(tool.python_deps) == 2
