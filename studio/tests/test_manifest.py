"""Tests for manifest tracker."""

import json
import tempfile
from pathlib import Path

import pytest

from studio.manifest.tracker import FileOwnership, ManifestTracker


class TestManifestTracker:
    def test_empty_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tracker = ManifestTracker(Path(tmp))
            manifest = tracker.get_manifest()
            assert len(manifest.entries) == 0

    def test_update_and_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            # Write a test file
            test_file = tmp_path / "test.yaml"
            test_file.write_text("hello: world", encoding="utf-8")

            tracker = ManifestTracker(tmp_path)
            tracker.update_manifest([test_file], ownership="studio")

            manifest = tracker.get_manifest()
            assert "test.yaml" in manifest.entries
            assert manifest.entries["test.yaml"].ownership == FileOwnership.STUDIO

    def test_user_owned_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            test_file = tmp_path / "stub.py"
            test_file.write_text("# original", encoding="utf-8")

            tracker = ManifestTracker(tmp_path)
            tracker.update_manifest([test_file], ownership="studio")
            tracker.mark_user_owned("stub.py")

            # Modify the file
            test_file.write_text("# user edited", encoding="utf-8")

            conflicts = tracker.check_conflicts()
            assert len(conflicts) == 1
            assert "stub.py" in conflicts[0]

    def test_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            test_file = tmp_path / "agents.yaml"
            test_file.write_text("agents: []", encoding="utf-8")

            # Write manifest
            tracker1 = ManifestTracker(tmp_path)
            tracker1.update_manifest([test_file])

            # Read back with fresh tracker
            tracker2 = ManifestTracker(tmp_path)
            manifest = tracker2.get_manifest()
            assert "agents.yaml" in manifest.entries

    def test_manifest_file_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            test_file = tmp_path / "test.yaml"
            test_file.write_text("test", encoding="utf-8")

            tracker = ManifestTracker(tmp_path)
            tracker.update_manifest([test_file])

            manifest_path = tmp_path / ".studio-manifest.json"
            assert manifest_path.exists()
            data = json.loads(manifest_path.read_text())
            assert "entries" in data
