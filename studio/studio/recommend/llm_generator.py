"""LLM-powered agent and phase generation for arbitrary domains.

When the static archetype catalog doesn't cover the user's domain,
this module calls a configured LLM to generate domain-specific agents
and workflow phases from the project description.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = 60.0

_SYSTEM_PROMPT = """You are an expert at designing multi-agent AI workflows. Given a project description, you generate a team of specialized AI agents and workflow phases for that domain.

Rules:
- Generate agents that are relevant to the DOMAIN described, not software development agents
- Each agent should have a clear, distinct role in the domain workflow
- Generate 5-10 agents depending on complexity
- Generate workflow phases that represent the logical stages of work in this domain
- Each phase should have at least one agent assigned
- Phases should be sequentially ordered with clear transitions
- Agent IDs should be kebab-case (e.g., "market-analyst-agent")
- Phase IDs should be kebab-case (e.g., "market-research")
- Confidence scores should reflect how relevant each agent/phase is (0.6-0.95)

Return ONLY valid JSON matching this exact schema, no other text:
{
  "domain": "string - detected domain name",
  "team_name": "string - suggested team name",
  "team_description": "string - brief team description",
  "agents": [
    {
      "id": "string - kebab-case agent ID",
      "name": "string - human readable name",
      "description": "string - what this agent does",
      "system_prompt": "string - the system prompt for this agent",
      "skills": ["string - skill tags"],
      "default_phase": "string - phase ID this agent belongs to",
      "confidence": 0.8,
      "reason": "string - why this agent is recommended"
    }
  ],
  "phases": [
    {
      "id": "string - kebab-case phase ID",
      "name": "string - human readable phase name",
      "order": 1,
      "description": "string - what happens in this phase",
      "confidence": 0.8,
      "reason": "string - why this phase is recommended"
    }
  ]
}"""


async def generate_from_llm(
    description: str,
    api_keys: dict[str, str],
    endpoints: dict[str, str],
) -> dict[str, Any] | None:
    """Call an LLM to generate domain-specific agents and phases.

    Tries providers in order: anthropic, openai, google, grok, ollama.
    Returns parsed JSON or None if no provider is available.
    """
    providers = [
        ("anthropic", _call_anthropic),
        ("openai", _call_openai),
        ("google", _call_google),
        ("grok", _call_grok),
        ("ollama", _call_ollama),
    ]

    for provider_id, call_fn in providers:
        api_key = api_keys.get(provider_id, "")
        endpoint = endpoints.get(provider_id, "")

        # Skip providers without keys (except ollama)
        if provider_id != "ollama" and not api_key:
            continue

        try:
            logger.info("Attempting LLM generation via %s", provider_id)
            raw = await call_fn(description, api_key, endpoint)
            result = _parse_response(raw)
            if result:
                logger.info(
                    "LLM generated %d agents, %d phases via %s",
                    len(result.get("agents", [])),
                    len(result.get("phases", [])),
                    provider_id,
                )
                return result
        except Exception as exc:
            logger.warning("LLM generation via %s failed: %s", provider_id, exc)
            continue

    return None


def _parse_response(raw: str) -> dict[str, Any] | None:
    """Extract JSON from LLM response text."""
    text = raw.strip()

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code block
    for marker in ("```json", "```"):
        if marker in text:
            start = text.index(marker) + len(marker)
            end = text.index("```", start) if "```" in text[start:] else len(text)
            try:
                return json.loads(text[start:end].strip())
            except (json.JSONDecodeError, ValueError):
                pass

    logger.warning("Failed to parse LLM response as JSON")
    return None


async def _call_anthropic(description: str, api_key: str, endpoint: str) -> str:
    """Call Anthropic Claude API."""
    url = (endpoint.rstrip("/") if endpoint else "https://api.anthropic.com") + "/v1/messages"
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.post(
            url,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 4096,
                "temperature": 0.3,
                "system": _SYSTEM_PROMPT,
                "messages": [
                    {"role": "user", "content": f"Generate a team of AI agents and workflow phases for this project:\n\n{description}"},
                ],
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["content"][0]["text"]


async def _call_openai(description: str, api_key: str, endpoint: str) -> str:
    """Call OpenAI API."""
    url = (endpoint.rstrip("/") if endpoint else "https://api.openai.com") + "/v1/chat/completions"
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4o",
                "temperature": 0.3,
                "max_tokens": 4096,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": f"Generate a team of AI agents and workflow phases for this project:\n\n{description}"},
                ],
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


async def _call_google(description: str, api_key: str, endpoint: str) -> str:
    """Call Google Generative AI API."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.post(
            url,
            json={
                "systemInstruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
                "contents": [
                    {"parts": [{"text": f"Generate a team of AI agents and workflow phases for this project:\n\n{description}"}]},
                ],
                "generationConfig": {"temperature": 0.3, "maxOutputTokens": 4096},
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]


async def _call_grok(description: str, api_key: str, endpoint: str) -> str:
    """Call xAI Grok API (OpenAI-compatible)."""
    return await _call_openai(description, api_key, endpoint or "https://api.x.ai")


async def _call_ollama(description: str, api_key: str, endpoint: str) -> str:
    """Call local Ollama API."""
    base = (endpoint.rstrip("/") if endpoint else "http://localhost:11434")
    url = f"{base}/api/chat"
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.post(
            url,
            json={
                "model": "llama3.1:8b",
                "stream": False,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": f"Generate a team of AI agents and workflow phases for this project:\n\n{description}"},
                ],
                "options": {"temperature": 0.3},
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["message"]["content"]
