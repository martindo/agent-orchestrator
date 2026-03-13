"""Connector audit helpers — bridge between connectors and the platform audit trail."""

from __future__ import annotations

import logging

from ..governance.audit_logger import AuditLogger, RecordType
from .models import ConnectorInvocationRequest, ConnectorInvocationResult

logger = logging.getLogger(__name__)


def log_connector_invocation(
    audit_logger: AuditLogger,
    request: ConnectorInvocationRequest,
    result: ConnectorInvocationResult,
) -> None:
    """Record a connector invocation in the platform audit trail.

    Args:
        audit_logger: Platform AuditLogger instance.
        request: The original invocation request.
        result: The invocation result.
    """
    context = request.context
    data = {
        "run_id": context.get("run_id"),
        "workflow_id": context.get("workflow_id"),
        "module_name": context.get("module_name"),
        "agent_role": context.get("agent_role"),
        "capability_type": request.capability_type.value,
        "connector_id": result.connector_id,
        "provider": result.provider,
        "operation": request.operation,
        "parameter_keys": list(request.parameters.keys()),
        "status": result.status.value,
        "duration_ms": result.duration_ms,
        "timestamp": result.timestamp.isoformat(),
        "cost_info": result.cost_info.model_dump() if result.cost_info else None,
        "error_message": result.error_message,
    }
    summary = (
        f"connector={result.connector_id} "
        f"capability={request.capability_type.value} "
        f"op={request.operation} "
        f"status={result.status.value}"
    )
    work_id = context.get("work_id", "")
    audit_logger.append(
        record_type=RecordType.SYSTEM_EVENT,
        action="connector_invocation",
        summary=summary,
        work_id=work_id,
        data=data,
    )
