"""Unified tool type system for multi-callable interface."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ToolParameter:
    """A parameter for a tool callable.

    Represents one parameter in a tool callable's signature.
    """

    name: str
    type: str  # Python type string: "str", "int", "bool", "list[str]", etc.
    required: bool
    default: str | None = None
    description: str = ""

    def signature_fragment(self) -> str:
        """Generate Python signature fragment for this parameter.

        Examples:
            - Required: "target: str"
            - Optional with default: 'timeout: int = 30' or 'name: str = "default"'
            - Optional no default: "flags: str | None = None"
        """
        if self.required:
            return f"{self.name}: {self.type}"

        if self.default is not None:
            # Only quote string-type defaults, don't quote numeric/bool/etc
            if self.type == "str":
                # Check if already quoted to avoid double-quoting
                if self.default.startswith('"') and self.default.endswith('"'):
                    return f"{self.name}: {self.type} = {self.default}"
                return f'{self.name}: {self.type} = "{self.default}"'
            return f"{self.name}: {self.type} = {self.default}"

        return f"{self.name}: {self.type} | None = None"


@dataclass(frozen=True)
class ToolCallable:
    """A callable within a tool.

    Represents one way to invoke a tool (e.g., "syn_scan" for nmap).
    """

    name: str
    description: str
    parameters: tuple[ToolParameter, ...]

    def signature(self) -> str:
        """Generate Python-style signature string.

        Returns signature with required params first, then optional.

        Example: "scan(target: str, port: int = 80)"
        """
        if not self.parameters:
            return f"{self.name}()"

        # Sort parameters: required first, then optional
        required = [p for p in self.parameters if p.required]
        optional = [p for p in self.parameters if not p.required]
        sorted_params = required + optional

        param_strs = [p.signature_fragment() for p in sorted_params]
        return f"{self.name}({', '.join(param_strs)})"

    def __repr__(self) -> str:
        """Format as: signature: description"""
        return f"{self.signature()}: {self.description}"


@dataclass(frozen=True)
class Tool:
    """A tool with one or more callables.

    Represents a complete tool (e.g., "nmap") that can be invoked
    in multiple ways (e.g., "syn_scan", "udp_scan", "quick").
    """

    name: str
    description: str
    callables: tuple[ToolCallable, ...]
    tags: frozenset[str] = field(default_factory=frozenset)

    def signatures(self) -> list[str]:
        """Get all callable signatures for this tool."""
        return [c.signature() for c in self.callables]

    def __repr__(self) -> str:
        """Format tool with all callables for actionable display."""
        lines = [f"{self.name}: {self.description}"]
        for c in self.callables:
            lines.append(f"  {c!r}")
        return "\n".join(lines)
