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
import logging
import os
import threading
from enum import Enum
from pathlib import Path
from typing import Any

from agent_orchestrator.adapters.llm_adapter import LLMAdapter
from agent_orchestrator.adapters.metrics_adapter import MetricsCollector
from agent_orchestrator.configuration.agent_manager import AgentManager
from agent_orchestrator.configuration.loader import ConfigurationManager
from agent_orchestrator.configuration.models import (
    AgentDefinition,
    ProfileConfig,
    SettingsConfig,
    WorkflowPhaseConfig,
)
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
from agent_orchestrator.governance.audit_logger import AuditLogger, RecordType
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
    ) -> None:
        self._config = config_manager
        self._event_bus = event_bus or EventBus()
        self._state = EngineState.IDLE
        self._lock = threading.Lock()

        # AgentManager for CRUD operations
        self._agent_manager: AgentManager | None = None

        # Governance and observability (initialized on start)
        self._governor: Governor | None = None
        self._review_queue: ReviewQueue | None = None
        self._audit_logger: AuditLogger | None = None
        self._metrics: MetricsCollector | None = None

        # Components initialized on start()
        self._queue: WorkQueue | None = None
        self._pipeline: PipelineManager | None = None
        self._agent_pool: AgentPool | None = None
        self._phase_executor: PhaseExecutor | None = None
        self._agent_executor: AgentExecutor | None = None
        self._processing_task: asyncio.Task[None] | None = None
        self._llm_call_fn = llm_call_fn

    @property
    def state(self) -> EngineState:
        """Current engine state."""
        return self._state

    @property
    def event_bus(self) -> EventBus:
        """The engine's event bus."""
        return self._event_bus

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
            self._initialize_components(profile)

            with self._lock:
                self._state = EngineState.RUNNING

            self._processing_task = asyncio.create_task(self._processing_loop())

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
            adapter = LLMAdapter(settings)
            self._register_providers(adapter, settings)
            self._agent_executor = AgentExecutor(llm_call_fn=adapter.call)
        else:
            self._agent_executor = AgentExecutor(llm_call_fn=self._llm_call_fn)

        self._phase_executor = PhaseExecutor(
            agent_pool=self._agent_pool,
            agent_executor=self._agent_executor,
            event_bus=self._event_bus,
        )
        self._agent_manager = AgentManager(self._config)

        # Governance and observability
        self._governor = Governor(profile.governance)
        self._review_queue = ReviewQueue()
        state_dir = self._config.workspace_dir / ".state"
        state_dir.mkdir(parents=True, exist_ok=True)
        self._audit_logger = AuditLogger(state_dir / "audit")
        self._metrics = MetricsCollector(state_dir / "metrics.jsonl")

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

        await self._queue.push(work_item)

        await self._event_bus.emit(Event(
            type=EventType.WORK_SUBMITTED,
            data={"work_id": work_item.id, "type": work_item.type_id},
            source="engine",
        ))
        logger.info("Work item '%s' submitted", work_item.id)
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

        logger.info("Processing work item '%s'", work_item.id)

        await self._event_bus.emit(Event(
            type=EventType.WORK_STARTED,
            data={"work_id": work_item.id},
            source="engine",
        ))

        if self._audit_logger is not None:
            self._audit_logger.append(
                RecordType.STATE_CHANGE,
                "work.started",
                f"Work item '{work_item.id}' processing started",
                work_id=work_item.id,
            )

        try:
            phase_id = self._pipeline.enter_pipeline(work_item)
        except WorkflowError as e:
            logger.error("Failed to enter pipeline: %s", e, exc_info=True)
            work_item.status = WorkItemStatus.FAILED
            work_item.error = str(e)
            if self._audit_logger is not None:
                self._audit_logger.append(
                    RecordType.ERROR,
                    "pipeline.entry_failed",
                    str(e),
                    work_id=work_item.id,
                )
            return

        # Process through phases until complete or terminal
        while phase_id is not None:
            phase = self._pipeline.get_current_phase(work_item.id)
            if phase is None:
                break

            if phase.is_terminal:
                work_item.status = WorkItemStatus.COMPLETED
                break

            # Governance check before phase execution
            if self._governor is not None:
                decision = self._governor.evaluate(
                    {"confidence": 0.5, "work_type": work_item.type_id, "phase": phase.id},
                    work_type=work_item.type_id,
                )

                if decision.resolution == Resolution.ABORT:
                    logger.warning(
                        "Governance ABORT for '%s' at phase '%s': %s",
                        work_item.id, phase.id, decision.reason,
                    )
                    work_item.status = WorkItemStatus.FAILED
                    work_item.error = f"Governance abort: {decision.reason}"
                    if self._audit_logger is not None:
                        self._audit_logger.append(
                            RecordType.DECISION,
                            "governance.abort",
                            decision.reason,
                            work_id=work_item.id,
                            data={"phase": phase.id, "confidence": decision.confidence},
                        )
                    await self._event_bus.emit(Event(
                        type=EventType.WORK_FAILED,
                        data={"work_id": work_item.id, "error": work_item.error},
                        source="engine",
                    ))
                    return

                if decision.resolution == Resolution.QUEUE_FOR_REVIEW:
                    if self._review_queue is not None:
                        self._review_queue.enqueue(
                            work_id=work_item.id,
                            phase_id=phase.id,
                            reason=decision.reason,
                            decision_data={"confidence": decision.confidence},
                        )
                    if self._audit_logger is not None:
                        self._audit_logger.append(
                            RecordType.ESCALATION,
                            "governance.review_queued",
                            decision.reason,
                            work_id=work_item.id,
                            data={"phase": phase.id},
                        )

            # Lock for execution
            if not self._pipeline.lock_for_execution(work_item.id, "engine"):
                logger.warning("Could not lock work item '%s'", work_item.id)
                break

            import time
            phase_start = time.monotonic()

            try:
                result = await self._phase_executor.execute_phase(
                    phase, work_item,
                )
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
                        tags={"phase": phase.id, "work_id": work_item.id},
                    )
                    self._metrics.increment(
                        "phase.completed",
                        tags={"phase": phase.id, "result": phase_result.value},
                    )

            except Exception as e:
                logger.error(
                    "Phase execution error for '%s': %s",
                    work_item.id, e, exc_info=True,
                )
                self._pipeline.unlock(work_item.id)
                work_item.status = WorkItemStatus.FAILED
                work_item.error = str(e)
                if self._audit_logger is not None:
                    self._audit_logger.append(
                        RecordType.ERROR,
                        "phase.execution_error",
                        str(e),
                        work_id=work_item.id,
                        data={"phase": phase.id},
                    )
                break

        # Emit completion event and record audit
        if work_item.status == WorkItemStatus.COMPLETED:
            await self._event_bus.emit(Event(
                type=EventType.WORK_COMPLETED,
                data={"work_id": work_item.id},
                source="engine",
            ))
            if self._audit_logger is not None:
                self._audit_logger.append(
                    RecordType.STATE_CHANGE,
                    "work.completed",
                    f"Work item '{work_item.id}' completed",
                    work_id=work_item.id,
                )
            if self._metrics is not None:
                self._metrics.increment("work.completed")
        elif work_item.status == WorkItemStatus.FAILED:
            await self._event_bus.emit(Event(
                type=EventType.WORK_FAILED,
                data={"work_id": work_item.id, "error": work_item.error},
                source="engine",
            ))
            if self._audit_logger is not None:
                self._audit_logger.append(
                    RecordType.STATE_CHANGE,
                    "work.failed",
                    f"Work item '{work_item.id}' failed: {work_item.error}",
                    work_id=work_item.id,
                )
            if self._metrics is not None:
                self._metrics.increment("work.failed")

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
