"""Datadog telemetry connector provider.

Implements query_metrics, get_logs, list_alerts, and get_health against
the Datadog REST API. Requires both a DD-API-KEY and DD-APPLICATION-KEY.
"""
from __future__ import annotations

import logging
import time

import httpx

from ...models import ConnectorCostInfo
from ._base import BaseTelemetryProvider, TelemetryProviderError

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 30.0


class DatadogTelemetryProvider(BaseTelemetryProvider):
    """Datadog-backed telemetry connector provider.

    Supports query_metrics, get_logs, list_alerts, and get_health operations.
    Authenticates via DD-API-KEY and DD-APPLICATION-KEY headers.

    Example::

        provider = DatadogTelemetryProvider(
            api_key="dd_api_key",
            app_key="dd_app_key",
            site="datadoghq.com",
        )
    """

    def __init__(
        self,
        api_key: str,
        app_key: str,
        site: str = "datadoghq.com",
    ) -> None:
        if not api_key:
            raise ValueError("DatadogTelemetryProvider requires a non-empty api_key")
        if not app_key:
            raise ValueError("DatadogTelemetryProvider requires a non-empty app_key")
        self._api_key = api_key
        self._app_key = app_key
        self._site = site

    @classmethod
    def from_env(cls) -> "DatadogTelemetryProvider | None":
        """Create an instance from environment variables.

        Required env vars: ``DATADOG_API_KEY``, ``DATADOG_APP_KEY``
        Optional env vars: ``DATADOG_SITE`` (default: ``datadoghq.com``)

        Returns None if either required env var is not set.
        """
        import os

        api_key = os.environ.get("DATADOG_API_KEY", "")
        app_key = os.environ.get("DATADOG_APP_KEY", "")
        if not api_key or not app_key:
            return None
        return cls(
            api_key=api_key,
            app_key=app_key,
            site=os.environ.get("DATADOG_SITE", "datadoghq.com"),
        )

    @property
    def provider_id(self) -> str:
        """Unique provider identifier used for registry lookups."""
        return "telemetry.datadog"

    @property
    def display_name(self) -> str:
        """Human-readable name shown in the registry descriptor."""
        return "Datadog Telemetry"

    def is_available(self) -> bool:
        """Return True if both the API key and application key are configured."""
        return bool(self._api_key) and bool(self._app_key)

    def _auth_headers(self) -> dict[str, str]:
        """Build Datadog authentication headers."""
        return {
            "DD-API-KEY": self._api_key,
            "DD-APPLICATION-KEY": self._app_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _api_url(self, path: str) -> str:
        """Build a full Datadog API URL for the configured site."""
        return f"https://api.{self._site}/{path}"

    async def _query_metrics(
        self,
        query: str,
        start: str | None,
        end: str | None,
        step: str | None,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Query scalar metrics via the Datadog v2 scalar query API.

        Args:
            query: Datadog metrics query expression.
            start: UNIX timestamp string for the query window start, or None.
            end: UNIX timestamp string for the query window end, or None.
            step: Not used by the scalar API; reserved for future range queries.

        Returns:
            Tuple of (ExternalArtifact dict, ConnectorCostInfo).

        Raises:
            TelemetryProviderError: On HTTP or API errors.
        """
        now = int(time.time())
        from_ts = int(start) if start else now - 3600
        to_ts = int(end) if end else now

        body: dict = {
            "data": {
                "type": "scalar_request",
                "attributes": {
                    "formulas": [{"formula": query}],
                    "from": from_ts,
                    "to": to_ts,
                    "queries": [
                        {
                            "name": "q",
                            "data_source": "metrics",
                            "query": query,
                        }
                    ],
                },
            }
        }

        try:
            async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
                response = await client.post(
                    self._api_url("api/v2/query/scalars"),
                    headers=self._auth_headers(),
                    json=body,
                )
                response.raise_for_status()
                data: dict = response.json()
        except httpx.HTTPError as exc:
            raise TelemetryProviderError(f"Datadog query_metrics error: {exc}") from exc

        value = 0.0
        try:
            series = (
                data.get("data", {})
                .get("attributes", {})
                .get("columns", [{}])[0]
                .get("values", [0.0])
            )
            value = float(series[0]) if series else 0.0
        except (IndexError, TypeError, ValueError) as exc:
            logger.debug("Datadog: could not parse metric value from response: %s", exc)

        artifact = self._make_metric_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            metric_name=query,
            value=value,
            unit=None,
            labels={},
            interval_seconds=None,
            raw_payload=data,
            provenance={"provider": "datadog", "query": query},
        )

        cost_info = ConnectorCostInfo(estimated_cost=0.0, unit_label="query")
        logger.info("Datadog query_metrics: query=%r value=%s", query, value)
        return artifact.model_dump(mode="json"), cost_info

    async def _get_logs(
        self,
        query: str,
        start: str | None,
        end: str | None,
        limit: str | None,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Retrieve log entries from Datadog matching a filter expression.

        Args:
            query: Datadog log search query string.
            start: ISO8601 or relative time string for window start, or None.
            end: ISO8601 or relative time string for window end, or None.
            limit: Maximum number of log events to return, or None (default 100).

        Returns:
            Tuple of (ExternalArtifact dict, None — no tracked API cost).

        Raises:
            TelemetryProviderError: On HTTP or API errors.
        """
        page_limit = int(limit) if limit else 100
        body: dict = {
            "filter": {
                "query": query,
                "from": start or "now-1h",
                "to": end or "now",
            },
            "page": {"limit": page_limit},
        }

        try:
            async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
                response = await client.post(
                    self._api_url("api/v2/logs/events/search"),
                    headers=self._auth_headers(),
                    json=body,
                )
                response.raise_for_status()
                data: dict = response.json()
        except httpx.HTTPError as exc:
            raise TelemetryProviderError(f"Datadog get_logs error: {exc}") from exc

        items: list[dict] = data.get("data", [])
        artifact = self._make_list_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            resource_type="log_entries",
            items=items,
            raw_payload=data,
            provenance={"provider": "datadog", "query": query},
        )

        logger.info("Datadog get_logs: query=%r count=%d", query, len(items))
        return artifact.model_dump(mode="json"), None

    async def _list_alerts(
        self,
        state: str | None,
        limit: str | None,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """List monitors/alerts from Datadog.

        Args:
            state: Optional monitor state filter (e.g. "Alert", "OK", "Warn").
            limit: Maximum number of monitors to return, or None (default 50).

        Returns:
            Tuple of (ExternalArtifact dict, None — no tracked API cost).

        Raises:
            TelemetryProviderError: On HTTP or API errors.
        """
        page_size = int(limit) if limit else 50
        params: dict = {"monitor_tags": "", "page_size": page_size}
        if state:
            params["monitor_status"] = state

        try:
            async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
                response = await client.get(
                    self._api_url("api/v1/monitor"),
                    headers=self._auth_headers(),
                    params=params,
                )
                response.raise_for_status()
                data: list = response.json()
        except httpx.HTTPError as exc:
            raise TelemetryProviderError(f"Datadog list_alerts error: {exc}") from exc

        if not isinstance(data, list):
            data = []

        items = [
            {
                "id": m.get("id"),
                "name": m.get("name"),
                "type": m.get("type"),
                "status": m.get("overall_state"),
                "query": m.get("query"),
                "message": m.get("message"),
            }
            for m in data
        ]

        artifact = self._make_list_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            resource_type="alerts",
            items=items,
            raw_payload={"monitors": data},
            provenance={"provider": "datadog", "state": state},
        )

        logger.info("Datadog list_alerts: state=%r count=%d", state, len(items))
        return artifact.model_dump(mode="json"), None

    async def _get_health(self) -> tuple[dict, ConnectorCostInfo | None]:
        """Validate Datadog API connectivity.

        Returns:
            Tuple of (ExternalArtifact dict with metric_name="health" value=1.0,
            None — no tracked API cost).

        Raises:
            TelemetryProviderError: When the API returns a non-200 response.
        """
        try:
            async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
                response = await client.get(
                    self._api_url("api/v1/validate"),
                    headers=self._auth_headers(),
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise TelemetryProviderError(
                f"Datadog get_health error: {exc}"
            ) from exc

        artifact = self._make_metric_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            metric_name="health",
            value=1.0,
            unit=None,
            labels={},
            interval_seconds=None,
            raw_payload={"valid": True},
            provenance={"provider": "datadog"},
        )

        logger.info("Datadog get_health: OK")
        return artifact.model_dump(mode="json"), None
