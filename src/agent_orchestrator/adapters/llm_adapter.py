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
            logger.warning(
                "No provider registered for '%s', using mock response",
                llm_config.provider,
            )
            return {
                "response": f"Mock response (provider '{llm_config.provider}' not registered)",
                "model": llm_config.model,
                "confidence": 0.5,
            }

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

    def get_api_key(self, provider: str) -> str | None:
        """Get API key for a provider."""
        return self._api_keys.get(provider)
