"""Routes for LLM API key and provider settings.

GET  /api/studio/settings                    — get current settings (keys masked)
PUT  /api/studio/settings                    — update API keys and endpoints
GET  /api/studio/settings/models/{provider}  — fetch available models from provider API

Keys are stored in memory and optionally persisted to a YAML file
in the workspace directory. Actual key values are never returned
in GET responses — only a boolean ``has_key`` flag.

Models are fetched live from each provider's API using the stored
API key. No hardcoded model lists.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx
import yaml
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/studio/settings", tags=["settings"])

# Known LLM providers — models are fetched dynamically, not hardcoded
PROVIDERS: list[dict[str, str]] = [
    {"id": "openai", "name": "OpenAI (ChatGPT)", "env_var": "AGENT_ORCH_OPENAI_API_KEY"},
    {"id": "anthropic", "name": "Anthropic (Claude)", "env_var": "AGENT_ORCH_ANTHROPIC_API_KEY"},
    {"id": "google", "name": "Google (Gemini)", "env_var": "AGENT_ORCH_GOOGLE_API_KEY"},
    {"id": "grok", "name": "xAI (Grok)", "env_var": "AGENT_ORCH_GROK_API_KEY"},
    {"id": "ollama", "name": "Ollama (Local)", "env_var": ""},
]

_SETTINGS_FILE = "studio-settings.yaml"
_DEFAULT_OLLAMA_ENDPOINT = "http://localhost:11434"
_HTTP_TIMEOUT = 15.0


# ---- Request / Response Models ----


class ProviderResponse(BaseModel):
    """A single LLM provider with masked key status."""

    id: str
    name: str
    has_key: bool = False
    endpoint: str = ""


class SettingsResponse(BaseModel):
    """Full settings response with all providers."""

    providers: list[ProviderResponse] = Field(default_factory=list)


class UpdateSettingsRequest(BaseModel):
    """Request to update API keys and endpoints."""

    api_keys: dict[str, str] = Field(
        default_factory=dict,
        description="Provider ID -> API key. Empty string clears the key.",
    )
    endpoints: dict[str, str] = Field(
        default_factory=dict,
        description="Provider ID -> custom endpoint URL.",
    )


class ModelInfo(BaseModel):
    """A single model returned by a provider."""

    id: str
    name: str


class ModelsResponse(BaseModel):
    """Available models fetched from a provider API."""

    provider: str
    models: list[ModelInfo] = Field(default_factory=list)
    error: str | None = None


# ---- Helpers ----


def _get_settings_store(request: Request) -> dict[str, Any]:
    """Get or create the in-memory settings store on app state."""
    if not hasattr(request.app.state, "llm_settings"):
        request.app.state.llm_settings = {
            "api_keys": {},
            "endpoints": {},
        }
        _load_from_disk(request)
    return request.app.state.llm_settings


def _settings_path(request: Request) -> Path:
    """Get the path to the settings YAML file."""
    config = request.app.state.studio_config
    return Path(config.workspace_dir) / _SETTINGS_FILE


def _load_from_disk(request: Request) -> None:
    """Load settings from YAML file if it exists."""
    path = _settings_path(request)
    if not path.exists():
        return
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return
        store = request.app.state.llm_settings
        store["api_keys"] = data.get("api_keys", {})
        store["endpoints"] = data.get("endpoints", {})
        logger.info("Loaded LLM settings from %s", path)
    except Exception as exc:
        logger.warning("Failed to load settings from %s: %s", path, exc)


def _save_to_disk(request: Request) -> None:
    """Persist current settings to YAML file."""
    store = _get_settings_store(request)
    path = _settings_path(request)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "api_keys": store["api_keys"],
            "endpoints": store["endpoints"],
        }
        path.write_text(
            yaml.safe_dump(data, default_flow_style=False),
            encoding="utf-8",
        )
        logger.info("Saved LLM settings to %s", path)
    except Exception as exc:
        logger.warning("Failed to save settings to %s: %s", path, exc)


def _build_response(store: dict[str, Any]) -> SettingsResponse:
    """Build the settings response with masked keys."""
    providers: list[ProviderResponse] = []
    for p in PROVIDERS:
        pid = p["id"]
        has_key = bool(store["api_keys"].get(pid))
        if pid == "ollama":
            has_key = True
        providers.append(ProviderResponse(
            id=pid,
            name=p["name"],
            has_key=has_key,
            endpoint=store["endpoints"].get(pid, ""),
        ))
    return SettingsResponse(providers=providers)


# ---- Model Fetching ----


async def _fetch_openai_models(api_key: str, base_url: str = "") -> list[ModelInfo]:
    """Fetch models from OpenAI API (GET /v1/models)."""
    url = (base_url.rstrip("/") if base_url else "https://api.openai.com") + "/v1/models"
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.get(url, headers={"Authorization": f"Bearer {api_key}"})
        resp.raise_for_status()
        data = resp.json()

    models: list[ModelInfo] = []
    for m in data.get("data", []):
        model_id = m.get("id", "")
        # Filter to chat models — skip embedding, tts, whisper, dall-e, etc.
        if any(skip in model_id for skip in ("embedding", "tts", "whisper", "dall-e", "davinci", "babbage", "moderation")):
            continue
        models.append(ModelInfo(id=model_id, name=model_id))

    models.sort(key=lambda m: m.id)
    return models


async def _fetch_anthropic_models(api_key: str) -> list[ModelInfo]:
    """Fetch models from Anthropic API (GET /v1/models)."""
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.get(
            "https://api.anthropic.com/v1/models",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        resp.raise_for_status()
        data = resp.json()

    models: list[ModelInfo] = []
    for m in data.get("data", []):
        model_id = m.get("id", "")
        display = m.get("display_name", model_id)
        models.append(ModelInfo(id=model_id, name=display))

    models.sort(key=lambda m: m.id)
    return models


async def _fetch_google_models(api_key: str) -> list[ModelInfo]:
    """Fetch models from Google Generative AI API."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()

    models: list[ModelInfo] = []
    for m in data.get("models", []):
        model_id = m.get("name", "").replace("models/", "")
        display = m.get("displayName", model_id)
        # Filter to generative models
        methods = m.get("supportedGenerationMethods", [])
        if "generateContent" in methods:
            models.append(ModelInfo(id=model_id, name=display))

    models.sort(key=lambda m: m.id)
    return models


async def _fetch_grok_models(api_key: str) -> list[ModelInfo]:
    """Fetch models from xAI API (OpenAI-compatible, GET /v1/models)."""
    return await _fetch_openai_models(api_key, base_url="https://api.x.ai")


async def _fetch_ollama_models(endpoint: str = "") -> list[ModelInfo]:
    """Fetch locally available models from Ollama (GET /api/tags)."""
    base = (endpoint.rstrip("/") if endpoint else _DEFAULT_OLLAMA_ENDPOINT)
    url = f"{base}/api/tags"
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()

    models: list[ModelInfo] = []
    for m in data.get("models", []):
        model_id = m.get("name", "")
        # Use the model name, strip digest details
        display = m.get("model", model_id)
        models.append(ModelInfo(id=model_id, name=display))

    models.sort(key=lambda m: m.id)
    return models


# ---- Routes ----


@router.get("", response_model=SettingsResponse)
def get_settings(request: Request) -> SettingsResponse:
    """Get current LLM settings with masked API keys."""
    store = _get_settings_store(request)
    return _build_response(store)


@router.put("", response_model=SettingsResponse)
def update_settings(
    body: UpdateSettingsRequest,
    request: Request,
) -> SettingsResponse:
    """Update API keys and/or endpoints.

    Keys are stored in memory and persisted to disk. Empty string
    values clear the corresponding key.
    """
    store = _get_settings_store(request)

    for provider_id, key in body.api_keys.items():
        if key:
            store["api_keys"][provider_id] = key
        else:
            store["api_keys"].pop(provider_id, None)

    for provider_id, endpoint in body.endpoints.items():
        if endpoint:
            store["endpoints"][provider_id] = endpoint
        else:
            store["endpoints"].pop(provider_id, None)

    _save_to_disk(request)

    logger.info(
        "Updated LLM settings: %d keys, %d endpoints",
        len(store["api_keys"]),
        len(store["endpoints"]),
    )
    return _build_response(store)


@router.get("/models/{provider_id}", response_model=ModelsResponse)
async def list_provider_models(
    provider_id: str,
    request: Request,
) -> ModelsResponse:
    """Fetch available models from a provider's API.

    Requires the provider's API key to be configured (except Ollama).
    Calls the provider's model listing endpoint in real time.
    """
    store = _get_settings_store(request)
    api_key = store["api_keys"].get(provider_id, "")
    endpoint = store["endpoints"].get(provider_id, "")

    try:
        if provider_id == "openai":
            if not api_key:
                raise HTTPException(status_code=400, detail="OpenAI API key not configured")
            models = await _fetch_openai_models(api_key, endpoint)

        elif provider_id == "anthropic":
            if not api_key:
                raise HTTPException(status_code=400, detail="Anthropic API key not configured")
            models = await _fetch_anthropic_models(api_key)

        elif provider_id == "google":
            if not api_key:
                raise HTTPException(status_code=400, detail="Google API key not configured")
            models = await _fetch_google_models(api_key)

        elif provider_id == "grok":
            if not api_key:
                raise HTTPException(status_code=400, detail="Grok API key not configured")
            models = await _fetch_grok_models(api_key)

        elif provider_id == "ollama":
            models = await _fetch_ollama_models(endpoint)

        else:
            raise HTTPException(status_code=404, detail=f"Unknown provider: {provider_id}")

        return ModelsResponse(provider=provider_id, models=models)

    except HTTPException:
        raise
    except httpx.ConnectError as exc:
        return ModelsResponse(
            provider=provider_id,
            models=[],
            error=f"Cannot connect to {provider_id} — check endpoint or network",
        )
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 401:
            return ModelsResponse(
                provider=provider_id,
                models=[],
                error="Invalid API key",
            )
        return ModelsResponse(
            provider=provider_id,
            models=[],
            error=f"API error ({status})",
        )
    except Exception as exc:
        logger.warning("Failed to fetch models for %s: %s", provider_id, exc)
        return ModelsResponse(
            provider=provider_id,
            models=[],
            error=str(exc),
        )
