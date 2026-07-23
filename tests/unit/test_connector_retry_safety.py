"""Connector retry safety for non-idempotent writes (audit 6.3).

The executor's default retryable set includes the generic FAILURE status, so a
write op (create_ticket, send_message) could be retried on an ambiguous failure
and duplicate the write. Writes are now restricted to retrying only UNAVAILABLE.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_orchestrator.connectors.executor import ConnectorExecutor
from agent_orchestrator.connectors.models import (
    CapabilityType,
    ConnectorInvocationRequest,
    ConnectorInvocationResult,
    ConnectorOperationDescriptor,
    ConnectorProviderDescriptor,
    ConnectorRetryPolicy,
    ConnectorStatus,
)

CAP = CapabilityType.TICKETING


def _provider(operation: str, read_only: bool, status: ConnectorStatus) -> MagicMock:
    provider = MagicMock()
    provider.get_descriptor.return_value = ConnectorProviderDescriptor(
        provider_id="tp", display_name="TP", capability_types=[CAP],
        operations=[ConnectorOperationDescriptor(
            operation=operation, description="x", capability_type=CAP, read_only=read_only,
        )],
    )
    result = ConnectorInvocationResult(
        request_id="r", connector_id="tp", provider="tp",
        capability_type=CAP, operation=operation, status=status,
    )
    provider.execute = AsyncMock(side_effect=[result] * 6)
    return provider


def _policy() -> ConnectorRetryPolicy:
    # Default retryable_statuses = [TIMEOUT, UNAVAILABLE, FAILURE]; fast backoff.
    return ConnectorRetryPolicy(max_retries=3, delay_seconds=0.0, backoff_multiplier=1.0)


async def _run(provider: MagicMock, operation: str) -> ConnectorInvocationResult:
    req = ConnectorInvocationRequest(capability_type=CAP, operation=operation)
    return await ConnectorExecutor().execute(provider, req, _policy())


# ---- Writes: ambiguous failures are NOT retried -----------------------------


@pytest.mark.asyncio
async def test_write_failure_not_retried():
    provider = _provider("create_ticket", read_only=False, status=ConnectorStatus.FAILURE)
    await _run(provider, "create_ticket")
    assert provider.execute.call_count == 1  # generic FAILURE → no retry for writes


@pytest.mark.asyncio
async def test_write_timeout_not_retried():
    provider = _provider("send_message", read_only=False, status=ConnectorStatus.TIMEOUT)
    await _run(provider, "send_message")
    assert provider.execute.call_count == 1  # ambiguous (may have applied) → no retry


@pytest.mark.asyncio
async def test_write_unavailable_is_retried():
    # UNAVAILABLE means rejected before running → safe to retry even for writes.
    provider = _provider("create_ticket", read_only=False, status=ConnectorStatus.UNAVAILABLE)
    await _run(provider, "create_ticket")
    assert provider.execute.call_count == 4  # 1 + 3 retries


# ---- Reads: idempotent → full retry set applies -----------------------------


@pytest.mark.asyncio
async def test_read_failure_is_retried():
    provider = _provider("search_tickets", read_only=True, status=ConnectorStatus.FAILURE)
    await _run(provider, "search_tickets")
    assert provider.execute.call_count == 4  # reads retry on FAILURE


@pytest.mark.asyncio
async def test_unknown_operation_treated_as_write():
    # Operation not in the descriptor → conservative (no retry on FAILURE).
    provider = _provider("declared_op", read_only=True, status=ConnectorStatus.FAILURE)
    await _run(provider, "undeclared_op")  # request op differs from the declared one
    assert provider.execute.call_count == 1
