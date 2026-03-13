"""Contract Framework — public API.

Provides capability and artifact contract registration, storage,
and validation for the agent-orchestrator platform.

Domain modules may register their own contracts without modifying platform core::

    from agent_orchestrator.contracts import (
        ArtifactContract,
        ArtifactValidationRule,
        CapabilityContract,
        ContractRegistry,
        ContractValidator,
    )

    registry = ContractRegistry()
    registry.register_capability_contract(
        CapabilityContract(
            contract_id="search-query-v1",
            capability_type="search",
            operation_name="query",
            input_schema={"required": ["q"], "properties": {"q": {"type": "string"}}},
        )
    )
    validator = ContractValidator(registry)
"""

from .models import (
    ArtifactContract,
    ArtifactValidationRule,
    AuditRequirement,
    CapabilityContract,
    ContractRetryPolicy,
    ContractTimeoutPolicy,
    ContractValidationResult,
    ContractViolation,
    ContractViolationSeverity,
    FailureSemantic,
    LifecycleState,
    ReadWriteClassification,
)
from .registry import ContractRegistry
from .validator import ContractValidator

__all__ = [
    # Models
    "CapabilityContract",
    "ArtifactContract",
    "ArtifactValidationRule",
    "ContractTimeoutPolicy",
    "ContractRetryPolicy",
    "ContractValidationResult",
    "ContractViolation",
    # Enums
    "ReadWriteClassification",
    "AuditRequirement",
    "FailureSemantic",
    "ContractViolationSeverity",
    "LifecycleState",
    # Registry & Validator
    "ContractRegistry",
    "ContractValidator",
]
