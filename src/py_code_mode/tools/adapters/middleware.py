"""ToolAdapter wrapper that applies tool call middleware."""

from __future__ import annotations

import uuid
from typing import Any

from py_code_mode.tools.adapters.base import ToolAdapter
from py_code_mode.tools.middleware import ToolCallContext, ToolMiddleware, compose_tool_middlewares
from py_code_mode.tools.types import Tool


class MiddlewareAdapter:
    """Wrap a ToolAdapter with a middleware chain for call_tool()."""

    def __init__(
        self,
        inner: ToolAdapter,
        middlewares: tuple[ToolMiddleware, ...],
        *,
        executor_type: str | None = None,
        origin: str | None = None,
    ) -> None:
        self._inner = inner
        self._middlewares = middlewares
        self._executor_type = executor_type
        self._origin = origin

    @property
    def inner(self) -> ToolAdapter:
        return self._inner

    def list_tools(self) -> list[Tool]:
        return self._inner.list_tools()

    async def describe(self, tool_name: str, callable_name: str) -> dict[str, str]:
        return await self._inner.describe(tool_name, callable_name)

    async def call_tool(
        self,
        name: str,
        callable_name: str | None,
        args: dict[str, Any],
    ) -> Any:
        if not self._middlewares:
            return await self._inner.call_tool(name, callable_name, args)

        ctx = ToolCallContext(
            tool_name=name,
            callable_name=callable_name,
            args=args,
            adapter_name=type(self._inner).__name__,
            executor_type=self._executor_type,
            origin=self._origin,
            request_id=uuid.uuid4().hex,
        )

        async def _terminal(c: ToolCallContext) -> Any:
            return await self._inner.call_tool(c.tool_name, c.callable_name, c.args)

        chain = compose_tool_middlewares(self._middlewares, _terminal)
        return await chain(ctx)

    async def close(self) -> None:
        await self._inner.close()
