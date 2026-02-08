import pytest


def test_deno_sandbox_aliases_exist() -> None:
    from py_code_mode.execution import DENO_PYODIDE_AVAILABLE

    if not DENO_PYODIDE_AVAILABLE:
        pytest.skip("Deno sandbox backend is optional and not available in this environment.")

    from py_code_mode.execution import (
        DenoPyodideConfig,
        DenoPyodideExecutor,
        DenoSandboxConfig,
        DenoSandboxExecutor,
    )

    assert DenoSandboxConfig is DenoPyodideConfig
    assert DenoSandboxExecutor is DenoPyodideExecutor
