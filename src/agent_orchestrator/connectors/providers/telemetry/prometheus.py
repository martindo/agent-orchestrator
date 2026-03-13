"""Prometheus telemetry connector provider.

Implements query_metrics, get_logs, list_alerts, and get_health against
the Prometheus HTTP API. Supports optional basic authentication.
"""
from __future__ import annotations

import logging

import httpx

from ...models import ConnectorCostInfo
from ._base import BaseTelemetryProvider, TelemetryProviderError

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 30.0


class PrometheusTelemetryProvider(BaseTelemetryProvider):
    """Prometheus-backed telemetry connector provider.

    Supports query_metrics, get_logs (stub — Prometheus has no native log API),
    list_alerts, and get_health operations.

    Example::

        provider = PrometheusTelemetryProvider(
            url="http://localhost:9090",
            username="admin",
            password="secret",
        )
    """

    def __init__(
        self,
        url: str,
        username: str = "",
        password: str = "",
    ) -> None:
        if not url:
            raise ValueError("PrometheusTelemetryProvider requires a non-empty url")
        self._api_key = url  # satisfies is_available()
        self._url = url.rstrip("/")
        self._username = username
        self._password = password

    @classmethod
    def from_env(cls) -> "PrometheusTelemetryProvider | None":
        """Create an instance from environment variables.

        Required env vars: ``PROMETHEUS_URL``
        Optional env vars: ``PROMETHEUS_USERNAME``, ``PROMETHEUS_PASSWORD``

        Returns None if ``PROMETHEUS_URL`` is not set.
        """
        import os

        url = os.environ.get("PROMETHEUS_URL", "")
        if not url:
            return None
        return cls(
            url=url,
            username=os.environ.get("PROMETHEUS_USERNAME", ""),
            password=os.environ.get("PROMETHEUS_PASSWORD", ""),
        )

    @property
    def provider_id(self) -> str:
        """Unique provider identifier used for registry lookups."""
        return "telemetry.prometheus"

    @property
    def display_name(self) -> str:
        """Human-readable name shown in the registry descriptor."""
        return "Prometheus Telemetry"

    def _auth(self) -> httpx.BasicAuth | None:
        """Return BasicAuth if both username and password are configured."""
        if self._username and self._password:
            return httpx.BasicAuth(self._username, self._password)
        return None

    async def _query_metrics(
        self,
        query: str,
        start: str | None,
        end: str | None,
        step: str | None,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Execute a PromQL query against the Prometheus HTTP API.

        Uses the range query endpoint when both start and end are provided;
        falls back to the instant query endpoint otherwise.

        Args:
            query: PromQL expression to evaluate.
            start: UNIX timestamp string for the range start, or None.
            end: UNIX timestamp string for the range end, or None.
            step: Resolution step (e.g. "60") in seconds, or None (default 60).

        Returns:
            Tuple of (ExternalArtifact dict, None — no tracked API cost).

        Raises:
            TelemetryProviderError: On HTTP or API errors.
        """
        auth = self._auth()

        try:
            async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
                if start and end:
                    response = await client.get(
                        f"{self._url}/api/v1/query_range",
                        auth=auth,
                        params={
                            "query": query,
                            "start": start,
                            "end": end,
                            "step": step or "60",
                        },
                    )
                else:
                    response = await client.get(
                        f"{self._url}/api/v1/query",
                        auth=auth,
                        params={"query": query},
                    )
                response.raise_for_status()
                data: dict = response.json()
        except httpx.HTTPError as exc:
            raise TelemetryProviderError(
                f"Prometheus query_metrics error: {exc}"
            ) from exc

        value = 0.0
        try:
            result = data.get("data", {}).get("result", [])
            if result:
                raw_value = result[0].get("value", [None, "0"])
                value = float(raw_value[1]) if raw_value and len(raw_value) > 1 else 0.0
        except (IndexError, TypeError, ValueError) as exc:
            logger.debug(
                "Prometheus: could not parse metric value from response: %s", exc
            )

        artifact = self._make_metric_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            metric_name=query,
            value=value,
            unit=None,
            labels={},
            interval_seconds=float(step) if step else None,
            raw_payload=data,
            provenance={"provider": "prometheus", "query": query},
        )

        logger.info("Prometheus query_metrics: query=%r value=%s", query, value)
        return artifact.model_dump(mode="json"), None

    async def _get_logs(
        self,
        query: str,
        start: str | None,
        end: str | None,
        limit: str | None,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Return an empty log artifact — Prometheus has no native log API.

        Args:
            query: Ignored; Prometheus does not support log queries.
            start: Ignored.
            end: Ignored.
            limit: Ignored.

        Returns:
            Tuple of (ExternalArtifact dict with empty items, None).
        """
        artifact = self._make_list_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            resource_type="log_entries",
            items=[],
            raw_payload={"items": []},
            provenance={
                "provider": "prometheus",
                "note": "Prometheus does not support log queries",
            },
        )

        logger.info("Prometheus get_logs: not supported, returning empty result")
        return artifact.model_dump(mode="json"), None

    async def _list_alerts(
        self,
        state: str | None,
        limit: str | None,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """List active alerts from the Prometheus alerts endpoint.

        Args:
            state: Optional alert state filter (e.g. "firing", "pending").
            limit: Not enforced server-side; used to truncate the result list.

        Returns:
            Tuple of (ExternalArtifact dict, None — no tracked API cost).

        Raises:
            TelemetryProviderError: On HTTP or API errors.
        """
        auth = self._auth()

        try:
            async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
                response = await client.get(
                    f"{self._url}/api/v1/alerts",
                    auth=auth,
                )
                response.raise_for_status()
                data: dict = response.json()
        except httpx.HTTPError as exc:
            raise TelemetryProviderError(
                f"Prometheus list_alerts error: {exc}"
            ) from exc

        all_alerts: list[dict] = data.get("data", {}).get("alerts", [])

        if state:
            all_alerts = [a for a in all_alerts if a.get("state") == state]

        page_limit = int(limit) if limit else len(all_alerts)
        items = all_alerts[:page_limit]

        artifact = self._make_list_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            resource_type="alerts",
            items=items,
            raw_payload=data,
            provenance={"provider": "prometheus", "state": state},
        )

        logger.info("Prometheus list_alerts: state=%r count=%d", state, len(items))
        return artifact.model_dump(mode="json"), None

    async def _get_health(self) -> tuple[dict, ConnectorCostInfo | None]:
        """Check Prometheus connectivity via the healthy endpoint.

        Returns:
            Tuple of (ExternalArtifact dict with metric_name="health" value=1.0,
            None — no tracked API cost).

        Raises:
            TelemetryProviderError: When the endpoint returns a non-200 response.
        """
        auth = self._auth()

        try:
            async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
                response = await client.get(
                    f"{self._url}/-/healthy",
                    auth=auth,
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise TelemetryProviderError(
                f"Prometheus get_health error: {exc}"
            ) from exc

        artifact = self._make_metric_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            metric_name="health",
            value=1.0,
            unit=None,
            labels={},
            interval_seconds=None,
            raw_payload={"healthy": True},
            provenance={"provider": "prometheus"},
        )

        logger.info("Prometheus get_health: OK")
        return artifact.model_dump(mode="json"), None
