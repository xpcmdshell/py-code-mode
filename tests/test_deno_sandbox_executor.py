import hashlib
import math
import os
from dataclasses import dataclass
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("PY_CODE_MODE_TEST_DENO") != "1",
    reason="Set PY_CODE_MODE_TEST_DENO=1 to run Deno/Pyodide integration tests.",
)


class _StableEmbedder:
    """Deterministic lightweight embedder for integration tests.

    Avoids pulling large sentence-transformers models while still exercising
    semantic-search codepaths.
    """

    def __init__(self, dimension: int = 64) -> None:
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self._dimension
        for token in "".join(c.lower() if c.isalnum() else " " for c in text).split():
            h = hashlib.sha256(token.encode("utf-8")).digest()
            idx = int.from_bytes(h[:4], "big") % self._dimension
            vec[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def embed_query(self, query: str) -> list[float]:
        return self._embed_one(query)


@dataclass
class _TestStorage:
    """Minimal StorageBackend for exercising workflows/artifacts via RPC."""

    root: Path

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

        from py_code_mode.artifacts import FileArtifactStore
        from py_code_mode.workflows import FileWorkflowStore, WorkflowLibrary

        self._artifact_store = FileArtifactStore(self.root / "artifacts")
        self._workflow_store = FileWorkflowStore(self.root / "workflows")
        self._workflow_library = WorkflowLibrary(
            embedder=_StableEmbedder(),
            store=self._workflow_store,
            vector_store=None,
        )

    def get_serializable_access(self):
        from py_code_mode.execution.protocol import FileStorageAccess

        return FileStorageAccess(
            workflows_path=self.root / "workflows",
            artifacts_path=self.root / "artifacts",
            vectors_path=None,
        )

    def get_workflow_library(self):
        return self._workflow_library

    def get_artifact_store(self):
        return self._artifact_store


@pytest.mark.asyncio
async def test_deno_sandbox_executor_basic(tmp_path: Path) -> None:
    from py_code_mode.execution import DenoSandboxConfig, DenoSandboxExecutor
    from py_code_mode.session import Session
    from py_code_mode.storage import FileStorage

    storage = FileStorage(tmp_path / "storage")
    deno_dir = tmp_path / "deno_dir"
    deno_dir.mkdir(parents=True, exist_ok=True)

    executor = DenoSandboxExecutor(
        DenoSandboxConfig(
            deno_dir=deno_dir,
            default_timeout=60.0,
            ipc_timeout=120.0,
            network_profile="none",
        )
    )

    async with Session(storage=storage, executor=executor) as session:
        r1 = await session.run("1 + 1")
        assert r1.error is None
        assert r1.value == 2

        r2 = await session.run("x = 40")
        assert r2.error is None

        r3 = await session.run("x + 2")
        assert r3.error is None
        assert r3.value == 42


@pytest.mark.asyncio
async def test_deno_sandbox_executor_deps_add_installs(tmp_path: Path) -> None:
    from py_code_mode.execution import DenoSandboxConfig, DenoSandboxExecutor
    from py_code_mode.session import Session
    from py_code_mode.storage import FileStorage

    storage = FileStorage(tmp_path / "storage")
    deno_dir = tmp_path / "deno_dir"
    deno_dir.mkdir(parents=True, exist_ok=True)

    executor = DenoSandboxExecutor(
        DenoSandboxConfig(
            deno_dir=deno_dir,
            default_timeout=300.0,
            deps_timeout=300.0,
            ipc_timeout=120.0,
            network_profile="deps-only",
        )
    )

    async with Session(storage=storage, executor=executor) as session:
        r = await session.run(
            "await deps.add('packaging')\nimport packaging\npackaging.__version__"
        )
        assert r.error is None
        assert isinstance(r.value, str)
        assert r.value


@pytest.mark.asyncio
async def test_deno_sandbox_executor_sync_deps_on_start(tmp_path: Path) -> None:
    from py_code_mode.execution import DenoSandboxConfig, DenoSandboxExecutor
    from py_code_mode.session import Session
    from py_code_mode.storage import FileStorage

    storage = FileStorage(tmp_path / "storage")
    deno_dir = tmp_path / "deno_dir"
    deno_dir.mkdir(parents=True, exist_ok=True)

    executor = DenoSandboxExecutor(
        DenoSandboxConfig(
            deno_dir=deno_dir,
            default_timeout=60.0,
            deps_timeout=300.0,
            ipc_timeout=120.0,
            deps=("packaging",),
            network_profile="deps-only",
        )
    )

    async with Session(storage=storage, executor=executor, sync_deps_on_start=True) as session:
        r = await session.run("import packaging\npackaging.__version__")
        assert r.error is None
        assert isinstance(r.value, str)
        assert r.value


@pytest.mark.asyncio
async def test_deno_sandbox_executor_network_none_blocks_installs(tmp_path: Path) -> None:
    from py_code_mode.execution import DenoSandboxConfig, DenoSandboxExecutor
    from py_code_mode.session import Session
    from py_code_mode.storage import FileStorage

    storage = FileStorage(tmp_path / "storage")
    deno_dir = tmp_path / "deno_dir"
    deno_dir.mkdir(parents=True, exist_ok=True)

    executor = DenoSandboxExecutor(
        DenoSandboxConfig(
            deno_dir=deno_dir,
            default_timeout=120.0,
            deps_timeout=120.0,
            ipc_timeout=120.0,
            network_profile="none",
        )
    )

    async with Session(storage=storage, executor=executor) as session:
        r = await session.run(
            "await deps.add('packaging')\nimport packaging\npackaging.__version__"
        )
        assert r.error is not None


@pytest.mark.asyncio
async def test_deno_sandbox_executor_artifacts_roundtrip(tmp_path: Path) -> None:
    from py_code_mode.execution import DenoSandboxConfig, DenoSandboxExecutor
    from py_code_mode.session import Session
    from py_code_mode.storage import FileStorage

    storage = FileStorage(tmp_path / "storage")
    deno_dir = tmp_path / "deno_dir"
    deno_dir.mkdir(parents=True, exist_ok=True)

    executor = DenoSandboxExecutor(
        DenoSandboxConfig(
            deno_dir=deno_dir,
            default_timeout=60.0,
            ipc_timeout=120.0,
            network_profile="none",
        )
    )

    async with Session(storage=storage, executor=executor) as session:
        r = await session.run(
            "await artifacts.save('obj', {'a': 1, 'b': [2, 3]}, description='t')\n"
            "(await artifacts.load('obj'))['b'][1]"
        )
        assert r.error is None
        assert r.value == 3


@pytest.mark.asyncio
async def test_deno_sandbox_executor_workflows_roundtrip(tmp_path: Path) -> None:
    from py_code_mode.execution import DenoSandboxConfig, DenoSandboxExecutor
    from py_code_mode.session import Session
    from py_code_mode.storage import FileStorage

    storage = FileStorage(tmp_path / "storage")
    deno_dir = tmp_path / "deno_dir"
    deno_dir.mkdir(parents=True, exist_ok=True)

    executor = DenoSandboxExecutor(
        DenoSandboxConfig(
            deno_dir=deno_dir,
            default_timeout=60.0,
            ipc_timeout=120.0,
            network_profile="none",
        )
    )

    source = "async def run(name: str) -> str:\n    return 'hi ' + name\n"

    async with Session(storage=storage, executor=executor) as session:
        r = await session.run(
            "await workflows.create('hello', "
            f"{source!r}, "
            "'test wf')\n"
            "(await workflows.get('hello'))['source']"
        )
        assert r.error is None
        assert r.value == source

        r2 = await session.run("await workflows.invoke('hello', name='py-code-mode')")
        assert r2.error is None
        assert r2.value == "hi py-code-mode"


@pytest.mark.asyncio
async def test_deno_sandbox_executor_workflow_calls_other_workflow(tmp_path: Path) -> None:
    """Ensure a workflow can invoke another workflow inside the sandbox."""

    from py_code_mode.execution import DenoSandboxConfig, DenoSandboxExecutor
    from py_code_mode.session import Session
    from py_code_mode.storage import FileStorage

    storage = FileStorage(tmp_path / "storage")
    deno_dir = tmp_path / "deno_dir"
    deno_dir.mkdir(parents=True, exist_ok=True)

    executor = DenoSandboxExecutor(
        DenoSandboxConfig(
            deno_dir=deno_dir,
            default_timeout=60.0,
            ipc_timeout=120.0,
            network_profile="none",
        )
    )

    src_double = "async def run(x: int) -> int:\n    return x * 2\n"
    src_quadruple = (
        "async def run(x: int) -> int:\n"
        "    d = await workflows.invoke(workflow_name='double', x=x)\n"
        "    return await workflows.invoke(workflow_name='double', x=d)\n"
    )

    async with Session(storage=storage, executor=executor) as session:
        r1 = await session.run(f"await workflows.create('double', {src_double!r}, 'double')")
        assert r1.error is None

        r2 = await session.run(
            f"await workflows.create('quadruple', {src_quadruple!r}, 'quadruple')"
        )
        assert r2.error is None

        r3 = await session.run("await workflows.invoke('quadruple', x=10)")
        assert r3.error is None
        assert r3.value == 40


@pytest.mark.asyncio
async def test_deno_sandbox_executor_tools_via_rpc(tmp_path: Path) -> None:
    from py_code_mode.execution import DenoSandboxConfig, DenoSandboxExecutor
    from py_code_mode.session import Session
    from py_code_mode.storage import FileStorage

    tools_dir = tmp_path / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    (tools_dir / "echo.yaml").write_text(
        "\n".join(
            [
                "name: echo",
                "description: Echo text",
                "command: /bin/echo",
                "timeout: 5",
                "schema:",
                "  positional:",
                "    - name: message",
                "      type: string",
                "      required: true",
                "      description: message",
                "recipes:",
                "  say:",
                "    description: Echo message",
                "    params:",
                "      message: {}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    storage = FileStorage(tmp_path / "storage")
    deno_dir = tmp_path / "deno_dir"
    deno_dir.mkdir(parents=True, exist_ok=True)

    executor = DenoSandboxExecutor(
        DenoSandboxConfig(
            deno_dir=deno_dir,
            tools_path=tools_dir,
            default_timeout=60.0,
            ipc_timeout=120.0,
            network_profile="none",
        )
    )

    async with Session(storage=storage, executor=executor) as session:
        r_list = await session.run("_ts = await tools.list()\nsorted([t['name'] for t in _ts])")
        assert r_list.error is None
        assert "echo" in r_list.value

        r = await session.run("(await tools.echo.say(message='hi')).strip()")
        assert r.error is None
        assert r.value == "hi"


@pytest.mark.asyncio
async def test_deno_sandbox_executor_tool_middleware_is_invoked(tmp_path: Path) -> None:
    from py_code_mode.execution import DenoSandboxConfig, DenoSandboxExecutor
    from py_code_mode.session import Session
    from py_code_mode.storage import FileStorage
    from py_code_mode.tools import ToolCallContext, ToolMiddleware

    tools_dir = tmp_path / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    (tools_dir / "echo.yaml").write_text(
        "\n".join(
            [
                "name: echo",
                "description: Echo text",
                "command: /bin/echo",
                "timeout: 5",
                "schema:",
                "  positional:",
                "    - name: message",
                "      type: string",
                "      required: true",
                "      description: message",
                "recipes:",
                "  say:",
                "    description: Echo message",
                "    params:",
                "      message: {}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    events: list[str] = []

    class _Recorder(ToolMiddleware):
        async def __call__(self, ctx: ToolCallContext, call_next):  # type: ignore[override]
            events.append(f"pre:{ctx.full_name}:{ctx.executor_type}:{ctx.origin}")
            out = await call_next(ctx)
            events.append(f"post:{ctx.full_name}")
            return out

    storage = FileStorage(tmp_path / "storage")
    deno_dir = tmp_path / "deno_dir"
    deno_dir.mkdir(parents=True, exist_ok=True)

    executor = DenoSandboxExecutor(
        DenoSandboxConfig(
            deno_dir=deno_dir,
            tools_path=tools_dir,
            tool_middlewares=(_Recorder(),),
            default_timeout=60.0,
            ipc_timeout=120.0,
            network_profile="none",
        )
    )

    async with Session(storage=storage, executor=executor) as session:
        r = await session.run("(await tools.echo.say(message='hi')).strip()")
        assert r.error is None
        assert r.value == "hi"

    assert events == [
        "pre:echo.say:deno-sandbox:deno-sandbox",
        "post:echo.say",
    ]


@pytest.mark.asyncio
async def test_deno_sandbox_executor_tool_large_output_is_chunked(tmp_path: Path) -> None:
    from py_code_mode.execution import DenoSandboxConfig, DenoSandboxExecutor
    from py_code_mode.session import Session
    from py_code_mode.storage import FileStorage

    tools_dir = tmp_path / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    (tools_dir / "pyrun.yaml").write_text(
        "\n".join(
            [
                "name: pyrun",
                "description: Run Python snippet",
                "command: python",
                "timeout: 10",
                "schema:",
                "  options:",
                "    command:",
                "      type: string",
                "      short: c",
                "      description: code snippet",
                "recipes:",
                "  run:",
                "    description: Run snippet via -c",
                "    params:",
                "      command: {}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    storage = FileStorage(tmp_path / "storage")
    deno_dir = tmp_path / "deno_dir"
    deno_dir.mkdir(parents=True, exist_ok=True)

    executor = DenoSandboxExecutor(
        DenoSandboxConfig(
            deno_dir=deno_dir,
            tools_path=tools_dir,
            default_timeout=180.0,
            ipc_timeout=120.0,
            network_profile="none",
        )
    )

    async with Session(storage=storage, executor=executor) as session:
        r = await session.run(
            "\n".join(
                [
                    "code = \"import sys; sys.stdout.write('x' * (2 * 1024 * 1024))\"",
                    "len(await tools.pyrun.run(command=code))",
                ]
            )
        )
        assert r.error is None
        assert r.value == 2 * 1024 * 1024


@pytest.mark.asyncio
async def test_deno_sandbox_executor_rpc_does_not_deadlock(tmp_path: Path) -> None:
    from py_code_mode.execution import DenoSandboxConfig, DenoSandboxExecutor
    from py_code_mode.session import Session
    from py_code_mode.storage import FileStorage

    storage = FileStorage(tmp_path / "storage")
    deno_dir = tmp_path / "deno_dir"
    deno_dir.mkdir(parents=True, exist_ok=True)

    executor = DenoSandboxExecutor(
        DenoSandboxConfig(
            deno_dir=deno_dir,
            default_timeout=15.0,
            ipc_timeout=120.0,
            network_profile="none",
        )
    )

    async with Session(storage=storage, executor=executor) as session:
        r = await session.run(
            "\n".join(
                [
                    "await artifacts.save('x', {'n': 1}, description='')",
                    "s = 0",
                    "for _ in range(50):",
                    "    if await artifacts.exists('x'):",
                    "        s += (await artifacts.load('x'))['n']",
                    "s",
                ]
            )
        )
        assert r.error is None
        assert r.value == 50


@pytest.mark.asyncio
async def test_deno_sandbox_executor_reset_clears_state(tmp_path: Path) -> None:
    from py_code_mode.execution import DenoSandboxConfig, DenoSandboxExecutor
    from py_code_mode.session import Session
    from py_code_mode.storage import FileStorage

    storage = FileStorage(tmp_path / "storage")
    deno_dir = tmp_path / "deno_dir"
    deno_dir.mkdir(parents=True, exist_ok=True)

    executor = DenoSandboxExecutor(
        DenoSandboxConfig(
            deno_dir=deno_dir,
            default_timeout=60.0,
            ipc_timeout=120.0,
            network_profile="none",
        )
    )

    async with Session(storage=storage, executor=executor) as session:
        r1 = await session.run("x = 1\nx")
        assert r1.error is None
        assert r1.value == 1

        await session.reset()

        r2 = await session.run("x")
        assert r2.error is not None


@pytest.mark.asyncio
async def test_deno_sandbox_executor_session_add_dep_installs(tmp_path: Path) -> None:
    from py_code_mode.execution import DenoSandboxConfig, DenoSandboxExecutor
    from py_code_mode.session import Session
    from py_code_mode.storage import FileStorage

    storage = FileStorage(tmp_path / "storage")
    deno_dir = tmp_path / "deno_dir"
    deno_dir.mkdir(parents=True, exist_ok=True)

    executor = DenoSandboxExecutor(
        DenoSandboxConfig(
            deno_dir=deno_dir,
            default_timeout=300.0,
            deps_timeout=300.0,
            ipc_timeout=120.0,
            network_profile="deps-only",
        )
    )

    async with Session(storage=storage, executor=executor) as session:
        out = await session.add_dep("packaging")
        assert out["failed"] == []

        r = await session.run("import packaging\npackaging.__version__")
        assert r.error is None
        assert isinstance(r.value, str)


@pytest.mark.asyncio
async def test_deno_sandbox_executor_mcp_tool_via_rpc(tmp_path: Path) -> None:
    from py_code_mode.execution import DenoSandboxConfig, DenoSandboxExecutor
    from py_code_mode.session import Session
    from py_code_mode.storage import FileStorage

    tools_dir = tmp_path / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)

    # Local stdio MCP server using fastmcp.
    mcp_server = tmp_path / "mcp_server.py"
    mcp_server.write_text(
        "\n".join(
            [
                "from fastmcp import FastMCP",
                "",
                "mcp = FastMCP('test')",
                "",
                "@mcp.tool",
                "async def add(a: int, b: int) -> str:",
                "    return str(a + b)",
                "",
                "if __name__ == '__main__':",
                "    mcp.run()",
                "",
            ]
        ),
        encoding="utf-8",
    )

    (tools_dir / "math.yaml").write_text(
        "\n".join(
            [
                "name: math",
                "type: mcp",
                "transport: stdio",
                "command: python",
                f"args: [{mcp_server!s}]",
                "description: Simple math MCP server",
                "",
            ]
        ),
        encoding="utf-8",
    )

    storage = FileStorage(tmp_path / "storage")
    deno_dir = tmp_path / "deno_dir"
    deno_dir.mkdir(parents=True, exist_ok=True)

    executor = DenoSandboxExecutor(
        DenoSandboxConfig(
            deno_dir=deno_dir,
            tools_path=tools_dir,
            default_timeout=60.0,
            ipc_timeout=120.0,
            network_profile="none",
        )
    )

    async with Session(storage=storage, executor=executor) as session:
        r_list = await session.run("_ts = await tools.list()\nsorted([t['name'] for t in _ts])")
        assert r_list.error is None
        assert "math" in r_list.value

        r = await session.run("(await tools.math.add(a=2, b=3)).strip()")
        assert r.error is None
        assert r.value == "5"


@pytest.mark.asyncio
async def test_deno_sandbox_executor_workflows_search_via_rpc(tmp_path: Path) -> None:
    from py_code_mode.execution import DenoSandboxConfig, DenoSandboxExecutor
    from py_code_mode.session import Session

    storage = _TestStorage(tmp_path / "storage")
    deno_dir = tmp_path / "deno_dir"
    deno_dir.mkdir(parents=True, exist_ok=True)

    executor = DenoSandboxExecutor(
        DenoSandboxConfig(
            deno_dir=deno_dir,
            default_timeout=60.0,
            ipc_timeout=120.0,
            network_profile="none",
        )
    )

    src = "async def run() -> str:\n    return 'hello world'\n"

    async with Session(storage=storage, executor=executor) as session:
        r1 = await session.run(f"await workflows.create('wf', {src!r}, 'greeting workflow')")
        assert r1.error is None

        r2 = await session.run("(await workflows.search('greeting', limit=5))[0]['name']")
        assert r2.error is None
        assert r2.value == "wf"


@pytest.mark.asyncio
async def test_deno_sandbox_executor_artifact_payload_size_limits(tmp_path: Path) -> None:
    from py_code_mode.execution import DenoSandboxConfig, DenoSandboxExecutor
    from py_code_mode.session import Session
    from py_code_mode.storage import FileStorage

    storage = FileStorage(tmp_path / "storage")
    store = storage.get_artifact_store()
    store.save("small", "x" * (200 * 1024), description="")
    store.save("big", "x" * (2 * 1024 * 1024), description="")
    deno_dir = tmp_path / "deno_dir"
    deno_dir.mkdir(parents=True, exist_ok=True)

    executor = DenoSandboxExecutor(
        DenoSandboxConfig(
            deno_dir=deno_dir,
            default_timeout=180.0,
            ipc_timeout=120.0,
            network_profile="none",
        )
    )

    async with Session(storage=storage, executor=executor) as session:
        r_ok = await session.run(
            "\n".join(
                [
                    "len(await artifacts.load('small'))",
                ]
            )
        )
        assert r_ok.error is None
        assert r_ok.value == 200 * 1024

        r_big = await session.run(
            "\n".join(
                [
                    "len(await artifacts.load('big'))",
                ]
            )
        )
        assert r_big.error is None
        assert r_big.value == 2 * 1024 * 1024


@pytest.mark.asyncio
async def test_deno_sandbox_executor_soft_timeout_wedges_until_reset(tmp_path: Path) -> None:
    from py_code_mode.execution import DenoSandboxConfig, DenoSandboxExecutor
    from py_code_mode.session import Session
    from py_code_mode.storage import FileStorage

    storage = FileStorage(tmp_path / "storage")
    deno_dir = tmp_path / "deno_dir"
    deno_dir.mkdir(parents=True, exist_ok=True)

    executor = DenoSandboxExecutor(
        DenoSandboxConfig(
            deno_dir=deno_dir,
            default_timeout=0.05,
            ipc_timeout=120.0,
            network_profile="none",
        )
    )

    async with Session(storage=storage, executor=executor) as session:
        r1 = await session.run("import time\ntime.sleep(0.2)\n1")
        assert r1.error is not None
        assert "timeout" in r1.error.lower()

        r2 = await session.run("1 + 1")
        assert r2.error is not None
        assert "previous execution timed out" in r2.error.lower()

        await session.reset()

        r3 = await session.run("1 + 1")
        assert r3.error is None
        assert r3.value == 2
