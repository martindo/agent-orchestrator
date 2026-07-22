"""LLM Adapter — Multi-provider LLM access.

Bridges agent-orchestrator to various LLM providers.
Each agent can specify its own provider/model; API keys
are stored centrally in settings.

Thread-safe: Stateless call function.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

from agent_orchestrator.configuration.models import LLMConfig, SettingsConfig
from agent_orchestrator.exceptions import ConfigurationError

logger = logging.getLogger(__name__)


@runtime_checkable
class LLMProviderProtocol(Protocol):
    """Protocol for LLM provider implementations."""

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str,
        **kwargs: Any,
    ) -> dict[str, Any]: ...


class LLMAdapter:
    """Multi-provider LLM adapter.

    Routes LLM calls to the correct provider based on agent config.
    API keys are resolved from settings.

    Thread-safe: Stateless routing logic.
    """

    def __init__(self, settings: SettingsConfig) -> None:
        self._api_keys = dict(settings.api_keys)
        self._endpoints = dict(settings.llm_endpoints)
        self._providers: dict[str, LLMProviderProtocol] = {}

    def register_provider(self, name: str, provider: LLMProviderProtocol) -> None:
        """Register a provider implementation.

        Args:
            name: Provider name (openai, anthropic, etc.).
            provider: Provider implementation.
        """
        self._providers[name] = provider
        logger.info("Registered LLM provider: %s", name)

    async def call(
        self,
        system_prompt: str,
        user_prompt: str,
        llm_config: LLMConfig,
    ) -> dict[str, Any]:
        """Call an LLM using the specified config.

        Args:
            system_prompt: System instruction.
            user_prompt: User message.
            llm_config: Provider, model, and parameters.

        Returns:
            LLM response dict.
        """
        provider = self._providers.get(llm_config.provider)
        if provider is None:
            # Refuse to fabricate a response. Previously this returned a fake
            # "Mock response ... confidence 0.5" with success=True, so a
            # deployment missing an API key would "succeed" on invented output
            # and feed garbage downstream. Fail loudly instead.
            raise ConfigurationError(
                f"No LLM provider registered for '{llm_config.provider}'. "
                f"Configure an API key for it (in settings, or via the "
                f"AGENT_ORCH_{llm_config.provider.upper()}_API_KEY env var) — "
                f"refusing to fabricate a response."
            )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        return await provider.complete(
            messages=messages,
            model=llm_config.model,
            temperature=llm_config.temperature,
            max_tokens=llm_config.max_tokens,
        )

    async def list_models(self, provider: str) -> list[dict[str, str]]:
        """List available models for a provider.

        Returns a list of dicts with 'id' and 'name' keys.
        """
        prov = self._providers.get(provider)
        if prov is None:
            return []
        if not hasattr(prov, "list_models"):
            return []
        return await prov.list_models()

    def get_api_key(self, provider: str) -> str | None:
        """Get API key for a provider."""
        return self._api_keys.get(provider)
