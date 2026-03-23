"""Custom exception hierarchy for Studio.

All Studio-specific exceptions inherit from StudioError so callers
can catch broadly or narrowly as needed.
"""


class StudioError(Exception):
    """Base exception for all Studio errors."""


class ConversionError(StudioError):
    """Failed to convert between IR models and runtime ProfileConfig."""


class GenerationError(StudioError):
    """Failed to generate YAML output from IR models."""


class ValidationError(StudioError):
    """Profile validation failed."""


class TemplateImportError(StudioError):
    """Failed to import a profile template from disk."""


class TemplateExportError(StudioError):
    """Failed to export a profile to disk."""


class DeploymentError(StudioError):
    """Failed to deploy a profile to the runtime workspace."""


class ConnectorDiscoveryError(StudioError):
    """Failed to discover connectors from the runtime API."""


class SchemaExtractionError(StudioError):
    """Failed to extract JSON schemas from runtime models."""


class ConditionParseError(StudioError):
    """Failed to parse or build a condition expression."""


class GraphValidationError(StudioError):
    """Workflow graph failed structural validation."""


class ManifestError(StudioError):
    """Error reading or writing the generation manifest."""


class ExtensionStubError(StudioError):
    """Failed to generate an extension stub."""
