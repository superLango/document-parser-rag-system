"""Tool registry with whitelist permissions and bounded results."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal


class ToolError(RuntimeError):
    pass


@dataclass
class ToolResult:
    ok: bool
    value: Any = None
    error: str | None = None
    denied: bool = False
    truncated: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "value": self.value,
            "error": self.error,
            "denied": self.denied,
            "truncated": self.truncated,
        }


ToolHandler = Callable[[dict[str, Any], dict[str, Any]], Awaitable[Any]]


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    permission: Literal["read", "write"] = "read"
    handler: ToolHandler | None = None
    timeout_seconds: float = 10.0
    metadata: dict[str, Any] = field(default_factory=dict)


class ToolRegistry:
    def __init__(self, max_result_chars: int = 4000) -> None:
        self.max_result_chars = max_result_chars
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.handler is None:
            raise ValueError(f"tool {tool.name} has no handler")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def catalog(self, allowed: list[str] | None = None) -> list[dict[str, Any]]:
        names = set(allowed) if allowed is not None else set(self._tools)
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
                "permission": tool.permission,
            }
            for name, tool in sorted(self._tools.items())
            if name in names
        ]

    def permissions(self) -> dict[str, str]:
        return {name: tool.permission for name, tool in sorted(self._tools.items())}

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        allowed: list[str],
        context: dict[str, Any],
    ) -> ToolResult:
        if name not in allowed:
            return ToolResult(ok=False, error="tool_not_allowed", denied=True)
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(ok=False, error=f"unknown_tool:{name}")
        try:
            value = await asyncio.wait_for(
                tool.handler(arguments or {}, context),
                timeout=tool.timeout_seconds,
            )
        except TimeoutError:
            return ToolResult(ok=False, error="tool_timeout")
        except Exception as exc:  # noqa: BLE001 - tool errors are observations
            return ToolResult(ok=False, error=str(exc)[:500])
        serialized = json.dumps(value, ensure_ascii=False, default=str)
        if len(serialized) > self.max_result_chars:
            value = {
                "truncated": True,
                "preview": serialized[: self.max_result_chars],
                "full_chars": len(serialized),
            }
            return ToolResult(ok=True, value=value, truncated=True)
        return ToolResult(ok=True, value=value)
