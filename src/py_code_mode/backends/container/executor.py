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

from py_code_mode.backend import Capability, register_backend
from py_code_mode.backends.container.client import SessionClient
from py_code_mode.backends.container.config import ContainerConfig
from py_code_mode.types import ExecutionResult


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

    async def start(self) -> None:
        """Start the container and wait for it to be healthy."""
        # Initialize Docker client
        self._docker = docker.from_env()

        # Prepare container config
        docker_config = self.config.to_docker_config()

        # Create artifacts directory if needed
        if self.config.host_artifacts_path:
            self.config.host_artifacts_path.mkdir(parents=True, exist_ok=True)

        # Start container
        self._container = self._docker.containers.run(**docker_config)

        # Get assigned port
        self._port = self._get_container_port()

        # Create session client
        self._client = SessionClient(
            base_url=f"http://{self.config.host}:{self._port}",
            timeout=self.config.timeout,
        )

        # Wait for container to be healthy
        await self._wait_for_healthy()

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
            raise RuntimeError("Container not started. Use 'async with' or call start()")

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
