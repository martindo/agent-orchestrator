"""Agent Orchestrator — Generic agent orchestration & governance platform.

Public SDK surface. App developers should import from this module:

    from agent_orchestrator import OrchestrationEngine, WorkItem, ConfigurationManager
"""

__version__ = "0.1.0"

# ---- Core types ----
from agent_orchestrator.core.engine import EngineState, OrchestrationEngine
from agent_orchestrator.core.event_bus import Event, EventBus, EventType
from agent_orchestrator.core.work_queue import WorkItem, WorkItemHistoryEntry, WorkItemStatus

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
    SLAConfig,
    WorkItemTypeConfig,
)

# ---- Persistence ----
from agent_orchestrator.persistence.lineage import (
    LineageBuilder,
    LineageEvent,
    WorkItemLineage,
)

# ---- Governance ----
from agent_orchestrator.governance.audit_logger import AuditLogger
from agent_orchestrator.governance.governor import (
    GovernanceDecision,
    Governor,
    Resolution,
)

# ---- Knowledge ----
from agent_orchestrator.knowledge import (
    KnowledgeStore,
    MemoryQuery,
    MemoryRecord,
    MemoryType,
)

# ---- Catalog ----
from agent_orchestrator.catalog import (
    CapabilityRegistration,
    InvocationMode,
    MemoryUsagePolicy,
    SecurityClassification,
    TeamRegistry,
)

# ---- Decision Ledger ----
from agent_orchestrator.governance.decision_ledger import (
    DecisionLedger,
    DecisionOutcome,
    DecisionRecord,
    DecisionType,
)

# ---- Skill Map ----
from agent_orchestrator.catalog.skill_map import SkillMap
from agent_orchestrator.catalog.skill_models import (
    SkillCoverage,
    SkillMaturity,
    SkillMetrics,
    SkillRecord,
)

# ---- Simulation ----
from agent_orchestrator.simulation import (
    ComparisonResult,
    SimulationConfig,
    SimulationOutcome,
    SimulationResult,
    SimulationSandbox,
    SimulationStatus,
)
from agent_orchestrator.simulation.models import (
    BenchmarkCase,
    BenchmarkCaseResult,
    BenchmarkRunResult,
    BenchmarkSuiteConfig,
)

# ---- Exceptions ----
from agent_orchestrator.exceptions import (
    AgentError,
    CatalogError,
    ConfigurationError,
    ConnectorError,
    ContractError,
    ContractViolationError,
    GovernanceError,
    KnowledgeError,
    LedgerError,
    OrchestratorError,
    PersistenceError,
    ProfileError,
    SimulationError,
    ValidationError,
    WorkflowError,
    WorkItemError,
    WorkItemValidationError,
)

# ---- MCP (optional — available only if mcp package installed) ----
try:
    from agent_orchestrator.mcp import (
        MCPTransportType,
        MCPServerConfig,
        MCPClientConfig,
        MCPServerHostConfig,
        MCPProfileConfig,
        MCPError,
        MCPConnectionError,
        MCPToolCallError,
        MCPResourceError,
        MCPConfigurationError,
    )
    _MCP_AVAILABLE = True
except ImportError:
    _MCP_AVAILABLE = False

__all__ = [
    # Version
    "__version__",
    # Core
    "OrchestrationEngine",
    "EngineState",
    "WorkItem",
    "WorkItemHistoryEntry",
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
    "SLAConfig",
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
    "WorkItemValidationError",
    "ConnectorError",
    "ContractError",
    "ContractViolationError",
    "CatalogError",
    "LedgerError",
    "SimulationError",
    # Decision Ledger
    "DecisionLedger",
    "DecisionRecord",
    "DecisionType",
    "DecisionOutcome",
    # Skill Map
    "SkillMap",
    "SkillRecord",
    "SkillMetrics",
    "SkillCoverage",
    "SkillMaturity",
    # Simulation
    "SimulationSandbox",
    "SimulationConfig",
    "SimulationResult",
    "SimulationOutcome",
    "SimulationStatus",
    # Lineage
    "LineageBuilder",
    "LineageEvent",
    "WorkItemLineage",
    # Simulation
    "ComparisonResult",
    # Benchmark
    "BenchmarkCase",
    "BenchmarkCaseResult",
    "BenchmarkRunResult",
    "BenchmarkSuiteConfig",
    # Catalog
    "CapabilityRegistration",
    "InvocationMode",
    "MemoryUsagePolicy",
    "SecurityClassification",
    "TeamRegistry",
    # Knowledge
    "KnowledgeStore",
    "MemoryQuery",
    "MemoryRecord",
    "MemoryType",
    "KnowledgeError",
]

if _MCP_AVAILABLE:
    __all__.extend([
        "MCPTransportType",
        "MCPServerConfig",
        "MCPClientConfig",
        "MCPServerHostConfig",
        "MCPProfileConfig",
        "MCPError",
        "MCPConnectionError",
        "MCPToolCallError",
        "MCPResourceError",
        "MCPConfigurationError",
    ])
