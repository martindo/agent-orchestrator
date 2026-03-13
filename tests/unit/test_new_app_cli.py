"""Tests for the new-app CLI scaffolding command."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml
from click.testing import CliRunner

_src_dir = Path(__file__).resolve().parent.parent.parent / "src"
if str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

from agent_orchestrator.cli.commands import main


class TestNewAppCommand:
    """Tests for agent-orchestrator new-app CLI command."""

    def test_scaffolds_basic_app(self, tmp_path: Path) -> None:
        runner = CliRunner()
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        result = runner.invoke(main, ["new-app", "my-test-app", "--workspace", str(workspace)])
        assert result.exit_code == 0, result.output

        profile_dir = workspace / "profiles" / "my-test-app"
        assert profile_dir.is_dir()
        assert (profile_dir / "app.yaml").exists()
        assert (profile_dir / "agents.yaml").exists()
        assert (profile_dir / "workflow.yaml").exists()
        assert (profile_dir / "governance.yaml").exists()
        assert (profile_dir / "workitems.yaml").exists()
        assert (profile_dir / "helpers" / "__init__.py").exists()
        assert (profile_dir / "tests" / "conftest.py").exists()
        assert (profile_dir / "tests" / "test_example.py").exists()

    def test_app_yaml_content(self, tmp_path: Path) -> None:
        runner = CliRunner()
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        runner.invoke(main, ["new-app", "my-app", "--workspace", str(workspace)])

        with open(workspace / "profiles" / "my-app" / "app.yaml", encoding="utf-8") as f:
            manifest = yaml.safe_load(f)

        assert manifest["name"] == "my-app"
        assert manifest["version"] == "0.1.0"
        assert "openai" in manifest["requires"]["providers"]

    def test_agents_yaml_content(self, tmp_path: Path) -> None:
        runner = CliRunner()
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        runner.invoke(main, ["new-app", "my-app", "--workspace", str(workspace)])

        with open(workspace / "profiles" / "my-app" / "agents.yaml", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        assert len(data["agents"]) == 1
        assert data["agents"][0]["id"] == "my-app-agent"
        assert data["agents"][0]["phases"] == ["process"]

    def test_with_hooks_flag(self, tmp_path: Path) -> None:
        runner = CliRunner()
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        result = runner.invoke(
            main, ["new-app", "hook-app", "--workspace", str(workspace), "--with-hooks"],
        )
        assert result.exit_code == 0, result.output

        hooks_file = workspace / "profiles" / "hook-app" / "helpers" / "hooks.py"
        assert hooks_file.exists()

        content = hooks_file.read_text(encoding="utf-8")
        assert "process_hook" in content

        # Verify manifest references the hook
        with open(workspace / "profiles" / "hook-app" / "app.yaml", encoding="utf-8") as f:
            manifest = yaml.safe_load(f)
        assert "process" in manifest["hooks"]

    def test_existing_profile_fails(self, tmp_path: Path) -> None:
        runner = CliRunner()
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        # Create first
        runner.invoke(main, ["new-app", "my-app", "--workspace", str(workspace)])
        # Try again
        result = runner.invoke(main, ["new-app", "my-app", "--workspace", str(workspace)])
        assert result.exit_code != 0

    def test_workflow_has_two_phases(self, tmp_path: Path) -> None:
        runner = CliRunner()
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        runner.invoke(main, ["new-app", "my-app", "--workspace", str(workspace)])

        with open(workspace / "profiles" / "my-app" / "workflow.yaml", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        assert len(data["phases"]) == 2
        assert data["phases"][0]["id"] == "process"
        assert data["phases"][1]["is_terminal"] is True

    def test_generated_tests_importable(self, tmp_path: Path) -> None:
        """Verify the generated test files have valid Python syntax."""
        runner = CliRunner()
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        runner.invoke(main, ["new-app", "my-app", "--workspace", str(workspace)])

        test_file = workspace / "profiles" / "my-app" / "tests" / "test_example.py"
        content = test_file.read_text(encoding="utf-8")
        # Should compile without syntax errors
        compile(content, str(test_file), "exec")
