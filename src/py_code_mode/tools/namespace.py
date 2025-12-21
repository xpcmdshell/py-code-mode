"""Agent-facing namespace layer for tools: tools.X.Y(...)"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from py_code_mode.tools.types import Tool, ToolCallable

if TYPE_CHECKING:
    from py_code_mode.tools.registry import ToolRegistry


class ToolsNamespace:
    """Agent-facing namespace: tools.X.Y(...)

    Provides attribute-based access to tools and their callables.

    Usage:
        # Recipe invocation
        tools.nmap.syn_scan(target="10.0.0.1")
        tools.docker.run(image="nginx", flags="-d")

        # Escape hatch (raw tool invocation)
        tools.echo(text="hello")

        # Discovery
        tools.list()  # List all tools
        tools.search("network")  # Search tools
    """

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Set the event loop to use for async tool calls."""
        self._loop = loop

    def __getattr__(self, tool_name: str) -> ToolProxy:
        """Get a tool proxy by name."""
        # Don't intercept private attributes or special methods
        if tool_name.startswith("_"):
            raise AttributeError(tool_name)

        # Find tool in unified tools list
        all_tools = self._registry.get_all_tools()
        tool = next((t for t in all_tools if t.name == tool_name), None)

        # Tool not found
        if tool is None:
            available = [t.name for t in all_tools]
            raise AttributeError(
                f"Unknown tool: {tool_name}. Available: {', '.join(sorted(available))}"
            )

        return ToolProxy(self._registry, tool, self._loop)

    def list(self) -> list[Tool]:
        """List all available tools."""
        return self._registry.get_all_tools()

    def search(self, query: str, limit: int = 5) -> list[Tool]:
        """Search tools by query string."""
        from py_code_mode.tools.registry import substring_search

        return substring_search(
            query=query,
            items=self._registry.get_all_tools(),
            get_name=lambda t: t.name,
            get_description=lambda t: t.description,
            limit=limit,
        )


class ToolProxy:
    """Proxy for a single tool - enables tools.docker.run(...)

    Provides attribute-based access to tool callables and escape hatch for raw invocation.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        tool: Tool,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self._registry = registry
        self._tool = tool
        self._loop = loop
        self._callables = {c.name: c for c in tool.callables}

    def __call__(self, **kwargs: Any) -> Any:
        """Escape hatch - invoke tool directly without recipe.

        This delegates to the adapter's call_tool method, bypassing recipes.
        """
        tool_name = self._tool.name

        # Define the async execution logic
        async def _execute() -> Any:
            adapter = self._registry.find_adapter_for_tool(tool_name)
            if adapter is None:
                raise RuntimeError(f"No adapter found for tool: {tool_name}")
            return await adapter.call_tool(tool_name, None, kwargs)

        # Check if we're in async context (has running loop)
        try:
            asyncio.get_running_loop()
            # In async context - return coroutine for await
            return _execute()
        except RuntimeError:
            # Not in async context - execute sync
            pass

        # Sync execution path
        coro = _execute()

        # When called from a thread (via executor.run -> to_thread), use
        # the stored loop with run_coroutine_threadsafe to schedule on main loop.
        if self._loop is not None:
            future = asyncio.run_coroutine_threadsafe(coro, self._loop)
            return future.result()

        # Standalone sync usage - create new loop
        return asyncio.run(coro)

    def __getattr__(self, callable_name: str) -> CallableProxy:
        """Get a callable proxy by name."""
        if callable_name not in self._callables:
            raise AttributeError(
                f"Unknown callable: {self._tool.name}.{callable_name}. "
                f"Available: {', '.join(sorted(self._callables.keys()))}"
            )
        return CallableProxy(
            self._registry, self._tool.name, self._callables[callable_name], self._loop
        )

    def list(self) -> list[ToolCallable]:
        """List all callables for this tool."""
        return list(self._tool.callables)


class CallableProxy:
    """Proxy for a single callable - enables invocation and introspection."""

    def __init__(
        self,
        registry: ToolRegistry,
        tool_name: str,
        callable: ToolCallable,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self._registry = registry
        self._tool_name = tool_name
        self._callable = callable
        self._loop = loop

    def __call__(self, **kwargs: Any) -> Any:
        """Invoke the callable with the given arguments.

        Returns a coroutine if called from async context, executes sync otherwise.
        This allows both `await tools.x.y()` and `tools.x.y()` to work.
        """
        tool_name = self._tool_name
        callable_name = self._callable.name

        # Define the async execution logic
        async def _execute() -> Any:
            adapter = self._registry.find_adapter_for_tool(tool_name)
            if adapter is None:
                raise RuntimeError(f"No adapter found for tool: {tool_name}")
            return await adapter.call_tool(tool_name, callable_name, kwargs)

        # Check if we're in async context (has running loop)
        try:
            asyncio.get_running_loop()
            # In async context - return coroutine for await
            return _execute()
        except RuntimeError:
            # Not in async context - execute sync
            pass

        # Sync execution path
        coro = _execute()

        # When called from a thread (via executor.run -> to_thread), use
        # the stored loop with run_coroutine_threadsafe to schedule on main loop.
        if self._loop is not None:
            future = asyncio.run_coroutine_threadsafe(coro, self._loop)
            return future.result()

        # Standalone sync usage - create new loop
        return asyncio.run(coro)

    async def describe(self) -> dict[str, str]:
        """Get parameter descriptions for this callable."""
        adapter = self._registry.find_adapter_for_tool(self._tool_name)
        if adapter is None:
            raise RuntimeError(f"No adapter found for tool: {self._tool_name}")
        return await adapter.describe(self._tool_name, self._callable.name)

    def signature(self) -> str:
        """Get the signature string for this callable."""
        return self._callable.signature()
