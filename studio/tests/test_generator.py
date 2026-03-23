"""Tests for YAML generation."""

import tempfile
from pathlib import Path

import pytest
import yaml

from studio.generation.generator import (
    generate_component_yaml,
    generate_profile_yaml,
    write_profile_to_directory,
)
from studio.ir.models import TeamSpec


class TestGenerateProfileYaml:
    def test_generates_all_files(self, content_moderation_team: TeamSpec) -> None:
        files = generate_profile_yaml(content_moderation_team)
        assert "agents.yaml" in files
        assert "workflow.yaml" in files
        assert "governance.yaml" in files
        assert "workitems.yaml" in files

    def test_agents_yaml_parseable(self, content_moderation_team: TeamSpec) -> None:
        files = generate_profile_yaml(content_moderation_team)
        data = yaml.safe_load(files["agents.yaml"])
        assert "agents" in data
        assert len(data["agents"]) == 3
        assert data["agents"][0]["id"] == "sentiment-analyzer"

    def test_workflow_yaml_parseable(self, content_moderation_team: TeamSpec) -> None:
        files = generate_profile_yaml(content_moderation_team)
        data = yaml.safe_load(files["workflow.yaml"])
        assert data["name"] == "Content Moderation Pipeline"
        assert len(data["phases"]) == 4

    def test_governance_yaml_parseable(self, content_moderation_team: TeamSpec) -> None:
        files = generate_profile_yaml(content_moderation_team)
        data = yaml.safe_load(files["governance.yaml"])
        assert "delegated_authority" in data
        assert "policies" in data

    def test_workitems_yaml_parseable(self, content_moderation_team: TeamSpec) -> None:
        files = generate_profile_yaml(content_moderation_team)
        data = yaml.safe_load(files["workitems.yaml"])
        assert "work_item_types" in data
        assert len(data["work_item_types"]) == 1


class TestGenerateComponentYaml:
    def test_agents_component(self, content_moderation_team: TeamSpec) -> None:
        content = generate_component_yaml(content_moderation_team, "agents")
        data = yaml.safe_load(content)
        assert "agents" in data

    def test_invalid_component(self, content_moderation_team: TeamSpec) -> None:
        from studio.exceptions import GenerationError
        with pytest.raises(GenerationError, match="Unknown component"):
            generate_component_yaml(content_moderation_team, "invalid")


class TestWriteProfileToDirectory:
    def test_writes_files(self, content_moderation_team: TeamSpec) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            files = write_profile_to_directory(content_moderation_team, Path(tmp))
            assert len(files) >= 4
            for f in files:
                assert f.exists()
                assert f.stat().st_size > 0
