"""Test fixtures for py-code-mode."""

import fnmatch
import functools
import os
import shutil
import subprocess
from datetime import UTC, datetime
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


# =============================================================================
# Docker Image Staleness Check
# =============================================================================

DOCKER_IMAGE_NAME = "py-code-mode-tools:latest"
PROJECT_ROOT = Path(__file__).parent.parent


def _get_docker_image_creation_time() -> datetime | None:
    """Get the creation timestamp of the Docker image.

    Returns None if:
    - Docker is not available
    - Docker daemon is not running
    - Image does not exist
    """
    try:
        import docker

        client = docker.from_env()
        image = client.images.get(DOCKER_IMAGE_NAME)
        # Image.attrs['Created'] is ISO format string like '2024-01-15T10:30:00.123456789Z'
        created_str = image.attrs["Created"]
        # Parse ISO format, handling nanoseconds by truncating to microseconds
        if "." in created_str:
            base, frac = created_str.rsplit(".", 1)
            # Remove trailing 'Z' and truncate to 6 digits (microseconds)
            frac = frac.rstrip("Z")[:6]
            created_str = f"{base}.{frac}+00:00"
        else:
            created_str = created_str.rstrip("Z") + "+00:00"
        return datetime.fromisoformat(created_str)
    except ImportError:
        # Docker SDK not installed
        return None
    except Exception:
        # Docker not running or image not found
        return None


def _get_source_modification_time() -> datetime:
    """Get the most recent modification time of source files.

    Checks:
    - src/py_code_mode/**/*.py
    - docker/*
    - pyproject.toml
    """
    latest_mtime = 0.0

    # Check source files
    src_dir = PROJECT_ROOT / "src" / "py_code_mode"
    if src_dir.exists():
        for py_file in src_dir.rglob("*.py"):
            mtime = py_file.stat().st_mtime
            if mtime > latest_mtime:
                latest_mtime = mtime

    # Check docker directory
    docker_dir = PROJECT_ROOT / "docker"
    if docker_dir.exists():
        for docker_file in docker_dir.iterdir():
            if docker_file.is_file():
                mtime = docker_file.stat().st_mtime
                if mtime > latest_mtime:
                    latest_mtime = mtime

    # Check pyproject.toml
    pyproject = PROJECT_ROOT / "pyproject.toml"
    if pyproject.exists():
        mtime = pyproject.stat().st_mtime
        if mtime > latest_mtime:
            latest_mtime = mtime

    return datetime.fromtimestamp(latest_mtime, tz=UTC)


def _check_docker_image_staleness() -> str | None:
    """Check if Docker image is stale relative to source files.

    Returns:
        Error message if stale/missing, None if up-to-date
    """
    image_time = _get_docker_image_creation_time()

    if image_time is None:
        return f"Docker image '{DOCKER_IMAGE_NAME}' not found."

    source_time = _get_source_modification_time()

    if source_time > image_time:
        return (
            f"Docker image '{DOCKER_IMAGE_NAME}' is stale. "
            f"Image built: {image_time.isoformat()}, "
            f"Source modified: {source_time.isoformat()}."
        )

    return None


def _rebuild_docker_image() -> None:
    """Rebuild the Docker images from project root.

    Raises:
        pytest.fail: If either docker build command fails.
    """
    # Build base image first
    result = subprocess.run(
        ["docker", "build", "-f", "docker/Dockerfile.base", "-t", "py-code-mode:base", "."],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.fail(
            f"Failed to build py-code-mode:base image.\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )

    # Build tools image
    result = subprocess.run(
        ["docker", "build", "-f", "docker/Dockerfile.tools", "-t", DOCKER_IMAGE_NAME, "."],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.fail(
            f"Failed to build {DOCKER_IMAGE_NAME} image.\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )


@pytest.fixture(scope="session")
def docker_image_check():
    """Session-scoped fixture that rebuilds Docker image if stale.

    This fixture is automatically used by container tests via the
    pytest_collection_modifyitems hook below. If the image is missing
    or stale, it will be rebuilt automatically.
    """
    staleness_reason = _check_docker_image_staleness()
    if staleness_reason:
        print(f"\n{staleness_reason} Rebuilding...")
        _rebuild_docker_image()
        print("Docker image rebuilt successfully.")


def pytest_collection_modifyitems(config, items):  # noqa: ARG001
    """Add docker_image_check fixture to all tests in xdist_group('docker')."""
    for item in items:
        # Check if test is in the docker xdist group
        for marker in item.iter_markers("xdist_group"):
            if marker.args and marker.args[0] == "docker":
                # Add the fixture as a dependency
                if "docker_image_check" not in item.fixturenames:
                    item.fixturenames.insert(0, "docker_image_check")


class MockAdapter:
    """Mock adapter for testing."""

    def __init__(
        self,
        tools: list[ToolDefinition] | list[str],
        call_results: dict[str, Any] | None = None,
    ) -> None:
        from py_code_mode.tools.types import Tool, ToolCallable

        self._call_log: list[tuple[str, dict[str, Any]]] = []
        self._responses: dict[str, Any] = call_results or {}

        # Build Tool objects
        self._tools: list[Tool] = []
        if tools and isinstance(tools[0], str):
            for name in tools:
                callable_obj = ToolCallable(
                    name=name,
                    description=f"Mock {name}",
                    parameters=(),
                )
                tool = Tool(
                    name=name,
                    description=f"Mock {name}",
                    callables=(callable_obj,),
                )
                self._tools.append(tool)
        else:
            # tools is list[ToolDefinition]
            for td in tools:  # type: ignore[union-attr]
                callable_obj = ToolCallable(
                    name=td.name,
                    description=td.description,
                    parameters=(),
                )
                tool = Tool(
                    name=td.name,
                    description=td.description,
                    callables=(callable_obj,),
                    tags=td.tags,
                )
                self._tools.append(tool)

    def set_response(self, tool_name: str, response: Any) -> None:
        """Set the response for a tool call."""
        self._responses[tool_name] = response

    def list_tools(self) -> list:
        """Return Tool objects."""
        return self._tools

    async def call_tool(
        self,
        name: str,
        callable_name: str | None,
        args: dict[str, Any],
    ) -> Any:
        """Call a tool."""
        self._call_log.append((name, args))
        if name in self._responses:
            return self._responses[name]
        return {"status": "ok", "tool": name, "args": args}

    async def describe(self, tool_name: str, callable_name: str) -> dict[str, str]:
        """Get parameter descriptions for a callable.

        Args:
            tool_name: Name of the tool.
            callable_name: Name of the callable.

        Returns:
            Dict mapping parameter names to descriptions.
        """
        return {}

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


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    """Clean up orphaned Docker containers after test session.

    This hook runs after all tests complete (success, failure, or interruption).
    It ensures that any py-code-mode-tools containers that weren't properly
    cleaned up get stopped and removed.
    """
    try:
        import logging  # noqa: PLC0415

        import docker  # noqa: PLC0415

        logger = logging.getLogger(__name__)
        client = docker.from_env()

        # Find all running containers with our test image
        containers = client.containers.list(
            filters={"ancestor": "py-code-mode-tools:latest", "status": "running"}
        )

        if containers:
            logger.warning(
                f"Found {len(containers)} orphaned py-code-mode-tools containers. Cleaning up..."
            )

            for container in containers:
                container_id = container.id[:12]
                try:
                    logger.info(f"Stopping container {container_id}")
                    container.stop(timeout=5)
                    logger.info(f"Removing container {container_id}")
                    container.remove()
                except Exception as e:
                    logger.error(f"Failed to clean up container {container_id}: {e}")

    except ImportError:
        # Docker not available, skip cleanup
        pass
    except Exception:  # noqa: BLE001
        # Don't fail tests because of cleanup errors
        pass


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
description: Echo text back

schema:
  positional:
    - name: text
      type: string
      required: true
      description: Text to echo

recipes:
  echo:
    description: Echo text
    params:
      text: {}
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


@pytest.fixture
def nmap_yaml(tmp_path: Path) -> Path:
    """Create nmap.yaml with schema + recipes."""
    content = """
name: nmap
description: Network scanner
command: nmap
timeout: 300

schema:
  options:
    sS: {type: boolean, short: sS, description: TCP SYN scan}
    sV: {type: boolean, short: sV, description: Version detection}
    Pn: {type: boolean, short: Pn, description: Skip host discovery}
    p: {type: string, short: p, description: Port ranges}
    oX: {type: string, short: oX, description: XML output file}
  positional:
    - name: target
      type: string
      required: true
      description: Target host or network

recipes:
  syn_scan:
    description: Stealthy TCP SYN scan
    preset:
      sS: true
      Pn: true
    params:
      target: {}
      p: {default: "-"}

  quick:
    description: Fast scan of common ports
    preset:
      sS: true
      p: "22,80,443,8080,8443"
    params:
      target: {}
"""
    file = tmp_path / "nmap.yaml"
    file.write_text(content)
    return file


@pytest.fixture
def simple_tool_yaml(tmp_path: Path) -> Path:
    """Simple tool with one recipe."""
    content = """
name: ping
description: ICMP ping
command: ping
timeout: 10

schema:
  options:
    c: {type: integer, short: c, description: Count}
  positional:
    - name: host
      type: string
      required: true
      description: Target host

recipes:
  ping:
    description: Ping a host
    params:
      host: {}
      c: {required: false}
"""
    file = tmp_path / "ping.yaml"
    file.write_text(content)
    return file
