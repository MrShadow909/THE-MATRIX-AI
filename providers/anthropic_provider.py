"""Anthropic provider. Uses the official `anthropic` SDK if installed.
Import is lazy so the rest of NEO works even without the package.
"""

from __future__ import annotations

import os
from typing import Any

from neo_code.providers.base import Provider, ProviderResponse, ToolCall


class AnthropicProvider(Provider):
    """Provider backed by the Anthropic Messages API (Claude models)."""

    id = "anthropic"

    def __init__(self, model: str, api_key: str | None = None, **kwargs):
        super().__init__(model, **kwargs)
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self._client = None

    def is_available(self) -> str | None:
        """None if the `anthropic` SDK is installed and an API key is
        set, else a human-readable reason it's not ready."""
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return "The 'anthropic' package is not installed. Run: pip install anthropic"
        if not self.api_key:
            return "ANTHROPIC_API_KEY is not set."
        return None

    def _get_client(self):
        """Lazily construct and cache the `anthropic.Anthropic` client."""
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    def complete(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
    ) -> ProviderResponse:
        """Call the Anthropic Messages API and normalize the response
        into a ProviderResponse (concatenated text blocks + parsed
        tool_use blocks)."""
        client = self._get_client()
        resp = client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system_prompt,
            messages=messages,
            tools=tool_schemas or None,
        )

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, arguments=block.input))

        return ProviderResponse(
            text="\n".join(text_parts),
            tool_calls=tool_calls,
            stop_reason=resp.stop_reason,
            raw=resp,
        )
