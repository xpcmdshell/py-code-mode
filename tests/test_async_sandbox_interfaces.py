import os
from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_inprocess_executor_supports_await_tools_and_artifacts(tmp_path: Path) -> None:
    from py_code_mode.execution import InProcessConfig, InProcessExecutor
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
    executor = InProcessExecutor(config=InProcessConfig(tools_path=tools_dir))

    async with Session(storage=storage, executor=executor) as session:
        r_list = await session.run("_ts = await tools.list()\nsorted([t.name for t in _ts])")
        assert r_list.error is None
        assert "echo" in r_list.value

        r_call = await session.run("(await tools.echo.say(message='hi')).strip()")
        assert r_call.error is None
        assert r_call.value == "hi"

        r_art = await session.run(
            "\n".join(
                [
                    "await artifacts.save('obj', {'a': 1}, description='')",
                    "(await artifacts.load('obj'))['a']",
                ]
            )
        )
        assert r_art.error is None
        assert r_art.value == 1


pytestmark_subprocess = pytest.mark.skipif(
    os.environ.get("PY_CODE_MODE_TEST_SUBPROCESS") == "0",
    reason="Subprocess async-sandbox smoke can be disabled with PY_CODE_MODE_TEST_SUBPROCESS=0",
)


@pytestmark_subprocess
@pytest.mark.asyncio
async def test_subprocess_executor_supports_await_tools_workflows_artifacts(tmp_path: Path) -> None:
    from py_code_mode.execution import SubprocessConfig, SubprocessExecutor
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
    executor = SubprocessExecutor(
        config=SubprocessConfig(tools_path=tools_dir, default_timeout=60.0)
    )

    async with Session(storage=storage, executor=executor) as session:
        r_list = await session.run(
            "_ts = await tools.list()\n" "sorted([t['name'] for t in _ts])",
        )
        assert r_list.error is None
        assert "echo" in r_list.value

        r_call = await session.run("(await tools.echo.say(message='hi')).strip()")
        assert r_call.error is None
        assert r_call.value == "hi"

        source = "async def run(name: str) -> str:\n    return 'hi ' + name\n"
        r_wf = await session.run(
            "\n".join(
                [
                    f"await workflows.create('hello', {source!r}, 'desc')",
                    "(await workflows.get('hello'))['source']",
                ]
            )
        )
        assert r_wf.error is None
        assert r_wf.value == source

        r_art = await session.run(
            "\n".join(
                [
                    "await artifacts.save('obj', {'a': 1}, description='')",
                    "(await artifacts.load('obj'))['a']",
                ]
            )
        )
        assert r_art.error is None
        assert r_art.value == 1
