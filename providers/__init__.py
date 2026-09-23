from __future__ import annotations

from neo_code.config import Config
from neo_code.providers.anthropic_provider import AnthropicProvider
from neo_code.providers.base import Provider, ProviderResponse, ToolCall
from neo_code.providers.deepseek_provider import DeepSeekProvider
from neo_code.providers.ollama_provider import OllamaProvider
from neo_code.providers.openai_provider import OpenAIProvider

_REGISTRY = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "ollama": OllamaProvider,
    "deepseek": DeepSeekProvider,
}


def create_provider(
    config: Config,
    provider_id: str | None = None,
    model: str | None = None,
) -> Provider:
    """Factory: instantiate the Provider named by `provider_id` (or
    `config.provider` if omitted), using `model` (or `config.model`)
    and credentials/host resolved from `config`.

    Raises:
        ValueError: if `provider_id` isn't a registered provider.
    """
    provider_id = provider_id or config.provider
    model = model or config.model

    cls = _REGISTRY.get(provider_id)

    if cls is None:
        raise ValueError(f"Unknown provider '{provider_id}'. " f"Available: {', '.join(_REGISTRY)}")

    if provider_id == "ollama":
        return cls(
            model=model,
            host=config.ollama_host,
        )

    return cls(
        model=model,
        api_key=config.api_key_for(provider_id),
    )


def available_providers() -> list[str]:
    """Return the registered provider ids (e.g. for `/setup` prompts)."""
    return list(_REGISTRY.keys())


__all__ = [
    "Provider",
    "ProviderResponse",
    "ToolCall",
    "AnthropicProvider",
    "OpenAIProvider",
    "OllamaProvider",
    "DeepSeekProvider",
    "create_provider",
    "available_providers",
]
