"""Tests for IR ↔ runtime ProfileConfig conversion."""

import pytest
from studio.conversion.converter import ir_to_profile_dict
from studio.ir.models import TeamSpec


class TestIRToProfileDict:
    def test_converts_team(self, content_moderation_team: TeamSpec) -> None:
        d = ir_to_profile_dict(content_moderation_team)
        assert d["name"] == "Content Moderation Pipeline"
        assert len(d["agents"]) == 3
        assert d["agents"][0]["id"] == "sentiment-analyzer"
        assert d["agents"][0]["llm"]["provider"] == "openai"

    def test_workflow_structure(self, content_moderation_team: TeamSpec) -> None:
        d = ir_to_profile_dict(content_moderation_team)
        wf = d["workflow"]
        assert wf["name"] == "Content Moderation Pipeline"
        assert len(wf["statuses"]) == 7
        assert len(wf["phases"]) == 4

    def test_governance_structure(self, content_moderation_team: TeamSpec) -> None:
        d = ir_to_profile_dict(content_moderation_team)
        gov = d["governance"]
        assert gov["delegated_authority"]["auto_approve_threshold"] == 0.9
        assert len(gov["policies"]) == 2

    def test_work_items_structure(self, content_moderation_team: TeamSpec) -> None:
        d = ir_to_profile_dict(content_moderation_team)
        wits = d["work_item_types"]
        assert len(wits) == 1
        assert wits[0]["id"] == "content-submission"
        assert len(wits[0]["custom_fields"]) == 3

    def test_empty_team(self) -> None:
        team = TeamSpec(name="empty")
        d = ir_to_profile_dict(team)
        assert d["name"] == "empty"
        assert len(d["agents"]) == 0
