"""Container-based code executor.

ContainerExecutor provides the same interface as InProcessExecutor but executes
code inside a Docker container for process isolation.

Capabilities:
- TIMEOUT: Yes (via session server)
- PROCESS_ISOLATION: Yes (Docker container)
- RESET: Yes (can reset session state)

Usage:
    config = ContainerConfig(image="py-code-mode-tools:latest")
    async with ContainerExecutor(config) as executor:
        result = await executor.run('tools.call("cli.nmap", {"target": "10.0.0.1"})')
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

try:
    from docker.models.containers import Container

    import docker

    DOCKER_AVAILABLE = True
except ImportError:
    DOCKER_AVAILABLE = False
    docker = None  # type: ignore
    Container = None  # type: ignore

from py_code_mode.backend import (
    Capability,
    StorageAccess,
    register_backend,
)
from py_code_mode.backends.container.client import SessionClient
from py_code_mode.backends.container.config import ContainerConfig
from py_code_mode.types import ExecutionResult


def _transform_localhost_for_docker(url: str) -> str:
    """Transform localhost URLs for access from inside Docker containers.

    Inside a Docker container, 'localhost' refers to the container itself,
    not the host machine. On macOS/Windows, use 'host.docker.internal' to
    reach host services from within containers.

    Args:
        url: Original URL (e.g., redis://localhost:6379)

    Returns:
        Transformed URL (e.g., redis://host.docker.internal:6379)
    """
    import platform
    from urllib.parse import urlparse, urlunparse

    parsed = urlparse(url)
    if parsed.hostname in ("localhost", "127.0.0.1"):
        # macOS and Windows Docker Desktop support host.docker.internal
        # Linux requires --add-host or host network mode
        if platform.system() in ("Darwin", "Windows"):
            # Replace hostname while preserving port and other components
            netloc = (
                f"host.docker.internal:{parsed.port}"
                if parsed.port
                else "host.docker.internal"
            )
            return urlunparse(parsed._replace(netloc=netloc))
    return url


class ContainerExecutor:
    """Execute code inside a Docker container.

    This is a drop-in replacement for InProcessExecutor that provides
    isolation via Docker containers. The container runs a session
    server that maintains persistent state.

    Capabilities:
    - TIMEOUT: Yes
    - PROCESS_ISOLATION: Yes
    - RESET: Yes
    """

    # Capabilities this backend supports
    _CAPABILITIES = frozenset(
        {
            Capability.TIMEOUT,
            Capability.PROCESS_ISOLATION,
            Capability.RESET,
        }
    )

    def __init__(self, config: ContainerConfig) -> None:
        """Initialize container executor.

        Args:
            config: Container configuration.
        """
        if not DOCKER_AVAILABLE:
            raise ImportError(
                "docker required for ContainerExecutor. Install with: pip install docker"
            )

        self.config = config
        self._docker: Any = None
        self._container: Container | None = None
        self._client: SessionClient | None = None
        self._port: int | None = None

    @classmethod
    async def create(
        cls,
        artifacts: str | None = None,
        skills: str | None = None,
        tools: str | None = None,
        image: str = "py-code-mode-tools:latest",
        timeout: float = 30.0,
        **kwargs: Any,
    ) -> ContainerExecutor:
        """Create container executor from factory kwargs.

        NOTE: This is a convenience factory. Prefer using Session API
        which handles storage access wiring automatically.

        Args:
            artifacts: Path to artifacts directory on host.
            skills: Path to skills directory on host.
            tools: Path to tools directory on host.
            image: Docker image to use.
            timeout: Default execution timeout.
            **kwargs: Additional options (ignored for compatibility).

        Returns:
            Started ContainerExecutor.
        """
        from pathlib import Path

        from py_code_mode.backend import FileStorageAccess

        config = ContainerConfig(
            image=image,
            timeout=timeout,
        )

        # Build storage access from paths
        storage_access = FileStorageAccess(
            tools_path=Path(tools) if tools else None,
            skills_path=Path(skills) if skills else None,
            artifacts_path=Path(artifacts) if artifacts else Path("/tmp/artifacts"),
        )

        executor = cls(config)
        await executor.start(storage_access=storage_access)
        return executor

    def supports(self, capability: str) -> bool:
        """Check if this backend supports a capability."""
        return capability in self._CAPABILITIES

    def supported_capabilities(self) -> set[str]:
        """Return set of all capabilities this backend supports."""
        return set(self._CAPABILITIES)

    async def __aenter__(self) -> ContainerExecutor:
        """Start container and connect."""
        await self.start()
        return self

    async def __aexit__(self, *args: object) -> None:
        """Stop container and cleanup."""
        await self.close()

    def _create_docker_client(self) -> Any:
        """Create Docker client, trying multiple socket locations if needed."""
        from pathlib import Path

        # Try standard from_env first (respects DOCKER_HOST)
        try:
            client = docker.from_env()
            client.ping()
            return client
        except Exception:
            pass

        # Common socket locations across platforms
        socket_paths = [
            Path.home()
            / ".docker"
            / "run"
            / "docker.sock",  # Docker Desktop (macOS/Windows)
            Path("/var/run/docker.sock"),  # Linux default
            Path("/run/docker.sock"),  # Some Linux distros
        ]

        for socket_path in socket_paths:
            if socket_path.exists():
                try:
                    client = docker.DockerClient(base_url=f"unix://{socket_path}")
                    client.ping()
                    return client
                except Exception:
                    continue

        raise RuntimeError(
            "Could not connect to Docker. Make sure Docker is running.\n"
            "Tried DOCKER_HOST env var and common socket locations."
        )

    def _find_project_root(self) -> Any:
        """Find project root by looking for docker/ directory.

        Returns:
            Path to project root.

        Raises:
            RuntimeError: If project root cannot be found.
        """
        from pathlib import Path

        # Start from this file's location and walk up
        current = Path(__file__).resolve().parent
        while current != current.parent:
            if (current / "docker" / "Dockerfile.base").exists():
                return current
            current = current.parent
        raise RuntimeError(
            "Could not find project root with docker/ directory. "
            "This likely means py-code-mode is installed from a package. "
            "Please build the image manually:\n"
            "  docker build -f docker/Dockerfile.base -t py-code-mode:base .\n"
            f"  docker build -f docker/Dockerfile.tools -t {self.config.image} ."
        )

    def _ensure_image_exists(self) -> None:
        """Build Docker image if it doesn't exist.

        Raises:
            RuntimeError: If image doesn't exist and auto_build is disabled,
                        or if build fails.
        """
        # Check if image exists
        try:
            self._docker.images.get(self.config.image)
            return  # Image exists, no need to build
        except docker.errors.ImageNotFound:
            pass  # Image not found, continue to build logic

        # Image doesn't exist
        if not self.config.auto_build:
            raise RuntimeError(
                f"Docker image '{self.config.image}' not found. "
                "Build it with:\n"
                f"  docker build -f docker/Dockerfile.base -t py-code-mode:base .\n"
                f"  docker build -f docker/Dockerfile.tools -t {self.config.image} ."
            )

        # Auto-build enabled - build the image
        self._build_image()

    def _build_image(self) -> None:
        """Build the Docker image from Dockerfiles.

        Raises:
            RuntimeError: If build fails or project root cannot be found.
        """
        import logging

        logger = logging.getLogger(__name__)

        # Find project root (where docker/ directory is)
        project_root = self._find_project_root()

        # Check if base image exists, build if missing
        base_image_exists = False
        try:
            self._docker.images.get("py-code-mode:base")
            base_image_exists = True
        except docker.errors.ImageNotFound:
            pass

        if not base_image_exists:
            logger.info("Building py-code-mode:base image...")
            try:
                self._docker.images.build(
                    path=str(project_root),
                    dockerfile="docker/Dockerfile.base",
                    tag="py-code-mode:base",
                    rm=True,
                )
                logger.info("Successfully built py-code-mode:base")
            except Exception as e:
                raise RuntimeError(f"Failed to build base image: {e}") from e

        # Build tools image
        logger.info(f"Building {self.config.image} image...")
        try:
            self._docker.images.build(
                path=str(project_root),
                dockerfile="docker/Dockerfile.tools",
                tag=self.config.image,
                rm=True,
            )
            logger.info(f"Successfully built {self.config.image}")
        except Exception as e:
            raise RuntimeError(f"Failed to build tools image: {e}") from e

    async def start(
        self,
        storage_access: StorageAccess | None = None,
    ) -> None:
        """Start the container and wait for it to be healthy.

        Args:
            storage_access: Storage access descriptor from Session.
                           Determines volume mounts (FileStorageAccess) or
                           Redis connection (RedisStorageAccess).
        """
        from py_code_mode.backend import FileStorageAccess, RedisStorageAccess

        # Initialize Docker client with fallback socket detection
        self._docker = self._create_docker_client()

        # Ensure image exists (build if needed and auto_build=True)
        self._ensure_image_exists()

        # Extract paths/urls from storage access
        tools_path = None
        skills_path = None
        artifacts_path = None
        redis_url = None

        if storage_access is None:
            # No storage access - proceed with defaults
            pass
        elif isinstance(storage_access, FileStorageAccess):
            tools_path = storage_access.tools_path
            skills_path = storage_access.skills_path
            artifacts_path = storage_access.artifacts_path
            # Create directories on host before mounting
            # Skills need to exist for volume mount
            if skills_path:
                skills_path.mkdir(parents=True, exist_ok=True)
            # Artifacts need to exist for volume mount
            if artifacts_path:
                artifacts_path.mkdir(parents=True, exist_ok=True)
        elif isinstance(storage_access, RedisStorageAccess):
            redis_url = storage_access.redis_url
            # Transform localhost URLs for Docker container access
            # Inside container, localhost refers to container itself, not host
            if redis_url:
                redis_url = _transform_localhost_for_docker(redis_url)

        # Prepare container config with storage access
        docker_config = self.config.to_docker_config(
            tools_path=tools_path,
            skills_path=skills_path,
            artifacts_path=artifacts_path,
            redis_url=redis_url,
        )

        # Start container
        self._container = self._docker.containers.run(**docker_config)

        try:
            # Get assigned port
            self._port = self._get_container_port()

            # Create session client
            self._client = SessionClient(
                base_url=f"http://{self.config.host}:{self._port}",
                timeout=self.config.timeout,
            )

            # Wait for container to be healthy
            await self._wait_for_healthy()
        except Exception:
            # Clean up container on any startup failure
            await self.stop()
            raise

    async def stop(self) -> None:
        """Stop and remove the container."""
        if self._client:
            await self._client.close()
            self._client = None

        if self._container:
            try:
                self._container.stop(timeout=10)
            except Exception:
                pass
            try:
                self._container.remove()
            except Exception:
                pass
            self._container = None

    async def close(self) -> None:
        """Release executor resources (protocol method, aliases stop())."""
        await self.stop()

    async def run(
        self,
        code: str,
        timeout: float | None = None,
    ) -> ExecutionResult:
        """Execute code in the container.

        Args:
            code: Python code to execute.
            timeout: Optional execution timeout.

        Returns:
            ExecutionResult with value, stdout, error.
        """
        if self._client is None:
            raise RuntimeError(
                "Container not started. Use 'async with' or call start()"
            )

        result = await self._client.execute(code, timeout=timeout)

        return ExecutionResult(
            value=result.value,
            stdout=result.stdout,
            error=result.error,
        )

    async def reset(self) -> None:
        """Reset the session state inside the container."""
        if self._client is None:
            raise RuntimeError("Container not started")
        await self._client.reset()

    def _get_container_port(self) -> int:
        """Get the host port mapped to container port 8080."""
        if self._container is None:
            raise RuntimeError("Container not started")

        # Refresh container info to get port bindings
        self._container.reload()

        # Get port mapping
        ports = self._container.attrs.get("NetworkSettings", {}).get("Ports", {})
        port_8080 = ports.get("8080/tcp")

        if port_8080 and len(port_8080) > 0:
            return int(port_8080[0]["HostPort"])

        # Fallback to configured port
        if self.config.port > 0:
            return self.config.port

        raise RuntimeError("Could not determine container port")

    async def _wait_for_healthy(self) -> None:
        """Wait for container to be healthy."""
        if self._client is None:
            raise RuntimeError("Client not initialized")

        start_time = time.time()
        while time.time() - start_time < self.config.startup_timeout:
            try:
                health = await self._client.health()
                if health.status == "healthy":
                    return
            except Exception:
                pass

            await asyncio.sleep(self.config.health_check_interval)

        raise TimeoutError(
            f"Container did not become healthy within {self.config.startup_timeout}s"
        )

    @property
    def container_id(self) -> str | None:
        """Get the container ID."""
        if self._container:
            return self._container.id
        return None

    @property
    def port(self) -> int | None:
        """Get the mapped host port."""
        return self._port


# Register this backend
register_backend("container", ContainerExecutor)
