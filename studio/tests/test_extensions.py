"""Tests for extension stub generation."""

import tempfile
from pathlib import Path

import pytest

from studio.extensions.generator import (
    generate_all_stubs,
    generate_connector_stub,
    generate_event_handler_stub,
    generate_hook_stub,
)
from studio.ir.models import TeamSpec


class TestConnectorStub:
    def test_generates_valid_python(self) -> None:
        code = generate_connector_stub("my-api", "My Custom API", "EXTERNAL_API")
        assert "class MyApiProvider:" in code
        assert "def execute(" in code
        assert "def get_descriptor(" in code
        assert "my-api" in code
        # Verify it compiles
        compile(code, "<test>", "exec")

    def test_class_name_from_provider_id(self) -> None:
        code = generate_connector_stub("slack-webhook", "Slack Webhook", "MESSAGING")
        assert "class SlackWebhookProvider:" in code


class TestEventHandlerStub:
    def test_generates_valid_python(self) -> None:
        code = generate_event_handler_stub("my-handler", ["work_item.submitted"])
        assert "class MyHandlerHandler:" in code
        assert "def handle(" in code
        assert "work_item.submitted" in code
        compile(code, "<test>", "exec")

    def test_default_events(self) -> None:
        code = generate_event_handler_stub("default")
        assert "work_item.submitted" in code
        assert "phase.completed" in code


class TestHookStub:
    def test_generates_valid_python(self) -> None:
        code = generate_hook_stub("analysis")
        assert "def hook_analysis(" in code
        assert "context: dict" in code
        assert "return context" in code
        compile(code, "<test>", "exec")

    def test_custom_name(self) -> None:
        code = generate_hook_stub("review", hook_name="pre_review")
        assert "def pre_review(" in code


class TestGenerateAllStubs:
    def test_generates_stubs(self, content_moderation_team: TeamSpec) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = generate_all_stubs(content_moderation_team, Path(tmp))
            assert len(result.files) > 0
            assert len(result.written) > 0
            # Check files actually exist
            for path in result.written:
                assert path.exists()
                assert path.stat().st_size > 0
