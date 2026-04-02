"""Multi-tenant isolation middleware."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class TenantContext:
    """Represents a tenant in the multi-tenant platform."""

    tenant_id: str
    tenant_name: str
    data_prefix: str  # Used to namespace data storage


# Simple tenant registry
_tenants: dict[str, TenantContext] = {
    "default": TenantContext(
        tenant_id="default", tenant_name="Default", data_prefix="default"
    ),
}


def get_tenant(tenant_id: str) -> Optional[TenantContext]:
    """Look up a tenant by ID."""
    return _tenants.get(tenant_id)


def create_tenant(tenant_id: str, tenant_name: str) -> TenantContext:
    """Create and register a new tenant."""
    ctx = TenantContext(
        tenant_id=tenant_id, tenant_name=tenant_name, data_prefix=tenant_id
    )
    _tenants[tenant_id] = ctx
    logger.info("Tenant created: %s", tenant_id)
    return ctx


def list_tenants() -> list[TenantContext]:
    """Return all registered tenants."""
    return list(_tenants.values())


def delete_tenant(tenant_id: str) -> bool:
    """Delete a tenant. The default tenant cannot be deleted."""
    if tenant_id == "default":
        return False
    return _tenants.pop(tenant_id, None) is not None
