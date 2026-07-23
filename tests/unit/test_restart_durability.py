"""Restart-durability tests (audit 3.4 + 3.5).

3.4 — non-terminal work items persisted by a previous run are re-enqueued on
start instead of being orphaned.
3.5 — pending human-review items survive a restart (the ReviewQueue is given a
persistence path).
"""

from __future__ import annotations

import asyncio

import pytest

from agent_orchestrator.core.engine import OrchestrationEngine
from agent_orchestrator.core.work_queue import TERMINAL_STATUSES, WorkItem, WorkItemStatus
from agent_orchestrator.persistence.backend import build_work_item_store

from .test_core import _make_test_config_manager


async def _fake_llm(**kwargs) -> dict:
    return {"response": "ok\nCONFIDENCE: 0.9", "model": "m"}


@pytest.mark.asyncio
async def test_orphaned_work_recovered_on_restart(tmp_path):
    # A prior run persisted an unfinished item, then died.
    config = _make_test_config_manager(tmp_path)
    store = build_work_item_store(config.get_settings(), config.workspace_dir)
    orphan = WorkItem(id="w1", type_id="task", title="Orphan")
    orphan.status = WorkItemStatus.QUEUED
    store.save(orphan)

    # A fresh engine must pick it up and drive it to completion (a stub LLM is
    # injected so processing succeeds). If recovery didn't run, w1 would stay
    # orphaned in the store and never reach a terminal state.
    engine = OrchestrationEngine(config, llm_call_fn=_fake_llm)
    await engine.start()
    try:
        terminal = None
        for _ in range(200):
            await asyncio.sleep(0.05)
            got = store.load("w1")
            if got is not None and got.status.value in TERMINAL_STATUSES:
                terminal = got
                break
    finally:
        await engine.stop()

    assert terminal is not None, "orphaned work item was never recovered/processed"
    assert terminal.status == WorkItemStatus.COMPLETED


@pytest.mark.asyncio
async def test_no_incomplete_work_is_a_noop(tmp_path):
    # Recovery on a clean workspace must not error or enqueue anything.
    config = _make_test_config_manager(tmp_path)
    engine = OrchestrationEngine(config)
    await engine.start()
    try:
        assert engine._queue.size() == 0
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_pending_reviews_survive_restart(tmp_path):
    config = _make_test_config_manager(tmp_path)

    engine1 = OrchestrationEngine(config)
    await engine1.start()
    try:
        engine1._review_queue.enqueue("w1", "process", "needs a human")
        assert engine1._review_queue.pending_count() == 1
        # The queue was given a real persistence path (3.5).
        assert engine1._review_queue._persistence_path is not None
    finally:
        await engine1.stop()

    # A fresh engine on the same workspace reloads the pending review.
    engine2 = OrchestrationEngine(config)
    await engine2.start()
    try:
        assert engine2._review_queue.pending_count() == 1
    finally:
        await engine2.stop()
