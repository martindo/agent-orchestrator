"""Anthropic LLM provider."""

from __future__ import annotations

import logging
from typing import Any

from anthropic import AsyncAnthropic

logger = logging.getLogger(__name__)


class AnthropicProvider:
    """LLM provider backed by the Anthropic API."""

    def __init__(self, api_key: str) -> None:
        self._client = AsyncAnthropic(api_key=api_key)

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Call the Anthropic messages API.

        Extracts any system message from the list and passes it
        via the dedicated ``system`` parameter.
        """
        system_text = ""
        user_messages: list[dict[str, str]] = []
        for msg in messages:
            if msg["role"] == "system":
                system_text = msg["content"]
            else:
                user_messages.append(msg)

        response = await self._client.messages.create(
            model=model,
            system=system_text,
            messages=user_messages,  # type: ignore[arg-type]
            temperature=kwargs.get("temperature", 0.3),
            max_tokens=kwargs.get("max_tokens", 4000),
        )
        content = response.content[0].text if response.content else ""
        usage = response.usage
        return {
            "response": content,
            "model": response.model,
            "usage": {
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
            },
        }
