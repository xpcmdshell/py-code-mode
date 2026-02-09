from __future__ import annotations

from typing import Any

import pytest

from py_code_mode.tools import ToolCallContext, ToolMiddleware, ToolRegistry
from py_code_mode.tools.types import Tool, ToolCallable, ToolParameter


class _FakeAdapter:
    def __init__(self, tool_name: str = "echo") -> None:
        self._tool_name = tool_name
        self.calls: list[tuple[str, str | None, dict[str, Any]]] = []

    def list_tools(self) -> list[Tool]:
        return [
            Tool(
                name=self._tool_name,
                description="Echo",
                callables=(
                    ToolCallable(
                        name="say",
                        description="Say",
                        parameters=(
                            ToolParameter(
                                name="message",
                                type="str",
                                required=True,
                                default=None,
                                description="msg",
                            ),
                        ),
                    ),
                ),
            )
        ]

    async def call_tool(self, name: str, callable_name: str | None, args: dict[str, Any]) -> Any:
        self.calls.append((name, callable_name, dict(args)))
        return {"ok": True, "name": name, "callable": callable_name, "args": dict(args)}

    async def describe(self, tool_name: str, callable_name: str) -> dict[str, str]:
        return {"message": "msg"}

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_tool_middleware_wraps_registry_call_tool() -> None:
    adapter = _FakeAdapter()
    registry = ToolRegistry()
    registry.register_adapter(adapter)  # registers echo

    events: list[str] = []

    class _Recorder(ToolMiddleware):
        async def __call__(self, ctx: ToolCallContext, call_next):  # type: ignore[override]
            events.append(f"pre:{ctx.full_name}:{ctx.executor_type}:{ctx.origin}")
            out = await call_next(ctx)
            events.append(f"post:{ctx.full_name}")
            return out

    registry.apply_tool_middlewares(
        (_Recorder(),),
        executor_type="deno-sandbox",
        origin="deno-sandbox",
    )

    res = await registry.call_tool("echo", "say", {"message": "hi"})
    assert res["ok"] is True
    assert adapter.calls == [("echo", "say", {"message": "hi"})]
    assert events == [
        "pre:echo.say:deno-sandbox:deno-sandbox",
        "post:echo.say",
    ]


@pytest.mark.asyncio
async def test_tool_middleware_can_rewrite_args() -> None:
    adapter = _FakeAdapter()
    registry = ToolRegistry()
    registry.register_adapter(adapter)

    class _Rewrite(ToolMiddleware):
        async def __call__(self, ctx: ToolCallContext, call_next):  # type: ignore[override]
            ctx.args["message"] = "rewritten"
            return await call_next(ctx)

    registry.apply_tool_middlewares(
        (_Rewrite(),),
        executor_type="deno-sandbox",
        origin="deno-sandbox",
    )

    res = await registry.call_tool("echo", "say", {"message": "hi"})
    assert res["args"]["message"] == "rewritten"
    assert adapter.calls == [("echo", "say", {"message": "rewritten"})]


@pytest.mark.asyncio
async def test_tool_middleware_can_short_circuit() -> None:
    from py_code_mode.errors import ToolCallError

    adapter = _FakeAdapter()
    registry = ToolRegistry()
    registry.register_adapter(adapter)

    class _Deny(ToolMiddleware):
        async def __call__(self, ctx: ToolCallContext, call_next):  # type: ignore[override]
            raise RuntimeError(f"denied: {ctx.full_name}")

    registry.apply_tool_middlewares((_Deny(),), executor_type="deno-sandbox", origin="deno-sandbox")

    with pytest.raises(ToolCallError, match="denied: echo.say"):
        await registry.call_tool("echo", "say", {"message": "hi"})
    assert adapter.calls == []


@pytest.mark.asyncio
async def test_tool_middleware_applies_to_new_adapters_registered_later() -> None:
    adapter1 = _FakeAdapter("echo1")
    registry = ToolRegistry()
    registry.register_adapter(adapter1)

    events: list[str] = []

    class _Recorder(ToolMiddleware):
        async def __call__(self, ctx: ToolCallContext, call_next):  # type: ignore[override]
            events.append(f"pre:{ctx.full_name}")
            return await call_next(ctx)

    registry.apply_tool_middlewares(
        (_Recorder(),), executor_type="deno-sandbox", origin="deno-sandbox"
    )

    # Register a new adapter after middleware is applied.
    adapter2 = _FakeAdapter("echo2")
    registry.register_adapter(adapter2)

    res = await registry.call_tool("echo2", "say", {"message": "hi"})
    assert res["ok"] is True
    assert events == ["pre:echo2.say"]


@pytest.mark.asyncio
async def test_apply_tool_middlewares_replaces_chain_not_stacks() -> None:
    adapter = _FakeAdapter()
    registry = ToolRegistry()
    registry.register_adapter(adapter)

    events: list[str] = []

    class _RecorderA(ToolMiddleware):
        async def __call__(self, ctx: ToolCallContext, call_next):  # type: ignore[override]
            events.append("A")
            return await call_next(ctx)

    class _RecorderB(ToolMiddleware):
        async def __call__(self, ctx: ToolCallContext, call_next):  # type: ignore[override]
            events.append("B")
            return await call_next(ctx)

    registry.apply_tool_middlewares(
        (_RecorderA(),), executor_type="deno-sandbox", origin="deno-sandbox"
    )
    registry.apply_tool_middlewares(
        (_RecorderB(),), executor_type="deno-sandbox", origin="deno-sandbox"
    )

    await registry.call_tool("echo", "say", {"message": "hi"})
    assert events == ["B"]
