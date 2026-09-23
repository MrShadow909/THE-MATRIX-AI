"""OpenAI provider. Uses the official `openai` SDK if installed.
Included as part of Phase 2 (see BOSS_NEO_REVIEW.md) but functional now.
"""

from __future__ import annotations

import json
import os
from typing import Any

from neo_code.providers.base import Provider, ProviderResponse, ToolCall


class OpenAIProvider(Provider):
    """Provider backed by the OpenAI Chat Completions API (GPT models)."""

    id = "openai"

    def __init__(self, model: str, api_key: str | None = None, **kwargs):
        super().__init__(model, **kwargs)
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self._client = None

    def is_available(self) -> str | None:
        """None if the `openai` SDK is installed and an API key is
        set, else a human-readable reason it's not ready."""
        try:
            import openai  # noqa: F401
        except ImportError:
            return "The 'openai' package is not installed. Run: pip install openai"
        if not self.api_key:
            return "OPENAI_API_KEY is not set."
        return None

    def _get_client(self):
        """Lazily construct and cache the `openai.OpenAI` client."""
        if self._client is None:
            import openai

            self._client = openai.OpenAI(api_key=self.api_key)
        return self._client

    def complete(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
    ) -> ProviderResponse:
        """Translate NEO's Anthropic-shaped tool schemas into
        OpenAI's `function` tool format, call Chat Completions, and
        normalize the response (including best-effort JSON parsing of
        tool call arguments) into a ProviderResponse."""
        client = self._get_client()

        oa_tools = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"],
                },
            }
            for t in tool_schemas
        ]

        oa_messages = [{"role": "system", "content": system_prompt}, *messages]

        resp = client.chat.completions.create(
            model=self.model,
            messages=oa_messages,
            tools=oa_tools or None,
        )
        choice = resp.choices[0]
        msg = choice.message

        tool_calls: list[ToolCall] = []
        for call in msg.tool_calls or []:
            try:
                args = json.loads(call.function.arguments)
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(ToolCall(id=call.id, name=call.function.name, arguments=args))

        return ProviderResponse(
            text=msg.content or "",
            tool_calls=tool_calls,
            stop_reason=choice.finish_reason,
            raw=resp,
        )
