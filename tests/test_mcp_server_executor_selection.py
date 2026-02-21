"""E2E tests for MCP executor selection using a real MCP stdio client."""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from mcp.client.stdio import StdioServerParameters, stdio_client


def _docker_daemon_available() -> bool:
    try:
        import docker

        docker.from_env().ping()
        return True
    except Exception:
        return False


@pytest.fixture
def mcp_storage_dir(tmp_path: Path) -> tuple[Path, Path]:
    """Create storage + tools directories for MCP E2E tests."""
    storage = tmp_path / "storage"
    storage.mkdir()
    (storage / "workflows").mkdir()
    (storage / "artifacts").mkdir()

    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    (tools_dir / "echo.yaml").write_text(
        """
name: echo
description: Echo text back
command: echo
timeout: 10
schema:
  positional:
    - name: text
      type: string
      required: true
recipes:
  say:
    description: Echo text
    params:
      text: {}
""".strip()
        + "\n"
    )
    return storage, tools_dir


@asynccontextmanager
async def _mcp_session(args: list[str]) -> Any:
    from mcp import ClientSession

    server_params = StdioServerParameters(command="py-code-mode-mcp", args=args)
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


@pytest.mark.asyncio
async def test_mcp_server_subprocess_backend_options_e2e(
    tmp_path: Path,
    mcp_storage_dir: tuple[Path, Path],
) -> None:
    """Real MCP flow with subprocess backend and subprocess-specific options."""
    storage_path, tools_path = mcp_storage_dir
    venv_path = tmp_path / "subprocess-venv"

    async with _mcp_session(
        [
            "--storage",
            str(storage_path),
            "--tools",
            str(tools_path),
            "--executor",
            "subprocess",
            "--subprocess-venv-path",
            str(venv_path),
            "--subprocess-no-cache-venv",
            "--subprocess-startup-timeout",
            "90",
            "--subprocess-ipc-timeout",
            "30",
            "--timeout",
            "30",
        ]
    ) as session:
        result = await session.call_tool("run_code", {"code": "x = 40\nx + 2"})
        assert "42" in result.content[0].text

    # With --subprocess-no-cache-venv, default cleanup-on-close is enabled.
    assert not venv_path.exists()


@pytest.mark.asyncio
async def test_mcp_server_inprocess_backend_options_e2e(
    mcp_storage_dir: tuple[Path, Path],
) -> None:
    """Real MCP flow with in-process backend and in-process-specific options."""
    storage_path, tools_path = mcp_storage_dir

    async with _mcp_session(
        [
            "--storage",
            str(storage_path),
            "--tools",
            str(tools_path),
            "--executor",
            "in-process",
            "--inprocess-ipc-timeout",
            "15",
            "--timeout",
            "30",
        ]
    ) as session:
        run_result = await session.call_tool("run_code", {"code": "6 * 7"})
        assert "42" in run_result.content[0].text

        tools_result = await session.call_tool("list_tools", {})
        tools_data = json.loads(tools_result.content[0].text)
        tool_names = {tool["name"] for tool in tools_data}
        assert "echo" in tool_names


@pytest.mark.asyncio
@pytest.mark.deno
async def test_mcp_server_deno_backend_options_e2e(
    tmp_path: Path,
    mcp_storage_dir: tuple[Path, Path],
) -> None:
    """Real MCP flow with deno-sandbox backend and Deno-specific options."""
    if os.environ.get("PY_CODE_MODE_TEST_DENO") != "1":
        pytest.skip("Set PY_CODE_MODE_TEST_DENO=1 to run Deno/Pyodide MCP E2E tests.")

    storage_path, tools_path = mcp_storage_dir
    deno_dir = tmp_path / "deno-cache"
    deno_dir.mkdir(parents=True, exist_ok=True)

    async with _mcp_session(
        [
            "--storage",
            str(storage_path),
            "--tools",
            str(tools_path),
            "--executor",
            "deno-sandbox",
            "--deno-dir",
            str(deno_dir),
            "--deno-network-profile",
            "none",
            "--deno-ipc-timeout",
            "120",
            "--deno-deps-timeout",
            "120",
            "--timeout",
            "180",
        ]
    ) as session:
        result = await session.call_tool("run_code", {"code": "40 + 2"})
        assert "42" in result.content[0].text


@pytest.mark.asyncio
@pytest.mark.docker
async def test_mcp_server_container_backend_options_e2e(
    mcp_storage_dir: tuple[Path, Path],
) -> None:
    """Real MCP flow with container backend and container-specific options."""
    if not _docker_daemon_available():
        if os.environ.get("CI") == "true":
            pytest.fail("Docker daemon not available in CI")
        pytest.skip("Docker daemon not available")

    storage_path, tools_path = mcp_storage_dir
    async with _mcp_session(
        [
            "--storage",
            str(storage_path),
            "--tools",
            str(tools_path),
            "--executor",
            "container",
            "--container-startup-timeout",
            "120",
            "--container-ipc-timeout",
            "60",
            "--container-auth-disabled",
            "--timeout",
            "30",
        ]
    ) as session:
        result = await session.call_tool("run_code", {"code": "41 + 1"})
        assert "42" in result.content[0].text
