"""Tests for skill map REST API routes."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_orchestrator.api.skillmap_routes import skillmap_router
from agent_orchestrator.catalog.skill_map import SkillMap
from agent_orchestrator.catalog.skill_models import SkillRecord


def _make_app(skill_map: SkillMap | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(skillmap_router, prefix="/api/v1")
    if skill_map is not None:
        mock_engine = MagicMock()
        mock_engine.skill_map = skill_map
        app.state.engine = mock_engine
    else:
        app.state.engine = None
    return TestClient(app)


class TestListSkills:
    def test_list_empty(self) -> None:
        client = _make_app(SkillMap())
        resp = client.get("/api/v1/skills")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_with_data(self) -> None:
        sm = SkillMap()
        sm.register_skill(SkillRecord(skill_id="analysis", name="Analysis"))
        client = _make_app(sm)
        resp = client.get("/api/v1/skills")
        assert len(resp.json()) == 1

    def test_no_engine(self) -> None:
        client = _make_app()
        resp = client.get("/api/v1/skills")
        assert resp.status_code == 503


class TestGetSkill:
    def test_get_existing(self) -> None:
        sm = SkillMap()
        sm.register_skill(SkillRecord(skill_id="coding", name="Coding"))
        client = _make_app(sm)
        resp = client.get("/api/v1/skills/coding")
        assert resp.status_code == 200
        assert resp.json()["skill_id"] == "coding"

    def test_get_not_found(self) -> None:
        client = _make_app(SkillMap())
        resp = client.get("/api/v1/skills/missing")
        assert resp.status_code == 404


class TestRegisterSkill:
    def test_register(self) -> None:
        sm = SkillMap()
        client = _make_app(sm)
        resp = client.post("/api/v1/skills", json={
            "skill_id": "new-skill",
            "name": "New Skill",
            "tags": ["test"],
            "agent_ids": ["agent-1"],
        })
        assert resp.status_code == 201
        assert resp.json()["skill_id"] == "new-skill"
        assert sm.get_skill("new-skill") is not None


class TestUnregisterSkill:
    def test_delete(self) -> None:
        sm = SkillMap()
        sm.register_skill(SkillRecord(skill_id="del", name="Delete"))
        client = _make_app(sm)
        resp = client.delete("/api/v1/skills/del")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

    def test_delete_not_found(self) -> None:
        client = _make_app(SkillMap())
        resp = client.delete("/api/v1/skills/missing")
        assert resp.status_code == 404


class TestRecordExecution:
    def test_record(self) -> None:
        sm = SkillMap()
        sm.register_skill(SkillRecord(skill_id="test", name="Test"))
        client = _make_app(sm)
        resp = client.post("/api/v1/skills/test/record", json={
            "agent_id": "agent-1",
            "success": True,
            "confidence": 0.85,
            "duration_seconds": 5.0,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["metrics"]["total_executions"] == 1
        assert data["metrics"]["success_rate"] == 1.0

    def test_record_not_found(self) -> None:
        client = _make_app(SkillMap())
        resp = client.post("/api/v1/skills/missing/record", json={
            "agent_id": "a",
            "success": True,
        })
        assert resp.status_code == 404


class TestCoverageReport:
    def test_coverage(self) -> None:
        sm = SkillMap()
        sm.register_skill(SkillRecord(skill_id="a", name="A", agent_ids=["a1"]))
        sm.register_skill(SkillRecord(skill_id="b", name="B"))
        client = _make_app(sm)
        # Note: /skills/coverage/report must be registered before /skills/{skill_id}
        # FastAPI handles this correctly with path specificity
        resp = client.get("/api/v1/skills/coverage/report")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_skills"] == 2
        assert data["covered_skills"] == 1


class TestAgentProfile:
    def test_profile(self) -> None:
        sm = SkillMap()
        sm.register_skill(SkillRecord(skill_id="s1", name="S1", agent_ids=["agent-x"]))
        sm.record_execution("s1", "agent-x", success=True, confidence=0.9, duration_seconds=2.0)
        client = _make_app(sm)
        resp = client.get("/api/v1/skills/agent/agent-x/profile")
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_id"] == "agent-x"
        assert data["total_executions"] == 1


class TestSummary:
    def test_summary(self) -> None:
        sm = SkillMap()
        sm.register_skill(SkillRecord(skill_id="a", name="A", agent_ids=["a1"]))
        client = _make_app(sm)
        resp = client.get("/api/v1/skills/summary")
        assert resp.status_code == 200
        assert resp.json()["total_skills"] == 1
