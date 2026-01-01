"""RPC protocol definitions for host<->kernel communication.

This module defines the message format for bidirectional RPC between the host
process and the Jupyter kernel subprocess. Messages are serialized as JSON and
sent via the stdin channel (input_request/input_reply).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RPCRequest:
    """RPC request from kernel to host.

    The kernel sends this via input_request with JSON in the prompt field.
    The host parses it, dispatches to the appropriate provider method,
    and sends back an RPCResponse.

    Attributes:
        method: The RPC method name (e.g., "call_tool", "invoke_skill").
        params: Method parameters as a dict.
        id: Unique request ID for correlation with response.
    """

    method: str
    params: dict[str, Any]
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for JSON transmission.

        Returns:
            Dict with type, id, method, and params fields.
        """
        return {
            "type": "rpc_request",
            "id": self.id,
            "method": self.method,
            "params": self.params,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RPCRequest:
        """Deserialize from dictionary.

        Args:
            data: Dict containing id, method, and params fields.

        Returns:
            RPCRequest instance.

        Raises:
            KeyError: If required fields are missing.
        """
        return cls(
            id=data["id"],
            method=data["method"],
            params=data.get("params", {}),
        )


@dataclass
class RPCResponse:
    """RPC response from host to kernel.

    The host sends this via input_reply with JSON in the value field.
    The kernel parses it and either returns the result or raises an error.

    Attributes:
        id: Request ID this response corresponds to.
        result: The method result (if successful).
        error: Structured error dict (if failed).
            Format: {"namespace": str, "operation": str, "message": str, "type": str}
            Non-dict values indicate a protocol violation and will raise RPCTransportError.
    """

    id: str
    result: Any = None
    error: dict[str, Any] | str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for JSON transmission.

        Returns:
            Dict with type, id, and either result or error field.
        """
        data: dict[str, Any] = {
            "type": "rpc_response",
            "id": self.id,
        }
        if self.error is not None:
            data["error"] = self.error
        else:
            data["result"] = self.result
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RPCResponse:
        """Deserialize from dictionary.

        Args:
            data: Dict containing id and either result or error field.

        Returns:
            RPCResponse instance.

        Raises:
            KeyError: If required fields are missing.
        """
        return cls(
            id=data["id"],
            result=data.get("result"),
            error=data.get("error"),
        )
