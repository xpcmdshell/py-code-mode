"""Test fixtures for py-code-mode."""

from typing import Any

import pytest

from py_code_mode import JsonSchema, ToolDefinition
from py_code_mode.adapters.base import ToolAdapter


class MockAdapter:
    """Mock adapter for testing."""

    def __init__(
        self,
        tools: list[ToolDefinition] | list[str],
        call_results: dict[str, Any] | None = None,
    ) -> None:
        # Support both ToolDefinition list and simple string list
        if tools and isinstance(tools[0], str):
            self._tools = {
                name: ToolDefinition(
                    name=name,
                    description=f"Mock {name}",
                    input_schema=JsonSchema(type="object"),
                )
                for name in tools
            }
        else:
            self._tools = {t.name: t for t in tools}  # type: ignore
        self._call_log: list[tuple[str, dict[str, Any]]] = []
        self._responses: dict[str, Any] = call_results or {}

    def set_response(self, tool_name: str, response: Any) -> None:
        """Set the response for a tool call."""
        self._responses[tool_name] = response

    async def list_tools(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    async def call_tool(self, name: str, args: dict[str, Any]) -> Any:
        self._call_log.append((name, args))
        if name in self._responses:
            return self._responses[name]
        return {"status": "ok", "tool": name, "args": args}

    async def close(self) -> None:
        self._closed = True

    @property
    def closed(self) -> bool:
        """Whether the adapter has been closed."""
        return getattr(self, "_closed", False)

    @property
    def call_log(self) -> list[tuple[str, dict[str, Any]]]:
        return self._call_log


@pytest.fixture
def mock_tool_definition() -> ToolDefinition:
    """Create a sample tool definition."""
    return ToolDefinition(
        name="test_tool",
        description="A test tool",
        input_schema=JsonSchema(
            type="object",
            properties={
                "query": JsonSchema(type="string", description="Search query"),
                "limit": JsonSchema(type="integer", description="Max results"),
            },
            required=["query"],
        ),
        output_schema=JsonSchema(
            type="object",
            properties={
                "results": JsonSchema(type="array", items=JsonSchema(type="string")),
            },
        ),
        tags=frozenset({"search", "test"}),
        timeout_seconds=30.0,
    )


@pytest.fixture
def network_tools() -> list[ToolDefinition]:
    """Create network-related tool definitions."""
    return [
        ToolDefinition(
            name="nmap",
            description="Network scanner",
            input_schema=JsonSchema(
                type="object",
                properties={
                    "target": JsonSchema(type="string"),
                    "ports": JsonSchema(type="string"),
                },
                required=["target"],
            ),
            tags=frozenset({"network", "recon"}),
        ),
        ToolDefinition(
            name="ping",
            description="ICMP ping",
            input_schema=JsonSchema(
                type="object",
                properties={"host": JsonSchema(type="string")},
                required=["host"],
            ),
            tags=frozenset({"network"}),
        ),
    ]


@pytest.fixture
def web_tools() -> list[ToolDefinition]:
    """Create web-related tool definitions."""
    return [
        ToolDefinition(
            name="curl",
            description="HTTP client",
            input_schema=JsonSchema(
                type="object",
                properties={"url": JsonSchema(type="string")},
                required=["url"],
            ),
            tags=frozenset({"web", "http"}),
        ),
        ToolDefinition(
            name="ffuf",
            description="Web fuzzer",
            input_schema=JsonSchema(
                type="object",
                properties={
                    "url": JsonSchema(type="string"),
                    "wordlist": JsonSchema(type="string"),
                },
                required=["url"],
            ),
            tags=frozenset({"web", "recon"}),
        ),
    ]


@pytest.fixture
def mock_adapter(mock_tool_definition: ToolDefinition) -> MockAdapter:
    """Create a mock adapter with one tool."""
    return MockAdapter([mock_tool_definition])


@pytest.fixture
def network_adapter(network_tools: list[ToolDefinition]) -> MockAdapter:
    """Create a mock adapter with network tools."""
    return MockAdapter(network_tools)


@pytest.fixture
def web_adapter(web_tools: list[ToolDefinition]) -> MockAdapter:
    """Create a mock adapter with web tools."""
    return MockAdapter(web_tools)


@pytest.fixture
def json_tools() -> list[ToolDefinition]:
    """Create JSON-related tool definitions."""
    return [
        ToolDefinition(
            name="jq",
            description="JSON processor",
            input_schema=JsonSchema(
                type="object",
                properties={"filter": JsonSchema(type="string")},
                required=["filter"],
            ),
            tags=frozenset({"json", "data"}),
        ),
    ]


@pytest.fixture
def json_adapter(json_tools: list[ToolDefinition]) -> MockAdapter:
    """Create a mock adapter with JSON tools."""
    return MockAdapter(json_tools)


class ControllableEmbedder:
    """Embedder that returns controlled vectors for deterministic tests.

    Use set_response() to map input text to specific vectors.
    Unknown inputs get zero vectors.
    """

    def __init__(self, dimension: int = 4) -> None:
        self.dimension = dimension
        self._responses: dict[str, list[float]] = {}

    def set_response(self, text: str, vector: list[float]) -> None:
        """Set the vector to return for a given text."""
        self._responses[text] = vector

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return controlled vectors for the given texts."""
        vectors = []
        for text in texts:
            if text in self._responses:
                vectors.append(self._responses[text])
            else:
                # Return zero vector for unknown inputs
                vectors.append([0.0] * self.dimension)
        return vectors

    def embed_query(self, query: str) -> list[float]:
        """Return controlled vector for a query text."""
        if query in self._responses:
            return self._responses[query]
        return [0.0] * self.dimension


@pytest.fixture
def controllable_embedder() -> ControllableEmbedder:
    """Create a controllable embedder for deterministic tests."""
    return ControllableEmbedder(dimension=4)
