"""SATOSHI cloud provider adapters.

All credentials are read on the Python server from environment variables;
there is no endpoint for the browser to read, submit or update keys.
Uses officially documented OpenAI-compatible chat completions. Never
falls back silently to another provider or executes model tool calls.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ProviderResponse:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"


# The default Qwen domain remains supported, with an optional new
# Alibaba workspace-specific address controlled by the local operator.
CLOUD_CONFIG = {
    "openai": ("OPENAI_API_KEY", "https://api.openai.com/v1"),
    "deepseek": ("DEEPSEEK_API_KEY", "https://api.deepseek.com"),
    "gemini": ("GEMINI_API_KEY", "https://generativelanguage.googleapis.com/v1beta/openai/"),
    "qwen": ("DASHSCOPE_API_KEY", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"),
    "mistral": ("MISTRAL_API_KEY", "https://api.mistral.ai/v1"),
}


def provider_base_url(provider: str) -> str:
    """Return HTTPS official endpoint; allow Qwen workspace domains only."""
    default = CLOUD_CONFIG[provider][1]
    if provider != "qwen":
        return default
    custom = os.getenv("SATOSHI_QWEN_BASE_URL", "").strip()
    if not custom:
        return default
    parsed = urlsplit(custom)
    host = parsed.hostname or ""
    allowed = (host in {"dashscope-intl.aliyuncs.com", "dashscope.aliyuncs.com"}
               or host.endswith(".maas.aliyuncs.com"))
    if (parsed.scheme != "https" or not allowed or parsed.username or parsed.password
            or parsed.port not in (None, 443) or parsed.query or parsed.fragment
            or not parsed.path.rstrip("/").endswith("/compatible-mode/v1")):
        raise ValueError("Qwen base URL must be an official HTTPS Alibaba OpenAI-compatible endpoint")
    return custom.rstrip("/")


def resolve_api_key(provider: str) -> str:
    name = CLOUD_CONFIG[provider][0]
    key = os.getenv(name, "")
    if provider == "gemini" and not key:
        key = os.getenv("GOOGLE_API_KEY", "")
    if provider == "qwen" and not key:
        key = os.getenv("QWEN_API_KEY", "")
    return key.strip()


class CompatibleProvider:
    """Normalize OpenAI-compatible SDK messages and function calls."""

    def __init__(self, provider_id: str, model: str):
        if provider_id not in CLOUD_CONFIG:
            raise ValueError("Unknown provider")
        self.id = provider_id
        self.model = model
        self.api_key = resolve_api_key(provider_id)
        self.base_url = provider_base_url(provider_id)

    def is_available(self) -> str | None:
        if not self.api_key:
            return f"{CLOUD_CONFIG[self.id][0]} is not configured"
        try:
            import openai  # noqa: F401
        except ImportError:
            return "Python dependency missing: pip install openai"
        # This is configuration readiness, NOT a network authentication test.
        return None

    def complete(self, system_prompt: str, messages: list[dict], tool_schemas: list[dict]) -> ProviderResponse:
        missing = self.is_available()
        if missing:
            raise RuntimeError(missing)
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key, base_url=self.base_url,
                        timeout=90.0, max_retries=1)
        cleaned_messages = [{"role": "system", "content": system_prompt}]
        for entry in messages:
            role, content = entry.get("role"), entry.get("content")
            if role not in ("user", "assistant"):
                continue
            # The local coding loop records tool results as text, NOT as
            # untrusted model-native tool objects across provider switches.
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False)
            cleaned_messages.append({"role": role, "content": content[:14000]})
        tools = []
        for item in tool_schemas:
            tools.append({"type": "function", "function": {
                "name": item["name"], "description": item.get("description", ""),
                "parameters": item["input_schema"]}})
        kwargs = {"model": self.model, "messages": cleaned_messages}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        response = client.chat.completions.create(**kwargs)
        if not response.choices:
            raise RuntimeError("Provider returned no choices")
        choice = response.choices[0]
        message = choice.message
        parsed_calls = []
        for call in message.tool_calls or []:
            if not getattr(call, "function", None):
                continue
            try:
                args = json.loads(call.function.arguments or "{}")
                if not isinstance(args, dict):
                    args = {}
            except json.JSONDecodeError:
                args = {}
            parsed_calls.append(ToolCall(call.id or "", call.function.name or "", args))
        content = message.content
        if not isinstance(content, str):
            content = "" if content is None else str(content)
        return ProviderResponse(text=content, tool_calls=parsed_calls,
                                stop_reason=choice.finish_reason or "end_turn")
