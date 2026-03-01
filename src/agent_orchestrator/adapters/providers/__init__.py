"""LLM provider implementations.

Each provider is imported conditionally so missing SDKs
don't prevent the rest of the system from loading.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_orchestrator.adapters.providers.anthropic_provider import (
        AnthropicProvider,
    )
    from agent_orchestrator.adapters.providers.google_provider import GoogleProvider
    from agent_orchestrator.adapters.providers.grok_provider import GrokProvider
    from agent_orchestrator.adapters.providers.ollama_provider import OllamaProvider
    from agent_orchestrator.adapters.providers.openai_provider import OpenAIProvider

__all__ = [
    "AnthropicProvider",
    "GoogleProvider",
    "GrokProvider",
    "OllamaProvider",
    "OpenAIProvider",
]


def _try_import(name: str):  # noqa: ANN202
    """Lazily import a provider class, returning *None* if its SDK is missing."""
    import importlib

    module_map = {
        "OpenAIProvider": "agent_orchestrator.adapters.providers.openai_provider",
        "AnthropicProvider": "agent_orchestrator.adapters.providers.anthropic_provider",
        "GoogleProvider": "agent_orchestrator.adapters.providers.google_provider",
        "GrokProvider": "agent_orchestrator.adapters.providers.grok_provider",
        "OllamaProvider": "agent_orchestrator.adapters.providers.ollama_provider",
    }
    mod_path = module_map.get(name)
    if mod_path is None:
        return None
    try:
        mod = importlib.import_module(mod_path)
        return getattr(mod, name)
    except (ImportError, AttributeError):
        return None


def __getattr__(name: str):  # noqa: ANN202
    cls = _try_import(name)
    if cls is not None:
        return cls
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
