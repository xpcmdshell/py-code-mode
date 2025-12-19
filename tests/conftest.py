"""Test fixtures for py-code-mode."""

import fnmatch
import functools
import os
import shutil
from pathlib import Path
from typing import Any

import pytest
import redis

from py_code_mode import JsonSchema, ToolDefinition

# Configure DOCKER_HOST for Docker Desktop on macOS/Windows
# This fixes socket path issues for both testcontainers and our ContainerExecutor
if not os.environ.get("DOCKER_HOST"):
    _docker_desktop_socket = Path.home() / ".docker" / "run" / "docker.sock"
    if _docker_desktop_socket.exists():
        os.environ["DOCKER_HOST"] = f"unix://{_docker_desktop_socket}"

# Optional testcontainers import - only available if testcontainers[redis] installed
try:
    from testcontainers.redis import RedisContainer

    TESTCONTAINERS_AVAILABLE = True
except ImportError:
    RedisContainer = None  # type: ignore[misc, assignment]
    TESTCONTAINERS_AVAILABLE = False


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
            self._tools = {t.name: t for t in tools}  # type: ignore[union-attr]
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


# --- Storage and Session Test Fixtures ---


def requires_redis(fn):
    """Decorator to skip tests if Redis is not available."""

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            url = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379")
            client = redis.from_url(url)
            client.ping()
        except Exception:
            pytest.skip("Redis not available")
        return await fn(*args, **kwargs)

    return wrapper


def requires_docker(fn):
    """Decorator to skip tests if Docker is not available."""

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        if shutil.which("docker") is None:
            pytest.skip("Docker not available")
        return await fn(*args, **kwargs)

    return wrapper


# Markers for parametrized skip conditions
def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "requires_redis: mark test as requiring Redis")
    config.addinivalue_line("markers", "requires_docker: mark test as requiring Docker")


class MockConnectionPool:
    """Mock connection pool to match redis.ConnectionPool interface."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: str | None = None,
    ) -> None:
        self.connection_kwargs = {
            "host": host,
            "port": port,
            "db": db,
            "password": password,
        }


class MockRedisClient:
    """Mock Redis client for testing RedisStorage without actual Redis."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: str | None = None,
    ) -> None:
        self._data: dict[str, dict[str, bytes]] = {}
        self._strings: dict[str, bytes] = {}
        # Match real redis.Redis interface for session.py:_derive_storage_access()
        self.connection_pool = MockConnectionPool(host, port, db, password)

    def hset(self, key: str, field: str, value: bytes) -> int:
        if key not in self._data:
            self._data[key] = {}
        self._data[key][field] = value
        return 1

    def hget(self, key: str, field: str) -> bytes | None:
        return self._data.get(key, {}).get(field)

    def hdel(self, key: str, *fields: str) -> int:
        count = 0
        if key in self._data:
            for field in fields:
                if field in self._data[key]:
                    del self._data[key][field]
                    count += 1
        return count

    def hgetall(self, key: str) -> dict[str, bytes]:
        return self._data.get(key, {})

    def hexists(self, key: str, field: str) -> bool:
        return field in self._data.get(key, {})

    def hkeys(self, key: str) -> list[str]:
        return list(self._data.get(key, {}).keys())

    def hlen(self, key: str) -> int:
        return len(self._data.get(key, {}))

    def set(self, key: str, value: bytes, ex: int | None = None) -> bool:
        self._strings[key] = value
        return True

    def get(self, key: str) -> bytes | None:
        return self._strings.get(key)

    def delete(self, *keys: str) -> int:
        count = 0
        for key in keys:
            if key in self._strings:
                del self._strings[key]
                count += 1
            if key in self._data:
                del self._data[key]
                count += 1
        return count

    def exists(self, key: str) -> int:
        if key in self._strings or key in self._data:
            return 1
        return 0

    def keys(self, pattern: str = "*") -> list[str]:
        """Simple pattern matching for keys."""
        all_keys = list(self._strings.keys()) + list(self._data.keys())
        if pattern == "*":
            return all_keys
        return [k for k in all_keys if fnmatch.fnmatch(k, pattern)]


@pytest.fixture
def mock_redis() -> MockRedisClient:
    """Create a mock Redis client for testing."""
    return MockRedisClient()


@pytest.fixture
def temp_storage_dir(tmp_path: Any) -> Any:
    """Create a temporary directory structure for storage tests."""
    storage_root = Path(tmp_path) / "storage"
    storage_root.mkdir()

    tools_dir = storage_root / "tools"
    tools_dir.mkdir()

    skills_dir = storage_root / "skills"
    skills_dir.mkdir()

    artifacts_dir = storage_root / "artifacts"
    artifacts_dir.mkdir()

    return storage_root


@pytest.fixture
def sample_tool_yaml() -> str:
    """Sample tool YAML for testing."""
    return """
name: echo
type: cli
command: echo
args: "{text}"
description: Echo text back
"""


@pytest.fixture
def sample_skill_source() -> str:
    """Sample skill source code for testing."""
    return '''"""Double a number."""

def run(n: int) -> int:
    return n * 2
'''


@pytest.fixture
def sample_artifact_data() -> dict[str, Any]:
    """Sample artifact data for testing."""
    return {
        "name": "test_artifact",
        "data": {"key": "value", "count": 42},
        "description": "Test artifact for unit tests",
    }


# --- Testcontainers Redis Fixtures ---


@pytest.fixture(scope="function")
def redis_container():
    """Spin up a fresh Redis container per test using testcontainers.

    Each test gets an isolated Redis instance - no cross-test pollution.
    Container starts in ~1-2 seconds on Linux.
    """
    if not TESTCONTAINERS_AVAILABLE:
        pytest.skip("testcontainers[redis] not installed")

    with RedisContainer(image="redis:7-alpine") as container:
        yield container


@pytest.fixture
def redis_client(redis_container):
    """Get a Redis client connected to the testcontainer."""
    return redis_container.get_client()


@pytest.fixture
def redis_url(redis_container) -> str:
    """Get the Redis URL for the testcontainer."""
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)
    return f"redis://{host}:{port}"
