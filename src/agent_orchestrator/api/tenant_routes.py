"""Tenant management routes for multi-tenant isolation."""

from __future__ import annotations

from fastapi import APIRouter

from ..middleware.tenant import create_tenant, delete_tenant, get_tenant, list_tenants

router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.get("/")
async def get_tenants() -> dict:
    """List all tenants."""
    tenants = list_tenants()
    return {"data": [t.__dict__ for t in tenants], "total": len(tenants)}


@router.post("/")
async def create_new_tenant(body: dict) -> dict:
    """Create a new tenant."""
    tenant = create_tenant(body.get("tenant_id", ""), body.get("tenant_name", ""))
    return {"success": True, "data": tenant.__dict__}


@router.get("/{tenant_id}")
async def get_tenant_detail(tenant_id: str) -> dict:
    """Get details for a specific tenant."""
    tenant = get_tenant(tenant_id)
    if not tenant:
        return {"error": "Tenant not found"}
    return {"success": True, "data": tenant.__dict__}


@router.delete("/{tenant_id}")
async def remove_tenant(tenant_id: str) -> dict:
    """Delete a tenant by ID."""
    removed = delete_tenant(tenant_id)
    return {"success": removed}
