"""ConnectorExecutor — reusable execution layer for connector providers.

Handles: retry policies, timeouts, error normalization,
telemetry hooks, and cost tracking hooks.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from ..exceptions import OrchestratorError
from .models import (
    ConnectorInvocationRequest,
    ConnectorInvocationResult,
    ConnectorStatus,
)
from .trace import ConnectorExecutionTrace, ConnectorTraceStore

if TYPE_CHECKING:
    from ..adapters.metrics_adapter import MetricsCollector
    from .models import ConnectorRetryPolicy
    from .registry import ConnectorProviderProtocol

logger = logging.getLogger(__name__)

_RETRYABLE_STATUSES = {ConnectorStatus.TIMEOUT, ConnectorStatus.UNAVAILABLE, ConnectorStatus.FAILURE}


class ConnectorExecutorError(OrchestratorError):
    """Raised when the executor encounters an unrecoverable error."""


class ConnectorExecutor:
    """Reusable execution layer for connector provider calls.

    Responsibilities:
    - Provider execution with asyncio timeout
    - Retry policy with exponential backoff
    - Error normalization to ConnectorInvocationResult
    - Cost tracking via MetricsCollector
    - Execution trace emission
    """

    def __init__(
        self,
        trace_store: ConnectorTraceStore | None = None,
        metrics: "MetricsCollector | None" = None,
    ) -> None:
        self._trace_store = trace_store
        self._metrics = metrics

    async def execute(
        self,
        provider: "ConnectorProviderProtocol",
        request: ConnectorInvocationRequest,
        retry_policy: "ConnectorRetryPolicy | None" = None,
    ) -> ConnectorInvocationResult:
        """Execute a provider with retry, timeout, error normalization.

        Args:
            provider: The connector provider to call.
            request: The invocation request.
            retry_policy: Optional retry configuration.

        Returns:
            ConnectorInvocationResult (never raises).
        """
        max_retries = retry_policy.max_retries if retry_policy else 0
        delay = retry_policy.delay_seconds if retry_policy else 1.0
        backoff = retry_policy.backoff_multiplier if retry_policy else 2.0
        retryable = set(retry_policy.retryable_statuses) if retry_policy else _RETRYABLE_STATUSES

        last_result: ConnectorInvocationResult | None = None
        for attempt in range(1, max_retries + 2):  # attempts = max_retries + 1
            last_result = await self._attempt(provider, request, attempt)
            self._record_trace(request, last_result, attempt)
            self._record_cost(last_result)
            if last_result.status not in retryable or attempt > max_retries:
                break
            wait = delay * (backoff ** (attempt - 1))
            logger.info(
                "Connector retry %d/%d in %.1fs: connector=%s status=%s",
                attempt,
                max_retries,
                wait,
                last_result.connector_id,
                last_result.status.value,
            )
            await asyncio.sleep(wait)

        return last_result  # type: ignore[return-value]

    async def _attempt(
        self,
        provider: "ConnectorProviderProtocol",
        request: ConnectorInvocationRequest,
        attempt: int,
    ) -> ConnectorInvocationResult:
        """Execute a single attempt against the provider."""
        descriptor = provider.get_descriptor()
        start = time.monotonic()
        try:
            if request.timeout_seconds:
                result = await asyncio.wait_for(
                    provider.execute(request),
                    timeout=request.timeout_seconds,
                )
            else:
                result = await provider.execute(request)
            return result
        except asyncio.TimeoutError:
            duration_ms = (time.monotonic() - start) * 1000
            logger.warning(
                "Connector timeout: provider=%s op=%s attempt=%d",
                descriptor.provider_id,
                request.operation,
                attempt,
            )
            return ConnectorInvocationResult(
                request_id=request.request_id,
                connector_id=descriptor.provider_id,
                provider=descriptor.provider_id,
                capability_type=request.capability_type,
                operation=request.operation,
                status=ConnectorStatus.TIMEOUT,
                error_message=f"Timed out after {request.timeout_seconds}s",
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = (time.monotonic() - start) * 1000
            logger.error(
                "Connector error: provider=%s op=%s attempt=%d",
                descriptor.provider_id,
                request.operation,
                attempt,
                exc_info=True,
            )
            return ConnectorInvocationResult(
                request_id=request.request_id,
                connector_id=descriptor.provider_id,
                provider=descriptor.provider_id,
                capability_type=request.capability_type,
                operation=request.operation,
                status=ConnectorStatus.FAILURE,
                error_message=str(exc),
                duration_ms=duration_ms,
            )

    def _record_trace(
        self,
        request: ConnectorInvocationRequest,
        result: ConnectorInvocationResult,
        attempt: int,
    ) -> None:
        """Emit a trace record if a trace store is configured."""
        if self._trace_store is None:
            return
        context = request.context
        trace = ConnectorExecutionTrace(
            request_id=request.request_id,
            run_id=context.get("run_id"),
            workflow_id=context.get("workflow_id"),
            module_name=context.get("module_name"),
            agent_role=context.get("agent_role"),
            connector_id=result.connector_id,
            provider=result.provider,
            capability_type=result.capability_type,
            operation=result.operation,
            parameter_keys=list(request.parameters.keys()),
            status=result.status,
            duration_ms=result.duration_ms,
            cost_info=result.cost_info,
            error_message=result.error_message,
            attempt_number=attempt,
        )
        try:
            self._trace_store.record(trace)
        except Exception:
            logger.warning("Failed to record connector trace", exc_info=True)

    def _record_cost(self, result: ConnectorInvocationResult) -> None:
        """Emit cost metrics if a metrics collector and cost info are available."""
        if self._metrics is None or result.cost_info is None:
            return
        tags = {
            "capability_type": result.capability_type.value,
            "provider": result.provider,
            "connector_id": result.connector_id,
            "operation": result.operation,
        }
        cost_info = result.cost_info
        try:
            if cost_info.request_cost is not None:
                self._metrics.record("connector.request_cost", cost_info.request_cost, tags)
            if cost_info.usage_units is not None:
                self._metrics.record("connector.usage_units", cost_info.usage_units, tags)
            if cost_info.provider_reported_cost is not None:
                self._metrics.record(
                    "connector.provider_cost", cost_info.provider_reported_cost, tags
                )
            if cost_info.estimated_cost is not None:
                self._metrics.record("connector.estimated_cost", cost_info.estimated_cost, tags)
            self._metrics.increment("connector.invocations", tags)
        except Exception:
            logger.warning("Failed to record connector cost metrics", exc_info=True)
