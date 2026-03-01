"""Ollama LLM provider — local self-hosted models."""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_ENDPOINT = "http://localhost:11434"


class OllamaProvider:
    """LLM provider for a local Ollama instance.

    Communicates via Ollama's ``/api/chat`` HTTP endpoint
    using ``httpx.AsyncClient``.
    """

    def __init__(self, endpoint: str = _DEFAULT_ENDPOINT) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._client = httpx.AsyncClient(timeout=120.0)

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Call the Ollama chat API."""
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": kwargs.get("temperature", 0.3),
            },
        }
        response = await self._client.post(
            f"{self._endpoint}/api/chat",
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        content = data.get("message", {}).get("content", "")
        return {
            "response": content,
            "model": model,
        }
