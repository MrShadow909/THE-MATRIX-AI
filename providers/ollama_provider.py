"""Ollama provider — talks to a local Ollama server over HTTP.
No API key required. Tool-calling support depends on the local model;
if the model doesn't emit tool calls, NEO simply operates in
text/chat mode for that turn.
"""

from __future__ import annotations

import json
from typing import Any

from neo_code.providers.base import Provider, ProviderResponse, ToolCall


class OllamaProvider(Provider):
    """Provider backed by a local Ollama server's `/api/chat` endpoint."""

    id = "ollama"

    def __init__(self, model: str, host: str = "http://localhost:11434", **kwargs):
        super().__init__(model, **kwargs)
        self.host = host.rstrip("/")

    def is_available(self) -> str | None:
        """None if `requests` is installed and the Ollama server at
        `self.host` responds to `/api/tags`, else a human-readable
        reason it's not ready."""
        try:
            import requests
        except ImportError:
            return "The 'requests' package is not installed. Run: pip install requests"
        try:
            r = requests.get(f"{self.host}/api/tags", timeout=3)
            if r.status_code != 200:
                return f"Ollama server responded with status {r.status_code}."
        except requests.RequestException as exc:
            return f"Cannot reach Ollama at {self.host}: {exc}"
        return None

    def complete(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
    ) -> ProviderResponse:
        """POST to Ollama's `/api/chat`, serializing any structured
        (list-typed) message content to a JSON string first since
        Ollama expects plain string content, and normalize the
        response into a ProviderResponse."""
        import requests

        ollama_tools = [
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

        ollama_messages = [{"role": "system", "content": system_prompt}]
        for m in messages:
            content = m["content"]
            if isinstance(content, list):
                content = json.dumps(content)
            ollama_messages.append({"role": m["role"], "content": content})

        payload = {
            "model": self.model,
            "messages": ollama_messages,
            "stream": False,
        }
        if ollama_tools:
            payload["tools"] = ollama_tools

        resp = requests.post(f"{self.host}/api/chat", json=payload, timeout=180)
        resp.raise_for_status()
        data = resp.json()
        message = data.get("message", {})

        tool_calls: list[ToolCall] = []
        for i, call in enumerate(message.get("tool_calls", []) or []):
            fn = call.get("function", {})
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            tool_calls.append(
                ToolCall(id=f"ollama-call-{i}", name=fn.get("name", ""), arguments=args)
            )

        return ProviderResponse(
            text=message.get("content", ""),
            tool_calls=tool_calls,
            stop_reason="tool_use" if tool_calls else "end_turn",
            raw=data,
        )
