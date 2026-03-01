"""Grok (xAI) LLM provider — OpenAI-compatible API."""

from __future__ import annotations

import logging
from typing import Any

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

_GROK_BASE_URL = "https://api.x.ai/v1"


class GrokProvider:
    """LLM provider backed by the xAI Grok API.

    Uses the OpenAI SDK pointed at xAI's OpenAI-compatible endpoint.
    """

    def __init__(self, api_key: str) -> None:
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=_GROK_BASE_URL,
        )

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Call the Grok chat completions API."""
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
