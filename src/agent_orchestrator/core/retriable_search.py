"""REMOVED — domain-specific code extracted from platform core.

``RetriableSearchService``, ``UnverifiedClaim``, and ``TargetedQuery`` are
research/fact-checking domain concepts and do not belong in the platform
runtime.  They have been moved to:

    profiles/research-team/retriable_search.py

If you are building a research-domain application and need this service,
copy that file into your application package and import it from there.

To inject equivalent behaviour into the engine, pass a ``phase_context_hook``
callable to ``OrchestrationEngine.__init__``:

    def my_hook(work_item, phase):
        # domain logic here — engine stays agnostic
        return {}

    engine = OrchestrationEngine(config_manager, phase_context_hook=my_hook)
"""

raise ImportError(
    "agent_orchestrator.core.retriable_search has been removed from the platform. "
    "See the module docstring (profiles/research-team/retriable_search.py) for the "
    "migration path."
)
