"""Tool call middleware and context types.

This layer is designed to be generic: it can be used for audit logging,
allow/deny decisions, interactive approvals, argument rewriting, retries, etc.

Middleware runs on the host side where tools are executed (CLI/MCP/HTTP).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class ToolCallContext:
    """Context for a single tool call.

    Notes:
    - `args` is intentionally mutable to support argument rewriting.
    - `executor_type` and `origin` are best-effort labels (not security boundaries).
    """

    tool_name: str
    callable_name: str | None
    args: dict[str, Any]

    # Optional metadata for middleware consumers.
    adapter_name: str | None = None
    executor_type: str | None = None  # e.g. "deno-sandbox", "subprocess"
    origin: str | None = None  # e.g. "deno-sandbox", "host"
    request_id: str | None = None
    timeout: float | None = None

    @property
    def full_name(self) -> str:
        if self.callable_name:
            return f"{self.tool_name}.{self.callable_name}"
        return self.tool_name


type CallNext = Callable[[ToolCallContext], Awaitable[Any]]


class ToolMiddleware(Protocol):
    async def __call__(self, ctx: ToolCallContext, call_next: CallNext) -> Any: ...


def compose_tool_middlewares(
    middlewares: tuple[ToolMiddleware, ...],
    terminal: CallNext,
) -> CallNext:
    """Compose middlewares around a terminal call.

    Middleware order is outer-to-inner:
        middlewares[0] wraps middlewares[1] wraps ... wraps terminal
    """

    call_next = terminal
    for mw in reversed(middlewares):

        async def _wrapped(
            ctx: ToolCallContext,
            _mw: ToolMiddleware = mw,
            _n: CallNext = call_next,
        ):
            return await _mw(ctx, _n)

        call_next = _wrapped

    return call_next
