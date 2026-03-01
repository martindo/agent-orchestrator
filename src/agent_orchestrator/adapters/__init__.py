"""Adapters — bridges to coderswarm-packages."""

from agent_orchestrator.adapters.llm_adapter import LLMAdapter, LLMProviderProtocol
from agent_orchestrator.adapters.metrics_adapter import MetricsCollector
from agent_orchestrator.adapters.providers import (
    AnthropicProvider,
    GoogleProvider,
    GrokProvider,
    OllamaProvider,
    OpenAIProvider,
)
from agent_orchestrator.adapters.webhook_adapter import WebhookAdapter, WebhookConfig

__all__ = [
    "AnthropicProvider",
    "GoogleProvider",
    "GrokProvider",
    "LLMAdapter",
    "LLMProviderProtocol",
    "MetricsCollector",
    "OllamaProvider",
    "OpenAIProvider",
    "WebhookAdapter",
    "WebhookConfig",
]
