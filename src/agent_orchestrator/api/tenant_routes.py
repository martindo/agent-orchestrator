"""Tenant management routes for multi-tenant isolation."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..middleware.tenant import create_tenant, delete_tenant, get_tenant, list_tenants

router = APIRouter(prefix="/tenants", tags=["tenants"])


class CreateTenantRequest(BaseModel):
    tenant_id: str = Field(..., min_length=1)
    tenant_name: str = Field(..., min_length=1)


@router.get("/")
async def get_tenants() -> dict:
    """List all tenants."""
    tenants = list_tenants()
    return {"data": [t.__dict__ for t in tenants], "total": len(tenants)}


@router.post("/")
async def create_new_tenant(body: CreateTenantRequest) -> dict:
    """Create a new tenant."""
    tenant = create_tenant(body.tenant_id, body.tenant_name)
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
