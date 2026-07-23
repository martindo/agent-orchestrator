"""Google Gemini LLM provider."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import google.generativeai as genai

logger = logging.getLogger(__name__)


class GoogleProvider:
    """LLM provider backed by Google Generative AI (Gemini)."""

    def __init__(self, api_key: str) -> None:
        genai.configure(api_key=api_key)
        self._api_key = api_key

    async def list_models(self) -> list[dict[str, str]]:
        """List available Gemini models."""
        try:
            def _sync_list() -> list[dict[str, str]]:
                models = []
                for m in genai.list_models():
                    if "generateContent" in (m.supported_generation_methods or []):
                        models.append({"id": m.name.replace("models/", ""), "name": m.display_name or m.name})
                return models
            return await asyncio.to_thread(_sync_list)
        except Exception:
            logger.warning("Failed to list Google models via API", exc_info=True)
            return []

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Call the Gemini API.

        Converts OpenAI-style messages to Gemini ``contents`` format
        and runs the synchronous SDK in a thread.
        """
        system_text = ""
        contents: list[dict[str, Any]] = []
        for msg in messages:
            if msg["role"] == "system":
                system_text = msg["content"]
            else:
                role = "model" if msg["role"] == "assistant" else "user"
                contents.append({"role": role, "parts": [msg["content"]]})

        gen_config = genai.types.GenerationConfig(
            temperature=kwargs.get("temperature", 0.3),
            max_output_tokens=kwargs.get("max_tokens", 4000),
        )

        def _sync_call() -> Any:
            gen_model = genai.GenerativeModel(
                model_name=model,
                system_instruction=system_text or None,
                generation_config=gen_config,
            )
            return gen_model.generate_content(contents)

        response = await asyncio.to_thread(_sync_call)
        result: dict[str, Any] = {
            "response": response.text,
            "model": model,
        }
        # Surface token usage so cost/metrics can price it (was discarded).
        usage = getattr(response, "usage_metadata", None)
        if usage is not None:
            result["usage"] = {
                "prompt_tokens": getattr(usage, "prompt_token_count", 0) or 0,
                "completion_tokens": getattr(usage, "candidates_token_count", 0) or 0,
                "total_tokens": getattr(usage, "total_token_count", 0) or 0,
            }
        return result
