"""Docker log diagnostics helpers for pytest failures."""

from __future__ import annotations

from typing import Any


def did_test_fail(node: Any) -> bool:
    """Return True when setup/call/teardown failed for the current test."""
    for phase in ("setup", "call", "teardown"):
        report = getattr(node, f"rep_{phase}", None)
        if report and report.failed:
            return True
    return False


def _decode_log_output(output: bytes | str | None, max_chars: int = 40_000) -> str:
    """Decode docker log payload and keep only the tail to avoid huge failures."""
    if output is None:
        return ""
    if isinstance(output, bytes):
        text = output.decode("utf-8", errors="replace")
    else:
        text = output
    if len(text) <= max_chars:
        return text
    truncated = len(text) - max_chars
    return f"... [truncated {truncated} chars]\n{text[-max_chars:]}"


def _emit_container_logs(
    *,
    source: str,
    container_id: str,
    stdout: bytes | str | None,
    stderr: bytes | str | None,
) -> None:
    """Print container logs into pytest captured output for failed tests."""
    stdout_text = _decode_log_output(stdout).strip()
    stderr_text = _decode_log_output(stderr).strip()
    if not stdout_text and not stderr_text:
        return
    print("\n========== Docker container logs ==========")
    print(f"source: {source}")
    print(f"container: {container_id}")
    if stdout_text:
        print("----- stdout -----")
        print(stdout_text)
    if stderr_text:
        print("----- stderr -----")
        print(stderr_text)
    print("==========================================")


def emit_executor_container_logs(container: Any, source: str) -> None:
    """Best-effort log dump for docker SDK containers used by ContainerExecutor."""
    container_id = getattr(container, "id", "unknown")
    try:
        stdout = container.logs(stdout=True, stderr=False)
        stderr = container.logs(stdout=False, stderr=True)
    except Exception as exc:  # noqa: BLE001
        print(
            f"\n[container-log-capture] failed for {source} ({container_id}): {exc}",
        )
        return
    _emit_container_logs(
        source=source,
        container_id=container_id,
        stdout=stdout,
        stderr=stderr,
    )


def emit_testcontainer_logs(container: Any, source: str) -> None:
    """Best-effort log dump for testcontainers containers."""
    container_id = "unknown"
    try:
        wrapped = container.get_wrapped_container()
        container_id = getattr(wrapped, "id", "unknown")
    except Exception:  # noqa: BLE001
        pass
    try:
        stdout, stderr = container.get_logs()
    except Exception as exc:  # noqa: BLE001
        print(
            f"\n[container-log-capture] failed for {source} ({container_id}): {exc}",
        )
        return
    _emit_container_logs(
        source=source,
        container_id=container_id,
        stdout=stdout,
        stderr=stderr,
    )
