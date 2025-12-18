"""HTTP adapter for wrapping REST APIs as tools."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from py_code_mode.errors import ToolCallError, ToolNotFoundError
from py_code_mode.types import JsonSchema, ToolDefinition


@dataclass
class Endpoint:
    """Definition of an HTTP API endpoint as a tool.

    Args:
        name: Tool name for this endpoint.
        method: HTTP method (GET, POST, PUT, DELETE, etc.).
        path: URL path, can include {param} placeholders.
        description: Description of what the endpoint does.
        parameters: Optional parameter schema.
    """

    name: str
    method: str
    path: str
    description: str
    parameters: dict[str, JsonSchema] = field(default_factory=dict)


class HTTPAdapter:
    """Adapter for wrapping REST APIs as tools.

    Allows defining HTTP endpoints as tools that agents can call.

    Usage:
        adapter = HTTPAdapter(base_url="http://api.example.com")
        adapter.add_endpoint(Endpoint(
            name="get_user",
            method="GET",
            path="/users/{user_id}",
            description="Get user by ID",
            parameters={"user_id": JsonSchema(type="integer")}
        ))

        # Use through registry
        registry = ToolRegistry()
        await registry.register_adapter(adapter)
    """

    def __init__(
        self,
        base_url: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Initialize adapter with base URL.

        Args:
            base_url: Base URL for all API requests.
            headers: Optional default headers for all requests.
        """
        self.base_url = base_url.rstrip("/")
        self.headers = headers or {}
        self._endpoints: dict[str, Endpoint] = {}

    @property
    def endpoints(self) -> dict[str, Endpoint]:
        """Return registered endpoints."""
        return self._endpoints

    def add_endpoint(self, endpoint: Endpoint) -> None:
        """Register an endpoint as a tool.

        Args:
            endpoint: Endpoint definition.
        """
        self._endpoints[endpoint.name] = endpoint

    async def list_tools(self) -> list[ToolDefinition]:
        """List all endpoints as tools.

        Returns:
            List of ToolDefinition objects.
        """
        tools = []
        for endpoint in self._endpoints.values():
            # Build input schema from parameters
            properties = {}
            required = []
            for param_name, param_schema in endpoint.parameters.items():
                properties[param_name] = param_schema
                # All parameters are required unless they have a default
                required.append(param_name)

            input_schema = JsonSchema(
                type="object",
                properties=properties if properties else None,
                required=required if required else None,
                description=endpoint.description,
            )

            tool_def = ToolDefinition(
                name=endpoint.name,
                description=endpoint.description,
                input_schema=input_schema,
            )
            tools.append(tool_def)

        return tools

    async def call_tool(self, name: str, args: dict[str, Any]) -> Any:
        """Call an HTTP endpoint.

        Args:
            name: Endpoint name.
            args: Request parameters.

        Returns:
            JSON response from the endpoint.

        Raises:
            ToolNotFoundError: If endpoint not found.
            ToolCallError: If HTTP request fails.
        """
        if name not in self._endpoints:
            raise ToolNotFoundError(name)

        endpoint = self._endpoints[name]

        try:
            import aiohttp
        except ImportError as e:
            raise ImportError(
                "aiohttp package required for HTTP adapter. Install with: pip install aiohttp"
            ) from e

        # Build URL with path parameters
        url = self._build_url(endpoint.path, args)

        # Separate path params from body params
        path_params = self._extract_path_params(endpoint.path)
        body_params = {k: v for k, v in args.items() if k not in path_params}

        async with aiohttp.ClientSession(headers=self.headers) as session:
            try:
                if endpoint.method.upper() in ("POST", "PUT", "PATCH"):
                    response = await session.request(
                        endpoint.method.upper(),
                        url,
                        json=body_params if body_params else None,
                    )
                else:
                    response = await session.request(
                        endpoint.method.upper(),
                        url,
                        params=body_params if body_params else None,
                    )

                if response.status >= 400:
                    error_text = await response.text()
                    raise ToolCallError(
                        name,
                        tool_args=args,
                        cause=RuntimeError(f"HTTP {response.status}: {error_text}"),
                    )

                return await response.json()

            except aiohttp.ClientError as e:
                raise ToolCallError(name, tool_args=args, cause=e) from e

    def _build_url(self, path: str, args: dict[str, Any]) -> str:
        """Build full URL with path parameters substituted.

        Args:
            path: URL path template with {param} placeholders.
            args: Arguments to substitute.

        Returns:
            Full URL with parameters substituted.
        """
        # Substitute path parameters
        url = self.base_url + path
        for param_name, param_value in args.items():
            placeholder = "{" + param_name + "}"
            if placeholder in url:
                url = url.replace(placeholder, str(param_value))
        return url

    def _extract_path_params(self, path: str) -> set[str]:
        """Extract parameter names from path template.

        Args:
            path: URL path template.

        Returns:
            Set of parameter names found in path.
        """
        return set(re.findall(r"\{(\w+)\}", path))

    async def close(self) -> None:
        """Clean up resources (no-op for stateless HTTP adapter)."""
        pass
