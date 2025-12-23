"""Tests for ToolProxy explicit call methods.

ToolProxy and CallableProxy should have explicit call_async() and call_sync()
methods that always behave predictably, unlike __call__ which varies by context.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from py_code_mode.tools import ToolRegistry
from py_code_mode.tools.namespace import CallableProxy, ToolProxy, ToolsNamespace
from py_code_mode.tools.types import Tool, ToolCallable, ToolParameter


@pytest.fixture
def mock_registry() -> ToolRegistry:
    """Create a registry with a mock adapter."""
    registry = ToolRegistry()

    # Create a mock adapter with list_tools (not get_all_tools)
    mock_adapter = MagicMock()
    mock_adapter.list_tools.return_value = [
        Tool(
            name="testtool",
            description="A test tool",
            callables=[
                ToolCallable(
                    name="action",
                    description="Do an action",
                    parameters=[ToolParameter(name="value", type="string", required=True)],
                )
            ],
        )
    ]

    # call_tool returns async result
    async def mock_call_tool(
        tool_name: str, callable_name: str | None, kwargs: dict[str, Any]
    ) -> str:
        return f"called {tool_name}.{callable_name} with {kwargs}"

    mock_adapter.call_tool = AsyncMock(side_effect=mock_call_tool)

    registry.add_adapter(mock_adapter)
    return registry


@pytest.fixture
def tool_proxy(mock_registry: ToolRegistry) -> ToolProxy:
    """Create a ToolProxy for testtool."""
    tools = mock_registry.get_all_tools()
    tool = next(t for t in tools if t.name == "testtool")
    return ToolProxy(mock_registry, tool, loop=None)


@pytest.fixture
def callable_proxy(mock_registry: ToolRegistry) -> CallableProxy:
    """Create a CallableProxy for testtool.action."""
    tools = mock_registry.get_all_tools()
    tool = next(t for t in tools if t.name == "testtool")
    callable_obj = next(c for c in tool.callables if c.name == "action")
    return CallableProxy(mock_registry, "testtool", callable_obj, loop=None)


class TestCallAsyncReturnsCoroutine:
    """call_async() always returns an awaitable."""

    @pytest.mark.asyncio
    async def test_tool_proxy_call_async_returns_coroutine(self, tool_proxy: ToolProxy) -> None:
        """ToolProxy.call_async() returns awaitable."""
        result = tool_proxy.call_async(value="test")

        # Should be a coroutine
        assert inspect.iscoroutine(result)

        # Should be awaitable
        final = await result
        assert "testtool" in final

    @pytest.mark.asyncio
    async def test_callable_proxy_call_async_returns_coroutine(
        self, callable_proxy: CallableProxy
    ) -> None:
        """CallableProxy.call_async() returns awaitable."""
        result = callable_proxy.call_async(value="test")

        # Should be a coroutine
        assert inspect.iscoroutine(result)

        # Should be awaitable
        final = await result
        assert "testtool.action" in final

    @pytest.mark.asyncio
    async def test_call_async_works_in_async_context(self, callable_proxy: CallableProxy) -> None:
        """call_async works from async context."""
        result = await callable_proxy.call_async(value="from_async")
        assert "from_async" in result


class TestCallSyncReturnsResult:
    """call_sync() always blocks and returns result directly."""

    def test_tool_proxy_call_sync_returns_result(self, tool_proxy: ToolProxy) -> None:
        """ToolProxy.call_sync() blocks and returns result."""
        result = tool_proxy.call_sync(value="sync_test")

        # Should NOT be a coroutine
        assert not inspect.iscoroutine(result)

        # Should be the actual result string
        assert isinstance(result, str)
        assert "testtool" in result

    def test_callable_proxy_call_sync_returns_result(self, callable_proxy: CallableProxy) -> None:
        """CallableProxy.call_sync() blocks and returns result."""
        result = callable_proxy.call_sync(value="sync_test")

        # Should NOT be a coroutine
        assert not inspect.iscoroutine(result)

        # Should be the actual result string
        assert isinstance(result, str)
        assert "testtool.action" in result

    def test_call_sync_never_returns_coroutine(self, callable_proxy: CallableProxy) -> None:
        """call_sync() never returns a coroutine, always blocks."""
        # Call multiple times to ensure consistency
        for i in range(3):
            result = callable_proxy.call_sync(value=f"test_{i}")
            assert not inspect.iscoroutine(result)
            assert isinstance(result, str)


class TestCallSyncWithLoopReference:
    """call_sync() works from thread when loop reference is provided."""

    def test_call_sync_uses_loop_when_available(self, mock_registry: ToolRegistry) -> None:
        """call_sync uses run_coroutine_threadsafe with loop reference."""
        # Get tool and callable
        tools = mock_registry.get_all_tools()
        tool = next(t for t in tools if t.name == "testtool")
        callable_obj = next(c for c in tool.callables if c.name == "action")

        # Create proxy with a loop reference
        loop = asyncio.new_event_loop()

        try:
            # Start the loop in a thread
            import threading

            loop_thread = threading.Thread(target=loop.run_forever, daemon=True)
            loop_thread.start()

            proxy = CallableProxy(mock_registry, "testtool", callable_obj, loop=loop)

            # call_sync should work even though we're not in the loop's thread
            result = proxy.call_sync(value="threaded")

            assert not inspect.iscoroutine(result)
            assert "testtool.action" in result
            assert "threaded" in result
        finally:
            loop.call_soon_threadsafe(loop.stop)
            loop_thread.join(timeout=1.0)
            loop.close()

    @pytest.mark.asyncio
    async def test_call_sync_from_executor_thread(self, mock_registry: ToolRegistry) -> None:
        """call_sync works when called from asyncio.to_thread context."""
        tools = mock_registry.get_all_tools()
        tool = next(t for t in tools if t.name == "testtool")
        callable_obj = next(c for c in tool.callables if c.name == "action")

        loop = asyncio.get_running_loop()
        proxy = CallableProxy(mock_registry, "testtool", callable_obj, loop=loop)

        # Simulate executor calling from thread
        def thread_work() -> str:
            return proxy.call_sync(value="from_thread")

        result = await asyncio.to_thread(thread_work)

        assert "testtool.action" in result
        assert "from_thread" in result


class TestBackwardCompatibility:
    """__call__ still works as before."""

    @pytest.mark.asyncio
    async def test_dunder_call_still_works_async(self, callable_proxy: CallableProxy) -> None:
        """__call__ from async context still returns coroutine."""
        result = callable_proxy(value="dunder_async")

        # In async context, __call__ returns coroutine
        assert inspect.iscoroutine(result)

        final = await result
        assert "testtool.action" in final

    def test_dunder_call_still_works_sync(self, callable_proxy: CallableProxy) -> None:
        """__call__ from sync context still returns result."""
        result = callable_proxy(value="dunder_sync")

        # In sync context (no running loop), __call__ runs and returns result
        assert not inspect.iscoroutine(result)
        assert "testtool.action" in result

    def test_tool_proxy_dunder_call_works(self, tool_proxy: ToolProxy) -> None:
        """ToolProxy.__call__ still works."""
        result = tool_proxy(value="direct")

        assert not inspect.iscoroutine(result)
        assert "testtool" in result


class TestToolsNamespaceIntegration:
    """Explicit methods work through ToolsNamespace."""

    @pytest.mark.asyncio
    async def test_namespace_access_call_async(self, mock_registry: ToolRegistry) -> None:
        """tools.X.Y.call_async() works."""
        namespace = ToolsNamespace(mock_registry)

        result = await namespace.testtool.action.call_async(value="via_namespace")

        assert "testtool.action" in result
        assert "via_namespace" in result

    def test_namespace_access_call_sync(self, mock_registry: ToolRegistry) -> None:
        """tools.X.Y.call_sync() works."""
        namespace = ToolsNamespace(mock_registry)

        result = namespace.testtool.action.call_sync(value="via_namespace_sync")

        assert "testtool.action" in result
        assert "via_namespace_sync" in result
