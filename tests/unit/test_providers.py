"""Tests for LLM provider implementations.

All tests use mocked SDK clients — no real API calls are made.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_orchestrator.adapters.llm_adapter import LLMAdapter
from agent_orchestrator.configuration.models import LLMConfig, SettingsConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MESSAGES = [
    {"role": "system", "content": "You are helpful."},
    {"role": "user", "content": "Say hello."},
]

USER_ONLY = [{"role": "user", "content": "Say hello."}]


# ---------------------------------------------------------------------------
# OpenAI Provider
# ---------------------------------------------------------------------------


class TestOpenAIProvider:
    """Tests for OpenAIProvider."""

    @pytest.fixture(autouse=True)
    def _patch_sdk(self):
        mock_client = AsyncMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "Hello from OpenAI!"
        mock_usage = MagicMock(prompt_tokens=10, completion_tokens=5)
        mock_response = MagicMock(
            choices=[mock_choice],
            model="gpt-4o",
            usage=mock_usage,
        )
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch(
            "agent_orchestrator.adapters.providers.openai_provider.AsyncOpenAI",
            return_value=mock_client,
        ) as patched:
            self.mock_client = mock_client
            self.patched_cls = patched
            yield

    async def test_complete_returns_expected_format(self):
        from agent_orchestrator.adapters.providers.openai_provider import OpenAIProvider

        provider = OpenAIProvider(api_key="sk-test")
        result = await provider.complete(MESSAGES, model="gpt-4o", temperature=0.5)

        assert result["response"] == "Hello from OpenAI!"
        assert result["model"] == "gpt-4o"
        assert result["usage"]["prompt_tokens"] == 10
        assert result["usage"]["completion_tokens"] == 5

    async def test_passes_kwargs_to_sdk(self):
        from agent_orchestrator.adapters.providers.openai_provider import OpenAIProvider

        provider = OpenAIProvider(api_key="sk-test")
        await provider.complete(MESSAGES, model="gpt-4o", temperature=0.7, max_tokens=200)

        call_kwargs = self.mock_client.chat.completions.create.call_args
        assert call_kwargs.kwargs["temperature"] == 0.7
        assert call_kwargs.kwargs["max_tokens"] == 200

    async def test_handles_none_content(self):
        mock_choice = MagicMock()
        mock_choice.message.content = None
        self.mock_client.chat.completions.create.return_value = MagicMock(
            choices=[mock_choice], model="gpt-4o", usage=MagicMock(prompt_tokens=0, completion_tokens=0),
        )

        from agent_orchestrator.adapters.providers.openai_provider import OpenAIProvider

        provider = OpenAIProvider(api_key="sk-test")
        result = await provider.complete(MESSAGES, model="gpt-4o")
        assert result["response"] == ""


# ---------------------------------------------------------------------------
# Anthropic Provider
# ---------------------------------------------------------------------------


class TestAnthropicProvider:
    """Tests for AnthropicProvider."""

    @pytest.fixture(autouse=True)
    def _patch_sdk(self):
        mock_client = AsyncMock()
        mock_block = MagicMock()
        mock_block.text = "Hello from Anthropic!"
        mock_usage = MagicMock(input_tokens=12, output_tokens=8)
        mock_response = MagicMock(
            content=[mock_block],
            model="claude-sonnet-4-20250514",
            usage=mock_usage,
        )
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with patch(
            "agent_orchestrator.adapters.providers.anthropic_provider.AsyncAnthropic",
            return_value=mock_client,
        ):
            self.mock_client = mock_client
            yield

    async def test_complete_returns_expected_format(self):
        from agent_orchestrator.adapters.providers.anthropic_provider import AnthropicProvider

        provider = AnthropicProvider(api_key="sk-ant-test")
        result = await provider.complete(MESSAGES, model="claude-sonnet-4-20250514")

        assert result["response"] == "Hello from Anthropic!"
        assert result["model"] == "claude-sonnet-4-20250514"
        assert result["usage"]["input_tokens"] == 12
        assert result["usage"]["output_tokens"] == 8

    async def test_extracts_system_message(self):
        from agent_orchestrator.adapters.providers.anthropic_provider import AnthropicProvider

        provider = AnthropicProvider(api_key="sk-ant-test")
        await provider.complete(MESSAGES, model="claude-sonnet-4-20250514")

        call_kwargs = self.mock_client.messages.create.call_args
        assert call_kwargs.kwargs["system"] == "You are helpful."
        sent_messages = call_kwargs.kwargs["messages"]
        assert all(m["role"] != "system" for m in sent_messages)

    async def test_handles_empty_content(self):
        self.mock_client.messages.create.return_value = MagicMock(
            content=[],
            model="claude-sonnet-4-20250514",
            usage=MagicMock(input_tokens=0, output_tokens=0),
        )

        from agent_orchestrator.adapters.providers.anthropic_provider import AnthropicProvider

        provider = AnthropicProvider(api_key="sk-ant-test")
        result = await provider.complete(MESSAGES, model="claude-sonnet-4-20250514")
        assert result["response"] == ""


# ---------------------------------------------------------------------------
# Google Provider
# ---------------------------------------------------------------------------


class TestGoogleProvider:
    """Tests for GoogleProvider."""

    @pytest.fixture(autouse=True)
    def _patch_sdk(self):
        mock_model = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = "Hello from Gemini!"
        mock_model.generate_content.return_value = mock_resp

        with patch(
            "agent_orchestrator.adapters.providers.google_provider.genai"
        ) as mock_genai:
            mock_genai.GenerativeModel.return_value = mock_model
            mock_genai.types.GenerationConfig = MagicMock
            self.mock_genai = mock_genai
            self.mock_model = mock_model
            yield

    async def test_complete_returns_expected_format(self):
        from agent_orchestrator.adapters.providers.google_provider import GoogleProvider

        provider = GoogleProvider(api_key="google-test-key")
        result = await provider.complete(MESSAGES, model="gemini-pro")

        assert result["response"] == "Hello from Gemini!"
        assert result["model"] == "gemini-pro"

    async def test_converts_messages_to_gemini_format(self):
        from agent_orchestrator.adapters.providers.google_provider import GoogleProvider

        provider = GoogleProvider(api_key="google-test-key")
        await provider.complete(MESSAGES, model="gemini-pro")

        call_args = self.mock_model.generate_content.call_args
        contents = call_args[0][0]
        # System message should not appear in contents
        assert all(c["role"] != "system" for c in contents)
        # User message should be converted
        assert contents[0]["role"] == "user"
        assert contents[0]["parts"] == ["Say hello."]


# ---------------------------------------------------------------------------
# Grok Provider
# ---------------------------------------------------------------------------


class TestGrokProvider:
    """Tests for GrokProvider."""

    @pytest.fixture(autouse=True)
    def _patch_sdk(self):
        mock_client = AsyncMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "Hello from Grok!"
        mock_usage = MagicMock(prompt_tokens=8, completion_tokens=4)
        mock_response = MagicMock(
            choices=[mock_choice],
            model="grok-2",
            usage=mock_usage,
        )
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch(
            "agent_orchestrator.adapters.providers.grok_provider.AsyncOpenAI",
            return_value=mock_client,
        ) as patched:
            self.mock_client = mock_client
            self.patched_cls = patched
            yield

    async def test_complete_returns_expected_format(self):
        from agent_orchestrator.adapters.providers.grok_provider import GrokProvider

        provider = GrokProvider(api_key="xai-test")
        result = await provider.complete(MESSAGES, model="grok-2")

        assert result["response"] == "Hello from Grok!"
        assert result["model"] == "grok-2"

    async def test_uses_xai_base_url(self):
        from agent_orchestrator.adapters.providers.grok_provider import GrokProvider

        GrokProvider(api_key="xai-test")
        call_kwargs = self.patched_cls.call_args
        assert call_kwargs.kwargs["base_url"] == "https://api.x.ai/v1"


# ---------------------------------------------------------------------------
# Ollama Provider
# ---------------------------------------------------------------------------


class TestOllamaProvider:
    """Tests for OllamaProvider."""

    @pytest.fixture(autouse=True)
    def _patch_httpx(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "message": {"content": "Hello from Ollama!"},
        }
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch(
            "agent_orchestrator.adapters.providers.ollama_provider.httpx.AsyncClient",
            return_value=mock_client,
        ):
            self.mock_client = mock_client
            yield

    async def test_complete_returns_expected_format(self):
        from agent_orchestrator.adapters.providers.ollama_provider import OllamaProvider

        provider = OllamaProvider(endpoint="http://localhost:11434")
        result = await provider.complete(MESSAGES, model="llama3")

        assert result["response"] == "Hello from Ollama!"
        assert result["model"] == "llama3"

    async def test_posts_to_correct_endpoint(self):
        from agent_orchestrator.adapters.providers.ollama_provider import OllamaProvider

        provider = OllamaProvider(endpoint="http://myhost:11434")
        await provider.complete(MESSAGES, model="llama3")

        call_args = self.mock_client.post.call_args
        assert call_args[0][0] == "http://myhost:11434/api/chat"

    async def test_sends_correct_payload(self):
        from agent_orchestrator.adapters.providers.ollama_provider import OllamaProvider

        provider = OllamaProvider()
        await provider.complete(MESSAGES, model="llama3", temperature=0.8)

        call_kwargs = self.mock_client.post.call_args.kwargs
        payload = call_kwargs["json"]
        assert payload["model"] == "llama3"
        assert payload["stream"] is False
        assert payload["messages"] == MESSAGES

    async def test_default_endpoint(self):
        from agent_orchestrator.adapters.providers.ollama_provider import OllamaProvider

        provider = OllamaProvider()
        await provider.complete(MESSAGES, model="llama3")

        call_args = self.mock_client.post.call_args
        assert call_args[0][0] == "http://localhost:11434/api/chat"


# ---------------------------------------------------------------------------
# Provider Registration in Engine
# ---------------------------------------------------------------------------


class TestProviderRegistration:
    """Tests that the engine auto-registers providers when keys are present."""

    def _make_settings(self, **keys: str) -> SettingsConfig:
        return SettingsConfig(
            active_profile="test",
            api_keys=keys,
        )

    def test_registers_openai_when_key_present(self):
        settings = self._make_settings(openai="sk-test")
        adapter = LLMAdapter(settings)

        with patch(
            "importlib.import_module",
        ) as mock_import:
            mock_mod = MagicMock()
            mock_mod.OpenAIProvider.return_value = MagicMock()
            mock_import.return_value = mock_mod

            from agent_orchestrator.core.engine import OrchestrationEngine

            OrchestrationEngine._register_providers(adapter, settings)

        assert "openai" in adapter._providers

    def test_skips_provider_when_key_missing(self):
        settings = self._make_settings()  # no keys
        adapter = LLMAdapter(settings)

        from agent_orchestrator.core.engine import OrchestrationEngine

        # Patch ollama import to avoid real import
        with patch(
            "agent_orchestrator.adapters.providers.ollama_provider.httpx",
        ):
            OrchestrationEngine._register_providers(adapter, settings)

        assert "openai" not in adapter._providers
        assert "anthropic" not in adapter._providers

    def test_registers_ollama_always(self):
        settings = self._make_settings()
        adapter = LLMAdapter(settings)

        with patch(
            "agent_orchestrator.adapters.providers.ollama_provider.httpx",
        ):
            from agent_orchestrator.core.engine import OrchestrationEngine

            OrchestrationEngine._register_providers(adapter, settings)

        assert "ollama" in adapter._providers

    def test_skips_provider_on_import_error(self):
        settings = self._make_settings(openai="sk-test")
        adapter = LLMAdapter(settings)

        from agent_orchestrator.core.engine import OrchestrationEngine

        # Make both key-based and ollama imports fail
        def _fail_import(mod_path):
            raise ImportError("no sdk")

        with patch("importlib.import_module", side_effect=_fail_import):
            with patch(
                "agent_orchestrator.adapters.providers.ollama_provider",
                side_effect=ImportError("no sdk"),
            ):
                OrchestrationEngine._register_providers(adapter, settings)

        # Provider should NOT be registered if import failed
        assert "openai" not in adapter._providers


# ---------------------------------------------------------------------------
# LLM Adapter Routing
# ---------------------------------------------------------------------------


class TestLLMAdapterRouting:
    """Tests that LLMAdapter routes to the correct provider."""

    async def test_routes_to_registered_provider(self):
        settings = SettingsConfig(active_profile="test")
        adapter = LLMAdapter(settings)

        mock_provider = AsyncMock()
        mock_provider.complete = AsyncMock(
            return_value={"response": "routed!", "model": "gpt-4o"},
        )
        adapter.register_provider("openai", mock_provider)

        config = LLMConfig(provider="openai", model="gpt-4o")
        result = await adapter.call("system", "user", config)

        assert result["response"] == "routed!"
        mock_provider.complete.assert_awaited_once()

    async def test_returns_mock_for_unregistered_provider(self):
        settings = SettingsConfig(active_profile="test")
        adapter = LLMAdapter(settings)

        config = LLMConfig(provider="nonexistent", model="x")
        result = await adapter.call("system", "user", config)

        assert "Mock response" in result["response"]
        assert result["confidence"] == 0.5

    async def test_passes_messages_correctly(self):
        settings = SettingsConfig(active_profile="test")
        adapter = LLMAdapter(settings)

        mock_provider = AsyncMock()
        mock_provider.complete = AsyncMock(
            return_value={"response": "ok", "model": "m"},
        )
        adapter.register_provider("test", mock_provider)

        config = LLMConfig(provider="test", model="m", temperature=0.9, max_tokens=100)
        await adapter.call("sys prompt", "user msg", config)

        call_kwargs = mock_provider.complete.call_args.kwargs
        assert call_kwargs["messages"] == [
            {"role": "system", "content": "sys prompt"},
            {"role": "user", "content": "user msg"},
        ]
        assert call_kwargs["temperature"] == 0.9
        assert call_kwargs["max_tokens"] == 100
