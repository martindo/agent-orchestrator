"""OpenAI LLM provider."""

from __future__ import annotations

import logging
from typing import Any

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


class OpenAIProvider:
    """LLM provider backed by the OpenAI API."""

    def __init__(self, api_key: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key)

    async def list_models(self) -> list[dict[str, str]]:
        """List available OpenAI models via the API."""
        try:
            response = await self._client.models.list()
            models = [
                {"id": m.id, "name": m.id}
                for m in response.data
                if m.id.startswith(("gpt-", "o1", "o3", "o4"))
            ]
            models.sort(key=lambda m: m["id"])
            return models
        except Exception:
            logger.warning("Failed to list OpenAI models via API", exc_info=True)
            return []

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Call the OpenAI chat completions API."""
        response = await self._client.chat.completions.create(
            model=model,
            messages=messages,  # type: ignore[arg-type]
            temperature=kwargs.get("temperature", 0.3),
            max_tokens=kwargs.get("max_tokens", 4000),
        )
        choice = response.choices[0]
        usage = response.usage
        return {
            "response": choice.message.content or "",
            "model": response.model,
            "usage": {
                "prompt_tokens": usage.prompt_tokens if usage else 0,
                "completion_tokens": usage.completion_tokens if usage else 0,
            },
        }
