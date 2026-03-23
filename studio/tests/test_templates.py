"""Tests for template import/export."""

import tempfile
from pathlib import Path

import pytest

from studio.templates.manager import (
    export_template,
    import_template,
    list_templates,
)
from studio.ir.models import TeamSpec


class TestImportTemplate:
    def test_import_content_moderation(self) -> None:
        team = import_template(Path("profiles/content-moderation"))
        assert team.name == "Content Moderation Pipeline"
        assert len(team.agents) == 3
        assert len(team.workflow.phases) == 4
        assert len(team.workflow.statuses) == 7
        assert len(team.governance.policies) == 5
        assert len(team.work_item_types) == 2

    def test_import_nonexistent(self) -> None:
        from studio.exceptions import TemplateImportError
        with pytest.raises(TemplateImportError):
            import_template(Path("/nonexistent/path"))

    def test_agent_details(self) -> None:
        team = import_template(Path("profiles/content-moderation"))
        analyzer = next(a for a in team.agents if a.id == "sentiment-analyzer")
        assert analyzer.llm.provider == "openai"
        assert analyzer.llm.model == "gpt-4o"
        assert analyzer.concurrency == 3
        assert "analysis" in analyzer.phases


class TestExportTemplate:
    def test_roundtrip(self) -> None:
        team1 = import_template(Path("profiles/content-moderation"))
        with tempfile.TemporaryDirectory() as tmp:
            export_template(team1, Path(tmp))
            team2 = import_template(Path(tmp))

        assert team1.name == team2.name
        assert len(team1.agents) == len(team2.agents)
        assert len(team1.workflow.phases) == len(team2.workflow.phases)
        assert len(team1.governance.policies) == len(team2.governance.policies)
        assert len(team1.work_item_types) == len(team2.work_item_types)


class TestListTemplates:
    def test_lists_shipped_templates(self) -> None:
        templates = list_templates(Path("profiles"))
        names = [t["name"] for t in templates]
        assert "content-moderation" in names

    def test_empty_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            templates = list_templates(Path(tmp))
            assert len(templates) == 0
