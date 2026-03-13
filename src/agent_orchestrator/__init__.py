"""Agent Orchestrator — Generic agent orchestration & governance platform.

Public SDK surface. App developers should import from this module:

    from agent_orchestrator import OrchestrationEngine, WorkItem, ConfigurationManager
"""

__version__ = "0.1.0"

# ---- Core types ----
from agent_orchestrator.core.engine import EngineState, OrchestrationEngine
from agent_orchestrator.core.event_bus import Event, EventBus, EventType
from agent_orchestrator.core.work_queue import WorkItem, WorkItemStatus

# ---- Configuration ----
from agent_orchestrator.configuration.loader import ConfigurationManager
from agent_orchestrator.configuration.models import (
    AgentDefinition,
    AppManifest,
    ArtifactTypeConfig,
    ConditionConfig,
    DelegatedAuthorityConfig,
    DeploymentMode,
    ExecutionContext,
    FieldDefinition,
    FieldType,
    GovernanceConfig,
    LLMConfig,
    PolicyConfig,
    ProfileConfig,
    QualityGateConfig,
    RetryPolicy,
    SettingsConfig,
    StatusConfig,
    WorkflowConfig,
    WorkflowPhaseConfig,
    WorkItemTypeConfig,
)

# ---- Governance ----
from agent_orchestrator.governance.audit_logger import AuditLogger
from agent_orchestrator.governance.governor import (
    GovernanceDecision,
    Governor,
    Resolution,
)

# ---- Exceptions ----
from agent_orchestrator.exceptions import (
    AgentError,
    ConfigurationError,
    ConnectorError,
    ContractError,
    ContractViolationError,
    GovernanceError,
    OrchestratorError,
    PersistenceError,
    ProfileError,
    ValidationError,
    WorkflowError,
    WorkItemError,
)

__all__ = [
    # Version
    "__version__",
    # Core
    "OrchestrationEngine",
    "EngineState",
    "WorkItem",
    "WorkItemStatus",
    "EventBus",
    "Event",
    "EventType",
    # Configuration
    "ConfigurationManager",
    "ProfileConfig",
    "AgentDefinition",
    "WorkflowConfig",
    "WorkflowPhaseConfig",
    "LLMConfig",
    "SettingsConfig",
    "GovernanceConfig",
    "DelegatedAuthorityConfig",
    "PolicyConfig",
    "ConditionConfig",
    "QualityGateConfig",
    "RetryPolicy",
    "StatusConfig",
    "WorkItemTypeConfig",
    "ArtifactTypeConfig",
    "FieldDefinition",
    "FieldType",
    "AppManifest",
    "DeploymentMode",
    "ExecutionContext",
    # Governance
    "Governor",
    "GovernanceDecision",
    "Resolution",
    "AuditLogger",
    # Exceptions
    "OrchestratorError",
    "ConfigurationError",
    "ProfileError",
    "ValidationError",
    "WorkflowError",
    "AgentError",
    "GovernanceError",
    "PersistenceError",
    "WorkItemError",
    "ConnectorError",
    "ContractError",
    "ContractViolationError",
]
