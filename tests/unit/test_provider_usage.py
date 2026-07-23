"""Google + Ollama providers now surface token usage (audit 6.4).

They previously returned only {response, model}, dropping the usage the APIs
report — so downstream cost/metrics had nothing to price for these providers.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_orchestrator.adapters.providers import google_provider
from agent_orchestrator.adapters.providers.ollama_provider import OllamaProvider


# ---- Ollama -----------------------------------------------------------------


def _ollama_response(data: dict) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=data)
    return resp


@pytest.mark.asyncio
async def test_ollama_returns_usage():
    provider = OllamaProvider(endpoint="http://localhost:11434")
    provider._client.post = AsyncMock(return_value=_ollama_response({
        "message": {"content": "hi there"},
        "prompt_eval_count": 11,
        "eval_count": 7,
    }))
    result = await provider.complete([{"role": "user", "content": "hi"}], model="llama3.1")
    assert result["response"] == "hi there"
    assert result["usage"]["prompt_tokens"] == 11
    assert result["usage"]["completion_tokens"] == 7
    assert result["usage"]["total_tokens"] == 18


@pytest.mark.asyncio
async def test_ollama_missing_counts_default_zero():
    provider = OllamaProvider()
    provider._client.post = AsyncMock(return_value=_ollama_response({
        "message": {"content": "x"},  # older Ollama without counts
    }))
    result = await provider.complete([{"role": "user", "content": "hi"}], model="m")
    assert result["usage"] == {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


# ---- Google (Gemini) --------------------------------------------------------


@pytest.mark.asyncio
async def test_google_returns_usage(monkeypatch):
    provider = google_provider.GoogleProvider(api_key="k")

    response = MagicMock()
    response.text = "hello"
    response.usage_metadata = MagicMock(
        prompt_token_count=20, candidates_token_count=6, total_token_count=26,
    )
    model = MagicMock()
    model.generate_content = MagicMock(return_value=response)
    monkeypatch.setattr(google_provider.genai, "GenerativeModel", MagicMock(return_value=model))

    result = await provider.complete([{"role": "user", "content": "hi"}], model="gemini-2.0")
    assert result["response"] == "hello"
    assert result["usage"]["prompt_tokens"] == 20
    assert result["usage"]["completion_tokens"] == 6
    assert result["usage"]["total_tokens"] == 26


@pytest.mark.asyncio
async def test_google_without_usage_metadata(monkeypatch):
    provider = google_provider.GoogleProvider(api_key="k")

    response = MagicMock()
    response.text = "hello"
    response.usage_metadata = None
    model = MagicMock()
    model.generate_content = MagicMock(return_value=response)
    monkeypatch.setattr(google_provider.genai, "GenerativeModel", MagicMock(return_value=model))

    result = await provider.complete([{"role": "user", "content": "hi"}], model="gemini-2.0")
    assert result["response"] == "hello"
    assert "usage" not in result  # nothing fabricated when the API reports none
