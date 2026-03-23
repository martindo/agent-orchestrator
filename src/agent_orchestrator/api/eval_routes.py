"""REST API routes for evaluation, rubrics, A/B tests, and datasets.

Provides endpoints for LLM-as-judge evaluation, rubric management,
A/B test execution, and evaluation dataset CRUD.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

eval_router = APIRouter()


# ---- Request Models ----


class EvalDimensionRequest(BaseModel):
    """A single dimension in a rubric create request."""

    name: str
    description: str = ""
    weight: float = 1.0


class CreateRubricRequest(BaseModel):
    """Request body for creating an evaluation rubric."""

    name: str
    description: str = ""
    dimensions: list[EvalDimensionRequest] = Field(default_factory=list)
    system_prompt: str = ""


class EvaluateRequest(BaseModel):
    """Request body for running an LLM-as-judge evaluation."""

    rubric_id: str
    agent_output: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    agent_id: str = ""
    phase_id: str = ""
    work_id: str = ""


class ABTestRequest(BaseModel):
    """Request body for running an A/B test."""

    name: str = "A/B Test"
    variant_a: dict[str, Any] = Field(default_factory=dict)
    variant_b: dict[str, Any] = Field(default_factory=dict)
    dataset_id: str = ""
    max_items: int = 100
    historical_items: list[dict[str, Any]] = Field(default_factory=list)


class CreateDatasetRequest(BaseModel):
    """Request body for creating an evaluation dataset."""

    name: str
    description: str = ""
    items: list[dict[str, Any]] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


# ---- Helpers ----


def _get_rubric_store(request: Request) -> Any:
    """Extract RubricStore from engine, raising 503 if unavailable.

    Args:
        request: The incoming HTTP request.

    Returns:
        The RubricStore instance.

    Raises:
        HTTPException: 503 if unavailable.
    """
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    store = getattr(engine, "rubric_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Rubric store not initialized")
    return store


def _get_dataset_store(request: Request) -> Any:
    """Extract DatasetStore from engine, raising 503 if unavailable.

    Args:
        request: The incoming HTTP request.

    Returns:
        The DatasetStore instance.

    Raises:
        HTTPException: 503 if unavailable.
    """
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    store = getattr(engine, "dataset_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Dataset store not initialized")
    return store


def _get_sandbox(request: Request) -> Any:
    """Extract SimulationSandbox from engine, raising 503 if unavailable.

    Args:
        request: The incoming HTTP request.

    Returns:
        The SimulationSandbox instance.

    Raises:
        HTTPException: 503 if unavailable.
    """
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    sandbox = getattr(engine, "simulation_sandbox", None)
    if sandbox is None:
        raise HTTPException(status_code=503, detail="Simulation sandbox not initialized")
    return sandbox


# ---- Rubric Routes ----


@eval_router.get("/evals/rubrics")
async def list_rubrics(request: Request) -> list[dict[str, Any]]:
    """List all evaluation rubrics.

    Returns:
        All rubrics (built-in and user-created).
    """
    store = _get_rubric_store(request)
    rubrics = store.list_rubrics()
    return [r.to_dict() for r in rubrics]


@eval_router.post("/evals/rubrics", status_code=201)
async def create_rubric(
    body: CreateRubricRequest,
    request: Request,
) -> dict[str, Any]:
    """Create a new evaluation rubric.

    Args:
        body: Rubric definition.
        request: The incoming HTTP request.

    Returns:
        The created rubric.
    """
    store = _get_rubric_store(request)

    from agent_orchestrator.simulation.evaluator import EvalDimension, EvalRubric

    rubric = EvalRubric(
        rubric_id=f"rubric-{uuid.uuid4().hex[:8]}",
        name=body.name,
        description=body.description,
        dimensions=tuple(
            EvalDimension(
                name=d.name,
                description=d.description,
                weight=d.weight,
            )
            for d in body.dimensions
        ),
        system_prompt=body.system_prompt,
    )

    store.save_rubric(rubric)
    logger.info("Created rubric %s with %d dimensions", rubric.rubric_id, len(rubric.dimensions))
    return rubric.to_dict()


@eval_router.get("/evals/rubrics/{rubric_id}")
async def get_rubric(
    rubric_id: str,
    request: Request,
) -> dict[str, Any]:
    """Get an evaluation rubric by ID.

    Args:
        rubric_id: The rubric identifier.
        request: The incoming HTTP request.

    Returns:
        The rubric.
    """
    store = _get_rubric_store(request)
    rubric = store.load_rubric(rubric_id)
    if rubric is None:
        raise HTTPException(
            status_code=404,
            detail=f"Rubric '{rubric_id}' not found",
        )
    return rubric.to_dict()


@eval_router.delete("/evals/rubrics/{rubric_id}")
async def delete_rubric(
    rubric_id: str,
    request: Request,
) -> dict[str, Any]:
    """Delete an evaluation rubric.

    Args:
        rubric_id: The rubric to delete.
        request: The incoming HTTP request.

    Returns:
        Deletion confirmation.
    """
    store = _get_rubric_store(request)
    deleted = store.delete_rubric(rubric_id)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Rubric '{rubric_id}' not found or is a built-in rubric",
        )
    logger.info("Deleted rubric %s", rubric_id)
    return {"rubric_id": rubric_id, "deleted": True}


# ---- Evaluate Route ----


@eval_router.post("/evals/evaluate", status_code=200)
async def run_evaluation(
    body: EvaluateRequest,
    request: Request,
) -> dict[str, Any]:
    """Run an LLM-as-judge evaluation.

    Args:
        body: Evaluation request with rubric_id, agent output, and context.
        request: The incoming HTTP request.

    Returns:
        Evaluation result with per-dimension scores.
    """
    store = _get_rubric_store(request)
    rubric = store.load_rubric(body.rubric_id)
    if rubric is None:
        raise HTTPException(
            status_code=404,
            detail=f"Rubric '{body.rubric_id}' not found",
        )

    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    # Get LLM call function
    llm_adapter = getattr(engine, "llm_adapter", None)
    if llm_adapter is None:
        raise HTTPException(
            status_code=503,
            detail="LLM adapter not initialized — cannot run evaluation",
        )

    from agent_orchestrator.configuration.models import LLMConfig
    from agent_orchestrator.simulation.evaluator import LLMJudgeEvaluator

    # Wrap adapter.call with a default LLMConfig for the evaluator
    default_llm_config = LLMConfig(provider="openai", model="gpt-4o")

    async def _eval_llm_call(system_prompt: str, user_prompt: str) -> dict[str, Any]:
        return await llm_adapter.call(system_prompt, user_prompt, default_llm_config)

    evaluator = LLMJudgeEvaluator(llm_call_fn=_eval_llm_call)
    result = await evaluator.evaluate(
        rubric=rubric,
        agent_output=body.agent_output,
        work_item_context=body.context,
        agent_id=body.agent_id,
        phase_id=body.phase_id,
        work_id=body.work_id,
    )

    logger.info(
        "Evaluation completed: rubric=%s, aggregate=%.3f",
        body.rubric_id, result.aggregate_score,
    )
    return result.to_dict()


# ---- A/B Test Route ----


@eval_router.post("/evals/ab-test", status_code=201)
async def run_ab_test(
    body: ABTestRequest,
    request: Request,
) -> dict[str, Any]:
    """Run an A/B test comparing two workflow variants.

    Args:
        body: A/B test configuration.
        request: The incoming HTTP request.

    Returns:
        A/B test summary with winner and metrics.
    """
    sandbox = _get_sandbox(request)

    from agent_orchestrator.simulation.ab_test import ABTestConfig, ABTestRunner

    test_config = ABTestConfig(
        test_id=f"ab-{uuid.uuid4().hex[:8]}",
        name=body.name,
        variant_a=body.variant_a,
        variant_b=body.variant_b,
        dataset_id=body.dataset_id,
        max_items=body.max_items,
    )

    # Get items from dataset store or inline
    items = body.historical_items
    if not items and body.dataset_id:
        ds_store = _get_dataset_store(request)
        dataset = ds_store.load_dataset(body.dataset_id)
        if dataset is not None:
            items = dataset.items

    if not items:
        raise HTTPException(
            status_code=400,
            detail="No items provided — supply historical_items or a valid dataset_id",
        )

    runner = ABTestRunner(sandbox)
    result = await runner.run_test(test_config, items)
    summary = runner.summarize(result)

    logger.info(
        "A/B test %s completed: winner=%s",
        test_config.test_id, result.comparison.winner,
    )
    return summary


# ---- Dataset Routes ----


@eval_router.get("/evals/datasets")
async def list_datasets(request: Request) -> list[dict[str, Any]]:
    """List all evaluation datasets.

    Returns:
        All datasets, newest first.
    """
    store = _get_dataset_store(request)
    datasets = store.list_datasets()
    return [
        {
            "dataset_id": d.dataset_id,
            "name": d.name,
            "description": d.description,
            "item_count": len(d.items),
            "created_at": d.created_at,
            "tags": d.tags,
            "version": d.version,
        }
        for d in datasets
    ]


@eval_router.post("/evals/datasets", status_code=201)
async def create_dataset(
    body: CreateDatasetRequest,
    request: Request,
) -> dict[str, Any]:
    """Create a new evaluation dataset.

    Args:
        body: Dataset definition with items.
        request: The incoming HTTP request.

    Returns:
        The created dataset summary.
    """
    store = _get_dataset_store(request)
    dataset = store.create_from_work_items(
        name=body.name,
        items=body.items,
        description=body.description,
        tags=body.tags,
    )
    logger.info("Created dataset %s with %d items", dataset.dataset_id, len(dataset.items))
    return {
        "dataset_id": dataset.dataset_id,
        "name": dataset.name,
        "description": dataset.description,
        "item_count": len(dataset.items),
        "created_at": dataset.created_at,
        "tags": dataset.tags,
        "version": dataset.version,
    }


@eval_router.get("/evals/datasets/{dataset_id}")
async def get_dataset(
    dataset_id: str,
    request: Request,
) -> dict[str, Any]:
    """Get an evaluation dataset by ID.

    Args:
        dataset_id: The dataset identifier.
        request: The incoming HTTP request.

    Returns:
        The dataset with items.
    """
    store = _get_dataset_store(request)
    dataset = store.load_dataset(dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=404,
            detail=f"Dataset '{dataset_id}' not found",
        )
    return dataset.to_dict()


@eval_router.delete("/evals/datasets/{dataset_id}")
async def delete_dataset(
    dataset_id: str,
    request: Request,
) -> dict[str, Any]:
    """Delete an evaluation dataset.

    Args:
        dataset_id: The dataset to delete.
        request: The incoming HTTP request.

    Returns:
        Deletion confirmation.
    """
    store = _get_dataset_store(request)
    deleted = store.delete_dataset(dataset_id)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Dataset '{dataset_id}' not found",
        )
    logger.info("Deleted dataset %s", dataset_id)
    return {"dataset_id": dataset_id, "deleted": True}
