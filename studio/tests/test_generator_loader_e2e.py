"""End-to-end: Studio-generated YAML loads into the runtime (audit 5.5).

The generation tests stop at YAML parseability. This proves the stronger claim
that Studio's output is actually accepted by the runtime's profile loader
(`ProfileConfig`), catching schema drift between the two.

Skips when the runtime package isn't installed (e.g. a studio-only environment);
CI installs both so it runs there.
"""

from __future__ import annotations

import pytest

from studio.generation.generator import generate_profile_yaml


def test_generated_profile_loads_into_runtime(content_moderation_team, tmp_path):
    loader = pytest.importorskip("agent_orchestrator.configuration.loader")

    files = generate_profile_yaml(content_moderation_team)
    profile_dir = tmp_path / "profiles" / "content-moderation"
    profile_dir.mkdir(parents=True)
    for name, content in files.items():
        (profile_dir / name).write_text(content, encoding="utf-8")

    # The runtime loads + validates the Studio-generated component YAMLs.
    profile = loader.load_profile(profile_dir)

    assert profile.name == "content-moderation"
    assert len(profile.agents) >= 1
    assert len(profile.workflow.phases) >= 1
    # Every workflow phase references only agents that exist in the profile.
    agent_ids = {a.id for a in profile.agents}
    for phase in profile.workflow.phases:
        for referenced in getattr(phase, "agents", []):
            assert referenced in agent_ids
