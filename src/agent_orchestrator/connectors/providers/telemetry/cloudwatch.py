"""AWS CloudWatch telemetry connector provider.

Implements query_metrics, get_logs, list_alerts, and get_health against
the AWS CloudWatch and CloudWatch Logs APIs via boto3. All boto3 calls
are dispatched through run_in_executor for async compatibility.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, NoReturn

from ...models import ConnectorCostInfo
from ._base import BaseTelemetryProvider, TelemetryProviderError

logger = logging.getLogger(__name__)

_STATE_MAP: dict[str, str] = {
    "active": "ALARM",
    "ok": "OK",
    "insufficient": "INSUFFICIENT_DATA",
}


class CloudWatchTelemetryProvider(BaseTelemetryProvider):
    """AWS CloudWatch-backed telemetry connector provider.

    Supports query_metrics (GetMetricData), get_logs (FilterLogEvents),
    list_alerts (DescribeAlarms), and get_health (ListMetrics) operations.
    All boto3 calls are wrapped in run_in_executor to avoid blocking the
    async event loop.

    Example::

        provider = CloudWatchTelemetryProvider(
            region="us-east-1",
            aws_access_key_id="AKIA...",
            aws_secret_access_key="secret",
        )
    """

    def __init__(
        self,
        region: str,
        aws_access_key_id: str = "",
        aws_secret_access_key: str = "",
        aws_session_token: str = "",
    ) -> None:
        if not region:
            raise ValueError(
                "CloudWatchTelemetryProvider requires a non-empty region"
            )
        self._api_key = region  # satisfies is_available()
        self._region = region
        self._access_key = aws_access_key_id
        self._secret_key = aws_secret_access_key
        self._session_token = aws_session_token

    @classmethod
    def from_env(cls) -> "CloudWatchTelemetryProvider | None":
        """Create an instance from environment variables.

        Required env vars: ``AWS_REGION`` or ``AWS_DEFAULT_REGION``
        Optional env vars: ``AWS_ACCESS_KEY_ID``, ``AWS_SECRET_ACCESS_KEY``,
        ``AWS_SESSION_TOKEN``

        Returns None if no region is configured or if boto3 is not importable.
        """
        import os

        try:
            import boto3  # noqa: F401
        except ImportError:
            logger.warning(
                "boto3 is not installed; CloudWatchTelemetryProvider is unavailable"
            )
            return None

        region = os.environ.get("AWS_REGION", "") or os.environ.get(
            "AWS_DEFAULT_REGION", ""
        )
        if not region:
            return None

        return cls(
            region=region,
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", ""),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", ""),
            aws_session_token=os.environ.get("AWS_SESSION_TOKEN", ""),
        )

    @property
    def provider_id(self) -> str:
        """Unique provider identifier used for registry lookups."""
        return "telemetry.cloudwatch"

    @property
    def display_name(self) -> str:
        """Human-readable name shown in the registry descriptor."""
        return "AWS CloudWatch Telemetry"

    def _get_client(self, service: str) -> Any:
        """Create a boto3 client for the given AWS service.

        Args:
            service: AWS service name (e.g. "cloudwatch", "logs").

        Returns:
            boto3 service client configured for self._region.
        """
        import boto3

        kwargs: dict = {"region_name": self._region}
        if self._access_key:
            kwargs["aws_access_key_id"] = self._access_key
        if self._secret_key:
            kwargs["aws_secret_access_key"] = self._secret_key
        if self._session_token:
            kwargs["aws_session_token"] = self._session_token
        return boto3.client(service, **kwargs)

    async def _query_metrics(
        self,
        query: str,
        start: str | None,
        end: str | None,
        step: str | None,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Retrieve CloudWatch metric data using GetMetricData.

        The query string is used as a CloudWatch Metrics Insights expression.

        Args:
            query: CloudWatch metric expression (used in MetricDataQueries).
            start: UNIX timestamp string for the query window start, or None.
            end: UNIX timestamp string for the query window end, or None.
            step: Resolution period in seconds, or None (default 300).

        Returns:
            Tuple of (ExternalArtifact dict, None — no tracked API cost).

        Raises:
            TelemetryProviderError: On boto3 ClientError or other AWS errors.
        """
        start_time = (
            datetime.utcfromtimestamp(float(start))
            if start
            else datetime.utcnow() - timedelta(hours=1)
        )
        end_time = (
            datetime.utcfromtimestamp(float(end)) if end else datetime.utcnow()
        )
        period = int(step) if step else 300

        def _call() -> dict:
            try:
                client = self._get_client("cloudwatch")
                return client.get_metric_data(
                    MetricDataQueries=[
                        {
                            "Id": "q1",
                            "Expression": query,
                            "Period": period,
                        }
                    ],
                    StartTime=start_time,
                    EndTime=end_time,
                )
            except Exception as exc:
                _raise_provider_error("CloudWatch get_metric_data", exc)

        data: dict = await asyncio.get_running_loop().run_in_executor(None, _call)

        value = 0.0
        try:
            results = data.get("MetricDataResults", [])
            if results:
                values = results[0].get("Values", [])
                value = float(values[0]) if values else 0.0
        except (IndexError, TypeError, ValueError) as exc:
            logger.debug(
                "CloudWatch: could not parse metric value from response: %s", exc
            )

        artifact = self._make_metric_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            metric_name=query,
            value=value,
            unit=None,
            labels={},
            interval_seconds=float(period),
            raw_payload=_serialize_response(data),
            provenance={"provider": "cloudwatch", "region": self._region},
        )

        logger.info("CloudWatch query_metrics: query=%r value=%s", query, value)
        return artifact.model_dump(mode="json"), None

    async def _get_logs(
        self,
        query: str,
        start: str | None,
        end: str | None,
        limit: str | None,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Retrieve CloudWatch log events using FilterLogEvents.

        The query string is parsed as ``<log_group_name>:<filter_pattern>``
        when a colon is present; otherwise the entire string is used as the
        log group name with no filter pattern.

        Args:
            query: Log group name, optionally followed by ``:filter_pattern``.
            start: UNIX timestamp (milliseconds) string, or None.
            end: UNIX timestamp (milliseconds) string, or None.
            limit: Maximum number of log events, or None (default 100).

        Returns:
            Tuple of (ExternalArtifact dict, None — no tracked API cost).

        Raises:
            TelemetryProviderError: On boto3 ClientError or other AWS errors.
        """
        if ":" in query:
            log_group, filter_pattern = query.split(":", 1)
        else:
            log_group = query
            filter_pattern = ""

        page_limit = int(limit) if limit else 100

        def _call() -> dict:
            try:
                client = self._get_client("logs")
                kwargs: dict = {
                    "logGroupName": log_group,
                    "limit": page_limit,
                }
                if filter_pattern:
                    kwargs["filterPattern"] = filter_pattern
                if start:
                    kwargs["startTime"] = int(start)
                if end:
                    kwargs["endTime"] = int(end)
                return client.filter_log_events(**kwargs)
            except Exception as exc:
                _raise_provider_error("CloudWatch filter_log_events", exc)

        data: dict = await asyncio.get_running_loop().run_in_executor(None, _call)

        items: list[dict] = data.get("events", [])
        artifact = self._make_list_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            resource_type="log_entries",
            items=items,
            raw_payload=_serialize_response(data),
            provenance={
                "provider": "cloudwatch",
                "log_group": log_group,
                "region": self._region,
            },
        )

        logger.info(
            "CloudWatch get_logs: log_group=%r count=%d", log_group, len(items)
        )
        return artifact.model_dump(mode="json"), None

    async def _list_alerts(
        self,
        state: str | None,
        limit: str | None,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """List CloudWatch alarms using DescribeAlarms.

        Args:
            state: Optional alarm state filter ("active", "ok", or
                "insufficient"). Mapped to CloudWatch StateValue strings.
            limit: Maximum number of alarms to return, or None (default 50).

        Returns:
            Tuple of (ExternalArtifact dict, None — no tracked API cost).

        Raises:
            TelemetryProviderError: On boto3 ClientError or other AWS errors.
        """
        max_records = int(limit) if limit else 50

        def _call() -> dict:
            try:
                client = self._get_client("cloudwatch")
                kwargs: dict = {"MaxRecords": max_records}
                if state:
                    cw_state = _STATE_MAP.get(state.lower(), state)
                    kwargs["StateValue"] = cw_state
                return client.describe_alarms(**kwargs)
            except Exception as exc:
                _raise_provider_error("CloudWatch describe_alarms", exc)

        data: dict = await asyncio.get_running_loop().run_in_executor(None, _call)

        raw_alarms: list[dict] = data.get("MetricAlarms", [])
        items = [
            {
                "name": a.get("AlarmName"),
                "state": a.get("StateValue"),
                "description": a.get("AlarmDescription"),
                "arn": a.get("AlarmArn"),
                "metric_name": a.get("MetricName"),
                "namespace": a.get("Namespace"),
            }
            for a in raw_alarms
        ]

        artifact = self._make_list_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            resource_type="alerts",
            items=items,
            raw_payload=_serialize_response(data),
            provenance={
                "provider": "cloudwatch",
                "state": state,
                "region": self._region,
            },
        )

        logger.info("CloudWatch list_alerts: state=%r count=%d", state, len(items))
        return artifact.model_dump(mode="json"), None

    async def _get_health(self) -> tuple[dict, ConnectorCostInfo | None]:
        """Verify CloudWatch connectivity via ListMetrics.

        Args: None

        Returns:
            Tuple of (ExternalArtifact dict with metric_name="health" value=1.0,
            None — no tracked API cost).

        Raises:
            TelemetryProviderError: When the AWS call fails.
        """
        def _call() -> dict:
            try:
                client = self._get_client("cloudwatch")
                return client.list_metrics(MaxResults=1)
            except Exception as exc:
                _raise_provider_error("CloudWatch list_metrics", exc)

        data: dict = await asyncio.get_running_loop().run_in_executor(None, _call)

        artifact = self._make_metric_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            metric_name="health",
            value=1.0,
            unit=None,
            labels={},
            interval_seconds=None,
            raw_payload=_serialize_response(data),
            provenance={"provider": "cloudwatch", "region": self._region},
        )

        logger.info("CloudWatch get_health: OK region=%r", self._region)
        return artifact.model_dump(mode="json"), None


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _raise_provider_error(context: str, exc: Exception) -> NoReturn:
    """Wrap any exception (including boto3 ClientError) in TelemetryProviderError.

    Args:
        context: Human-readable description of the failing operation.
        exc: The original exception.

    Raises:
        TelemetryProviderError: Always.
    """
    raise TelemetryProviderError(f"{context} failed: {exc}") from exc


def _serialize_response(data: dict) -> dict:
    """Convert a boto3 response dict to a JSON-serializable dict.

    Replaces datetime objects with ISO8601 strings so the payload can be
    stored in the ExternalArtifact raw_payload field.

    Args:
        data: Raw boto3 API response dict.

    Returns:
        Copy of data with datetime values converted to strings.
    """
    result: dict = {}
    for key, value in data.items():
        if isinstance(value, datetime):
            result[key] = value.isoformat()
        elif isinstance(value, list):
            result[key] = [
                _serialize_response(item) if isinstance(item, dict) else (
                    item.isoformat() if isinstance(item, datetime) else item
                )
                for item in value
            ]
        elif isinstance(value, dict):
            result[key] = _serialize_response(value)
        else:
            result[key] = value
    return result
