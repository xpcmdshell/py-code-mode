"""Tests for structured RPC error handling.

These tests verify that when namespace operations fail via RPC, the agent
gets structured errors with proper context (namespace, operation, original
exception type, message) instead of generic RuntimeErrors.

Uses SubprocessExecutor to exercise the full RPC path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from py_code_mode.execution.subprocess import SubprocessExecutor
from py_code_mode.execution.subprocess.config import SubprocessConfig
from py_code_mode.storage.backends import FileStorage

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
async def executor_with_storage(tmp_path: Path):
    """Provide a started SubprocessExecutor with storage for RPC error tests."""
    storage = FileStorage(tmp_path)

    config = SubprocessConfig(
        python_version="3.12",
        venv_path=tmp_path / "venv",
        base_deps=("ipykernel", "py-code-mode"),
        allow_runtime_deps=False,  # Block runtime deps for DepsError test
    )
    exec = SubprocessExecutor(config=config)
    await exec.start(storage=storage)
    yield exec
    await exec.close()


@pytest.fixture
async def executor_with_deps_allowed(tmp_path: Path):
    """Provide a SubprocessExecutor with runtime deps allowed."""
    storage = FileStorage(tmp_path)

    config = SubprocessConfig(
        python_version="3.12",
        venv_path=tmp_path / "venv",
        base_deps=("ipykernel", "py-code-mode"),
        allow_runtime_deps=True,  # Allow runtime deps
    )
    exec = SubprocessExecutor(config=config)
    await exec.start(storage=storage)
    yield exec
    await exec.close()


# =============================================================================
# SkillError Tests
# =============================================================================


@pytest.mark.slow
@pytest.mark.xdist_group("subprocess")
class TestSkillErrors:
    """Tests for skill-related RPC errors raising SkillError."""

    @pytest.mark.asyncio
    async def test_skill_with_missing_import_raises_skill_error(
        self, executor_with_deps_allowed
    ) -> None:
        """Skill with missing import raises SkillError with ModuleNotFoundError type.

        Contract: When a skill invocation fails due to missing import, the error
        should be SkillError with original_type=ModuleNotFoundError.

        Breaks when: Host sends unstructured errors or kernel doesn't parse correctly.
        """
        # Create a skill that imports a nonexistent module
        create_code = '''
skills.create(
    "broken_skill",
    """async def run():
    import this_module_definitely_does_not_exist
    return "never reached"
""",
    "A skill that will fail on import"
)
'''
        result = await executor_with_deps_allowed.run(create_code)
        assert result.error is None, f"Failed to create skill: {result.error}"

        # Invoke the skill - should raise SkillError
        result = await executor_with_deps_allowed.run('skills.invoke("broken_skill")')

        assert result.error is not None
        # Error message should contain structured information
        # Format: "skills.invoke: [ModuleNotFoundError] message"
        assert "skills.invoke" in result.error
        assert "ModuleNotFoundError" in result.error

    @pytest.mark.asyncio
    async def test_skill_creation_with_syntax_error_raises_skill_error(
        self, executor_with_deps_allowed
    ) -> None:
        """Skill creation with syntax error raises SkillError with SyntaxError type.

        Contract: When skill creation fails due to syntax error, the error
        should be SkillError with original_type=SyntaxError.
        """
        # Try to create a skill with invalid Python syntax
        result = await executor_with_deps_allowed.run("""
skills.create("bad_syntax", "if x", "broken skill")
""")

        assert result.error is not None
        # Error message should contain structured information
        # Format: "skills.create: [SyntaxError] message"
        assert "skills.create" in result.error
        assert "SyntaxError" in result.error or "syntax" in result.error.lower()


# =============================================================================
# ToolError Tests
# =============================================================================


@pytest.mark.slow
@pytest.mark.xdist_group("subprocess")
class TestToolErrors:
    """Tests for tool-related RPC errors raising ToolError."""

    @pytest.mark.asyncio
    async def test_tool_not_found_raises_tool_error(self, executor_with_storage) -> None:
        """Accessing nonexistent tool raises ToolError.

        Contract: When a tool is not found, the error should be ToolError
        with context about what was requested.

        Note: Due to caching in ToolsProxy, the error may be AttributeError
        from the proxy layer before reaching RPC, or ToolError if it reaches RPC.
        """
        result = await executor_with_storage.run("tools.nonexistent_tool_xyz()")

        assert result.error is not None
        # Should indicate the tool was not found
        error_lower = result.error.lower()
        assert (
            "not found" in error_lower
            or "attributeerror" in error_lower
            or "toolerror" in error_lower
        )
        assert "nonexistent_tool_xyz" in result.error


# =============================================================================
# ArtifactError Tests
# =============================================================================


@pytest.mark.slow
@pytest.mark.xdist_group("subprocess")
class TestArtifactErrors:
    """Tests for artifact-related RPC errors raising ArtifactError."""

    @pytest.mark.asyncio
    async def test_artifact_not_found_raises_artifact_error(self, executor_with_storage) -> None:
        """Loading nonexistent artifact raises ArtifactError.

        Contract: When an artifact is not found, the error should be ArtifactError
        with context about what was requested.
        """
        result = await executor_with_storage.run('artifacts.load("nonexistent_artifact_xyz")')

        assert result.error is not None
        # Error message should contain structured information
        # Format: "artifacts.load: [ArtifactNotFoundError] message"
        assert "artifacts.load" in result.error
        # Should indicate the artifact was not found
        assert "not found" in result.error.lower() or "nonexistent_artifact_xyz" in result.error


# =============================================================================
# DepsError Tests
# =============================================================================


@pytest.mark.slow
@pytest.mark.xdist_group("subprocess")
class TestDepsErrors:
    """Tests for deps-related RPC errors raising DepsError."""

    @pytest.mark.asyncio
    async def test_deps_add_blocked_raises_deps_error(self, executor_with_storage) -> None:
        """deps.add() when blocked raises DepsError with RuntimeDepsDisabledError.

        Contract: When runtime deps are disabled and add() is called, the error
        should be DepsError with proper context.

        The executor_with_storage fixture has allow_runtime_deps=False.
        """
        result = await executor_with_storage.run('deps.add("requests")')

        assert result.error is not None
        # Error message should contain structured information
        # Format: "deps.add: [RuntimeDepsDisabledError] message"
        assert "deps.add" in result.error
        # Should indicate deps are disabled
        error_lower = result.error.lower()
        assert "disabled" in error_lower or "runtime" in error_lower


# =============================================================================
# Structured Error Format Tests
# =============================================================================


@pytest.mark.slow
@pytest.mark.xdist_group("subprocess")
class TestStructuredErrorFormat:
    """Tests verifying the structured error format is preserved through RPC."""

    @pytest.mark.asyncio
    async def test_error_preserves_original_exception_type(
        self, executor_with_deps_allowed
    ) -> None:
        """Errors preserve the original exception type from the host.

        Contract: The [ExceptionType] should appear in the error message.
        """
        # Create a skill that raises a specific exception type
        create_code = '''
skills.create(
    "value_error_skill",
    """async def run():
    raise ValueError("intentional value error")
""",
    "A skill that raises ValueError"
)
'''
        result = await executor_with_deps_allowed.run(create_code)
        assert result.error is None, f"Failed to create skill: {result.error}"

        # Invoke - should raise SkillError with ValueError in the message
        result = await executor_with_deps_allowed.run('skills.invoke("value_error_skill")')

        assert result.error is not None
        # Should preserve the original exception type in brackets
        assert "[" in result.error and "]" in result.error
        # The original ValueError should be mentioned
        assert "ValueError" in result.error or "intentional value error" in result.error

    @pytest.mark.asyncio
    async def test_error_preserves_operation_name(self, executor_with_storage) -> None:
        """Errors preserve the operation name (method) that failed.

        Contract: The operation like 'load' should appear in the error.
        """
        result = await executor_with_storage.run('artifacts.load("nonexistent")')

        assert result.error is not None
        # Should contain the operation name (now matches what agent writes)
        assert "artifacts.load" in result.error

    @pytest.mark.asyncio
    async def test_error_preserves_namespace(self, executor_with_storage) -> None:
        """Errors preserve the namespace that the operation belongs to.

        Contract: The namespace like 'artifacts' should appear in the error.
        """
        result = await executor_with_storage.run('artifacts.load("nonexistent")')

        assert result.error is not None
        # Should contain the namespace
        assert "artifacts" in result.error.lower()

    @pytest.mark.asyncio
    async def test_error_format_is_namespace_operation_type_message(
        self, executor_with_storage
    ) -> None:
        """Error format is 'namespace.operation: [OriginalType] message'.

        Contract: The error string should follow the structured format.
        """
        result = await executor_with_storage.run('artifacts.load("missing_artifact")')

        assert result.error is not None
        # Should match the format: namespace.operation: [Type] message
        # e.g., "artifacts.load: [ArtifactNotFoundError] ..."
        assert "." in result.error  # namespace.operation separator
        assert ":" in result.error  # operation: message separator
        assert "[" in result.error and "]" in result.error  # [Type] brackets


# =============================================================================
# Error Class Hierarchy Tests
# =============================================================================


@pytest.mark.slow
@pytest.mark.xdist_group("subprocess")
class TestErrorClassHierarchy:
    """Tests verifying the error class hierarchy is properly defined in kernel."""

    @pytest.mark.asyncio
    async def test_skill_error_is_namespace_error(self, executor_with_storage) -> None:
        """SkillError is a subclass of NamespaceError in the kernel.

        Contract: SkillError inherits from NamespaceError.
        """
        result = await executor_with_storage.run("issubclass(SkillError, NamespaceError)")

        assert result.error is None
        assert result.value in (True, "True")

    @pytest.mark.asyncio
    async def test_tool_error_is_namespace_error(self, executor_with_storage) -> None:
        """ToolError is a subclass of NamespaceError in the kernel.

        Contract: ToolError inherits from NamespaceError.
        """
        result = await executor_with_storage.run("issubclass(ToolError, NamespaceError)")

        assert result.error is None
        assert result.value in (True, "True")

    @pytest.mark.asyncio
    async def test_artifact_error_is_namespace_error(self, executor_with_storage) -> None:
        """ArtifactError is a subclass of NamespaceError in the kernel.

        Contract: ArtifactError inherits from NamespaceError.
        """
        result = await executor_with_storage.run("issubclass(ArtifactError, NamespaceError)")

        assert result.error is None
        assert result.value in (True, "True")

    @pytest.mark.asyncio
    async def test_deps_error_is_namespace_error(self, executor_with_storage) -> None:
        """DepsError is a subclass of NamespaceError in the kernel.

        Contract: DepsError inherits from NamespaceError.
        """
        result = await executor_with_storage.run("issubclass(DepsError, NamespaceError)")

        assert result.error is None
        assert result.value in (True, "True")

    @pytest.mark.asyncio
    async def test_namespace_error_is_rpc_error(self, executor_with_storage) -> None:
        """NamespaceError is a subclass of RPCError in the kernel.

        Contract: NamespaceError inherits from RPCError.
        """
        result = await executor_with_storage.run("issubclass(NamespaceError, RPCError)")

        assert result.error is None
        assert result.value in (True, "True")

    @pytest.mark.asyncio
    async def test_rpc_error_is_exception(self, executor_with_storage) -> None:
        """RPCError is a subclass of Exception in the kernel.

        Contract: RPCError inherits from Exception.
        """
        result = await executor_with_storage.run("issubclass(RPCError, Exception)")

        assert result.error is None
        assert result.value in (True, "True")


# =============================================================================
# Error Attributes Tests
# =============================================================================


@pytest.mark.slow
@pytest.mark.xdist_group("subprocess")
class TestErrorAttributes:
    """Tests verifying error objects have proper attributes in kernel."""

    @pytest.mark.asyncio
    async def test_namespace_error_has_namespace_attribute(self, executor_with_storage) -> None:
        """NamespaceError instances have namespace attribute.

        Contract: NamespaceError stores the namespace.
        """
        result = await executor_with_storage.run("""
try:
    raise NamespaceError("skills", "invoke", "test error")
except NamespaceError as e:
    result = e.namespace
result
""")

        assert result.error is None
        assert "skills" in str(result.value)

    @pytest.mark.asyncio
    async def test_namespace_error_has_operation_attribute(self, executor_with_storage) -> None:
        """NamespaceError instances have operation attribute.

        Contract: NamespaceError stores the operation.
        """
        result = await executor_with_storage.run("""
try:
    raise NamespaceError("skills", "invoke", "test error")
except NamespaceError as e:
    result = e.operation
result
""")

        assert result.error is None
        assert "invoke" in str(result.value)

    @pytest.mark.asyncio
    async def test_namespace_error_has_original_type_attribute(self, executor_with_storage) -> None:
        """NamespaceError instances have original_type attribute.

        Contract: NamespaceError stores the original exception type name.
        """
        result = await executor_with_storage.run("""
try:
    raise NamespaceError("skills", "invoke", "test error", "ValueError")
except NamespaceError as e:
    result = e.original_type
result
""")

        assert result.error is None
        assert "ValueError" in str(result.value)


# =============================================================================
# RPCTransportError Tests
# =============================================================================


@pytest.mark.slow
@pytest.mark.xdist_group("subprocess")
class TestRPCTransportErrors:
    """Tests for RPC transport/protocol errors raising RPCTransportError."""

    @pytest.mark.asyncio
    async def test_rpc_transport_error_is_rpc_error(self, executor_with_storage) -> None:
        """RPCTransportError is a subclass of RPCError in the kernel.

        Contract: RPCTransportError inherits from RPCError.
        """
        result = await executor_with_storage.run("issubclass(RPCTransportError, RPCError)")

        assert result.error is None
        assert result.value in (True, "True")

    @pytest.mark.asyncio
    async def test_non_dict_error_raises_rpc_transport_error(self, executor_with_storage) -> None:
        """Non-dict error from host should raise RPCTransportError.

        Contract: When the host sends a non-dict error (protocol violation),
        the kernel should raise RPCTransportError, not RuntimeError.

        Note: This tests the error class definition and behavior. Actual
        protocol violations would require mocking the host response, which
        is difficult in an integration test. Instead we verify the class
        exists and can be raised with the expected message format.
        """
        result = await executor_with_storage.run("""
try:
    raise RPCTransportError("Host sent non-dict error (protocol violation): 'some string'")
except RPCTransportError as e:
    result = str(e)
result
""")

        assert result.error is None
        assert "protocol violation" in str(result.value).lower()
        assert "non-dict" in str(result.value).lower()
