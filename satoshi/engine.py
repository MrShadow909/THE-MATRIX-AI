"""SATOSHI multi-provider engine: text chat and separately gated coder."""
from __future__ import annotations

import os
import re
import sys
import threading
import types
from pathlib import Path

from .prompt import SATOSHI_SYSTEM_PROMPT
from .providers_ext import CompatibleProvider

PROVIDERS = ("ollama", "openai", "anthropic", "deepseek", "gemini", "qwen", "mistral")
DEFAULT_MODELS = {
    "ollama": "llama3.2", "openai": "gpt-4o-mini",
    "anthropic": "claude-haiku-4-5", "deepseek": "deepseek-chat",
    "gemini": "gemini-2.5-flash", "qwen": "qwen-plus",
    "mistral": "mistral-small-latest",
}
MODEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}$")


def _neo_provider_modules():
    # A checkout may be named THE-MATRIX-AI instead of neo_code.
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
        self._lock = threading.RLock()
        self.provider_id = "ollama"
        self.model = DEFAULT_MODELS["ollama"]
        self.configure(provider or os.getenv("SATOSHI_PROVIDER", "ollama"),
                       model or os.getenv("SATOSHI_MODEL") or None)

    def configure(self, provider: str, model: str | None = None) -> dict:
        if not isinstance(provider, str) or provider.lower() not in PROVIDERS:
            raise ValueError("Unsupported SATOSHI_PROVIDER")
        provider = provider.lower()
        if model is not None and (not isinstance(model, str) or not MODEL_PATTERN.fullmatch(model)):
            raise ValueError("Model name can contain letters, numbers, periods, dashes, underscores, colons and slashes only")
        with self._lock:
            self.provider_id = provider
            self.model = model or DEFAULT_MODELS[provider]
        return {"provider": self.provider_id, "model": self.model}

    def _build_provider(self):
        with self._lock:
            provider, model = self.provider_id, self.model
        if provider in ("anthropic", "ollama"):
            Config, create_provider = _neo_provider_modules()
            config = Config(provider=provider, model=model,
                            ollama_host=os.getenv("SATOSHI_OLLAMA_HOST", "http://127.0.0.1:11434"),
                            api_keys={})
            return create_provider(config)
        return CompatibleProvider(provider, model)

    @staticmethod
    def provider_options() -> dict:
        return {"providers": [{"id": p, "default_model": DEFAULT_MODELS[p]}
                              for p in PROVIDERS],
                "configuration": "Set API keys in the Python server environment only; not in the browser."}

    def status(self):
        try:
            issue = self._build_provider().is_available()
        except Exception as exc:
            issue = str(exc)
        with self._lock:
            provider, model = self.provider_id, self.model
        return {"provider": provider, "model": model,
                "connected": issue is None, "configured": issue is None,
                "verified_live": False,
                "reason": issue, "autonomous_tools": False}

    def chat(self, message: str, history: list | None = None):
        if not isinstance(message, str) or not 1 <= len(message.strip()) <= 3000:
            raise ValueError("Message length must be 1–3000 characters")
        filtered = []
        for entry in (history or [])[-8:]:
            if (isinstance(entry, dict) and entry.get("role") in ("user", "assistant")
                    and isinstance(entry.get("content"), str)):
                filtered.append({"role": entry["role"], "content": entry["content"][:3000]})
        provider = self._build_provider()
        issue = provider.is_available()
        if issue:
            raise RuntimeError(f"Provider unavailable: {issue}")
        response = provider.complete(SATOSHI_SYSTEM_PROMPT,
                                     [*filtered, {"role": "user", "content": message}], [])
        if response.tool_calls:
            raise RuntimeError("Model requested unauthorized tools; request rejected")
        if response.stop_reason == "error":
            raise RuntimeError("Provider failed")
        return (response.text or "").strip()
