import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("PY_CODE_MODE_TEST_DENO") != "1",
    reason="Set PY_CODE_MODE_TEST_DENO=1 to run Deno/Pyodide integration tests.",
)


@pytest.mark.asyncio
async def test_deno_pyodide_executor_basic(tmp_path: Path) -> None:
    from py_code_mode.execution import DenoPyodideConfig, DenoPyodideExecutor
    from py_code_mode.session import Session
    from py_code_mode.storage import FileStorage

    storage = FileStorage(tmp_path / "storage")
    deno_dir = tmp_path / "deno_dir"
    deno_dir.mkdir(parents=True, exist_ok=True)

    executor = DenoPyodideExecutor(
        DenoPyodideConfig(
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
async def test_deno_pyodide_executor_deps_add_installs(tmp_path: Path) -> None:
    from py_code_mode.execution import DenoPyodideConfig, DenoPyodideExecutor
    from py_code_mode.session import Session
    from py_code_mode.storage import FileStorage

    storage = FileStorage(tmp_path / "storage")
    deno_dir = tmp_path / "deno_dir"
    deno_dir.mkdir(parents=True, exist_ok=True)

    executor = DenoPyodideExecutor(
        DenoPyodideConfig(
            deno_dir=deno_dir,
            default_timeout=300.0,
            deps_timeout=300.0,
            ipc_timeout=120.0,
            network_profile="deps-only",
        )
    )

    async with Session(storage=storage, executor=executor) as session:
        r = await session.run("deps.add('packaging')\nimport packaging\npackaging.__version__")
        assert r.error is None
        assert isinstance(r.value, str)
        assert r.value


@pytest.mark.asyncio
async def test_deno_pyodide_executor_sync_deps_on_start(tmp_path: Path) -> None:
    from py_code_mode.execution import DenoPyodideConfig, DenoPyodideExecutor
    from py_code_mode.session import Session
    from py_code_mode.storage import FileStorage

    storage = FileStorage(tmp_path / "storage")
    deno_dir = tmp_path / "deno_dir"
    deno_dir.mkdir(parents=True, exist_ok=True)

    executor = DenoPyodideExecutor(
        DenoPyodideConfig(
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
async def test_deno_pyodide_executor_network_none_blocks_installs(tmp_path: Path) -> None:
    from py_code_mode.execution import DenoPyodideConfig, DenoPyodideExecutor
    from py_code_mode.session import Session
    from py_code_mode.storage import FileStorage

    storage = FileStorage(tmp_path / "storage")
    deno_dir = tmp_path / "deno_dir"
    deno_dir.mkdir(parents=True, exist_ok=True)

    executor = DenoPyodideExecutor(
        DenoPyodideConfig(
            deno_dir=deno_dir,
            default_timeout=120.0,
            deps_timeout=120.0,
            ipc_timeout=120.0,
            network_profile="none",
        )
    )

    async with Session(storage=storage, executor=executor) as session:
        r = await session.run("deps.add('packaging')\nimport packaging\npackaging.__version__")
        assert r.error is not None


@pytest.mark.asyncio
async def test_deno_pyodide_executor_artifacts_roundtrip(tmp_path: Path) -> None:
    from py_code_mode.execution import DenoPyodideConfig, DenoPyodideExecutor
    from py_code_mode.session import Session
    from py_code_mode.storage import FileStorage

    storage = FileStorage(tmp_path / "storage")
    deno_dir = tmp_path / "deno_dir"
    deno_dir.mkdir(parents=True, exist_ok=True)

    executor = DenoPyodideExecutor(
        DenoPyodideConfig(
            deno_dir=deno_dir,
            default_timeout=60.0,
            ipc_timeout=120.0,
            network_profile="none",
        )
    )

    async with Session(storage=storage, executor=executor) as session:
        r = await session.run(
            "artifacts.save('obj', {'a': 1, 'b': [2, 3]}, description='t')\n"
            "artifacts.load('obj')['b'][1]"
        )
        assert r.error is None
        assert r.value == 3


@pytest.mark.asyncio
async def test_deno_pyodide_executor_workflows_roundtrip(tmp_path: Path) -> None:
    from py_code_mode.execution import DenoPyodideConfig, DenoPyodideExecutor
    from py_code_mode.session import Session
    from py_code_mode.storage import FileStorage

    storage = FileStorage(tmp_path / "storage")
    deno_dir = tmp_path / "deno_dir"
    deno_dir.mkdir(parents=True, exist_ok=True)

    executor = DenoPyodideExecutor(
        DenoPyodideConfig(
            deno_dir=deno_dir,
            default_timeout=60.0,
            ipc_timeout=120.0,
            network_profile="none",
        )
    )

    source = "async def run(name: str) -> str:\n    return 'hi ' + name\n"

    async with Session(storage=storage, executor=executor) as session:
        r = await session.run(
            "workflows.create('hello', "
            f"{source!r}, "
            "'test wf')\n"
            "workflows.get('hello')['source']"
        )
        assert r.error is None
        assert r.value == source


@pytest.mark.asyncio
async def test_deno_pyodide_executor_tools_via_rpc(tmp_path: Path) -> None:
    from py_code_mode.execution import DenoPyodideConfig, DenoPyodideExecutor
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

    executor = DenoPyodideExecutor(
        DenoPyodideConfig(
            deno_dir=deno_dir,
            tools_path=tools_dir,
            default_timeout=60.0,
            ipc_timeout=120.0,
            network_profile="none",
        )
    )

    async with Session(storage=storage, executor=executor) as session:
        r_list = await session.run("sorted([t['name'] for t in tools.list()])")
        assert r_list.error is None
        assert "echo" in r_list.value

        r = await session.run("tools.echo.say(message='hi').strip()")
        assert r.error is None
        assert r.value == "hi"


@pytest.mark.asyncio
async def test_deno_pyodide_executor_rpc_does_not_deadlock(tmp_path: Path) -> None:
    from py_code_mode.execution import DenoPyodideConfig, DenoPyodideExecutor
    from py_code_mode.session import Session
    from py_code_mode.storage import FileStorage

    storage = FileStorage(tmp_path / "storage")
    deno_dir = tmp_path / "deno_dir"
    deno_dir.mkdir(parents=True, exist_ok=True)

    executor = DenoPyodideExecutor(
        DenoPyodideConfig(
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
                    "artifacts.save('x', {'n': 1}, description='')",
                    "s = 0",
                    "for _ in range(50):",
                    "    if artifacts.exists('x'):",
                    "        s += artifacts.load('x')['n']",
                    "s",
                ]
            )
        )
        assert r.error is None
        assert r.value == 50


@pytest.mark.asyncio
async def test_deno_pyodide_executor_reset_clears_state(tmp_path: Path) -> None:
    from py_code_mode.execution import DenoPyodideConfig, DenoPyodideExecutor
    from py_code_mode.session import Session
    from py_code_mode.storage import FileStorage

    storage = FileStorage(tmp_path / "storage")
    deno_dir = tmp_path / "deno_dir"
    deno_dir.mkdir(parents=True, exist_ok=True)

    executor = DenoPyodideExecutor(
        DenoPyodideConfig(
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
async def test_deno_pyodide_executor_session_add_dep_installs(tmp_path: Path) -> None:
    from py_code_mode.execution import DenoPyodideConfig, DenoPyodideExecutor
    from py_code_mode.session import Session
    from py_code_mode.storage import FileStorage

    storage = FileStorage(tmp_path / "storage")
    deno_dir = tmp_path / "deno_dir"
    deno_dir.mkdir(parents=True, exist_ok=True)

    executor = DenoPyodideExecutor(
        DenoPyodideConfig(
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
