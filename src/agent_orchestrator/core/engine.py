"""OrchestrationEngine — Central coordinator for the orchestration platform.

Completely domain-agnostic. Reads user configuration to know what to do.
Coordinates the work queue, pipeline, agent pool, and phase executor.

Thread-safe: Uses asyncio for async coordination, locks for shared state.

State Ownership:
- Engine owns the overall lifecycle (start/stop/pause/resume).
- WorkQueue owns item ordering.
- PipelineManager owns phase positions.
- AgentPool owns agent instances.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import Any

from agent_orchestrator.adapters.llm_adapter import LLMAdapter
from agent_orchestrator.adapters.metrics_adapter import MetricsCollector
from agent_orchestrator.configuration.agent_manager import AgentManager
from agent_orchestrator.configuration.loader import ConfigurationManager
from agent_orchestrator.configuration.models import (
    AgentDefinition,
    ExecutionContext,
    ProfileConfig,
    SettingsConfig,
    WorkflowPhaseConfig,
)
from agent_orchestrator.core.context import create_root_context, create_run_context
from agent_orchestrator.core.agent_executor import AgentExecutor
from agent_orchestrator.core.agent_pool import AgentPool
from agent_orchestrator.core.event_bus import Event, EventBus, EventType
from agent_orchestrator.core.phase_executor import PhaseExecutor
from agent_orchestrator.core.pipeline_manager import (
    PhaseResult,
    PipelineManager,
)
from agent_orchestrator.core.work_queue import WorkItem, WorkItemStatus, WorkQueue
from agent_orchestrator.exceptions import AgentError, OrchestratorError, WorkflowError
from agent_orchestrator.persistence.work_item_store import WorkItemStore
from agent_orchestrator.governance.audit_logger import AuditLogger, RecordType
from agent_orchestrator.governance.decision_ledger import DecisionLedger, DecisionType, DecisionOutcome
from agent_orchestrator.governance.governor import Governor, GovernanceDecision, Resolution
from agent_orchestrator.governance.review_queue import ReviewQueue

logger = logging.getLogger(__name__)

QUEUE_POLL_INTERVAL_SECONDS = 0.5


class EngineState(str, Enum):
    """Lifecycle state of the orchestration engine."""

    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    STOPPED = "stopped"


class OrchestrationEngine:
    """Central coordinator — completely domain-agnostic.

    Reads user config to know what to do. Manages the full lifecycle
    of work item processing through configured workflow phases.

    Thread-safe: Uses asyncio internally, lock for state transitions.

    Usage:
        engine = OrchestrationEngine(config_manager, event_bus)
        await engine.start()
        work_id = await engine.submit_work(work_item)
        await engine.stop()
    """

    def __init__(
        self,
        config_manager: ConfigurationManager,
        event_bus: EventBus | None = None,
        llm_call_fn: Any | None = None,
        phase_context_hook: Callable[["WorkItem", "WorkflowPhaseConfig"], dict[str, Any]] | None = None,
    ) -> None:
        self._config = config_manager
        self._event_bus = event_bus or EventBus()
        self._state = EngineState.IDLE
        self._lock = threading.Lock()
        # Optional domain-supplied hook — called before each phase to inject
        # extra context into phase execution. Domain apps pass their own
        # function here; the engine itself has no knowledge of its contents.
        self._phase_context_hook = phase_context_hook

        # AgentManager for CRUD operations
        self._agent_manager: AgentManager | None = None

        # Governance and observability (initialized on start)
        self._governor: Governor | None = None
        self._review_queue: ReviewQueue | None = None
        self._audit_logger: AuditLogger | None = None
        self._metrics: MetricsCollector | None = None

        # Execution context (initialized on start)
        self._context: ExecutionContext | None = None

        # Components initialized on start()
        self._queue: WorkQueue | None = None
        self._pipeline: PipelineManager | None = None
        self._agent_pool: AgentPool | None = None
        self._phase_executor: PhaseExecutor | None = None
        self._agent_executor: AgentExecutor | None = None
        self._llm_adapter: LLMAdapter | None = None
        self._processing_task: asyncio.Task[None] | None = None
        self._llm_call_fn = llm_call_fn

        # Connector framework (registry created eagerly; service initialized on start)
        from ..connectors.registry import ConnectorRegistry
        from ..connectors.service import ConnectorService
        from ..connectors.governance_service import ConnectorGovernanceService
        from ..connectors.discovery import ConnectorProviderDiscovery, DiscoveryResult
        self._connector_registry: ConnectorRegistry = ConnectorRegistry()
        self._connector_service: ConnectorService | None = None
        self._connector_governance_service: ConnectorGovernanceService = ConnectorGovernanceService(
            self._connector_registry
        )
        self._connector_discovery: ConnectorProviderDiscovery = ConnectorProviderDiscovery(
            self._connector_registry
        )
        self._last_discovery_result: DiscoveryResult | None = None

        # Artifact store (initialized on start)
        self._artifact_store: Any | None = None

        # Work item persistence (initialized on start)
        self._work_item_store: WorkItemStore | None = None

        # Gap detection and agent synthesis
        self._gap_signal_collector: Any | None = None
        self._gap_analyzer: Any | None = None
        self._synthesizer: Any | None = None
        self._detected_gaps: list[Any] = []
        self._gap_lock = threading.Lock()

        # Knowledge store (initialized on start)
        self._knowledge_store: Any | None = None
        self._context_memory: Any | None = None

        # MCP integration (initialized on start if configured)
        self._mcp_client_manager: Any | None = None
        self._mcp_bridge: Any | None = None

        # Capability catalog (created eagerly; auto-registered on start)
        from agent_orchestrator.catalog.registry import TeamRegistry
        self._team_registry: TeamRegistry = TeamRegistry()

        # Decision ledger (initialized on start)
        self._decision_ledger: DecisionLedger | None = None

        # SLA monitor (initialized on start)
        self._sla_monitor: Any | None = None

        # Skill map (initialized on start)
        self._skill_map: Any | None = None

        # Simulation sandbox (created eagerly — stateless)
        from agent_orchestrator.simulation.sandbox import SimulationSandbox
        self._simulation_sandbox: SimulationSandbox = SimulationSandbox()

        # Evaluation stores (initialized on start)
        self._rubric_store: Any | None = None
        self._dataset_store: Any | None = None

    @property
    def state(self) -> EngineState:
        """Current engine state."""
        return self._state

    @property
    def context(self) -> ExecutionContext | None:
        """Current execution context (available after start)."""
        return self._context

    @property
    def event_bus(self) -> EventBus:
        """The engine's event bus."""
        return self._event_bus

    @property
    def llm_adapter(self) -> LLMAdapter | None:
        """The engine's LLM adapter (available after start)."""
        return self._llm_adapter

    @property
    def active_profile(self) -> ProfileConfig | None:
        """The currently loaded profile (available after start)."""
        try:
            return self._config.get_profile()
        except Exception:
            return None

    async def start(self) -> None:
        """Start the orchestration engine.

        Loads configuration, initializes components, and begins
        processing work items from the queue.

        Raises:
            OrchestratorError: If engine is already running.
        """
        with self._lock:
            if self._state not in (EngineState.IDLE, EngineState.STOPPED):
                msg = f"Cannot start engine in state '{self._state.value}'"
                raise OrchestratorError(msg)
            self._state = EngineState.STARTING

        logger.info("Starting orchestration engine")

        try:
            self._config.load()
            profile = self._config.get_profile()
            settings = self._config.get_settings()
            self._context = create_root_context(settings, profile.name)
            self._initialize_components(profile)

            with self._lock:
                self._state = EngineState.RUNNING

            # Initialize MCP client if configured
            await self._initialize_mcp(profile)

            self._processing_task = asyncio.create_task(self._processing_loop())

            # Start SLA monitor
            await self._start_sla_monitor()

            await self._event_bus.emit(Event(
                type=EventType.SYSTEM_STARTED,
                data={"profile": profile.name},
                source="engine",
            ))

            if self._audit_logger is not None:
                self._audit_logger.append(
                    RecordType.SYSTEM_EVENT,
                    "engine.start",
                    f"Engine started with profile '{profile.name}'",
                )

            logger.info("Engine started with profile '%s'", profile.name)
        except Exception as e:
            with self._lock:
                self._state = EngineState.STOPPED
            logger.error("Engine failed to start: %s", e, exc_info=True)
            raise

    def _initialize_components(self, profile: ProfileConfig) -> None:
        """Initialize all engine components from profile config."""
        self._queue = WorkQueue()
        self._pipeline = PipelineManager(profile.workflow)
        self._agent_pool = AgentPool()
        self._agent_pool.register_definitions(
            [a for a in profile.agents if a.enabled],
        )
        # Build LLM adapter with real providers when no explicit callback given
        if self._llm_call_fn is None:
            settings = self._config.get_settings()
            self._llm_adapter = LLMAdapter(settings)
            self._register_providers(self._llm_adapter, settings)
            self._agent_executor = AgentExecutor(llm_call_fn=self._llm_adapter.call)
        else:
            self._llm_adapter = None
            self._agent_executor = AgentExecutor(llm_call_fn=self._llm_call_fn)

        # Initialize artifact store
        try:
            from agent_orchestrator.persistence.artifact_store import ArtifactStore
            self._artifact_store = ArtifactStore(state_dir)
        except Exception:
            logger.debug("Artifact store initialization failed — continuing without it", exc_info=True)
            self._artifact_store = None

        self._phase_executor = PhaseExecutor(
            agent_pool=self._agent_pool,
            agent_executor=self._agent_executor,
            event_bus=self._event_bus,
            artifact_store=self._artifact_store,
        )
        self._agent_manager = AgentManager(self._config)

        # Governance and observability
        self._governor = Governor(profile.governance)
        self._review_queue = ReviewQueue()
        state_dir = self._config.workspace_dir / ".state"
        state_dir.mkdir(parents=True, exist_ok=True)
        self._audit_logger = AuditLogger(state_dir / "audit")
        self._metrics = MetricsCollector(state_dir / "metrics.jsonl")

        # Work item persistence
        workspace_str = str(self._config.workspace_dir)
        self._work_item_store = WorkItemStore(workspace_path=workspace_str)

        # Connector service — wires registry to audit logger and metrics
        from ..connectors.service import ConnectorService
        self._connector_service = ConnectorService(
            registry=self._connector_registry,
            audit_logger=self._audit_logger,
            metrics=self._metrics,
        )
        logger.info("Connector service initialized")

        # Auto-discover and register builtin connector providers
        self._last_discovery_result = self._connector_discovery.discover_builtin_providers()
        logger.info("Provider auto-discovery complete: %s", self._last_discovery_result.summary())

        # Knowledge store
        self._initialize_knowledge_store(state_dir)

        # Gap detection and agent synthesis
        self._initialize_gap_detection(profile)

        # Auto-register profile as a discoverable capability
        reg_settings = settings if self._llm_call_fn is None else self._config.get_settings()
        self._auto_register_capability(profile, reg_settings)

        # Decision ledger (cryptographic chain of trust)
        self._initialize_decision_ledger(state_dir)

        # Skill map (organizational capability registry)
        self._initialize_skill_map(state_dir, profile)

        # Evaluation stores (rubrics and datasets)
        self._initialize_eval_stores(state_dir)

    def _initialize_eval_stores(self, state_dir: Path) -> None:
        """Initialize evaluation rubric and dataset stores.

        Args:
            state_dir: State directory for persistence.
        """
        try:
            from agent_orchestrator.simulation.rubric_store import RubricStore
            self._rubric_store = RubricStore(state_dir / "rubrics")
            logger.info("Rubric store initialized at %s", state_dir / "rubrics")
        except Exception:
            logger.debug(
                "Rubric store initialization failed — continuing without it",
                exc_info=True,
            )
            self._rubric_store = None

        try:
            from agent_orchestrator.simulation.dataset import DatasetStore
            self._dataset_store = DatasetStore(state_dir / "datasets")
            logger.info("Dataset store initialized at %s", state_dir / "datasets")
        except Exception:
            logger.debug(
                "Dataset store initialization failed — continuing without it",
                exc_info=True,
            )
            self._dataset_store = None

    async def _initialize_mcp(self, profile: ProfileConfig) -> None:
        """Initialize MCP client manager and bridge if configured."""
        mcp_config = getattr(profile, "mcp", None)
        if mcp_config is None:
            return

        try:
            from agent_orchestrator.mcp.models import MCPProfileConfig
            if not isinstance(mcp_config, MCPProfileConfig):
                return

            client_config = mcp_config.client
            if not client_config.servers:
                return

            from agent_orchestrator.mcp.client_manager import MCPClientManager
            from agent_orchestrator.mcp.bridge import MCPConnectorBridge

            self._mcp_client_manager = MCPClientManager(client_config)
            connect_results = await self._mcp_client_manager.connect_all()
            logger.info("MCP client connections: %s", connect_results)

            self._mcp_bridge = MCPConnectorBridge(
                client_manager=self._mcp_client_manager,
                registry=self._connector_registry,
                config=client_config,
            )
            tool_counts = await self._mcp_bridge.register_all_tools()
            logger.info("MCP tools registered: %s", tool_counts)
        except ImportError:
            logger.debug("MCP package not installed — skipping MCP initialization")
        except Exception:
            logger.warning("MCP initialization failed", exc_info=True)

    @property
    def mcp_client_manager(self) -> Any | None:
        """The engine's MCP client manager (available after start if configured)."""
        return self._mcp_client_manager

    @staticmethod
    def _register_providers(adapter: LLMAdapter, settings: SettingsConfig) -> None:
        """Auto-register LLM providers based on available API keys and endpoints."""
        _provider_map: dict[str, tuple[str, str]] = {
            "openai": (
                "agent_orchestrator.adapters.providers.openai_provider",
                "OpenAIProvider",
            ),
            "anthropic": (
                "agent_orchestrator.adapters.providers.anthropic_provider",
                "AnthropicProvider",
            ),
            "google": (
                "agent_orchestrator.adapters.providers.google_provider",
                "GoogleProvider",
            ),
            "grok": (
                "agent_orchestrator.adapters.providers.grok_provider",
                "GrokProvider",
            ),
        }
        import importlib

        for name, (mod_path, cls_name) in _provider_map.items():
            key = settings.api_keys.get(name)
            if not key:
                continue
            try:
                mod = importlib.import_module(mod_path)
                cls = getattr(mod, cls_name)
                adapter.register_provider(name, cls(api_key=key))
            except ImportError:
                logger.warning(
                    "SDK for provider '%s' not installed — skipping", name,
                )

        # Ollama (no API key, uses endpoint)
        ollama_endpoint = (
            os.environ.get("OLLAMA_ENDPOINT")
            or settings.llm_endpoints.get("ollama")
            or "http://localhost:11434"
        )
        try:
            from agent_orchestrator.adapters.providers.ollama_provider import (
                OllamaProvider,
            )

            adapter.register_provider("ollama", OllamaProvider(endpoint=ollama_endpoint))
        except ImportError:
            logger.warning("httpx not installed — Ollama provider unavailable")

    async def stop(self) -> None:
        """Stop the orchestration engine gracefully.

        Cancels the processing loop and shuts down agent pool.
        """
        with self._lock:
            if self._state not in (EngineState.RUNNING, EngineState.PAUSED):
                logger.warning("Engine not running, nothing to stop")
                return
            self._state = EngineState.STOPPING

        logger.info("Stopping orchestration engine")

        # Disconnect MCP clients
        if self._mcp_client_manager is not None:
            try:
                await self._mcp_client_manager.disconnect_all()
            except Exception:
                logger.debug("Error disconnecting MCP clients", exc_info=True)
            self._mcp_client_manager = None
            self._mcp_bridge = None

        # Stop SLA monitor
        if self._sla_monitor is not None:
            try:
                await self._sla_monitor.stop()
            except Exception:
                logger.debug("Error stopping SLA monitor", exc_info=True)
            self._sla_monitor = None

        if self._processing_task is not None:
            self._processing_task.cancel()
            try:
                await self._processing_task
            except asyncio.CancelledError:
                pass

        if self._agent_pool is not None:
            self._agent_pool.shutdown()

        with self._lock:
            self._state = EngineState.STOPPED

        await self._event_bus.emit(Event(
            type=EventType.SYSTEM_STOPPED,
            source="engine",
        ))

        if self._audit_logger is not None:
            self._audit_logger.append(
                RecordType.SYSTEM_EVENT,
                "engine.stop",
                "Engine stopped",
            )

        logger.info("Engine stopped")

    async def pause(self) -> None:
        """Pause work item processing."""
        with self._lock:
            if self._state != EngineState.RUNNING:
                return
            self._state = EngineState.PAUSED
        logger.info("Engine paused")

    async def resume(self) -> None:
        """Resume work item processing."""
        with self._lock:
            if self._state != EngineState.PAUSED:
                return
            self._state = EngineState.RUNNING
        logger.info("Engine resumed")

    async def submit_work(self, work_item: WorkItem) -> str:
        """Submit a work item for processing.

        Args:
            work_item: The work item to process.

        Returns:
            The work item ID.

        Raises:
            OrchestratorError: If engine not running.
        """
        if self._state not in (EngineState.RUNNING, EngineState.PAUSED):
            msg = f"Cannot submit work — engine is '{self._state.value}'"
            raise OrchestratorError(msg)

        if self._queue is None:
            msg = "Engine queue not initialized"
            raise OrchestratorError(msg)

        # Assign run identity from execution context
        if self._context is not None:
            run_ctx = create_run_context(self._context)
            work_item.run_id = run_ctx.run_id
            work_item.app_id = run_ctx.app_id

        # Apply SLA defaults from WorkItemTypeConfig
        self._apply_sla_defaults(work_item)

        await self._queue.push(work_item)
        self._persist_work_item(work_item)

        await self._event_bus.emit(Event(
            type=EventType.WORK_SUBMITTED,
            data={"work_id": work_item.id, "type": work_item.type_id},
            source="engine",
            app_id=work_item.app_id,
            run_id=work_item.run_id,
        ))
        logger.info("Work item '%s' submitted (run_id=%s)", work_item.id, work_item.run_id)
        return work_item.id

    async def _processing_loop(self) -> None:
        """Main loop — pulls items from queue and processes through pipeline."""
        logger.debug("Processing loop started")
        while True:
            if self._state == EngineState.PAUSED:
                await asyncio.sleep(QUEUE_POLL_INTERVAL_SECONDS)
                continue

            if self._state not in (EngineState.RUNNING,):
                break

            try:
                await self._resume_reviewed_items()
                item = await self._queue.pop(timeout=QUEUE_POLL_INTERVAL_SECONDS)  # type: ignore[union-attr]
                if item is not None:
                    await self._process_work_item(item)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("Processing loop error: %s", e, exc_info=True)
                await self._event_bus.emit(Event(
                    type=EventType.SYSTEM_ERROR,
                    data={"error": str(e)},
                    source="engine",
                ))

    async def _process_work_item(self, work_item: WorkItem) -> None:
        """Process a single work item through the pipeline."""
        if self._pipeline is None or self._phase_executor is None:
            return

        logger.info("Processing work item '%s' (run_id=%s)", work_item.id, work_item.run_id)

        # Reconstruct run context from work item identity
        run_context: ExecutionContext | None = None
        if self._context is not None:
            run_context = create_run_context(self._context, run_id=work_item.run_id)

        _app_id = work_item.app_id
        _run_id = work_item.run_id

        await self._event_bus.emit(Event(
            type=EventType.WORK_STARTED,
            data={"work_id": work_item.id},
            source="engine",
            app_id=_app_id,
            run_id=_run_id,
        ))

        if self._audit_logger is not None:
            self._audit_logger.append(
                RecordType.STATE_CHANGE,
                "work.started",
                f"Work item '{work_item.id}' processing started",
                work_id=work_item.id,
                app_id=_app_id,
                run_id=_run_id,
            )

        try:
            phase_id = self._pipeline.enter_pipeline(work_item)
        except WorkflowError as e:
            logger.error("Failed to enter pipeline: %s", e, exc_info=True)
            work_item.record_transition(WorkItemStatus.FAILED, reason=str(e))
            work_item.error = str(e)
            self._persist_work_item(work_item)
            if self._audit_logger is not None:
                self._audit_logger.append(
                    RecordType.ERROR,
                    "pipeline.entry_failed",
                    str(e),
                    work_id=work_item.id,
                    app_id=_app_id,
                    run_id=_run_id,
                )
            return

        # Process through phases until complete or terminal
        while phase_id is not None:
            phase = self._pipeline.get_current_phase(work_item.id)
            if phase is None:
                break

            if phase.is_terminal:
                work_item.record_transition(
                    WorkItemStatus.COMPLETED,
                    phase_id=phase.id,
                    reason="terminal phase reached",
                )
                self._persist_work_item(work_item)
                break

            # Pre-execution governance check — use accumulated confidence
            # from prior phase results, or 0.5 for the first phase
            _prior_confidence = self._extract_prior_confidence(work_item)
            if self._governor is not None:
                decision = self._governor.evaluate(
                    {"confidence": _prior_confidence, "work_type": work_item.type_id, "phase": phase.id},
                    work_type=work_item.type_id,
                )

                # Record pre-execution governance decision in ledger
                self._record_governance_decision(
                    decision, work_item, phase.id, _run_id, _app_id,
                    stage="pre_execution",
                )

                if decision.resolution == Resolution.ABORT:
                    logger.warning(
                        "Governance ABORT for '%s' at phase '%s': %s",
                        work_item.id, phase.id, decision.reason,
                    )
                    work_item.record_transition(
                        WorkItemStatus.FAILED,
                        phase_id=phase.id,
                        reason=f"Governance abort: {decision.reason}",
                    )
                    work_item.error = f"Governance abort: {decision.reason}"
                    self._persist_work_item(work_item)
                    if self._audit_logger is not None:
                        self._audit_logger.append(
                            RecordType.DECISION,
                            "governance.abort",
                            decision.reason,
                            work_id=work_item.id,
                            data={"phase": phase.id, "confidence": decision.confidence},
                            app_id=_app_id,
                            run_id=_run_id,
                        )
                    await self._event_bus.emit(Event(
                        type=EventType.WORK_FAILED,
                        data={"work_id": work_item.id, "error": work_item.error},
                        source="engine",
                        app_id=_app_id,
                        run_id=_run_id,
                    ))
                    return

                if decision.resolution == Resolution.QUEUE_FOR_REVIEW:
                    if self._review_queue is not None:
                        review_id = self._review_queue.enqueue(
                            work_id=work_item.id,
                            phase_id=phase.id,
                            reason=decision.reason,
                            decision_data={"confidence": decision.confidence},
                        )
                        work_item.metadata["pending_review_id"] = review_id
                    if self._audit_logger is not None:
                        self._audit_logger.append(
                            RecordType.ESCALATION,
                            "governance.review_queued",
                            decision.reason,
                            work_id=work_item.id,
                            data={"phase": phase.id},
                            app_id=_app_id,
                            run_id=_run_id,
                        )
                    await self._event_bus.emit(Event(
                        type=EventType.GOVERNANCE_ESCALATION,
                        data={
                            "work_id": work_item.id,
                            "phase_id": phase.id,
                            "review_id": work_item.metadata.get("pending_review_id", ""),
                            "reason": decision.reason,
                        },
                        source="engine",
                        app_id=_app_id,
                        run_id=_run_id,
                    ))

            # Lock for execution
            if not self._pipeline.lock_for_execution(work_item.id, "engine"):
                logger.warning("Could not lock work item '%s'", work_item.id)
                break

            import time
            phase_start = time.monotonic()

            try:
                # Ask the domain-supplied hook (if any) for extra phase context.
                # The engine treats the returned dict as opaque — it is passed
                # straight through to the phase executor unchanged.
                phase_context: dict[str, Any] = {}
                if self._phase_context_hook is not None:
                    phase_context = self._phase_context_hook(work_item, phase)
                    if phase_context:
                        logger.debug(
                            "Phase context hook returned %d keys for work item %s phase %s",
                            len(phase_context),
                            work_item.id,
                            phase.id,
                        )

                # Inject relevant knowledge into phase context
                if self._knowledge_store is not None:
                    knowledge_ctx = self._build_knowledge_context(work_item, phase)
                    if knowledge_ctx:
                        phase_context["knowledge"] = knowledge_ctx

                result = await self._phase_executor.execute_phase(
                    phase, work_item, phase_context or None, context=run_context,
                )

                # Record agent execution decision in ledger
                phase_elapsed = time.monotonic() - phase_start
                self._record_execution_decision(
                    work_item, phase.id, result, phase_elapsed, _run_id, _app_id,
                )

                # Post-execution governance check with real confidence
                if self._governor is not None and result.success:
                    post_decision = self._governor.evaluate(
                        {
                            "confidence": result.aggregate_confidence,
                            "work_type": work_item.type_id,
                            "phase": phase.id,
                        },
                        work_type=work_item.type_id,
                    )
                    # Record post-execution governance decision in ledger
                    self._record_governance_decision(
                        post_decision, work_item, phase.id, _run_id, _app_id,
                        stage="post_execution",
                    )

                    if post_decision.resolution == Resolution.ABORT:
                        logger.warning(
                            "Post-execution governance ABORT for '%s' at phase '%s' (confidence=%.2f)",
                            work_item.id, phase.id, result.aggregate_confidence,
                        )
                        work_item.record_transition(
                            WorkItemStatus.FAILED,
                            phase_id=phase.id,
                            reason=f"Post-execution governance abort: {post_decision.reason}",
                        )
                        work_item.error = f"Post-execution governance abort: {post_decision.reason}"
                        self._persist_work_item(work_item)
                        if self._audit_logger is not None:
                            self._audit_logger.append(
                                RecordType.DECISION,
                                "governance.post_execution_abort",
                                post_decision.reason,
                                work_id=work_item.id,
                                data={"phase": phase.id, "confidence": result.aggregate_confidence},
                                app_id=_app_id,
                                run_id=_run_id,
                            )
                        break
                    if post_decision.resolution == Resolution.QUEUE_FOR_REVIEW:
                        if self._review_queue is not None:
                            review_id = self._review_queue.enqueue(
                                work_id=work_item.id,
                                phase_id=phase.id,
                                reason=post_decision.reason,
                                decision_data={"confidence": result.aggregate_confidence},
                            )
                            work_item.metadata["pending_review_id"] = review_id
                        if self._audit_logger is not None:
                            self._audit_logger.append(
                                RecordType.ESCALATION,
                                "governance.post_execution_review",
                                post_decision.reason,
                                work_id=work_item.id,
                                data={"phase": phase.id, "confidence": result.aggregate_confidence},
                                app_id=_app_id,
                                run_id=_run_id,
                            )
                        await self._event_bus.emit(Event(
                            type=EventType.GOVERNANCE_ESCALATION,
                            data={
                                "work_id": work_item.id,
                                "phase_id": phase.id,
                                "review_id": work_item.metadata.get("pending_review_id", ""),
                                "reason": post_decision.reason,
                            },
                            source="engine",
                            app_id=_app_id,
                            run_id=_run_id,
                        ))

                phase_result = PhaseResult.SUCCESS if result.success else PhaseResult.FAILURE
                phase_id = self._pipeline.complete_phase(
                    work_item.id, phase_result, {"agent_results": len(result.agent_results)},
                )

                # Record phase duration metric
                if self._metrics is not None:
                    elapsed = time.monotonic() - phase_start
                    self._metrics.record(
                        "phase.duration_seconds",
                        elapsed,
                        tags={"phase": phase.id, "work_id": work_item.id, "app_id": _app_id, "run_id": _run_id},
                    )
                    self._metrics.increment(
                        "phase.completed",
                        tags={"phase": phase.id, "result": phase_result.value, "app_id": _app_id, "run_id": _run_id},
                    )

            except Exception as e:
                logger.error(
                    "Phase execution error for '%s': %s",
                    work_item.id, e, exc_info=True,
                )
                self._pipeline.unlock(work_item.id)
                work_item.record_transition(
                    WorkItemStatus.FAILED,
                    phase_id=phase.id,
                    reason=str(e),
                )
                work_item.error = str(e)
                self._persist_work_item(work_item)
                if self._audit_logger is not None:
                    self._audit_logger.append(
                        RecordType.ERROR,
                        "phase.execution_error",
                        str(e),
                        work_id=work_item.id,
                        data={"phase": phase.id},
                        app_id=_app_id,
                        run_id=_run_id,
                    )
                break

        # Record work completion/failure in decision ledger
        self._record_completion_decision(work_item, _run_id, _app_id)

        # Emit completion event and record audit
        if work_item.status == WorkItemStatus.COMPLETED:
            await self._event_bus.emit(Event(
                type=EventType.WORK_COMPLETED,
                data={"work_id": work_item.id},
                source="engine",
                app_id=_app_id,
                run_id=_run_id,
            ))
            if self._audit_logger is not None:
                self._audit_logger.append(
                    RecordType.STATE_CHANGE,
                    "work.completed",
                    f"Work item '{work_item.id}' completed",
                    work_id=work_item.id,
                    app_id=_app_id,
                    run_id=_run_id,
                )
            if self._metrics is not None:
                self._metrics.increment("work.completed", tags={"app_id": _app_id, "run_id": _run_id})
        elif work_item.status == WorkItemStatus.FAILED:
            await self._event_bus.emit(Event(
                type=EventType.WORK_FAILED,
                data={"work_id": work_item.id, "error": work_item.error},
                source="engine",
                app_id=_app_id,
                run_id=_run_id,
            ))
            if self._audit_logger is not None:
                self._audit_logger.append(
                    RecordType.STATE_CHANGE,
                    "work.failed",
                    f"Work item '{work_item.id}' failed: {work_item.error}",
                    work_id=work_item.id,
                    app_id=_app_id,
                    run_id=_run_id,
                )
            if self._metrics is not None:
                self._metrics.increment("work.failed", tags={"app_id": _app_id, "run_id": _run_id})

    async def _resume_reviewed_items(self) -> None:
        """Check for completed reviews and resubmit or fail work items."""
        if self._review_queue is None or self._queue is None:
            return

        completed = self._review_queue.get_completed()
        for review_item in completed:
            # Find the work item with this pending review
            work_item = None
            if self._work_item_store is not None:
                try:
                    work_item = self._work_item_store.get(review_item.work_id)
                except Exception:
                    pass

            if work_item is None:
                continue

            pending_id = work_item.metadata.get("pending_review_id")
            if pending_id != review_item.id:
                continue

            # Clear the pending review marker
            work_item.metadata.pop("pending_review_id", None)

            if review_item.decision == "approved":
                logger.info(
                    "Review %s approved — resubmitting work item %s",
                    review_item.id, work_item.id,
                )
                await self._queue.push(work_item)
                await self._event_bus.emit(Event(
                    type=EventType.GOVERNANCE_REVIEW_COMPLETED,
                    data={
                        "work_id": work_item.id,
                        "review_id": review_item.id,
                        "decision": "approved",
                    },
                    source="engine",
                ))
            elif review_item.decision == "rejected":
                logger.info(
                    "Review %s rejected — failing work item %s",
                    review_item.id, work_item.id,
                )
                work_item.record_transition(
                    WorkItemStatus.FAILED,
                    reason=f"Review rejected: {review_item.review_notes}",
                )
                work_item.error = f"Review rejected: {review_item.review_notes}"
                self._persist_work_item(work_item)
                await self._event_bus.emit(Event(
                    type=EventType.GOVERNANCE_REVIEW_COMPLETED,
                    data={
                        "work_id": work_item.id,
                        "review_id": review_item.id,
                        "decision": "rejected",
                    },
                    source="engine",
                ))

    def _persist_work_item(self, work_item: WorkItem) -> None:
        """Persist a work item snapshot to the store (if initialized)."""
        if self._work_item_store is not None:
            try:
                self._work_item_store.save(work_item)
            except Exception as e:
                logger.error("Failed to persist work item '%s': %s", work_item.id, e, exc_info=True)

    @staticmethod
    def _extract_prior_confidence(work_item: WorkItem) -> float:
        """Extract confidence from prior phase results, or 0.5 if none."""
        from agent_orchestrator.core.output_parser import (
            aggregate_confidence,
            extract_confidence,
        )
        scores: list[float] = []
        for _agent_id, output in work_item.results.items():
            if isinstance(output, dict):
                scores.append(extract_confidence(output))
        return aggregate_confidence(scores)

    async def reload_config(self) -> None:
        """Hot-reload configuration from disk."""
        logger.info("Reloading configuration")
        self._config.reload()
        profile = self._config.get_profile()

        # Re-register agent definitions
        if self._agent_pool is not None:
            self._agent_pool.register_definitions(
                [a for a in profile.agents if a.enabled],
            )

        # Update pipeline with new workflow
        if self._pipeline is not None:
            self._pipeline = PipelineManager(profile.workflow)

        # Re-run static gap detection on reloaded profile
        with self._gap_lock:
            self._detected_gaps = [
                g for g in self._detected_gaps
                if not g.gap_source.value.startswith("static_")
            ]
        self._run_static_gap_detection(profile)

        await self._event_bus.emit(Event(
            type=EventType.CONFIG_RELOADED,
            data={"profile": profile.name},
            source="engine",
        ))

    @property
    def agent_manager(self) -> AgentManager | None:
        """The engine's agent manager, if initialized."""
        return self._agent_manager

    @property
    def governor(self) -> Governor | None:
        """The engine's governor, if initialized."""
        return self._governor

    @property
    def review_queue(self) -> ReviewQueue | None:
        """The engine's review queue, if initialized."""
        return self._review_queue

    @property
    def audit_logger(self) -> AuditLogger | None:
        """The engine's audit logger, if initialized."""
        return self._audit_logger

    @property
    def metrics(self) -> MetricsCollector | None:
        """The engine's metrics collector, if initialized."""
        return self._metrics

    @property
    def connector_service(self) -> "ConnectorService | None":
        """The engine's connector service (available after start)."""
        return self._connector_service

    @property
    def connector_governance_service(self) -> "ConnectorGovernanceService":
        """The engine's connector governance service (available immediately)."""
        return self._connector_governance_service

    @property
    def connector_discovery(self) -> "ConnectorProviderDiscovery":
        """The engine's provider discovery service (available immediately)."""
        return self._connector_discovery

    @property
    def team_registry(self) -> "TeamRegistry":
        """The engine's capability/team registry (available immediately)."""
        return self._team_registry

    @property
    def work_item_store(self) -> WorkItemStore | None:
        """The engine's work item persistence store (available after start)."""
        return self._work_item_store

    @property
    def artifact_store(self) -> Any | None:
        """The engine's artifact store (available after start)."""
        return self._artifact_store

    @property
    def decision_ledger(self) -> DecisionLedger | None:
        """The engine's cryptographic decision ledger (available after start)."""
        return self._decision_ledger

    @property
    def skill_map(self) -> Any | None:
        """The engine's organizational skill map (available after start)."""
        return self._skill_map

    @property
    def simulation_sandbox(self) -> "SimulationSandbox":
        """The engine's simulation sandbox (available immediately)."""
        return self._simulation_sandbox

    @property
    def rubric_store(self) -> Any | None:
        """The engine's evaluation rubric store (available after start)."""
        return self._rubric_store

    @property
    def dataset_store(self) -> Any | None:
        """The engine's evaluation dataset store (available after start)."""
        return self._dataset_store

    @property
    def knowledge_store(self) -> Any | None:
        """The engine's knowledge store (available after start)."""
        return self._knowledge_store

    @property
    def context_memory(self) -> Any | None:
        """The engine's context memory (available after start)."""
        return self._context_memory

    @property
    def last_discovery_result(self) -> "DiscoveryResult | None":
        """Result of the most recent provider discovery pass."""
        return self._last_discovery_result

    @property
    def detected_gaps(self) -> list[Any]:
        """All detected capability gaps (static + runtime)."""
        with self._gap_lock:
            return list(self._detected_gaps)

    def _initialize_decision_ledger(self, state_dir: Path) -> None:
        """Initialize the cryptographic decision ledger.

        Args:
            state_dir: State directory for persistence.
        """
        try:
            from agent_orchestrator.governance.decision_ledger import DecisionLedger
            self._decision_ledger = DecisionLedger(state_dir / "decisions")
            logger.info("Decision ledger initialized at %s", state_dir / "decisions")
        except Exception:
            logger.debug(
                "Decision ledger initialization failed — continuing without it",
                exc_info=True,
            )
            self._decision_ledger = None

    def _initialize_skill_map(
        self, state_dir: Path, profile: ProfileConfig,
    ) -> None:
        """Initialize the organizational skill map and auto-register skills.

        Args:
            state_dir: State directory for persistence.
            profile: The active profile for auto-registration.
        """
        try:
            from agent_orchestrator.catalog.skill_map import SkillMap
            self._skill_map = SkillMap(state_dir / "skills")
            registered = self._skill_map.auto_register_from_profile(
                profile.agents, profile.workflow.phases,
            )
            if registered > 0:
                logger.info("Auto-registered %d skills from profile", registered)
            logger.info("Skill map initialized at %s", state_dir / "skills")
        except Exception:
            logger.debug(
                "Skill map initialization failed — continuing without it",
                exc_info=True,
            )
            self._skill_map = None

    def _auto_register_capability(
        self, profile: ProfileConfig, settings: SettingsConfig,
    ) -> None:
        """Auto-register the active profile as a discoverable capability.

        Args:
            profile: The loaded profile configuration.
            settings: The workspace-level settings.
        """
        try:
            from agent_orchestrator.catalog.auto_register import (
                build_registration_from_profile,
            )
            registration = build_registration_from_profile(profile, settings)
            self._team_registry.register(registration)
            logger.info(
                "Auto-registered capability: %s", registration.capability_id,
            )
        except Exception:
            logger.warning(
                "Capability auto-registration failed — continuing without it",
                exc_info=True,
            )

    def _initialize_gap_detection(self, profile: ProfileConfig) -> None:
        """Initialize gap detection subsystem and run static analysis."""
        try:
            from agent_orchestrator.core.gap_detector import (
                GapAnalyzer,
                GapDetectionThresholds,
                GapSignalCollector,
            )
            from agent_orchestrator.core.agent_synthesizer import AgentSynthesizer

            # Runtime signal collector — subscribes to events
            self._gap_signal_collector = GapSignalCollector(
                event_bus=self._event_bus,
            )

            # Gap analyzer with default thresholds
            self._gap_analyzer = GapAnalyzer(GapDetectionThresholds())

            # Wire GAP_DETECTED listener to accumulate gaps
            self._event_bus.subscribe(
                EventType.GAP_DETECTED,
                self._on_gap_detected,
            )

            # Wire phase exit to run analysis
            self._event_bus.subscribe(
                EventType.WORK_PHASE_EXITED,
                self._on_phase_exited_analyze_gaps,
            )

            # Agent synthesizer — uses LLM adapter if available
            llm_fn = self._llm_adapter.call if self._llm_adapter is not None else self._llm_call_fn
            self._synthesizer = AgentSynthesizer(llm_call_fn=llm_fn)

            # Run static gap detection on current profile
            self._run_static_gap_detection(profile)

            logger.info("Gap detection subsystem initialized")
        except ImportError:
            logger.debug("Gap detection module not available", exc_info=True)
        except Exception:
            logger.warning("Failed to initialize gap detection", exc_info=True)

    def _run_static_gap_detection(self, profile: ProfileConfig) -> None:
        """Run static capability gap detection on the current profile."""
        from agent_orchestrator.core.gap_detector import (
            CapabilityGap,
            GapSeverity,
            GapSource,
        )
        from datetime import datetime, timezone
        from uuid import uuid4

        agent_map = {a.id: a for a in profile.agents if a.enabled}

        for phase in profile.workflow.phases:
            if phase.is_terminal or phase.skip:
                continue

            phase_skills: set[str] = set()
            for agent_id in phase.agents:
                agent = agent_map.get(agent_id)
                if agent is not None:
                    phase_skills.update(agent.skills)

            # Check required capabilities
            if phase.required_capabilities:
                missing = set(phase.required_capabilities) - phase_skills
                if missing:
                    gap = CapabilityGap(
                        id=f"gap-static-skill-{phase.id}-{uuid4().hex[:8]}",
                        phase_id=phase.id,
                        agent_id=None,
                        gap_source=GapSource.STATIC_SKILL_MISMATCH,
                        severity=GapSeverity.WARNING,
                        description=(
                            f"Phase '{phase.id}' requires capabilities "
                            f"{sorted(missing)} not provided by any assigned agent"
                        ),
                        evidence={
                            "required": sorted(phase.required_capabilities),
                            "available": sorted(phase_skills),
                            "missing": sorted(missing),
                        },
                        suggested_capabilities=sorted(missing),
                        detected_at=datetime.now(timezone.utc),
                    )
                    with self._gap_lock:
                        self._detected_gaps.append(gap)

            # Check empty phases
            if not phase.agents and not phase.skippable:
                gap = CapabilityGap(
                    id=f"gap-static-uncovered-{phase.id}-{uuid4().hex[:8]}",
                    phase_id=phase.id,
                    agent_id=None,
                    gap_source=GapSource.STATIC_UNCOVERED_PHASE,
                    severity=GapSeverity.CRITICAL,
                    description=f"Phase '{phase.id}' has no agents assigned",
                    evidence={"phase_agents": [], "skippable": False},
                    suggested_capabilities=list(phase.required_capabilities),
                    detected_at=datetime.now(timezone.utc),
                )
                with self._gap_lock:
                    self._detected_gaps.append(gap)

    async def _on_gap_detected(self, event: Event) -> None:
        """Handle GAP_DETECTED events by storing the gap."""
        gap = event.data.get("gap")
        if gap is not None:
            with self._gap_lock:
                self._detected_gaps.append(gap)
            logger.info("Gap detected: %s (phase=%s)", gap.id, gap.phase_id)

    async def _on_phase_exited_analyze_gaps(self, event: Event) -> None:
        """After a phase exits, run gap analysis on accumulated signals."""
        if self._gap_signal_collector is None or self._gap_analyzer is None:
            return
        windows = self._gap_signal_collector.get_windows()
        run_id = event.run_id
        new_gaps = self._gap_analyzer.analyze(windows, run_id=run_id)
        for gap in new_gaps:
            await self._event_bus.emit(Event(
                type=EventType.GAP_DETECTED,
                data={"gap": gap},
                source="gap_analyzer",
                run_id=run_id,
            ))

    def _initialize_knowledge_store(self, state_dir: Path) -> None:
        """Initialize the knowledge store and subscribe extraction handlers."""
        try:
            from agent_orchestrator.knowledge.store import KnowledgeStore
            from agent_orchestrator.knowledge.context_memory import ContextMemory
            self._knowledge_store = KnowledgeStore(state_dir)
            self._context_memory = ContextMemory(self._knowledge_store)

            # Subscribe auto-extraction handlers
            self._event_bus.subscribe(
                EventType.AGENT_COMPLETED,
                self._extract_agent_memories,
            )
            self._event_bus.subscribe(
                EventType.WORK_COMPLETED,
                self._auto_extract_completion_memories,
            )
            logger.info("Knowledge store initialized at %s", state_dir)
        except Exception:
            logger.debug("Knowledge store initialization failed — continuing without it", exc_info=True)
            self._knowledge_store = None

    def _build_knowledge_context(
        self, work_item: WorkItem, phase: WorkflowPhaseConfig,
    ) -> list[dict[str, Any]]:
        """Query KnowledgeStore for memories relevant to a phase."""
        if self._knowledge_store is None:
            return []
        try:
            from agent_orchestrator.knowledge.models import MemoryQuery
            query = MemoryQuery(
                tags=[phase.id, work_item.type_id],
                app_id=work_item.app_id or None,
                min_confidence=0.3,
                limit=10,
            )
            records = self._knowledge_store.retrieve(query)
            return [
                {
                    "memory_id": r.memory_id,
                    "memory_type": r.memory_type.value,
                    "title": r.title,
                    "content": r.content,
                    "tags": r.tags,
                    "confidence": r.confidence,
                    "source_agent_id": r.source_agent_id,
                }
                for r in records
            ]
        except Exception:
            logger.warning("Failed to build knowledge context", exc_info=True)
            return []

    async def _extract_agent_memories(self, event: Event) -> None:
        """Extract explicit memories from agent output on AGENT_COMPLETED.

        Also stores conversation turns (input/output) via ContextMemory.
        """
        # Store conversation turns via ContextMemory
        if self._context_memory is not None:
            try:
                agent_id = event.data.get("agent_id", "")
                work_id = event.data.get("work_id", "")
                phase_id = event.data.get("phase_id", "")
                run_id = event.run_id
                app_id = event.app_id
                output = event.data.get("output", {})

                # Store the agent input as a "user" turn
                agent_input = event.data.get("input", "")
                if agent_input:
                    input_text = agent_input if isinstance(agent_input, str) else json.dumps(agent_input, default=str)
                    self._context_memory.add_turn(
                        work_id=work_id,
                        agent_id=agent_id,
                        phase_id=phase_id,
                        role="user",
                        content=input_text,
                        run_id=run_id,
                        app_id=app_id,
                    )

                # Store the agent output as an "assistant" turn
                if output:
                    output_text = output if isinstance(output, str) else json.dumps(output, default=str)
                    self._context_memory.add_turn(
                        work_id=work_id,
                        agent_id=agent_id,
                        phase_id=phase_id,
                        role="assistant",
                        content=output_text,
                        run_id=run_id,
                        app_id=app_id,
                    )
            except Exception:
                logger.warning("Failed to store conversation turns", exc_info=True)

        if self._knowledge_store is None:
            return
        try:
            from agent_orchestrator.knowledge.extractor import MemoryExtractor
            output = event.data.get("output", {})
            if not isinstance(output, dict) or "memories" not in output:
                return
            records = MemoryExtractor.extract_from_agent_output(
                agent_id=event.data.get("agent_id", ""),
                work_id=event.data.get("work_id", ""),
                phase_id=event.data.get("phase_id", ""),
                run_id=event.run_id,
                app_id=event.app_id,
                output=output,
            )
            for record in records:
                self._knowledge_store.store(record)
                await self._event_bus.emit(Event(
                    type=EventType.MEMORY_STORED,
                    data={"memory_id": record.memory_id, "memory_type": record.memory_type.value},
                    source="knowledge_extractor",
                    app_id=event.app_id,
                    run_id=event.run_id,
                ))
        except Exception:
            logger.warning("Failed to extract agent memories", exc_info=True)

    async def _auto_extract_completion_memories(self, event: Event) -> None:
        """Auto-extract decision + strategy memories on WORK_COMPLETED."""
        if self._knowledge_store is None:
            return
        try:
            from agent_orchestrator.knowledge.extractor import MemoryExtractor
            work_id = event.data.get("work_id", "")
            work_item = self.get_work_item(work_id)
            if work_item is None:
                return
            phases_completed = list(work_item.results.keys()) if work_item.results else []
            records = MemoryExtractor.extract_completion_memories(
                work_id=work_id,
                run_id=event.run_id,
                app_id=event.app_id,
                results=work_item.results or {},
                phases_completed=phases_completed,
            )
            for record in records:
                self._knowledge_store.store(record)
                await self._event_bus.emit(Event(
                    type=EventType.MEMORY_STORED,
                    data={"memory_id": record.memory_id, "memory_type": record.memory_type.value},
                    source="knowledge_auto_extractor",
                    app_id=event.app_id,
                    run_id=event.run_id,
                ))
        except Exception:
            logger.warning("Failed to auto-extract completion memories", exc_info=True)

    def rediscover_providers(self, plugin_directory: "Path | None" = None) -> "DiscoveryResult":
        """Re-run provider discovery, optionally including an external directory.

        Args:
            plugin_directory: Optional path to scan for external provider plugins.

        Returns:
            DiscoveryResult summarising newly registered, skipped, and failed providers.
        """
        from ..connectors.discovery import DiscoveryResult
        combined = DiscoveryResult()
        builtin = self._connector_discovery.discover_builtin_providers()
        combined.registered.extend(builtin.registered)
        combined.skipped.extend(builtin.skipped)
        combined.errors.extend(builtin.errors)
        if plugin_directory is not None:
            from pathlib import Path as _Path
            ext = self._connector_discovery.discover_directory(_Path(plugin_directory))
            combined.registered.extend(ext.registered)
            combined.skipped.extend(ext.skipped)
            combined.errors.extend(ext.errors)
        self._last_discovery_result = combined
        logger.info("Re-discovery complete: %s", combined.summary())
        return combined

    def reset_work_to_phase(self, work_id: str, phase_id: str) -> bool:
        """Reset a completed/failed work item to a specific phase and re-queue it."""
        if self._pipeline is None or self._queue is None:
            return False
        if not self._pipeline.reset_to_phase(work_id, phase_id):
            return False
        work_item = self.get_work_item(work_id)
        if work_item is not None:
            self._queue.push(work_item)
        return True

    def get_work_item(self, work_id: str) -> WorkItem | None:
        """Get a work item by ID from the pipeline or queue."""
        if self._pipeline is not None:
            entry = self._pipeline.get_entry(work_id)
            if entry is not None:
                return entry.work_item
        if self._queue is not None:
            return self._queue.get_item(work_id)
        return None

    def list_work_items(self) -> list[dict[str, Any]]:
        """List all work items in the pipeline as serializable dicts."""
        if self._pipeline is None:
            return []
        entries = self._pipeline.get_all_entries()
        return [
            {
                "id": e.work_item.id,
                "type_id": e.work_item.type_id,
                "title": e.work_item.title,
                "status": e.work_item.status.value,
                "current_phase": e.current_phase_id,
                "priority": e.work_item.priority,
                "submitted_at": e.work_item.submitted_at.isoformat() if e.work_item.submitted_at else None,
                "started_at": e.work_item.started_at.isoformat() if e.work_item.started_at else None,
                "completed_at": e.work_item.completed_at.isoformat() if e.work_item.completed_at else None,
                "error": e.work_item.error,
                "attempt_count": e.work_item.attempt_count,
            }
            for e in entries
        ]

    def scale_agent(self, agent_id: str, concurrency: int) -> None:
        """Scale an agent's concurrency in the pool."""
        if self._agent_pool is None:
            msg = "Agent pool not initialized"
            raise OrchestratorError(msg)
        self._agent_pool.scale(agent_id, concurrency)

    def get_workflow_phases(self) -> list[WorkflowPhaseConfig]:
        """Get workflow phases from the current profile."""
        try:
            profile = self._config.get_profile()
            return list(profile.workflow.phases)
        except Exception:
            return []

    def get_workflow_phase(self, phase_id: str) -> WorkflowPhaseConfig | None:
        """Get a specific workflow phase by ID."""
        for phase in self.get_workflow_phases():
            if phase.id == phase_id:
                return phase
        return None

    async def register_agent(self, agent_data: dict[str, Any]) -> AgentDefinition:
        """Create a new agent and register it in the runtime pool.

        Coordinates AgentManager (config persistence) + AgentPool (runtime)
        + EventBus (notification).

        Args:
            agent_data: Dictionary of agent fields matching AgentDefinition.

        Returns:
            The created AgentDefinition.

        Raises:
            AgentError: If agent ID already exists or engine not running.
        """
        if self._agent_manager is None:
            msg = "Engine not started — cannot register agent"
            raise AgentError(msg)

        agent = self._agent_manager.create_agent(agent_data)

        if self._agent_pool is not None:
            self._agent_pool.register_definitions([agent])

        await self._event_bus.emit(Event(
            type=EventType.AGENT_CREATED,
            data={"agent_id": agent.id, "name": agent.name},
            source="engine",
        ))
        logger.info("Registered agent '%s' in engine", agent.id)
        return agent

    async def update_agent(
        self, agent_id: str, updates: dict[str, Any],
    ) -> AgentDefinition:
        """Update an agent's config and runtime definition.

        Args:
            agent_id: ID of the agent to update.
            updates: Dictionary of fields to update.

        Returns:
            The updated AgentDefinition.

        Raises:
            AgentError: If agent not found or engine not running.
        """
        if self._agent_manager is None:
            msg = "Engine not started — cannot update agent"
            raise AgentError(msg)

        agent = self._agent_manager.update_agent(agent_id, updates)

        if self._agent_pool is not None:
            self._agent_pool.update_definition(agent)

        await self._event_bus.emit(Event(
            type=EventType.AGENT_UPDATED,
            data={"agent_id": agent.id, "updates": list(updates.keys())},
            source="engine",
        ))
        logger.info("Updated agent '%s' in engine", agent_id)
        return agent

    async def unregister_agent(self, agent_id: str) -> bool:
        """Remove an agent from config and runtime pool.

        Args:
            agent_id: ID of the agent to remove.

        Returns:
            True if agent was found and removed.

        Raises:
            AgentError: If engine not running.
        """
        if self._agent_manager is None:
            msg = "Engine not started — cannot unregister agent"
            raise AgentError(msg)

        deleted = self._agent_manager.delete_agent(agent_id)
        if not deleted:
            return False

        if self._agent_pool is not None:
            self._agent_pool.unregister_definition(agent_id)

        await self._event_bus.emit(Event(
            type=EventType.AGENT_DELETED,
            data={"agent_id": agent_id},
            source="engine",
        ))
        logger.info("Unregistered agent '%s' from engine", agent_id)
        return True

    def get_status(self) -> dict[str, Any]:
        """Get engine status summary."""
        status: dict[str, Any] = {
            "state": self._state.value,
        }
        if self._queue is not None:
            status["queue"] = self._queue.get_stats()
        if self._pipeline is not None:
            status["pipeline"] = self._pipeline.get_stats()
        if self._agent_pool is not None:
            status["agents"] = self._agent_pool.get_stats()
        if self._governor is not None:
            status["governance"] = {
                "policies": len(self._governor.list_policies()),
                "pending_reviews": self._review_queue.pending_count() if self._review_queue else 0,
            }
        if self._metrics is not None:
            status["metrics"] = self._metrics.get_summary()
        return status

    # ---- Decision Ledger Helpers ----

    def _record_governance_decision(
        self,
        decision: GovernanceDecision,
        work_item: WorkItem,
        phase_id: str,
        run_id: str,
        app_id: str,
        *,
        stage: str = "pre_execution",
    ) -> None:
        """Record a governance check decision in the ledger."""
        if self._decision_ledger is None:
            return
        try:
            outcome = {
                Resolution.APPROVE: DecisionOutcome.APPROVED,
                Resolution.ABORT: DecisionOutcome.REJECTED,
                Resolution.QUEUE_FOR_REVIEW: DecisionOutcome.ESCALATED,
            }.get(decision.resolution, DecisionOutcome.APPROVED)

            self._decision_ledger.record_decision(
                decision_type=DecisionType.GOVERNANCE_CHECK,
                outcome=outcome,
                work_item_id=work_item.id,
                phase_id=phase_id,
                run_id=run_id,
                app_id=app_id,
                confidence=decision.confidence,
                policy_result=decision.resolution.value,
                policy_id=decision.policy_id if hasattr(decision, "policy_id") else "",
                reasoning_summary=f"{stage}: {decision.reason}",
                metadata={"stage": stage},
            )
        except Exception as exc:
            logger.warning("Failed to record governance decision: %s", exc)

    def _record_execution_decision(
        self,
        work_item: WorkItem,
        phase_id: str,
        result: Any,
        duration: float,
        run_id: str,
        app_id: str,
    ) -> None:
        """Record an agent execution decision in the ledger."""
        if self._decision_ledger is None:
            return
        try:
            outcome = (
                DecisionOutcome.COMPLETED if result.success
                else DecisionOutcome.FAILED
            )
            self._decision_ledger.record_decision(
                decision_type=DecisionType.AGENT_EXECUTION,
                outcome=outcome,
                work_item_id=work_item.id,
                phase_id=phase_id,
                run_id=run_id,
                app_id=app_id,
                confidence=result.aggregate_confidence,
                duration_seconds=duration,
                input_data=work_item.data,
                output_data=work_item.results,
                reasoning_summary=f"Phase {phase_id} execution: {len(result.agent_results)} agent(s)",
            )
        except Exception as exc:
            logger.warning("Failed to record execution decision: %s", exc)

    def _record_completion_decision(
        self,
        work_item: WorkItem,
        run_id: str,
        app_id: str,
    ) -> None:
        """Record work completion/failure in the decision ledger."""
        if self._decision_ledger is None:
            return
        if work_item.status not in (WorkItemStatus.COMPLETED, WorkItemStatus.FAILED):
            return
        try:
            outcome = (
                DecisionOutcome.COMPLETED
                if work_item.status == WorkItemStatus.COMPLETED
                else DecisionOutcome.FAILED
            )
            self._decision_ledger.record_decision(
                decision_type=DecisionType.WORK_COMPLETION,
                outcome=outcome,
                work_item_id=work_item.id,
                run_id=run_id,
                app_id=app_id,
                output_data=work_item.results,
                reasoning_summary=work_item.error or "completed successfully",
            )
        except Exception as exc:
            logger.warning("Failed to record completion decision: %s", exc)

    # ---- SLA Helpers ----

    def _apply_sla_defaults(self, work_item: WorkItem) -> None:
        """Apply SLA defaults from WorkItemTypeConfig if no deadline set."""
        if work_item.deadline is not None:
            return
        try:
            profile = self._config.get_profile()
            type_config = next(
                (t for t in profile.work_item_types if t.id == work_item.type_id),
                None,
            )
            if type_config is None:
                return
            sla = getattr(type_config, "sla", None)
            if sla is None:
                return
            if sla.default_deadline_seconds is not None:
                from datetime import timedelta
                work_item.deadline = work_item.submitted_at + timedelta(
                    seconds=sla.default_deadline_seconds,
                )
                work_item.sla_policy_id = f"sla-{type_config.id}"
                logger.debug(
                    "Applied SLA deadline to %s: %s",
                    work_item.id, work_item.deadline.isoformat(),
                )
        except Exception as exc:
            logger.warning("Failed to apply SLA defaults: %s", exc)

    async def _start_sla_monitor(self) -> None:
        """Start the SLA monitor background task."""
        if self._work_item_store is None:
            return
        try:
            from agent_orchestrator.core.sla_monitor import SLAMonitor
            self._sla_monitor = SLAMonitor(
                event_bus=self._event_bus,
                work_item_store=self._work_item_store,
            )
            await self._sla_monitor.start()
        except Exception:
            logger.debug("SLA monitor initialization failed", exc_info=True)
            self._sla_monitor = None
