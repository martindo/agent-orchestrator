"""API routes for the workflow scheduler."""

from __future__ import annotations

from fastapi import APIRouter

from agent_orchestrator.core.scheduler import ScheduleEntry, scheduler

router = APIRouter(prefix="/schedules", tags=["schedules"])


@router.get("/")
async def list_schedules() -> dict:
    """List all registered schedules."""
    entries = scheduler.get_all()
    return {"data": [e.__dict__ for e in entries], "total": len(entries)}


@router.post("/")
async def create_schedule(body: dict) -> dict:
    """Create a new schedule entry."""
    entry = ScheduleEntry(
        id=body.get("id", f"sched-{len(scheduler.get_all()) + 1}"),
        cron=body.get("cron", "interval:3600"),
        workflow_id=body.get("workflow_id", ""),
        input_template=body.get("input_template", {}),
        enabled=body.get("enabled", True),
    )
    scheduler.add_schedule(entry)
    return {"success": True, "data": entry.__dict__}


@router.get("/{schedule_id}")
async def get_schedule(schedule_id: str) -> dict:
    """Get a schedule by ID."""
    entry = scheduler.get(schedule_id)
    if not entry:
        return {"success": False, "error": "Schedule not found"}
    return {"success": True, "data": entry.__dict__}


@router.delete("/{schedule_id}")
async def delete_schedule(schedule_id: str) -> dict:
    """Delete a schedule by ID."""
    removed = scheduler.remove_schedule(schedule_id)
    return {"success": removed}


@router.post("/{schedule_id}/toggle")
async def toggle_schedule(schedule_id: str) -> dict:
    """Toggle a schedule's enabled state."""
    entry = scheduler.toggle(schedule_id)
    if not entry:
        return {"success": False, "error": "Schedule not found"}
    return {"success": True, "data": entry.__dict__}


@router.post("/start")
async def start_scheduler() -> dict:
    """Start the background scheduler loop."""
    await scheduler.start()
    return {"success": True, "message": "Scheduler started"}


@router.post("/stop")
async def stop_scheduler() -> dict:
    """Stop the background scheduler loop."""
    await scheduler.stop()
    return {"success": True, "message": "Scheduler stopped"}
