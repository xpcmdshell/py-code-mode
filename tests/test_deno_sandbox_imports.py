import pytest


def test_deno_sandbox_imports() -> None:
    from py_code_mode.execution import DENO_SANDBOX_AVAILABLE

    if not DENO_SANDBOX_AVAILABLE:
        pytest.skip("Deno sandbox backend is optional and not available in this environment.")

    from py_code_mode.execution import DenoSandboxConfig, DenoSandboxExecutor

    assert DenoSandboxConfig is not None
    assert DenoSandboxExecutor is not None
