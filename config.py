"""Configuration for NEO CLI.

Loads from (in order of precedence, highest last):
  1. built-in defaults
  2. ~/.neo/config.json  (user-level, persistent)
  3. <cwd>/.neo/config.json (project-level override)
  4. environment variables (highest precedence)

No network calls or side effects happen at import time.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

USER_CONFIG_DIR = Path.home() / ".neo"
USER_CONFIG_FILE = USER_CONFIG_DIR / "config.json"

DEFAULTS: dict[str, Any] = {
    "provider": "anthropic",
    "model": "claude-sonnet-5",
    "ollama_host": "http://localhost:11434",
    "max_iterations": 25,  # engineering-loop safety limit
    "command_timeout": 60,  # seconds, per shell command
    "require_confirmation": {
        "write": True,
        "delete": True,
        "execute": True,
        "system": True,
    },
    "log_dir": str(USER_CONFIG_DIR / "sessions"),
    "memory_file": str(USER_CONFIG_DIR / "memory.json"),
    "api_keys": {},  # NEW: persistent storage for provider API keys
}


def _project_config_path(root: Path) -> Path:
    return root / ".neo" / "config.json"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


@dataclass
class Config:
    """Resolved runtime configuration for one NEO invocation —
    see the module docstring for the precedence order `Config.load()`
    applies."""

    provider: str = DEFAULTS["provider"]
    model: str = DEFAULTS["model"]
    ollama_host: str = DEFAULTS["ollama_host"]
    max_iterations: int = DEFAULTS["max_iterations"]
    command_timeout: int = DEFAULTS["command_timeout"]
    require_confirmation: dict[str, bool] = field(
        default_factory=lambda: dict(DEFAULTS["require_confirmation"])
    )
    log_dir: str = DEFAULTS["log_dir"]
    memory_file: str = DEFAULTS["memory_file"]
    workspace: str = field(default_factory=lambda: os.getcwd())
    api_keys: dict[str, str] = field(default_factory=dict)   # NEW

    @classmethod
    def load(cls, workspace: str | None = None) -> Config:
        """Resolve a Config for `workspace` (default: cwd) by layering
        defaults -> user config -> project config -> env vars, per the
        module docstring's precedence order."""
        workspace_path = Path(workspace or os.getcwd()).resolve()

        merged = dict(DEFAULTS)
        merged = _deep_merge(merged, _load_json(USER_CONFIG_FILE))
        merged = _deep_merge(merged, _load_json(_project_config_path(workspace_path)))

        env_overrides = {
            "provider": os.environ.get("NEO_PROVIDER"),
            "model": os.environ.get("NEO_MODEL"),
            "ollama_host": os.environ.get("NEO_OLLAMA_HOST"),
        }
        for k, v in env_overrides.items():
            if v:
                merged[k] = v

        # Load api_keys from merged (already merged from config files)
        api_keys = merged.get("api_keys", {})
        if not isinstance(api_keys, dict):
            api_keys = {}

        merged["workspace"] = str(workspace_path)
        merged.pop("workspace", None)  # workspace handled separately below

        cfg = cls(
            provider=merged.get("provider", DEFAULTS["provider"]),
            model=merged.get("model", DEFAULTS["model"]),
            ollama_host=merged.get("ollama_host", DEFAULTS["ollama_host"]),
            max_iterations=int(merged.get("max_iterations", DEFAULTS["max_iterations"])),
            command_timeout=int(merged.get("command_timeout", DEFAULTS["command_timeout"])),
            require_confirmation=merged.get(
                "require_confirmation", dict(DEFAULTS["require_confirmation"])
            ),
            log_dir=merged.get("log_dir", DEFAULTS["log_dir"]),
            memory_file=merged.get("memory_file", DEFAULTS["memory_file"]),
            workspace=str(workspace_path),
            api_keys=api_keys,
        )
        return cfg

    def save_user(self) -> None:
        """Persist this config (excluding `workspace`, which is always
        resolved per-invocation) to ~/.neo/config.json."""
        USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        data.pop("workspace", None)
        with open(USER_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def api_key_for(self, provider: str) -> str | None:
        """Look up the API key for `provider` – first from the stored
        api_keys dict, then from environment variables."""
        # 1. stored keys
        if provider in self.api_keys:
            return self.api_keys[provider]
        # 2. environment variables (fallback)
        env_map = {
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
        }
        var = env_map.get(provider)
        return os.environ.get(var) if var else None