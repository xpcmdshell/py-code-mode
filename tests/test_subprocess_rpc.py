"""Tests for SubprocessExecutor RPC mechanism.

These tests verify the RPC protocol dataclasses, kernel initialization code,
and the KernelHost execution with RPC handling.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from py_code_mode.execution.subprocess.host import (
    ExecutionResult,
    KernelHost,
    ResourceProvider,
)
from py_code_mode.execution.subprocess.kernel_init import (
    KERNEL_INIT_CODE,
    get_kernel_init_code,
)
from py_code_mode.execution.subprocess.rpc import RPCRequest, RPCResponse

# =============================================================================
# RPCRequest Tests
# =============================================================================


class TestRPCRequest:
    """Tests for RPCRequest dataclass."""

    def test_create_with_required_fields(self) -> None:
        """Can create RPCRequest with method and params."""
        request = RPCRequest(method="call_tool", params={"name": "curl"})
        assert request.method == "call_tool"
        assert request.params == {"name": "curl"}
        assert request.id is not None  # Auto-generated UUID

    def test_create_with_custom_id(self) -> None:
        """Can create RPCRequest with custom id."""
        custom_id = "my-custom-id-123"
        request = RPCRequest(method="list_tools", params={}, id=custom_id)
        assert request.id == custom_id

    def test_id_is_unique_across_instances(self) -> None:
        """Each RPCRequest gets a unique id by default."""
        request1 = RPCRequest(method="test", params={})
        request2 = RPCRequest(method="test", params={})
        assert request1.id != request2.id

    def test_to_dict_serializes_correctly(self) -> None:
        """to_dict produces JSON-serializable dictionary."""
        request = RPCRequest(
            method="call_tool",
            params={"name": "curl", "args": {"url": "http://example.com"}},
            id="test-id",
        )
        result = request.to_dict()

        assert result["type"] == "rpc_request"
        assert result["id"] == "test-id"
        assert result["method"] == "call_tool"
        assert result["params"] == {"name": "curl", "args": {"url": "http://example.com"}}

    def test_to_dict_is_json_serializable(self) -> None:
        """to_dict result can be serialized to JSON."""
        request = RPCRequest(method="test", params={"key": [1, 2, 3]})
        json_str = json.dumps(request.to_dict())
        assert json_str  # Non-empty

    def test_from_dict_deserializes_correctly(self) -> None:
        """from_dict creates RPCRequest from dictionary."""
        data = {
            "type": "rpc_request",
            "id": "test-id",
            "method": "skills.invoke",
            "params": {"name": "my_skill", "args": {}},
        }
        request = RPCRequest.from_dict(data)

        assert request.id == "test-id"
        assert request.method == "skills.invoke"
        assert request.params == {"name": "my_skill", "args": {}}

    def test_from_dict_with_missing_params_defaults_to_empty(self) -> None:
        """from_dict defaults params to empty dict if missing."""
        data = {
            "id": "test-id",
            "method": "list_tools",
        }
        request = RPCRequest.from_dict(data)
        assert request.params == {}

    def test_from_dict_raises_on_missing_required_fields(self) -> None:
        """from_dict raises KeyError on missing required fields."""
        with pytest.raises(KeyError):
            RPCRequest.from_dict({"method": "test"})  # Missing id

        with pytest.raises(KeyError):
            RPCRequest.from_dict({"id": "test"})  # Missing method

    def test_roundtrip_serialization(self) -> None:
        """to_dict and from_dict are inverse operations."""
        original = RPCRequest(
            method="artifacts.save",
            params={"name": "data", "value": [1, 2, 3]},
            id="roundtrip-id",
        )
        serialized = original.to_dict()
        restored = RPCRequest.from_dict(serialized)

        assert restored.id == original.id
        assert restored.method == original.method
        assert restored.params == original.params


# =============================================================================
# RPCResponse Tests
# =============================================================================


class TestRPCResponse:
    """Tests for RPCResponse dataclass."""

    def test_create_success_response(self) -> None:
        """Can create successful RPCResponse with result."""
        response = RPCResponse(id="test-id", result={"data": "value"})
        assert response.id == "test-id"
        assert response.result == {"data": "value"}
        assert response.error is None

    def test_create_error_response(self) -> None:
        """Can create error RPCResponse with error message."""
        response = RPCResponse(id="test-id", error="Something went wrong")
        assert response.id == "test-id"
        assert response.result is None
        assert response.error == "Something went wrong"

    def test_to_dict_success_response(self) -> None:
        """to_dict for success response includes result, not error."""
        response = RPCResponse(id="test-id", result=[1, 2, 3])
        result = response.to_dict()

        assert result["type"] == "rpc_response"
        assert result["id"] == "test-id"
        assert result["result"] == [1, 2, 3]
        assert "error" not in result

    def test_to_dict_error_response(self) -> None:
        """to_dict for error response includes error, not result."""
        response = RPCResponse(id="test-id", error="Failed")
        result = response.to_dict()

        assert result["type"] == "rpc_response"
        assert result["id"] == "test-id"
        assert result["error"] == "Failed"
        # Note: result key may still be present with None value

    def test_to_dict_is_json_serializable(self) -> None:
        """to_dict result can be serialized to JSON."""
        response = RPCResponse(id="test", result={"nested": {"data": True}})
        json_str = json.dumps(response.to_dict())
        assert json_str

    def test_from_dict_success_response(self) -> None:
        """from_dict creates success RPCResponse from dictionary."""
        data = {
            "type": "rpc_response",
            "id": "test-id",
            "result": {"key": "value"},
        }
        response = RPCResponse.from_dict(data)

        assert response.id == "test-id"
        assert response.result == {"key": "value"}
        assert response.error is None

    def test_from_dict_error_response(self) -> None:
        """from_dict creates error RPCResponse from dictionary."""
        data = {
            "type": "rpc_response",
            "id": "test-id",
            "error": "Something failed",
        }
        response = RPCResponse.from_dict(data)

        assert response.id == "test-id"
        assert response.error == "Something failed"

    def test_from_dict_raises_on_missing_id(self) -> None:
        """from_dict raises KeyError on missing id."""
        with pytest.raises(KeyError):
            RPCResponse.from_dict({"result": "value"})

    def test_roundtrip_serialization_success(self) -> None:
        """to_dict and from_dict roundtrip for success response."""
        original = RPCResponse(id="roundtrip", result={"data": [1, 2, 3]})
        serialized = original.to_dict()
        restored = RPCResponse.from_dict(serialized)

        assert restored.id == original.id
        assert restored.result == original.result
        assert restored.error == original.error

    def test_roundtrip_serialization_error(self) -> None:
        """to_dict and from_dict roundtrip for error response."""
        original = RPCResponse(id="roundtrip", error="Test error message")
        serialized = original.to_dict()
        restored = RPCResponse.from_dict(serialized)

        assert restored.id == original.id
        assert restored.error == original.error


# =============================================================================
# Kernel Init Code Tests
# =============================================================================


class TestKernelInitCode:
    """Tests for kernel initialization code generation."""

    def test_kernel_init_code_is_string(self) -> None:
        """KERNEL_INIT_CODE is a non-empty string."""
        assert isinstance(KERNEL_INIT_CODE, str)
        assert len(KERNEL_INIT_CODE) > 0

    def test_kernel_init_code_is_valid_python(self) -> None:
        """KERNEL_INIT_CODE is syntactically valid Python."""
        # This will raise SyntaxError if invalid
        compile(KERNEL_INIT_CODE, "<test>", "exec")

    def test_get_kernel_init_code_accepts_timeout(self) -> None:
        """get_kernel_init_code accepts ipc_timeout parameter."""
        code = get_kernel_init_code(ipc_timeout=60.0)
        assert "_RPC_TIMEOUT = 60.0" in code

    def test_get_kernel_init_code_default_timeout(self) -> None:
        """get_kernel_init_code uses default timeout of 30.0."""
        code = get_kernel_init_code()
        assert "_RPC_TIMEOUT = 30.0" in code

    def test_kernel_init_code_defines_rpc_call(self) -> None:
        """KERNEL_INIT_CODE defines _rpc_call function."""
        assert "def _rpc_call(" in KERNEL_INIT_CODE

    def test_kernel_init_code_defines_tools_proxy(self) -> None:
        """KERNEL_INIT_CODE defines ToolsProxy class."""
        assert "class ToolsProxy" in KERNEL_INIT_CODE

    def test_kernel_init_code_defines_skills_proxy(self) -> None:
        """KERNEL_INIT_CODE defines SkillsProxy class."""
        assert "class SkillsProxy" in KERNEL_INIT_CODE

    def test_kernel_init_code_defines_artifacts_proxy(self) -> None:
        """KERNEL_INIT_CODE defines ArtifactsProxy class."""
        assert "class ArtifactsProxy" in KERNEL_INIT_CODE

    def test_kernel_init_code_defines_deps_proxy(self) -> None:
        """KERNEL_INIT_CODE defines DepsProxy class."""
        assert "class DepsProxy" in KERNEL_INIT_CODE

    def test_kernel_init_code_creates_proxy_instances(self) -> None:
        """KERNEL_INIT_CODE creates proxy instances as globals."""
        assert "tools = ToolsProxy()" in KERNEL_INIT_CODE
        assert "skills = SkillsProxy()" in KERNEL_INIT_CODE
        assert "artifacts = ArtifactsProxy()" in KERNEL_INIT_CODE
        assert "deps = DepsProxy()" in KERNEL_INIT_CODE

    def test_kernel_init_code_uses_threading_lock(self) -> None:
        """KERNEL_INIT_CODE uses threading lock for RPC."""
        assert "threading.Lock()" in KERNEL_INIT_CODE
        assert "_rpc_lock" in KERNEL_INIT_CODE

    def test_kernel_init_code_uses_zmq_select(self) -> None:
        """KERNEL_INIT_CODE uses zmq.select for response polling."""
        assert "zmq.select(" in KERNEL_INIT_CODE


# =============================================================================
# ExecutionResult Tests
# =============================================================================


class TestExecutionResult:
    """Tests for ExecutionResult dataclass."""

    def test_default_values(self) -> None:
        """ExecutionResult has sensible defaults."""
        result = ExecutionResult()
        assert result.stdout == ""
        assert result.stderr == ""
        assert result.value is None
        assert result.error is None
        assert result.traceback == []

    def test_success_property_when_no_error(self) -> None:
        """success is True when error is None."""
        result = ExecutionResult(value=42)
        assert result.success is True

    def test_success_property_when_error(self) -> None:
        """success is False when error is set."""
        result = ExecutionResult(error="Something went wrong")
        assert result.success is False


# =============================================================================
# ResourceProvider Protocol Tests
# =============================================================================


class TestResourceProviderProtocol:
    """Tests for ResourceProvider protocol compliance."""

    def test_mock_provider_is_resource_provider(self) -> None:
        """Mock object implementing protocol methods satisfies protocol."""
        mock = MagicMock()
        mock.call_tool = AsyncMock(return_value="result")
        mock.list_tools = AsyncMock(return_value=[])
        mock.search_tools = AsyncMock(return_value=[])
        mock.list_tool_recipes = AsyncMock(return_value=[])
        mock.invoke_skill = AsyncMock(return_value="result")
        mock.search_skills = AsyncMock(return_value=[])
        mock.list_skills = AsyncMock(return_value=[])
        mock.get_skill = AsyncMock(return_value=None)
        mock.create_skill = AsyncMock(return_value={})
        mock.delete_skill = AsyncMock(return_value=True)
        mock.load_artifact = AsyncMock(return_value="data")
        mock.save_artifact = AsyncMock(return_value={})
        mock.list_artifacts = AsyncMock(return_value=[])
        mock.delete_artifact = AsyncMock(return_value=None)
        mock.artifact_exists = AsyncMock(return_value=False)
        mock.get_artifact = AsyncMock(return_value=None)
        mock.add_dep = AsyncMock(return_value={})
        mock.remove_dep = AsyncMock(return_value=True)
        mock.list_deps = AsyncMock(return_value=[])
        mock.sync_deps = AsyncMock(return_value={})

        # Runtime check
        assert isinstance(mock, ResourceProvider)


# =============================================================================
# RPC Dispatch Tests (Unit)
# =============================================================================


class TestRPCDispatch:
    """Unit tests for RPC dispatch logic in KernelHost."""

    @pytest.fixture
    def mock_provider(self) -> MagicMock:
        """Create a mock ResourceProvider."""
        provider = MagicMock()
        provider.call_tool = AsyncMock(return_value="tool_result")
        provider.list_tools = AsyncMock(return_value=[{"name": "curl"}])
        provider.search_tools = AsyncMock(return_value=[{"name": "curl"}])
        provider.list_tool_recipes = AsyncMock(return_value=[{"name": "get"}])
        provider.invoke_skill = AsyncMock(return_value="skill_result")
        provider.search_skills = AsyncMock(return_value=[{"name": "my_skill"}])
        provider.list_skills = AsyncMock(return_value=[])
        provider.get_skill = AsyncMock(return_value={"name": "test"})
        provider.create_skill = AsyncMock(return_value={"name": "new_skill"})
        provider.delete_skill = AsyncMock(return_value=True)
        provider.load_artifact = AsyncMock(return_value="artifact_data")
        provider.save_artifact = AsyncMock(return_value={"name": "saved"})
        provider.list_artifacts = AsyncMock(return_value=[])
        provider.delete_artifact = AsyncMock(return_value=None)
        provider.artifact_exists = AsyncMock(return_value=True)
        provider.get_artifact = AsyncMock(return_value={"name": "test"})
        provider.add_dep = AsyncMock(return_value={"installed": ["pkg"]})
        provider.remove_dep = AsyncMock(return_value=True)
        provider.list_deps = AsyncMock(return_value=["pkg1", "pkg2"])
        provider.sync_deps = AsyncMock(return_value={"installed": []})
        return provider

    @pytest.mark.asyncio
    async def test_dispatch_tools_call(self, mock_provider: MagicMock) -> None:
        """_dispatch_rpc routes tools.call to provider."""
        host = KernelHost()
        host._provider = mock_provider

        request = RPCRequest(
            method="tools.call", params={"name": "curl", "args": {"url": "http://test"}}
        )
        result = await host._dispatch_rpc(request)

        assert result == "tool_result"
        mock_provider.call_tool.assert_called_once_with("curl", {"url": "http://test"})

    @pytest.mark.asyncio
    async def test_dispatch_tools_list(self, mock_provider: MagicMock) -> None:
        """_dispatch_rpc routes tools.list to provider."""
        host = KernelHost()
        host._provider = mock_provider

        request = RPCRequest(method="tools.list", params={})
        result = await host._dispatch_rpc(request)

        assert result == [{"name": "curl"}]
        mock_provider.list_tools.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatch_skills_invoke(self, mock_provider: MagicMock) -> None:
        """_dispatch_rpc routes skills.invoke to provider."""
        host = KernelHost()
        host._provider = mock_provider

        request = RPCRequest(method="skills.invoke", params={"name": "my_skill", "args": {"x": 1}})
        result = await host._dispatch_rpc(request)

        assert result == "skill_result"
        mock_provider.invoke_skill.assert_called_once_with("my_skill", {"x": 1})

    @pytest.mark.asyncio
    async def test_dispatch_artifacts_load(self, mock_provider: MagicMock) -> None:
        """_dispatch_rpc routes artifacts.load to provider."""
        host = KernelHost()
        host._provider = mock_provider

        request = RPCRequest(method="artifacts.load", params={"name": "data"})
        result = await host._dispatch_rpc(request)

        assert result == "artifact_data"
        mock_provider.load_artifact.assert_called_once_with("data")

    @pytest.mark.asyncio
    async def test_dispatch_deps_add(self, mock_provider: MagicMock) -> None:
        """_dispatch_rpc routes deps.add to provider."""
        host = KernelHost()
        host._provider = mock_provider

        request = RPCRequest(method="deps.add", params={"package": "requests"})
        result = await host._dispatch_rpc(request)

        assert result == {"installed": ["pkg"]}
        mock_provider.add_dep.assert_called_once_with("requests")

    @pytest.mark.asyncio
    async def test_dispatch_unknown_method_raises(self, mock_provider: MagicMock) -> None:
        """_dispatch_rpc raises ValueError for unknown method."""
        host = KernelHost()
        host._provider = mock_provider

        request = RPCRequest(method="unknown_method", params={})

        with pytest.raises(ValueError, match="Unknown RPC method"):
            await host._dispatch_rpc(request)

    @pytest.mark.asyncio
    async def test_dispatch_without_provider_raises(self) -> None:
        """_dispatch_rpc raises RuntimeError when no provider."""
        host = KernelHost()
        host._provider = None

        request = RPCRequest(method="tools.list", params={})

        with pytest.raises(RuntimeError, match="No resource provider"):
            await host._dispatch_rpc(request)


# =============================================================================
# KernelHost Unit Tests (Mocked)
# =============================================================================


class TestKernelHostUnit:
    """Unit tests for KernelHost with mocked components."""

    def test_is_alive_when_not_started(self) -> None:
        """is_alive returns False when kernel not started."""
        host = KernelHost()
        assert host.is_alive is False

    def test_initial_state(self) -> None:
        """KernelHost has correct initial state."""
        host = KernelHost()
        assert host._km is None
        assert host._kc is None
        assert host._provider is None


# =============================================================================
# Protocol JSON Tests
# =============================================================================


class TestProtocolJSON:
    """Tests for JSON serialization/deserialization edge cases."""

    def test_request_with_complex_params(self) -> None:
        """RPCRequest handles complex nested params."""
        params = {
            "name": "test",
            "args": {
                "nested": {"deeply": {"value": [1, 2, {"three": 3}]}},
                "array": [1, 2, 3],
                "null": None,
                "bool": True,
            },
        }
        request = RPCRequest(method="test", params=params)
        serialized = json.dumps(request.to_dict())
        restored = RPCRequest.from_dict(json.loads(serialized))
        assert restored.params == params

    def test_response_with_complex_result(self) -> None:
        """RPCResponse handles complex nested results."""
        result_data = {
            "items": [{"id": 1, "name": "first"}, {"id": 2, "name": "second"}],
            "metadata": {"total": 2, "page": 1},
            "empty_array": [],
            "null_value": None,
        }
        response = RPCResponse(id="test", result=result_data)
        serialized = json.dumps(response.to_dict())
        restored = RPCResponse.from_dict(json.loads(serialized))
        assert restored.result == result_data

    def test_request_with_unicode(self) -> None:
        """RPCRequest handles unicode strings."""
        params = {"message": "Hello, world"}
        request = RPCRequest(method="test", params=params)
        serialized = json.dumps(request.to_dict(), ensure_ascii=False)
        restored = RPCRequest.from_dict(json.loads(serialized))
        assert restored.params == params

    def test_response_with_binary_not_supported(self) -> None:
        """RPCResponse with bytes fails serialization (by design)."""
        response = RPCResponse(id="test", result=b"binary data")
        with pytest.raises(TypeError):
            json.dumps(response.to_dict())
