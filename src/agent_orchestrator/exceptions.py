"""Custom exceptions for agent-orchestrator.

All domain exceptions inherit from OrchestratorError to enable
catch-all handling while allowing specific exception targeting.
"""


class OrchestratorError(Exception):
    """Base exception for all agent-orchestrator errors."""


class ConfigurationError(OrchestratorError):
    """Invalid or missing configuration."""


class ProfileError(OrchestratorError):
    """Profile-related errors (not found, invalid, switch failure)."""


class ValidationError(OrchestratorError):
    """Cross-reference or schema validation failure."""


class WorkflowError(OrchestratorError):
    """Workflow execution or phase transition error."""


class AgentError(OrchestratorError):
    """Agent creation, execution, or pool error."""


class GovernanceError(OrchestratorError):
    """Policy evaluation or enforcement error."""


class PersistenceError(OrchestratorError):
    """State or config persistence error."""


class WorkItemError(OrchestratorError):
    """Work item creation, submission, or processing error."""
