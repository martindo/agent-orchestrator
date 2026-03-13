"""Tests for app manifest loading and integration."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

_src_dir = Path(__file__).resolve().parent.parent.parent / "src"
if str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

from agent_orchestrator.configuration.loader import load_profile
from agent_orchestrator.configuration.models import AppManifest, ProfileConfig
from agent_orchestrator.exceptions import ConfigurationError
from agent_orchestrator.testing import make_profile, make_workspace


class TestAppManifestModel:
    """Unit tests for the AppManifest Pydantic model."""

    def test_default_manifest(self) -> None:
        manifest = AppManifest()
        assert manifest.name == ""
        assert manifest.version == "0.0.0"
        assert manifest.requires == {}
        assert manifest.produces == {}
        assert manifest.hooks == {}

    def test_manifest_with_values(self) -> None:
        manifest = AppManifest(
            name="test-app",
            version="1.0.0",
            description="A test app",
            platform_version="0.1.0",
            requires={"providers": ["openai"]},
            produces={"work_item_types": ["task"]},
            hooks={"process": "myapp.hooks:process_hook"},
            author="test-user",
        )
        assert manifest.name == "test-app"
        assert manifest.version == "1.0.0"
        assert manifest.requires["providers"] == ["openai"]
        assert manifest.hooks["process"] == "myapp.hooks:process_hook"

    def test_manifest_is_frozen(self) -> None:
        manifest = AppManifest(name="frozen-test")
        with pytest.raises(Exception):
            manifest.name = "changed"


class TestProfileWithManifest:
    """Tests for ProfileConfig with optional manifest field."""

    def test_profile_without_manifest(self) -> None:
        profile = make_profile()
        assert profile.manifest is None

    def test_profile_with_manifest(self) -> None:
        manifest = AppManifest(name="my-app", version="1.0.0")
        profile = ProfileConfig(
            name="test",
            manifest=manifest,
        )
        assert profile.manifest is not None
        assert profile.manifest.name == "my-app"


class TestManifestLoading:
    """Integration tests for loading app.yaml from disk."""

    def test_load_profile_without_manifest(self, tmp_path: Path) -> None:
        workspace = make_workspace(tmp_path)
        profile = load_profile(workspace / "profiles" / "test-profile")
        assert profile.manifest is None

    def test_load_profile_with_manifest(self, tmp_path: Path) -> None:
        workspace = make_workspace(tmp_path)
        profile_dir = workspace / "profiles" / "test-profile"

        manifest_data = {
            "name": "test-app",
            "version": "1.0.0",
            "description": "Test app",
            "requires": {"providers": ["openai"]},
        }
        with open(profile_dir / "app.yaml", "w", encoding="utf-8") as f:
            yaml.dump(manifest_data, f)

        profile = load_profile(profile_dir)
        assert profile.manifest is not None
        assert profile.manifest.name == "test-app"
        assert profile.manifest.version == "1.0.0"

    def test_load_invalid_manifest_raises(self, tmp_path: Path) -> None:
        workspace = make_workspace(tmp_path)
        profile_dir = workspace / "profiles" / "test-profile"

        # Write invalid YAML (list instead of mapping)
        with open(profile_dir / "app.yaml", "w", encoding="utf-8") as f:
            f.write("- invalid\n- manifest\n")

        with pytest.raises(ConfigurationError):
            load_profile(profile_dir)
