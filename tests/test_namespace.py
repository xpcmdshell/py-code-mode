"""Tests for the namespace layer (ToolsNamespace, ToolProxy, CallableProxy)."""

import asyncio
from pathlib import Path

import pytest

from py_code_mode.tools.adapters.cli import CLIAdapter
from py_code_mode.tools.namespace import CallableProxy, ToolProxy, ToolsNamespace
from py_code_mode.tools.registry import ToolRegistry


@pytest.fixture
def docker_yaml(tmp_path: Path) -> Path:
    """Create docker.yaml with schema + recipes."""
    yaml_content = """
name: docker
description: Docker container management
command: docker
timeout: 60

schema:
  options:
    d: {type: boolean, description: Detached mode}
    p: {type: string, description: Port mapping}
  positional:
    - name: image
      type: string
      required: true
      description: Docker image

recipes:
  run:
    description: Run a container
    preset:
      d: true
    params:
      image: {}
      p: {default: ""}

  ps:
    description: List containers
    params: {}
"""
    yaml_file = tmp_path / "docker.yaml"
    yaml_file.write_text(yaml_content)
    return yaml_file


@pytest.fixture
def registry_with_tools(nmap_yaml: Path, docker_yaml: Path, tmp_path: Path) -> ToolRegistry:
    """Create registry with nmap and docker tools loaded."""
    adapter = CLIAdapter(tools_path=nmap_yaml.parent)
    registry = ToolRegistry()
    registry.add_adapter(adapter)
    return registry


@pytest.fixture
def namespace(registry_with_tools: ToolRegistry) -> ToolsNamespace:
    """Create namespace from registry."""
    return ToolsNamespace(registry_with_tools)


def test_tools_namespace_getattr_returns_tool_proxy(namespace: ToolsNamespace) -> None:
    """tools.nmap returns ToolProxy."""
    proxy = namespace.nmap
    assert isinstance(proxy, ToolProxy)
    assert proxy._tool.name == "nmap"


def test_tool_proxy_getattr_returns_callable_proxy(namespace: ToolsNamespace) -> None:
    """tools.nmap.syn_scan returns CallableProxy."""
    callable_proxy = namespace.nmap.syn_scan
    assert isinstance(callable_proxy, CallableProxy)
    assert callable_proxy._tool_name == "nmap"
    assert callable_proxy._callable.name == "syn_scan"


@pytest.mark.asyncio
async def test_callable_proxy_invokes_tool(namespace: ToolsNamespace, monkeypatch) -> None:
    """tools.nmap.syn_scan(target="...") invokes correctly."""

    # Mock subprocess to avoid actual nmap execution
    async def mock_create_subprocess_exec(*args, **kwargs):
        class MockProcess:
            async def communicate(self):
                return (b"Mock nmap output", b"")

            returncode = 0

        return MockProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", mock_create_subprocess_exec)

    result = await namespace.nmap.syn_scan(target="10.0.0.1")
    assert result == "Mock nmap output"


@pytest.mark.asyncio
async def test_callable_proxy_describe(namespace: ToolsNamespace) -> None:
    """tools.nmap.syn_scan.describe() returns param descriptions."""
    description = await namespace.nmap.syn_scan.describe()
    assert "target" in description
    assert description["target"] == ""


def test_callable_proxy_signature(namespace: ToolsNamespace) -> None:
    """tools.nmap.syn_scan.signature() returns signature string."""
    sig = namespace.nmap.syn_scan.signature()
    # Recipe params default to optional, signature format is "name(param: type | None = None, ...)"

    assert "syn_scan" in sig
    assert "target" in sig
    assert "p" in sig


def test_tool_proxy_list(namespace: ToolsNamespace) -> None:
    """tools.nmap.list() returns callable objects."""
    callables = namespace.nmap.list()
    callable_names = {c.name for c in callables}
    assert "syn_scan" in callable_names
    assert "version_scan" not in callable_names
    assert "ping_scan" not in callable_names
    assert "quick" in callable_names


def test_tools_namespace_list(namespace: ToolsNamespace) -> None:
    """tools.list() returns all Tool objects."""
    tools = namespace.list()
    assert len(tools) == 2
    tool_names = {t.name for t in tools}
    assert "nmap" in tool_names
    assert "docker" in tool_names


def test_unknown_tool_raises_attribute_error(namespace: ToolsNamespace) -> None:
    """tools.nonexistent raises AttributeError with available tools."""
    with pytest.raises(AttributeError) as exc_info:
        _ = namespace.nonexistent

    error_msg = str(exc_info.value)
    assert "Unknown tool: nonexistent" in error_msg
    assert "nmap" in error_msg
    assert "docker" in error_msg


def test_unknown_callable_raises_attribute_error(namespace: ToolsNamespace) -> None:
    """tools.nmap.nonexistent raises AttributeError with available callables."""
    with pytest.raises(AttributeError) as exc_info:
        _ = namespace.nmap.nonexistent

    error_msg = str(exc_info.value)
    assert "Unknown callable: nmap.nonexistent" in error_msg
    assert "syn_scan" in error_msg
    assert "quick" in error_msg


def test_multiple_tool_access(namespace: ToolsNamespace) -> None:
    """Access multiple tools and callables."""
    nmap_proxy = namespace.nmap
    docker_proxy = namespace.docker

    assert isinstance(nmap_proxy, ToolProxy)
    assert isinstance(docker_proxy, ToolProxy)

    syn_scan = nmap_proxy.syn_scan
    docker_run = docker_proxy.run

    assert isinstance(syn_scan, CallableProxy)
    assert isinstance(docker_run, CallableProxy)


def test_namespace_search(namespace: ToolsNamespace) -> None:
    """tools.search() finds tools by query."""
    results = namespace.search("network", limit=5)
    assert len(results) > 0
    # At minimum, nmap should match "network scanner"
    tool_names = {t.name for t in results}
    assert "nmap" in tool_names


# Test removed - use CLIAdapter(tools_path=...) for loading tools
