"""Connector Capability Framework — public API."""

from .auth import (
    AuthType,
    ConnectorAuthConfig,
    ConnectorSessionContext,
    build_session_context,
)
from .executor import ConnectorExecutor, ConnectorExecutorError
from .models import (
    CapabilityType,
    ConnectorConfig,
    ConnectorCostInfo,
    ConnectorCostMetadata,
    ConnectorInvocationRequest,
    ConnectorInvocationResult,
    ConnectorOperationDescriptor,
    ConnectorPermissionPolicy,
    ConnectorProviderDescriptor,
    ConnectorRateLimit,
    ConnectorRetryPolicy,
    ConnectorStatus,
    ExternalArtifact,
    ExternalReference,
    ExternalResourceDescriptor,
)
from .normalized import (
    DocumentArtifact,
    IdentityArtifact,
    MessageArtifact,
    NormalizedArtifactBase,
    RepositoryArtifact,
    SearchResultArtifact,
    SearchResultItem,
    TelemetryArtifact,
    TicketArtifact,
    get_normalized_type,
    try_normalize,
)
from .permissions import (
    ConnectorPermissionError,
    PermissionEvaluationResult,
    PermissionOutcome,
    evaluate_permission,
    evaluate_permission_detailed,
)
from .discovery import (
    ConnectorProviderDiscovery,
    DiscoveryResult,
    LazyConnectorProvider,
    ProviderLoadError,
    make_lazy_provider,
)
from .governance_service import (
    ConnectorDiscoveryItem,
    ConnectorGovernanceError,
    ConnectorGovernanceService,
    EffectivePermissions,
)
from .registry import ConnectorProviderProtocol, ConnectorRegistry
from .service import ConnectorService, ConnectorServiceError
from .trace import ConnectorExecutionTrace, ConnectorTraceStore

from ..contracts import (
    ArtifactContract,
    ArtifactValidationRule,
    AuditRequirement,
    CapabilityContract,
    ContractRegistry,
    ContractRetryPolicy,
    ContractTimeoutPolicy,
    ContractValidationResult,
    ContractValidator,
    ContractViolation,
    ContractViolationSeverity,
    FailureSemantic,
    LifecycleState,
    ReadWriteClassification,
)

__all__ = [
    # Auth
    "AuthType",
    "ConnectorAuthConfig",
    "ConnectorSessionContext",
    "build_session_context",
    # Models
    "CapabilityType",
    "ConnectorStatus",
    "ConnectorOperationDescriptor",
    "ConnectorProviderDescriptor",
    "ConnectorInvocationRequest",
    "ConnectorInvocationResult",
    "ConnectorCostInfo",
    "ConnectorCostMetadata",
    "ConnectorRetryPolicy",
    "ConnectorRateLimit",
    "ExternalReference",
    "ExternalResourceDescriptor",
    "ExternalArtifact",
    "ConnectorPermissionPolicy",
    "ConnectorConfig",
    # Normalized artifacts
    "NormalizedArtifactBase",
    "SearchResultItem",
    "SearchResultArtifact",
    "DocumentArtifact",
    "MessageArtifact",
    "TicketArtifact",
    "RepositoryArtifact",
    "TelemetryArtifact",
    "IdentityArtifact",
    "get_normalized_type",
    "try_normalize",
    # Registry
    "ConnectorRegistry",
    "ConnectorProviderProtocol",
    # Service
    "ConnectorService",
    "ConnectorServiceError",
    # Discovery
    "ConnectorProviderDiscovery",
    "DiscoveryResult",
    "ProviderLoadError",
    "LazyConnectorProvider",
    "make_lazy_provider",
    # Governance
    "ConnectorGovernanceService",
    "ConnectorGovernanceError",
    "ConnectorDiscoveryItem",
    "EffectivePermissions",
    # Permissions
    "evaluate_permission",
    "evaluate_permission_detailed",
    "PermissionOutcome",
    "PermissionEvaluationResult",
    "ConnectorPermissionError",
    # Trace / Executor
    "ConnectorExecutionTrace",
    "ConnectorTraceStore",
    "ConnectorExecutor",
    "ConnectorExecutorError",
    # Contract framework
    "CapabilityContract",
    "ArtifactContract",
    "ArtifactValidationRule",
    "ContractTimeoutPolicy",
    "ContractRetryPolicy",
    "ContractValidationResult",
    "ContractViolation",
    "ContractViolationSeverity",
    "ReadWriteClassification",
    "AuditRequirement",
    "FailureSemantic",
    "LifecycleState",
    "ContractRegistry",
    "ContractValidator",
]
