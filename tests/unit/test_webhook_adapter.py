"""Tests for webhook delivery: retry/backoff, failure reporting, HMAC (audit 4.3).

The old adapter did a single POST and swallowed HTTP errors, so notify() falsely
reported success. These lock in real retry/backoff, correct failure reporting,
and optional HMAC signing.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import httpx
import pytest

from agent_orchestrator.adapters import webhook_adapter
from agent_orchestrator.adapters.webhook_adapter import WebhookAdapter, WebhookConfig


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        self.request = httpx.Request("POST", "http://example.test/hook")

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"status {self.status_code}", request=self.request, response=self,
            )


class _FakeClient:
    """Returns/raises a scripted sequence across attempts; records calls."""

    def __init__(self, script: list) -> None:
        self._script = list(script)
        self.calls: list[dict] = []

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def post(self, url: str, **kwargs) -> _FakeResponse:
        self.calls.append({"url": url, **kwargs})
        outcome = self._script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return _FakeResponse(outcome)


@pytest.fixture
def patch_client(monkeypatch):
    def _install(script: list) -> _FakeClient:
        fake = _FakeClient(script)
        monkeypatch.setattr(webhook_adapter.httpx, "AsyncClient", lambda *a, **k: fake)
        return fake
    return _install


def _adapter(**cfg) -> tuple[WebhookAdapter, WebhookConfig]:
    adapter = WebhookAdapter()
    config = WebhookConfig(
        id="wh1", url="http://example.test/hook",
        max_retries=3, retry_backoff_seconds=0.0, **cfg,
    )
    adapter.register(config)
    return adapter, config


@pytest.mark.asyncio
async def test_success_first_attempt(patch_client):
    fake = patch_client([200])
    adapter, _ = _adapter()
    notified = await adapter.notify("work.done", {"x": 1})
    assert notified == ["wh1"]
    assert len(fake.calls) == 1


@pytest.mark.asyncio
async def test_retries_then_succeeds(patch_client):
    fake = patch_client([503, 200])  # one transient failure, then OK
    adapter, _ = _adapter()
    notified = await adapter.notify("work.done", {"x": 1})
    assert notified == ["wh1"]
    assert len(fake.calls) == 2


@pytest.mark.asyncio
async def test_retries_transport_error(patch_client):
    fake = patch_client([httpx.ConnectError("boom"), 200])
    adapter, _ = _adapter()
    notified = await adapter.notify("work.done", {"x": 1})
    assert notified == ["wh1"]
    assert len(fake.calls) == 2


@pytest.mark.asyncio
async def test_gives_up_and_reports_failure(patch_client):
    fake = patch_client([500, 500, 500, 500])  # 1 + 3 retries all fail
    adapter, _ = _adapter()
    notified = await adapter.notify("work.done", {"x": 1})
    assert notified == []               # failure is reported, not swallowed
    assert len(fake.calls) == 4


@pytest.mark.asyncio
async def test_no_retry_on_client_error(patch_client):
    fake = patch_client([400])  # 4xx → not retryable
    adapter, _ = _adapter()
    notified = await adapter.notify("work.done", {"x": 1})
    assert notified == []
    assert len(fake.calls) == 1


@pytest.mark.asyncio
async def test_hmac_signature(patch_client):
    fake = patch_client([200])
    adapter, _ = _adapter(secret="topsecret")
    await adapter.notify("work.done", {"x": 1})

    call = fake.calls[0]
    body_bytes = call["content"]
    sig_header = call["headers"]["X-Webhook-Signature"]
    expected = hmac.new(b"topsecret", body_bytes, hashlib.sha256).hexdigest()
    assert sig_header == f"sha256={expected}"
    # And the signed bytes are the actual JSON body.
    assert json.loads(body_bytes)["event_type"] == "work.done"


@pytest.mark.asyncio
async def test_no_signature_without_secret(patch_client):
    fake = patch_client([200])
    adapter, _ = _adapter()  # no secret
    await adapter.notify("work.done", {"x": 1})
    assert "X-Webhook-Signature" not in fake.calls[0]["headers"]
