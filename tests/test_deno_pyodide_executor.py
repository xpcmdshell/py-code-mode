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
