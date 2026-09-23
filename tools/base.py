"""Base Tool abstraction + registry.

Every concrete tool subclasses `Tool` and implements `run()`. The
registry exposes provider-agnostic JSON-schema descriptions so any
Provider (Anthropic/OpenAI/Ollama) can present the same tool set to
its underlying model in that provider's native tool-calling format.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from neo_code.core.permissions import PermissionLevel, PermissionManager


@dataclass
class ToolResult:
    """Outcome of one `Tool.run()` call: success flag, JSON-serializable
    output (on success), error message (on failure), and duration."""

    ok: bool
    output: Any = None
    error: str | None = None
    duration_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the plain dict shape fed back to the model as
        a tool_result message."""
        return {
            "ok": self.ok,
            "output": self.output,
            "error": self.error,
            "duration_s": round(self.duration_s, 3),
        }


class Tool:
    """Base class for every NEO tool. Subclasses set `name`,
    `description`, `parameters` (JSON schema), `permission`, and
    implement `execute()`. `run()` handles validation, permission
    checks, timing, and exception-to-error-string conversion so
    subclasses only need to implement the happy path."""

    name: str = "tool"
    description: str = ""
    permission: PermissionLevel = PermissionLevel.READ
    parameters: dict[str, Any] = {"type": "object", "properties": {}, "required": []}
    timeout_s: float = 30.0

    def schema(self) -> dict[str, Any]:
        """Provider-agnostic JSON-schema-shaped tool description, as
        consumed by ToolRegistry.schemas()."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }

    def validate(self, args: dict[str, Any]) -> str | None:
        """Return an error string if args are invalid, else None."""
        required = self.parameters.get("required", [])
        missing = [r for r in required if r not in args]
        if missing:
            return f"Missing required argument(s): {', '.join(missing)}"
        return None

    def describe_action(self, args: dict[str, Any]) -> str:
        """Human-readable description shown in confirmation prompts."""
        return f"{self.name}({args})"

    def execute(self, args: dict[str, Any]) -> Any:
        """Subclasses implement the tool's actual behavior here, raising
        on failure and returning a JSON-serializable result on success."""
        raise NotImplementedError

    def run(
        self,
        args: dict[str, Any],
        permissions: PermissionManager,
    ) -> ToolResult:
        """Validate args, check permissions, execute, and wrap the
        outcome (or any exception) in a ToolResult. This is the single
        entry point the Agent calls — subclasses should not override it."""
        start = time.time()
        err = self.validate(args)
        if err:
            return ToolResult(ok=False, error=err, duration_s=time.time() - start)

        if not permissions.check(self.describe_action(args), self.permission):
            return ToolResult(
                ok=False,
                error="Denied by user (permission not granted).",
                duration_s=time.time() - start,
            )

        try:
            output = self.execute(args)
            return ToolResult(ok=True, output=output, duration_s=time.time() - start)
        except Exception as exc:  # noqa: BLE001 - surface all tool errors to the model
            return ToolResult(ok=False, error=str(exc), duration_s=time.time() - start)


class ToolRegistry:
    """A simple name -> Tool lookup, populated by `build_tool_registry()`."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Add (or replace) a tool under its `.name`."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """Look up a tool by name, or None if not registered."""
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        """Return every registered tool."""
        return list(self._tools.values())

    def schemas(self) -> list[dict[str, Any]]:
        """JSON-schema descriptions of every registered tool, for
        passing to a Provider's `complete()` call."""
        return [t.schema() for t in self._tools.values()]

    def names(self) -> list[str]:
        """Return every registered tool's name."""
        return list(self._tools.keys())
