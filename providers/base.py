"""Provider abstraction. Every provider translates NEO's
internal message/tool format into its own API format and back, so
the Agent never needs to know which backend is in use.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    """A single tool invocation requested by the model: its provider-
    assigned id, the tool name, and the arguments dict."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ProviderResponse:
    """Normalized result of one `Provider.complete()` call: any text
    the model produced, any tool calls it requested, why it stopped,
    and the raw provider-native response for debugging."""

    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"
    raw: Any = None


class Provider:
    """Abstract provider. Subclasses implement `complete`."""

    id: str = "base"

    def __init__(self, model: str, **kwargs):
        self.model = model

    def complete(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
    ) -> ProviderResponse:
        """messages: list of {"role": "user"|"assistant"|"tool", "content": ...}
        Must return a ProviderResponse with any requested tool_calls.
        """
        raise NotImplementedError

    def is_available(self) -> str | None:
        """Return None if ready to use, else a human-readable reason it's not."""
        raise NotImplementedError
