"""Tests for the evaluation system — evaluator, rubric store, A/B tests, datasets, routes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_orchestrator.simulation.evaluator import (
    EvalDimension,
    EvalResult,
    EvalRubric,
    EvalScore,
    LLMJudgeEvaluator,
)
from agent_orchestrator.simulation.rubric_store import (
    DEFAULT_QUALITY_RUBRIC,
    DEFAULT_SAFETY_RUBRIC,
    RubricStore,
)
from agent_orchestrator.simulation.ab_test import (
    ABComparison,
    ABItemComparison,
    ABTestConfig,
    ABTestResult,
    ABTestRunner,
)
from agent_orchestrator.simulation.dataset import DatasetStore, EvalDataset
from agent_orchestrator.simulation.sandbox import SimulationSandbox
from agent_orchestrator.api.eval_routes import eval_router


# ---- Helpers ----

def _quality_rubric() -> EvalRubric:
    return EvalRubric(
        rubric_id="test-quality",
        name="Test Quality",
        dimensions=(
            EvalDimension(name="accuracy", description="How accurate", weight=1.0),
            EvalDimension(name="completeness", description="How complete", weight=0.8),
        ),
    )


def _make_historical_items(count: int = 3) -> list[dict[str, Any]]:
    return [
        {
            "id": f"wi-{i}",
            "data": {"query": f"test-{i}"},
            "status": "completed",
            "results": {"agent-1": {"output": f"result-{i}"}},
            "confidence": 0.7,
            "phases_completed": 2,
        }
        for i in range(count)
    ]


# ---- Evaluator Model Tests ----

class TestEvalModels:
    def test_eval_dimension_frozen(self) -> None:
        dim = EvalDimension(name="accuracy", description="test", weight=1.0)
        assert dim.name == "accuracy"
        with pytest.raises(AttributeError):
            dim.name = "other"  # type: ignore[misc]

    def test_eval_rubric_frozen(self) -> None:
        rubric = _quality_rubric()
        assert rubric.rubric_id == "test-quality"
        assert len(rubric.dimensions) == 2
        with pytest.raises(AttributeError):
            rubric.name = "other"  # type: ignore[misc]

    def test_eval_rubric_to_dict(self) -> None:
        rubric = _quality_rubric()
        d = rubric.to_dict()
        assert d["rubric_id"] == "test-quality"
        assert len(d["dimensions"]) == 2
        assert d["dimensions"][0]["name"] == "accuracy"

    def test_eval_rubric_from_dict(self) -> None:
        rubric = _quality_rubric()
        d = rubric.to_dict()
        restored = EvalRubric.from_dict(d)
        assert restored.rubric_id == rubric.rubric_id
        assert len(restored.dimensions) == len(rubric.dimensions)
        assert restored.dimensions[0].name == "accuracy"

    def test_eval_score(self) -> None:
        score = EvalScore(dimension="accuracy", score=0.85, reasoning="Good")
        assert score.score == 0.85

    def test_eval_result_to_dict(self) -> None:
        result = EvalResult(
            rubric_id="r1",
            work_id="w1",
            agent_id="a1",
            phase_id="p1",
            scores=[EvalScore(dimension="accuracy", score=0.9, reasoning="Great")],
            aggregate_score=0.9,
        )
        d = result.to_dict()
        assert d["rubric_id"] == "r1"
        assert len(d["scores"]) == 1
        assert d["aggregate_score"] == 0.9

    def test_builtin_rubrics_exist(self) -> None:
        assert DEFAULT_QUALITY_RUBRIC.rubric_id == "builtin-quality"
        assert len(DEFAULT_QUALITY_RUBRIC.dimensions) == 4
        assert DEFAULT_SAFETY_RUBRIC.rubric_id == "builtin-safety"
        assert len(DEFAULT_SAFETY_RUBRIC.dimensions) == 4


# ---- LLMJudgeEvaluator Tests ----

class TestLLMJudgeEvaluator:
    @pytest.mark.asyncio()
    async def test_evaluate_success(self) -> None:
        llm_response = json.dumps({
            "accuracy": {"score": 0.9, "reasoning": "Very accurate"},
            "completeness": {"score": 0.8, "reasoning": "Mostly complete"},
        })
        mock_fn = AsyncMock(return_value={"response": llm_response})
        evaluator = LLMJudgeEvaluator(llm_call_fn=mock_fn)
        rubric = _quality_rubric()

        result = await evaluator.evaluate(
            rubric=rubric,
            agent_output={"text": "Hello world"},
            work_item_context={"query": "test"},
            agent_id="agent-1",
            phase_id="phase-1",
            work_id="work-1",
        )

        assert result.rubric_id == "test-quality"
        assert result.work_id == "work-1"
        assert result.agent_id == "agent-1"
        assert len(result.scores) == 2
        assert result.scores[0].dimension == "accuracy"
        assert result.scores[0].score == 0.9
        # Weighted aggregate: (0.9*1.0 + 0.8*0.8) / (1.0 + 0.8) = 1.54/1.8
        expected_agg = round((0.9 * 1.0 + 0.8 * 0.8) / (1.0 + 0.8), 4)
        assert result.aggregate_score == expected_agg

    @pytest.mark.asyncio()
    async def test_evaluate_unparseable_response(self) -> None:
        mock_fn = AsyncMock(return_value={"response": "not valid json"})
        evaluator = LLMJudgeEvaluator(llm_call_fn=mock_fn)
        rubric = _quality_rubric()

        result = await evaluator.evaluate(
            rubric=rubric,
            agent_output={"text": "test"},
            work_item_context={},
        )

        # Should fallback to 0.5 for all dimensions
        assert len(result.scores) == 2
        for score in result.scores:
            assert score.score == 0.5

    @pytest.mark.asyncio()
    async def test_evaluate_llm_exception(self) -> None:
        mock_fn = AsyncMock(side_effect=RuntimeError("LLM down"))
        evaluator = LLMJudgeEvaluator(llm_call_fn=mock_fn)
        rubric = _quality_rubric()

        result = await evaluator.evaluate(
            rubric=rubric,
            agent_output={"text": "test"},
            work_item_context={},
        )

        assert len(result.scores) == 2
        for score in result.scores:
            assert score.score == 0.5

    @pytest.mark.asyncio()
    async def test_evaluate_with_markdown_fences(self) -> None:
        llm_response = '```json\n{"accuracy": {"score": 0.7, "reasoning": "OK"}, "completeness": {"score": 0.6, "reasoning": "Partial"}}\n```'
        mock_fn = AsyncMock(return_value={"response": llm_response})
        evaluator = LLMJudgeEvaluator(llm_call_fn=mock_fn)
        rubric = _quality_rubric()

        result = await evaluator.evaluate(
            rubric=rubric,
            agent_output={},
            work_item_context={},
        )

        assert result.scores[0].score == 0.7
        assert result.scores[1].score == 0.6

    @pytest.mark.asyncio()
    async def test_evaluate_batch(self) -> None:
        call_count = 0

        async def mock_fn(*args: Any, **kwargs: Any) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            return {"response": json.dumps({
                "accuracy": {"score": 0.8, "reasoning": "Good"},
                "completeness": {"score": 0.7, "reasoning": "OK"},
            })}

        evaluator = LLMJudgeEvaluator(llm_call_fn=mock_fn)
        rubric = _quality_rubric()

        results = await evaluator.evaluate_batch(
            rubric=rubric,
            results=[
                ({"output": "a"}, {"ctx": "1"}),
                ({"output": "b"}, {"ctx": "2"}),
            ],
            agent_id="a1",
            work_id_prefix="batch-",
        )

        assert len(results) == 2
        assert call_count == 2
        assert results[0].work_id == "batch-0"
        assert results[1].work_id == "batch-1"

    @pytest.mark.asyncio()
    async def test_evaluate_numeric_scores(self) -> None:
        """LLM returns bare numbers instead of objects."""
        llm_response = json.dumps({
            "accuracy": 0.95,
            "completeness": 0.85,
        })
        mock_fn = AsyncMock(return_value={"response": llm_response})
        evaluator = LLMJudgeEvaluator(llm_call_fn=mock_fn)
        rubric = _quality_rubric()

        result = await evaluator.evaluate(
            rubric=rubric,
            agent_output={},
            work_item_context={},
        )

        assert result.scores[0].score == 0.95
        assert result.scores[1].score == 0.85

    @pytest.mark.asyncio()
    async def test_evaluate_clamps_scores(self) -> None:
        llm_response = json.dumps({
            "accuracy": {"score": 1.5, "reasoning": "Over"},
            "completeness": {"score": -0.3, "reasoning": "Under"},
        })
        mock_fn = AsyncMock(return_value={"response": llm_response})
        evaluator = LLMJudgeEvaluator(llm_call_fn=mock_fn)
        rubric = _quality_rubric()

        result = await evaluator.evaluate(
            rubric=rubric,
            agent_output={},
            work_item_context={},
        )

        assert result.scores[0].score == 1.0
        assert result.scores[1].score == 0.0


# ---- RubricStore Tests ----

class TestRubricStore:
    def test_list_includes_builtins(self, tmp_path: Path) -> None:
        store = RubricStore(tmp_path / "rubrics")
        rubrics = store.list_rubrics()
        ids = [r.rubric_id for r in rubrics]
        assert "builtin-quality" in ids
        assert "builtin-safety" in ids

    def test_save_and_load(self, tmp_path: Path) -> None:
        store = RubricStore(tmp_path / "rubrics")
        rubric = _quality_rubric()
        store.save_rubric(rubric)

        loaded = store.load_rubric("test-quality")
        assert loaded is not None
        assert loaded.rubric_id == "test-quality"
        assert len(loaded.dimensions) == 2

    def test_load_builtin(self, tmp_path: Path) -> None:
        store = RubricStore(tmp_path / "rubrics")
        rubric = store.load_rubric("builtin-quality")
        assert rubric is not None
        assert rubric.name == "Default Quality Rubric"

    def test_load_nonexistent(self, tmp_path: Path) -> None:
        store = RubricStore(tmp_path / "rubrics")
        assert store.load_rubric("nonexistent") is None

    def test_delete(self, tmp_path: Path) -> None:
        store = RubricStore(tmp_path / "rubrics")
        rubric = _quality_rubric()
        store.save_rubric(rubric)

        assert store.delete_rubric("test-quality") is True
        assert store.load_rubric("test-quality") is None

    def test_delete_nonexistent(self, tmp_path: Path) -> None:
        store = RubricStore(tmp_path / "rubrics")
        assert store.delete_rubric("nonexistent") is False

    def test_delete_builtin_rejected(self, tmp_path: Path) -> None:
        store = RubricStore(tmp_path / "rubrics")
        assert store.delete_rubric("builtin-quality") is False

    def test_list_rubrics(self, tmp_path: Path) -> None:
        store = RubricStore(tmp_path / "rubrics")
        rubric = _quality_rubric()
        store.save_rubric(rubric)

        rubrics = store.list_rubrics()
        ids = [r.rubric_id for r in rubrics]
        assert "builtin-quality" in ids
        assert "builtin-safety" in ids
        assert "test-quality" in ids

    def test_persistence_across_instances(self, tmp_path: Path) -> None:
        store1 = RubricStore(tmp_path / "rubrics")
        store1.save_rubric(_quality_rubric())

        store2 = RubricStore(tmp_path / "rubrics")
        loaded = store2.load_rubric("test-quality")
        assert loaded is not None
        assert loaded.rubric_id == "test-quality"


# ---- ABTestRunner Tests ----

class TestABTestRunner:
    @pytest.mark.asyncio()
    async def test_run_test_dry_run(self) -> None:
        sandbox = SimulationSandbox()
        runner = ABTestRunner(sandbox)
        config = ABTestConfig(
            test_id="ab-001",
            name="Test A/B",
            variant_a={"version": "v1"},
            variant_b={"version": "v2"},
        )
        items = _make_historical_items(3)

        result = await runner.run_test(config, items)

        assert result.test_id == "ab-001"
        assert result.variant_a_results.items_processed == 3
        assert result.variant_b_results.items_processed == 3
        # Both dry runs produce same results, so should be tie
        assert result.comparison.winner == "tie"
        assert result.comparison.items_tied == 3
        assert result.duration_seconds >= 0

    @pytest.mark.asyncio()
    async def test_run_test_respects_max_items(self) -> None:
        sandbox = SimulationSandbox()
        runner = ABTestRunner(sandbox)
        config = ABTestConfig(
            test_id="ab-002",
            name="Limited",
            max_items=2,
        )
        items = _make_historical_items(5)

        result = await runner.run_test(config, items)

        assert result.variant_a_results.items_processed == 2
        assert result.variant_b_results.items_processed == 2

    @pytest.mark.asyncio()
    async def test_summarize(self) -> None:
        sandbox = SimulationSandbox()
        runner = ABTestRunner(sandbox)
        config = ABTestConfig(test_id="ab-003", name="Summary Test")
        items = _make_historical_items(2)

        result = await runner.run_test(config, items)
        summary = runner.summarize(result)

        assert summary["test_id"] == "ab-003"
        assert "winner" in summary
        assert "a_pass_rate" in summary
        assert "b_pass_rate" in summary
        assert "duration_seconds" in summary
        assert summary["total_items"] == 2


# ---- DatasetStore Tests ----

class TestDatasetStore:
    def test_create_and_load(self, tmp_path: Path) -> None:
        store = DatasetStore(tmp_path / "datasets")
        items = [{"id": "1", "data": {"q": "test"}}]
        dataset = store.create_from_work_items("Test DS", items)

        loaded = store.load_dataset(dataset.dataset_id)
        assert loaded is not None
        assert loaded.name == "Test DS"
        assert len(loaded.items) == 1

    def test_save_and_load(self, tmp_path: Path) -> None:
        store = DatasetStore(tmp_path / "datasets")
        ds = EvalDataset(
            dataset_id="ds-001",
            name="Manual",
            items=[{"data": "test"}],
            tags=["eval"],
        )
        store.save_dataset(ds)

        loaded = store.load_dataset("ds-001")
        assert loaded is not None
        assert loaded.name == "Manual"
        assert loaded.tags == ["eval"]

    def test_load_nonexistent(self, tmp_path: Path) -> None:
        store = DatasetStore(tmp_path / "datasets")
        assert store.load_dataset("nonexistent") is None

    def test_list_datasets(self, tmp_path: Path) -> None:
        store = DatasetStore(tmp_path / "datasets")
        store.create_from_work_items("DS1", [{"id": "1"}])
        store.create_from_work_items("DS2", [{"id": "2"}])

        datasets = store.list_datasets()
        assert len(datasets) == 2

    def test_delete(self, tmp_path: Path) -> None:
        store = DatasetStore(tmp_path / "datasets")
        ds = store.create_from_work_items("Delete Me", [{"id": "1"}])

        assert store.delete_dataset(ds.dataset_id) is True
        assert store.load_dataset(ds.dataset_id) is None

    def test_delete_nonexistent(self, tmp_path: Path) -> None:
        store = DatasetStore(tmp_path / "datasets")
        assert store.delete_dataset("nonexistent") is False

    def test_persistence_across_instances(self, tmp_path: Path) -> None:
        store1 = DatasetStore(tmp_path / "datasets")
        ds = store1.create_from_work_items("Persist", [{"id": "1"}])

        store2 = DatasetStore(tmp_path / "datasets")
        loaded = store2.load_dataset(ds.dataset_id)
        assert loaded is not None
        assert loaded.name == "Persist"

    def test_to_dict_from_dict(self) -> None:
        ds = EvalDataset(
            dataset_id="ds-round",
            name="Round Trip",
            items=[{"id": "1"}],
            tags=["test"],
            version=2,
        )
        d = ds.to_dict()
        restored = EvalDataset.from_dict(d)
        assert restored.dataset_id == "ds-round"
        assert restored.version == 2
        assert restored.tags == ["test"]


# ---- Simulation Persistence Tests ----

class TestSimulationPersistence:
    @pytest.mark.asyncio()
    async def test_persistence_enabled(self, tmp_path: Path) -> None:
        sandbox = SimulationSandbox(persistence_dir=tmp_path / "sims")
        from agent_orchestrator.simulation.models import SimulationConfig

        config = SimulationConfig(
            simulation_id="persist-sim",
            name="Persist Test",
            dry_run=True,
        )
        items = _make_historical_items(2)
        await sandbox.run_simulation(config=config, historical_items=items)

        # Verify file was written
        sim_file = tmp_path / "sims" / "simulations.jsonl"
        assert sim_file.exists()
        lines = sim_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["simulation_id"] == "persist-sim"

    @pytest.mark.asyncio()
    async def test_persistence_loads_on_init(self, tmp_path: Path) -> None:
        sandbox1 = SimulationSandbox(persistence_dir=tmp_path / "sims")
        from agent_orchestrator.simulation.models import SimulationConfig

        config = SimulationConfig(
            simulation_id="load-test",
            name="Load Test",
            dry_run=True,
        )
        await sandbox1.run_simulation(config=config, historical_items=_make_historical_items(1))

        sandbox2 = SimulationSandbox(persistence_dir=tmp_path / "sims")
        loaded = sandbox2.get_simulation("load-test")
        assert loaded is not None
        assert loaded.simulation_id == "load-test"

    def test_no_persistence_by_default(self) -> None:
        sandbox = SimulationSandbox()
        assert sandbox._persistence_file is None


# ---- Eval Routes Tests ----

def _make_eval_app(
    rubric_store: Any | None = None,
    dataset_store: Any | None = None,
    sandbox: SimulationSandbox | None = None,
) -> TestClient:
    app = FastAPI()
    app.include_router(eval_router, prefix="/api/v1")
    mock_engine = MagicMock()
    mock_engine.rubric_store = rubric_store
    mock_engine.dataset_store = dataset_store
    mock_engine.simulation_sandbox = sandbox or SimulationSandbox()
    mock_engine.llm_adapter = None
    app.state.engine = mock_engine
    return TestClient(app)


class TestEvalRubricRoutes:
    def test_list_rubrics(self, tmp_path: Path) -> None:
        store = RubricStore(tmp_path / "rubrics")
        client = _make_eval_app(rubric_store=store)
        resp = client.get("/api/v1/evals/rubrics")
        assert resp.status_code == 200
        data = resp.json()
        ids = [r["rubric_id"] for r in data]
        assert "builtin-quality" in ids
        assert "builtin-safety" in ids

    def test_create_rubric(self, tmp_path: Path) -> None:
        store = RubricStore(tmp_path / "rubrics")
        client = _make_eval_app(rubric_store=store)
        resp = client.post("/api/v1/evals/rubrics", json={
            "name": "Custom",
            "dimensions": [
                {"name": "speed", "description": "How fast", "weight": 1.0},
            ],
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Custom"
        assert len(data["dimensions"]) == 1
        assert data["rubric_id"].startswith("rubric-")

    def test_get_rubric(self, tmp_path: Path) -> None:
        store = RubricStore(tmp_path / "rubrics")
        client = _make_eval_app(rubric_store=store)
        resp = client.get("/api/v1/evals/rubrics/builtin-quality")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Default Quality Rubric"

    def test_get_rubric_not_found(self, tmp_path: Path) -> None:
        store = RubricStore(tmp_path / "rubrics")
        client = _make_eval_app(rubric_store=store)
        resp = client.get("/api/v1/evals/rubrics/nonexistent")
        assert resp.status_code == 404

    def test_delete_rubric(self, tmp_path: Path) -> None:
        store = RubricStore(tmp_path / "rubrics")
        store.save_rubric(_quality_rubric())
        client = _make_eval_app(rubric_store=store)
        resp = client.delete("/api/v1/evals/rubrics/test-quality")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

    def test_delete_rubric_not_found(self, tmp_path: Path) -> None:
        store = RubricStore(tmp_path / "rubrics")
        client = _make_eval_app(rubric_store=store)
        resp = client.delete("/api/v1/evals/rubrics/nonexistent")
        assert resp.status_code == 404

    def test_no_engine(self) -> None:
        app = FastAPI()
        app.include_router(eval_router, prefix="/api/v1")
        app.state.engine = None
        client = TestClient(app)
        resp = client.get("/api/v1/evals/rubrics")
        assert resp.status_code == 503


class TestEvalDatasetRoutes:
    def test_create_dataset(self, tmp_path: Path) -> None:
        store = DatasetStore(tmp_path / "datasets")
        client = _make_eval_app(dataset_store=store)
        resp = client.post("/api/v1/evals/datasets", json={
            "name": "Test Dataset",
            "items": [{"id": "1", "data": "test"}],
            "tags": ["eval"],
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Test Dataset"
        assert data["item_count"] == 1

    def test_list_datasets(self, tmp_path: Path) -> None:
        store = DatasetStore(tmp_path / "datasets")
        store.create_from_work_items("DS1", [{"id": "1"}])
        client = _make_eval_app(dataset_store=store)
        resp = client.get("/api/v1/evals/datasets")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_get_dataset(self, tmp_path: Path) -> None:
        store = DatasetStore(tmp_path / "datasets")
        ds = store.create_from_work_items("DS1", [{"id": "1"}])
        client = _make_eval_app(dataset_store=store)
        resp = client.get(f"/api/v1/evals/datasets/{ds.dataset_id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "DS1"

    def test_get_dataset_not_found(self, tmp_path: Path) -> None:
        store = DatasetStore(tmp_path / "datasets")
        client = _make_eval_app(dataset_store=store)
        resp = client.get("/api/v1/evals/datasets/nonexistent")
        assert resp.status_code == 404

    def test_delete_dataset(self, tmp_path: Path) -> None:
        store = DatasetStore(tmp_path / "datasets")
        ds = store.create_from_work_items("Delete Me", [{"id": "1"}])
        client = _make_eval_app(dataset_store=store)
        resp = client.delete(f"/api/v1/evals/datasets/{ds.dataset_id}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

    def test_delete_dataset_not_found(self, tmp_path: Path) -> None:
        store = DatasetStore(tmp_path / "datasets")
        client = _make_eval_app(dataset_store=store)
        resp = client.delete("/api/v1/evals/datasets/nonexistent")
        assert resp.status_code == 404


class TestEvalABTestRoute:
    def test_ab_test_with_inline_items(self, tmp_path: Path) -> None:
        rubric_store = RubricStore(tmp_path / "rubrics")
        ds_store = DatasetStore(tmp_path / "datasets")
        sandbox = SimulationSandbox()
        client = _make_eval_app(
            rubric_store=rubric_store,
            dataset_store=ds_store,
            sandbox=sandbox,
        )
        resp = client.post("/api/v1/evals/ab-test", json={
            "name": "Route AB Test",
            "variant_a": {"v": "a"},
            "variant_b": {"v": "b"},
            "historical_items": _make_historical_items(2),
        })
        assert resp.status_code == 201
        data = resp.json()
        assert "winner" in data
        assert data["total_items"] == 2

    def test_ab_test_with_dataset(self, tmp_path: Path) -> None:
        rubric_store = RubricStore(tmp_path / "rubrics")
        ds_store = DatasetStore(tmp_path / "datasets")
        ds = ds_store.create_from_work_items("AB DS", _make_historical_items(3))
        sandbox = SimulationSandbox()
        client = _make_eval_app(
            rubric_store=rubric_store,
            dataset_store=ds_store,
            sandbox=sandbox,
        )
        resp = client.post("/api/v1/evals/ab-test", json={
            "name": "Dataset AB",
            "dataset_id": ds.dataset_id,
        })
        assert resp.status_code == 201
        assert resp.json()["total_items"] == 3

    def test_ab_test_no_items(self, tmp_path: Path) -> None:
        rubric_store = RubricStore(tmp_path / "rubrics")
        ds_store = DatasetStore(tmp_path / "datasets")
        sandbox = SimulationSandbox()
        client = _make_eval_app(
            rubric_store=rubric_store,
            dataset_store=ds_store,
            sandbox=sandbox,
        )
        resp = client.post("/api/v1/evals/ab-test", json={
            "name": "Empty",
        })
        assert resp.status_code == 400


class TestEvalEvaluateRoute:
    def test_evaluate_no_llm_adapter(self, tmp_path: Path) -> None:
        rubric_store = RubricStore(tmp_path / "rubrics")
        client = _make_eval_app(rubric_store=rubric_store)
        resp = client.post("/api/v1/evals/evaluate", json={
            "rubric_id": "builtin-quality",
            "agent_output": {"text": "hello"},
            "context": {},
        })
        assert resp.status_code == 503

    def test_evaluate_rubric_not_found(self, tmp_path: Path) -> None:
        rubric_store = RubricStore(tmp_path / "rubrics")
        client = _make_eval_app(rubric_store=rubric_store)
        resp = client.post("/api/v1/evals/evaluate", json={
            "rubric_id": "nonexistent",
            "agent_output": {},
            "context": {},
        })
        assert resp.status_code == 404
