"""Thin, no-tools adapter over THE-MATRIX-AI providers (not the autonomous agent)."""
from __future__ import annotations

import os
import sys
import types
from pathlib import Path
from .prompt import SATOSHI_SYSTEM_PROMPT

PROVIDERS = {"ollama", "openai", "anthropic", "deepseek"}
DEFAULT_MODELS = {
    "ollama": "llama3.2", "openai": "gpt-4o-mini",
    "anthropic": "claude-3-5-haiku-latest", "deepseek": "deepseek-chat",
}


def _neo_provider_modules():
    # Neo's original package imports `neo_code.*`. GitHub clone may instead be
    # named THE-MATRIX-AI; alias the repo root without modifying global imports
    # outside this process. Only the existing providers are imported.
    root = Path(__file__).resolve().parent.parent
    if "neo_code" not in sys.modules:
        package = types.ModuleType("neo_code")
        package.__path__ = [str(root)]
        sys.modules["neo_code"] = package
    from neo_code.config import Config
    from neo_code.providers import create_provider
    return Config, create_provider


class SatoshiEngine:
    def __init__(self, provider: str | None = None, model: str | None = None):
        self.provider_id = (provider or os.getenv("SATOSHI_PROVIDER", "ollama")).lower()
        if self.provider_id not in PROVIDERS:
            raise ValueError("Unsupported SATOSHI_PROVIDER")
        self.model = model or os.getenv("SATOSHI_MODEL") or DEFAULT_MODELS[self.provider_id]

    def _build_provider(self):
        Config, create_provider = _neo_provider_modules()
        # Do not load ~/.neo/config.json: SATOSHI uses environment keys only.
        config = Config(
            provider=self.provider_id,
            model=self.model,
            ollama_host=os.getenv("SATOSHI_OLLAMA_HOST", "http://127.0.0.1:11434"),
            api_keys={},
        )
        return create_provider(config)

    def status(self):
        try:
            issue = self._build_provider().is_available()
        except Exception as exc:
            issue = str(exc)
        return {"provider": self.provider_id, "model": self.model,
                "connected": issue is None, "reason": issue,
                "autonomous_tools": False}

    def chat(self, message: str, history: list | None = None):
        if not isinstance(message, str) or not 1 <= len(message.strip()) <= 3000:
            raise ValueError("Message length must be 1–3000 characters")
        filtered = []
        for entry in (history or [])[-8:]:
            if (isinstance(entry, dict) and entry.get("role") in ("user", "assistant")
                    and isinstance(entry.get("content"), str)):
                filtered.append({"role": entry["role"],
                                 "content": entry["content"][:3000]})
        provider = self._build_provider()
        issue = provider.is_available()
        if issue:
            raise RuntimeError(f"Provider unavailable: {issue}")
        # Important: no Agent instance, no ToolRegistry, no tool schemas.
        response = provider.complete(SATOSHI_SYSTEM_PROMPT,
                                     [*filtered, {"role": "user", "content": message}], [])
        if response.tool_calls:
            raise RuntimeError("Model requested unauthorized tools; request rejected")
        if response.stop_reason == "error":
            raise RuntimeError("Provider failed: " + (response.text or "unknown error")[:200])
        return (response.text or "").strip()
