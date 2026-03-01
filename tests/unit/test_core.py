"""Unit tests for core engine components."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_src_dir = Path(__file__).resolve().parent.parent.parent / "src"
if str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

from agent_orchestrator.configuration.models import (
    AgentDefinition,
    GovernanceConfig,
    DelegatedAuthorityConfig,
    LLMConfig,
    PolicyConfig,
    ProfileConfig,
    SettingsConfig,
    WorkflowConfig,
    WorkflowPhaseConfig,
)
from agent_orchestrator.core.agent_executor import AgentExecutor, ExecutionResult
from agent_orchestrator.core.agent_pool import AgentInstance, AgentPool, AgentState
from agent_orchestrator.core.engine import EngineState, OrchestrationEngine
from agent_orchestrator.core.event_bus import Event, EventBus, EventType
from agent_orchestrator.core.phase_executor import PhaseExecutor
from agent_orchestrator.core.pipeline_manager import PhaseResult, PipelineManager
from agent_orchestrator.core.work_queue import WorkItem, WorkItemStatus, WorkQueue
from agent_orchestrator.exceptions import OrchestratorError, WorkflowError


# ---- EventBus Tests ----


class TestEventBus:
    """Tests for the EventBus pub/sub system."""

    @pytest.mark.asyncio
    async def test_subscribe_and_emit(self) -> None:
        bus = EventBus()
        received: list[Event] = []

        async def handler(event: Event) -> None:
            received.append(event)

        bus.subscribe(EventType.WORK_SUBMITTED, handler)
        await bus.emit(Event(type=EventType.WORK_SUBMITTED, data={"id": "w1"}))

        assert len(received) == 1
        assert received[0].data["id"] == "w1"

    @pytest.mark.asyncio
    async def test_wildcard_subscriber(self) -> None:
        bus = EventBus()
        received: list[Event] = []

        async def handler(event: Event) -> None:
            received.append(event)

        bus.subscribe_all(handler)
        await bus.emit(Event(type=EventType.WORK_SUBMITTED))
        await bus.emit(Event(type=EventType.SYSTEM_STARTED))

        assert len(received) == 2

    @pytest.mark.asyncio
    async def test_unsubscribe(self) -> None:
        bus = EventBus()
        received: list[Event] = []

        async def handler(event: Event) -> None:
            received.append(event)

        bus.subscribe(EventType.WORK_SUBMITTED, handler)
        bus.unsubscribe(EventType.WORK_SUBMITTED, handler)
        await bus.emit(Event(type=EventType.WORK_SUBMITTED))

        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_handler_error_does_not_block(self) -> None:
        bus = EventBus()
        received: list[Event] = []

        async def bad_handler(event: Event) -> None:
            raise RuntimeError("handler error")

        async def good_handler(event: Event) -> None:
            received.append(event)

        bus.subscribe(EventType.WORK_SUBMITTED, bad_handler)
        bus.subscribe(EventType.WORK_SUBMITTED, good_handler)
        await bus.emit(Event(type=EventType.WORK_SUBMITTED))

        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_clear(self) -> None:
        bus = EventBus()

        async def handler(event: Event) -> None:
            pass

        bus.subscribe(EventType.WORK_SUBMITTED, handler)
        bus.clear()

        # Should not raise, just no handlers
        await bus.emit(Event(type=EventType.WORK_SUBMITTED))


# ---- WorkQueue Tests ----


class TestWorkQueue:
    """Tests for the WorkQueue."""

    @pytest.mark.asyncio
    async def test_push_and_pop(self) -> None:
        queue = WorkQueue()
        item = WorkItem(id="w1", type_id="task", title="Test")
        await queue.push(item)

        assert queue.size() == 1
        popped = await queue.pop(timeout=1.0)
        assert popped is not None
        assert popped.id == "w1"
        assert queue.size() == 0

    @pytest.mark.asyncio
    async def test_priority_ordering(self) -> None:
        queue = WorkQueue()
        await queue.push(WorkItem(id="low", type_id="task", title="Low", priority=5))
        await queue.push(WorkItem(id="high", type_id="task", title="High", priority=1))

        first = await queue.pop(timeout=1.0)
        assert first is not None
        assert first.id == "high"

    @pytest.mark.asyncio
    async def test_duplicate_id_raises(self) -> None:
        queue = WorkQueue()
        item = WorkItem(id="w1", type_id="task", title="Test")
        await queue.push(item)

        with pytest.raises(ValueError, match="already in queue"):
            await queue.push(WorkItem(id="w1", type_id="task", title="Dup"))

    @pytest.mark.asyncio
    async def test_pop_timeout(self) -> None:
        queue = WorkQueue()
        result = await queue.pop(timeout=0.1)
        assert result is None

    @pytest.mark.asyncio
    async def test_stats(self) -> None:
        queue = WorkQueue()
        await queue.push(WorkItem(id="w1", type_id="task", title="Test"))
        stats = queue.get_stats()
        assert stats["current_size"] == 1
        assert stats["total_pushed"] == 1


# ---- AgentPool Tests ----


class TestAgentPool:
    """Tests for the AgentPool."""

    def _make_definition(self, agent_id: str = "agent-1", concurrency: int = 2) -> AgentDefinition:
        return AgentDefinition(
            id=agent_id,
            name=f"Agent {agent_id}",
            system_prompt="test",
            phases=["p1"],
            llm=LLMConfig(provider="openai", model="gpt-4o"),
            concurrency=concurrency,
        )

    def test_register_and_acquire(self) -> None:
        pool = AgentPool()
        defn = self._make_definition()
        pool.register_definitions([defn])

        instance = pool.acquire("agent-1")
        assert instance is not None
        assert instance.state == AgentState.RUNNING

    def test_concurrency_limit(self) -> None:
        pool = AgentPool()
        defn = self._make_definition(concurrency=1)
        pool.register_definitions([defn])

        first = pool.acquire("agent-1")
        assert first is not None
        second = pool.acquire("agent-1")
        assert second is None  # At limit

    def test_release_and_reacquire(self) -> None:
        pool = AgentPool()
        defn = self._make_definition(concurrency=1)
        pool.register_definitions([defn])

        first = pool.acquire("agent-1")
        assert first is not None
        pool.release(first.instance_id)

        second = pool.acquire("agent-1")
        assert second is not None
        assert second.instance_id == first.instance_id

    def test_release_failure(self) -> None:
        pool = AgentPool()
        defn = self._make_definition()
        pool.register_definitions([defn])

        instance = pool.acquire("agent-1")
        assert instance is not None
        pool.release(instance.instance_id, success=False)
        assert instance.state == AgentState.ERROR

    def test_unknown_agent(self) -> None:
        pool = AgentPool()
        assert pool.acquire("nonexistent") is None

    def test_scale(self) -> None:
        pool = AgentPool()
        defn = self._make_definition(concurrency=1)
        pool.register_definitions([defn])

        pool.scale("agent-1", 3)
        stats = pool.get_stats()
        assert stats["agent-1"]["max_concurrency"] == 3

    def test_stats(self) -> None:
        pool = AgentPool()
        defn = self._make_definition()
        pool.register_definitions([defn])

        pool.acquire("agent-1")
        stats = pool.get_stats()
        assert stats["agent-1"]["running"] == 1

    def test_shutdown(self) -> None:
        pool = AgentPool()
        defn = self._make_definition()
        pool.register_definitions([defn])
        pool.acquire("agent-1")
        pool.shutdown()
        stats = pool.get_stats()
        # All instances should be shutdown
        assert stats["agent-1"]["running"] == 0

    def test_update_definition(self) -> None:
        pool = AgentPool()
        defn = self._make_definition(concurrency=2)
        pool.register_definitions([defn])

        # Acquire and release an instance to make it idle
        instance = pool.acquire("agent-1")
        assert instance is not None
        pool.release(instance.instance_id)

        # Update definition
        updated_defn = defn.model_copy(update={"name": "Updated Agent"})
        pool.update_definition(updated_defn)

        # Idle instance should have updated definition
        reacquired = pool.acquire("agent-1")
        assert reacquired is not None
        assert reacquired.definition.name == "Updated Agent"

    def test_update_unknown_definition(self) -> None:
        pool = AgentPool()
        defn = self._make_definition(agent_id="unknown")
        # Should not raise, just log warning
        pool.update_definition(defn)

    def test_unregister_definition(self) -> None:
        pool = AgentPool()
        defn = self._make_definition()
        pool.register_definitions([defn])
        pool.acquire("agent-1")

        result = pool.unregister_definition("agent-1")
        assert result is True
        assert "agent-1" not in pool.get_stats()

        # Cannot acquire after unregister
        assert pool.acquire("agent-1") is None

    def test_unregister_unknown_returns_false(self) -> None:
        pool = AgentPool()
        assert pool.unregister_definition("nonexistent") is False


# ---- PipelineManager Tests ----


class TestPipelineManager:
    """Tests for the PipelineManager."""

    def _make_workflow(self) -> WorkflowConfig:
        return WorkflowConfig(
            name="test",
            phases=[
                WorkflowPhaseConfig(
                    id="phase-1", name="Phase 1", order=1,
                    agents=["a1"], on_success="phase-2", on_failure="phase-2",
                ),
                WorkflowPhaseConfig(
                    id="phase-2", name="Phase 2", order=2,
                    agents=[], is_terminal=True,
                ),
            ],
        )

    def test_enter_pipeline(self) -> None:
        pm = PipelineManager(self._make_workflow())
        item = WorkItem(id="w1", type_id="task", title="Test")
        phase_id = pm.enter_pipeline(item)
        assert phase_id == "phase-1"
        assert item.current_phase == "phase-1"

    def test_duplicate_entry_raises(self) -> None:
        pm = PipelineManager(self._make_workflow())
        item = WorkItem(id="w1", type_id="task", title="Test")
        pm.enter_pipeline(item)
        with pytest.raises(WorkflowError, match="already in pipeline"):
            pm.enter_pipeline(item)

    def test_complete_phase_success(self) -> None:
        pm = PipelineManager(self._make_workflow())
        item = WorkItem(id="w1", type_id="task", title="Test")
        pm.enter_pipeline(item)

        next_phase = pm.complete_phase("w1", PhaseResult.SUCCESS)
        assert next_phase == "phase-2"

    def test_terminal_phase(self) -> None:
        pm = PipelineManager(self._make_workflow())
        item = WorkItem(id="w1", type_id="task", title="Test")
        pm.enter_pipeline(item)

        pm.complete_phase("w1", PhaseResult.SUCCESS)  # -> phase-2
        result = pm.complete_phase("w1", PhaseResult.SUCCESS)  # terminal
        assert result is None
        assert item.status == WorkItemStatus.COMPLETED

    def test_lock_and_unlock(self) -> None:
        pm = PipelineManager(self._make_workflow())
        item = WorkItem(id="w1", type_id="task", title="Test")
        pm.enter_pipeline(item)

        assert pm.lock_for_execution("w1", "executor-1")
        assert not pm.lock_for_execution("w1", "executor-2")  # Already locked
        pm.unlock("w1")
        assert pm.lock_for_execution("w1", "executor-2")

    def test_skip_phase(self) -> None:
        workflow = WorkflowConfig(
            name="test",
            phases=[
                WorkflowPhaseConfig(
                    id="p1", name="P1", order=1,
                    agents=["a1"], on_success="p2",
                ),
                WorkflowPhaseConfig(
                    id="p2", name="P2", order=2,
                    agents=["a2"], skip=True, on_success="p3",
                ),
                WorkflowPhaseConfig(
                    id="p3", name="P3", order=3,
                    agents=[], is_terminal=True,
                ),
            ],
        )
        pm = PipelineManager(workflow)
        item = WorkItem(id="w1", type_id="task", title="Test")
        pm.enter_pipeline(item)

        next_phase = pm.complete_phase("w1", PhaseResult.SUCCESS)
        assert next_phase == "p3"  # Skipped p2

    def test_failure_path(self) -> None:
        workflow = WorkflowConfig(
            name="test",
            phases=[
                WorkflowPhaseConfig(
                    id="p1", name="P1", order=1,
                    agents=["a1"], on_success="p3", on_failure="p2",
                ),
                WorkflowPhaseConfig(
                    id="p2", name="P2 (fix)", order=2,
                    agents=["a2"], on_success="p1",
                ),
                WorkflowPhaseConfig(
                    id="p3", name="Done", order=3,
                    agents=[], is_terminal=True,
                ),
            ],
        )
        pm = PipelineManager(workflow)
        item = WorkItem(id="w1", type_id="task", title="Test")
        pm.enter_pipeline(item)

        next_phase = pm.complete_phase("w1", PhaseResult.FAILURE)
        assert next_phase == "p2"  # Went to failure path

    def test_stats(self) -> None:
        pm = PipelineManager(self._make_workflow())
        item = WorkItem(id="w1", type_id="task", title="Test")
        pm.enter_pipeline(item)
        stats = pm.get_stats()
        assert stats["total_items"] == 1

    def test_empty_workflow_raises(self) -> None:
        pm = PipelineManager(WorkflowConfig(name="empty"))
        item = WorkItem(id="w1", type_id="task", title="Test")
        with pytest.raises(WorkflowError, match="no phases"):
            pm.enter_pipeline(item)


# ---- AgentExecutor Tests ----


class TestAgentExecutor:
    """Tests for the AgentExecutor."""

    def _make_instance(self) -> AgentInstance:
        defn = AgentDefinition(
            id="test-agent",
            name="Test Agent",
            system_prompt="You are a test agent.",
            phases=["p1"],
            llm=LLMConfig(provider="openai", model="gpt-4o"),
        )
        return AgentInstance(instance_id="test-agent-1", definition=defn)

    @pytest.mark.asyncio
    async def test_execute_success(self) -> None:
        executor = AgentExecutor()
        instance = self._make_instance()
        item = WorkItem(id="w1", type_id="task", title="Test")

        result = await executor.execute(instance, item, "p1")
        assert result.success
        assert result.agent_id == "test-agent"
        assert result.output["confidence"] == 0.85

    @pytest.mark.asyncio
    async def test_execute_with_custom_llm(self) -> None:
        async def custom_llm(**kwargs) -> dict:
            return {"response": "custom", "status": "ok"}

        executor = AgentExecutor(llm_call_fn=custom_llm)
        instance = self._make_instance()
        item = WorkItem(id="w1", type_id="task", title="Test")

        result = await executor.execute(instance, item, "p1")
        assert result.success
        assert result.output["response"] == "custom"

    @pytest.mark.asyncio
    async def test_execute_retry_on_failure(self) -> None:
        call_count = 0

        async def failing_llm(**kwargs) -> dict:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("transient error")
            return {"response": "ok"}

        executor = AgentExecutor(llm_call_fn=failing_llm)
        instance = self._make_instance()
        item = WorkItem(id="w1", type_id="task", title="Test")

        result = await executor.execute(instance, item, "p1")
        assert result.success
        assert call_count == 3


# ---- PhaseExecutor Tests ----


class TestPhaseExecutor:
    """Tests for the PhaseExecutor."""

    def _setup(self) -> tuple[AgentPool, PhaseExecutor, EventBus]:
        bus = EventBus()
        pool = AgentPool()
        defn = AgentDefinition(
            id="agent-1",
            name="Agent 1",
            system_prompt="test",
            phases=["p1"],
            llm=LLMConfig(provider="openai", model="gpt-4o"),
            concurrency=2,
        )
        pool.register_definitions([defn])
        executor = AgentExecutor()
        phase_exec = PhaseExecutor(pool, executor, bus)
        return pool, phase_exec, bus

    @pytest.mark.asyncio
    async def test_execute_phase_sequential(self) -> None:
        _, phase_exec, _ = self._setup()
        phase = WorkflowPhaseConfig(
            id="p1", name="P1", order=1, agents=["agent-1"], parallel=False,
        )
        item = WorkItem(id="w1", type_id="task", title="Test")
        result = await phase_exec.execute_phase(phase, item)
        assert result.success
        assert len(result.agent_results) == 1

    @pytest.mark.asyncio
    async def test_execute_phase_no_agents(self) -> None:
        _, phase_exec, _ = self._setup()
        phase = WorkflowPhaseConfig(
            id="p1", name="P1", order=1, agents=[], is_terminal=True,
        )
        item = WorkItem(id="w1", type_id="task", title="Test")
        result = await phase_exec.execute_phase(phase, item)
        assert result.success

    @pytest.mark.asyncio
    async def test_events_emitted(self) -> None:
        _, phase_exec, bus = self._setup()
        events: list[Event] = []

        async def capture(event: Event) -> None:
            events.append(event)

        bus.subscribe_all(capture)
        phase = WorkflowPhaseConfig(
            id="p1", name="P1", order=1, agents=["agent-1"],
        )
        item = WorkItem(id="w1", type_id="task", title="Test")
        await phase_exec.execute_phase(phase, item)

        event_types = [e.type for e in events]
        assert EventType.WORK_PHASE_ENTERED in event_types
        assert EventType.AGENT_STARTED in event_types
        assert EventType.AGENT_COMPLETED in event_types
        assert EventType.WORK_PHASE_EXITED in event_types


# ---- Engine Integration Tests ----


def _make_test_config_manager(workspace_dir: Path) -> MagicMock:
    """Create a mock ConfigurationManager for engine tests."""
    config_mgr = MagicMock()
    config_mgr.workspace_dir = workspace_dir

    profile = ProfileConfig(
        name="test",
        agents=[
            AgentDefinition(
                id="agent-1",
                name="Test Agent",
                system_prompt="test",
                phases=["process"],
                llm=LLMConfig(provider="openai", model="gpt-4o"),
                concurrency=2,
            ),
        ],
        workflow=WorkflowConfig(
            name="test",
            phases=[
                WorkflowPhaseConfig(
                    id="process", name="Process", order=1,
                    agents=["agent-1"], on_success="done",
                ),
                WorkflowPhaseConfig(
                    id="done", name="Done", order=2,
                    agents=[], is_terminal=True,
                ),
            ],
        ),
        governance=GovernanceConfig(
            delegated_authority=DelegatedAuthorityConfig(
                auto_approve_threshold=0.8,
                review_threshold=0.5,
                abort_threshold=0.2,
            ),
        ),
    )

    config_mgr.get_profile.return_value = profile
    config_mgr.get_settings.return_value = SettingsConfig(active_profile="test")
    config_mgr.load.return_value = None
    return config_mgr


class TestEngineGovernance:
    """Tests for governance integration in the engine."""

    @pytest.mark.asyncio
    async def test_engine_initializes_governor(self, tmp_path: Path) -> None:
        config_mgr = _make_test_config_manager(tmp_path)
        engine = OrchestrationEngine(config_mgr)

        await engine.start()
        try:
            assert engine.governor is not None
            assert engine.review_queue is not None
        finally:
            await engine.stop()

    @pytest.mark.asyncio
    async def test_governor_properties_none_before_start(self, tmp_path: Path) -> None:
        config_mgr = _make_test_config_manager(tmp_path)
        engine = OrchestrationEngine(config_mgr)

        assert engine.governor is None
        assert engine.review_queue is None
        assert engine.audit_logger is None
        assert engine.metrics is None

    @pytest.mark.asyncio
    async def test_get_workflow_phases(self, tmp_path: Path) -> None:
        config_mgr = _make_test_config_manager(tmp_path)
        engine = OrchestrationEngine(config_mgr)

        phases = engine.get_workflow_phases()
        assert len(phases) == 2
        assert phases[0].id == "process"
        assert phases[1].id == "done"

    @pytest.mark.asyncio
    async def test_get_workflow_phase_by_id(self, tmp_path: Path) -> None:
        config_mgr = _make_test_config_manager(tmp_path)
        engine = OrchestrationEngine(config_mgr)

        phase = engine.get_workflow_phase("process")
        assert phase is not None
        assert phase.name == "Process"

        assert engine.get_workflow_phase("nonexistent") is None


class TestEngineAudit:
    """Tests for audit logging integration in the engine."""

    @pytest.mark.asyncio
    async def test_start_stop_records_audit(self, tmp_path: Path) -> None:
        config_mgr = _make_test_config_manager(tmp_path)
        engine = OrchestrationEngine(config_mgr)

        await engine.start()
        await engine.stop()

        assert engine.audit_logger is not None
        records = engine.audit_logger.query()
        actions = [r["action"] for r in records]
        assert "engine.start" in actions
        assert "engine.stop" in actions

    @pytest.mark.asyncio
    async def test_work_processing_records_audit(self, tmp_path: Path) -> None:
        config_mgr = _make_test_config_manager(tmp_path)
        engine = OrchestrationEngine(config_mgr)

        await engine.start()
        try:
            item = WorkItem(id="w1", type_id="task", title="Test")
            await engine.submit_work(item)
            # Allow processing loop to run
            await asyncio.sleep(0.5)
        finally:
            await engine.stop()

        records = engine.audit_logger.query(work_id="w1")
        assert len(records) > 0
        actions = [r["action"] for r in records]
        assert "work.started" in actions


class TestEngineMetrics:
    """Tests for metrics collection in the engine."""

    @pytest.mark.asyncio
    async def test_engine_initializes_metrics(self, tmp_path: Path) -> None:
        config_mgr = _make_test_config_manager(tmp_path)
        engine = OrchestrationEngine(config_mgr)

        await engine.start()
        try:
            assert engine.metrics is not None
            summary = engine.metrics.get_summary()
            assert "total_entries" in summary
            assert "counters" in summary
        finally:
            await engine.stop()

    @pytest.mark.asyncio
    async def test_status_includes_governance_and_metrics(self, tmp_path: Path) -> None:
        config_mgr = _make_test_config_manager(tmp_path)
        engine = OrchestrationEngine(config_mgr)

        await engine.start()
        try:
            status = engine.get_status()
            assert status["state"] == "running"
            assert "governance" in status
            assert "metrics" in status
            assert "pending_reviews" in status["governance"]
        finally:
            await engine.stop()

    @pytest.mark.asyncio
    async def test_work_processing_records_metrics(self, tmp_path: Path) -> None:
        config_mgr = _make_test_config_manager(tmp_path)
        engine = OrchestrationEngine(config_mgr)

        await engine.start()
        try:
            item = WorkItem(id="w1", type_id="task", title="Test")
            await engine.submit_work(item)
            await asyncio.sleep(0.5)
        finally:
            await engine.stop()

        summary = engine.metrics.get_summary()
        # Should have recorded at least phase metrics
        assert summary["total_entries"] > 0


class TestEngineWorkItems:
    """Tests for work item accessors on the engine."""

    @pytest.mark.asyncio
    async def test_list_work_items_empty(self, tmp_path: Path) -> None:
        config_mgr = _make_test_config_manager(tmp_path)
        engine = OrchestrationEngine(config_mgr)

        await engine.start()
        try:
            items = engine.list_work_items()
            assert items == []
        finally:
            await engine.stop()

    @pytest.mark.asyncio
    async def test_get_work_item_not_found(self, tmp_path: Path) -> None:
        config_mgr = _make_test_config_manager(tmp_path)
        engine = OrchestrationEngine(config_mgr)

        await engine.start()
        try:
            assert engine.get_work_item("nonexistent") is None
        finally:
            await engine.stop()

    @pytest.mark.asyncio
    async def test_scale_agent(self, tmp_path: Path) -> None:
        config_mgr = _make_test_config_manager(tmp_path)
        engine = OrchestrationEngine(config_mgr)

        await engine.start()
        try:
            engine.scale_agent("agent-1", 5)
            status = engine.get_status()
            assert status["agents"]["agent-1"]["max_concurrency"] == 5
        finally:
            await engine.stop()

    @pytest.mark.asyncio
    async def test_scale_agent_before_start_raises(self, tmp_path: Path) -> None:
        config_mgr = _make_test_config_manager(tmp_path)
        engine = OrchestrationEngine(config_mgr)

        with pytest.raises(OrchestratorError):
            engine.scale_agent("agent-1", 5)
