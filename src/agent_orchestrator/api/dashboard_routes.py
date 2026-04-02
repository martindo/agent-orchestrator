"""Dashboard routes — Aggregate metrics and activity feed.

Provides summary statistics for work items, agents, throughput,
and recent activity from the audit trail.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Request

logger = logging.getLogger(__name__)

dashboard_router = APIRouter()


def _get_engine(request: Request) -> Any:
    """Get the OrchestrationEngine from request state."""
    return getattr(request.app.state, "engine", None)


@dashboard_router.get("/dashboard/stats")
async def get_dashboard_stats(request: Request) -> dict[str, Any]:
    """Aggregate dashboard statistics."""
    engine = _get_engine(request)
    empty: dict[str, Any] = {
        "work_items": {"total": 0, "by_status": {}, "by_type": {}},
        "agents": {"total": 0, "by_definition": {}},
        "throughput": {"completed_today": 0, "completed_this_week": 0, "avg_per_day": 0.0},
        "queue": {"current_size": 0, "total_pushed": 0, "total_popped": 0},
        "sla": {"on_time": 0, "breached": 0, "compliance_pct": 100.0},
    }
    if engine is None:
        return empty

    # Work item stats from persistent store
    work_item_summary: dict[str, Any] = {}
    completed_today = 0
    completed_week = 0
    total_completed = 0

    store = getattr(engine, "work_item_store", None)
    if store is not None:
        try:
            work_item_summary = store.summary()
        except Exception:
            logger.warning("Failed to load work item summary", exc_info=True)

        # Count recently completed items
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=today_start.weekday())

        try:
            from agent_orchestrator.core.work_queue import WorkItemStatus
            completed_items = store.query(status=WorkItemStatus.COMPLETED, limit=1000)
            total_completed = len(completed_items)
            for item in completed_items:
                completed_at = getattr(item, "completed_at", None)
                if completed_at is None:
                    continue
                if completed_at >= today_start:
                    completed_today += 1
                if completed_at >= week_start:
                    completed_week += 1
        except Exception:
            logger.warning("Failed to query completed items", exc_info=True)

    # Agent pool stats
    agent_stats: dict[str, Any] = {}
    agent_total = 0
    try:
        pool = getattr(engine, "_agent_pool", None)
        if pool is not None:
            agent_stats = pool.get_stats()
            agent_total = sum(
                defn.get("total_instances", 0) for defn in agent_stats.values()
            )
    except Exception:
        logger.warning("Failed to load agent pool stats", exc_info=True)

    # Queue stats
    queue_stats: dict[str, Any] = {}
    try:
        queue = getattr(engine, "_queue", None)
        if queue is not None:
            queue_stats = queue.get_stats()
    except Exception:
        logger.warning("Failed to load queue stats", exc_info=True)

    # Throughput average
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())
    days_elapsed = max(1, (now - week_start).days or 1)
    avg_per_day = round(completed_week / days_elapsed, 1)

    return {
        "work_items": work_item_summary or {"total": 0, "by_status": {}, "by_type": {}},
        "agents": {
            "total": agent_total,
            "by_definition": agent_stats,
        },
        "throughput": {
            "completed_today": completed_today,
            "completed_this_week": completed_week,
            "avg_per_day": avg_per_day,
        },
        "queue": queue_stats or {"current_size": 0, "total_pushed": 0, "total_popped": 0},
        "sla": {
            "on_time": total_completed,
            "breached": 0,
            "compliance_pct": 100.0,
        },
    }


@dashboard_router.get("/dashboard/activity")
async def get_recent_activity(request: Request, limit: int = 20) -> dict[str, Any]:
    """Get recent activity from the audit trail."""
    engine = _get_engine(request)
    if engine is None:
        return {"activity": [], "total": 0}

    audit_logger = getattr(engine, "audit_logger", None)
    if audit_logger is None:
        return {"activity": [], "total": 0}

    try:
        entries = audit_logger.query(limit=limit)
        return {"activity": entries, "total": len(entries)}
    except Exception:
        logger.warning("Failed to query audit trail", exc_info=True)
        return {"activity": [], "total": 0}


@dashboard_router.get("/dashboard/summary")
async def get_summary(request: Request) -> dict[str, Any]:
    """Quick summary for dashboard header."""
    stats = await get_dashboard_stats(request)
    wi = stats["work_items"]
    by_status = wi.get("by_status", {})
    agents = stats.get("agents", {})
    by_def = agents.get("by_definition", {})

    agents_idle = sum(d.get("idle", 0) for d in by_def.values())
    agents_running = sum(d.get("running", 0) for d in by_def.values())

    return {
        "active_items": wi.get("total", 0) - by_status.get("completed", 0) - by_status.get("failed", 0) - by_status.get("cancelled", 0),
        "completed": by_status.get("completed", 0),
        "in_progress": by_status.get("in_progress", 0),
        "pending": by_status.get("pending", 0),
        "queued": by_status.get("queued", 0),
        "agents_running": agents_running,
        "agents_idle": agents_idle,
        "completed_today": stats["throughput"]["completed_today"],
    }
