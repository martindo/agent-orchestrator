"""Shared test fixtures for Studio tests."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from studio.config import StudioConfig
from studio.ir.models import (
    AgentSpec,
    ConditionSpec,
    DelegatedAuthoritySpec,
    GovernanceSpec,
    LLMSpec,
    OnFailureAction,
    PhaseSpec,
    PolicySpec,
    QualityGateSpec,
    RetryPolicySpec,
    StatusSpec,
    TeamSpec,
    WorkflowSpec,
    WorkItemFieldSpec,
    WorkItemTypeSpec,
    FieldType,
    ArtifactTypeSpec,
)


@pytest.fixture
def content_moderation_team() -> TeamSpec:
    """A realistic content moderation team for testing."""
    return TeamSpec(
        name="Content Moderation Pipeline",
        description="Multi-phase content moderation",
        agents=[
            AgentSpec(
                id="sentiment-analyzer",
                name="Sentiment Analyzer",
                description="Analyzes content sentiment",
                system_prompt="You are a sentiment analysis agent.",
                skills=["sentiment-analysis", "nlp"],
                phases=["analysis"],
                llm=LLMSpec(provider="openai", model="gpt-4o", temperature=0.1, max_tokens=2000),
                concurrency=3,
                retry_policy=RetryPolicySpec(max_retries=2, delay_seconds=1.0, backoff_multiplier=2.0),
            ),
            AgentSpec(
                id="content-reviewer",
                name="Content Reviewer",
                description="Reviews content against policies",
                system_prompt="You are a content moderation reviewer.",
                skills=["content-moderation"],
                phases=["review"],
                llm=LLMSpec(provider="anthropic", model="claude-sonnet-4-20250514", temperature=0.2),
                concurrency=2,
            ),
            AgentSpec(
                id="escalation-handler",
                name="Escalation Handler",
                system_prompt="You are a senior escalation handler.",
                phases=["escalation"],
                llm=LLMSpec(provider="anthropic", model="claude-sonnet-4-20250514", temperature=0.3),
            ),
        ],
        workflow=WorkflowSpec(
            name="Content Moderation Pipeline",
            description="Multi-phase content moderation",
            statuses=[
                StatusSpec(id="submitted", name="Submitted", is_initial=True, transitions_to=["analyzing"]),
                StatusSpec(id="analyzing", name="Analyzing", transitions_to=["in_review", "auto_approved"]),
                StatusSpec(id="in_review", name="In Review", transitions_to=["approved", "rejected", "escalated"]),
                StatusSpec(id="escalated", name="Escalated", transitions_to=["approved", "rejected"]),
                StatusSpec(id="approved", name="Approved", is_terminal=True),
                StatusSpec(id="rejected", name="Rejected", is_terminal=True),
                StatusSpec(id="auto_approved", name="Auto-Approved", is_terminal=True),
            ],
            phases=[
                PhaseSpec(
                    id="analysis",
                    name="Sentiment Analysis",
                    order=1,
                    agents=["sentiment-analyzer"],
                    quality_gates=[
                        QualityGateSpec(
                            name="confidence-gate",
                            conditions=[ConditionSpec(expression="confidence >= 0.5")],
                            on_failure=OnFailureAction.WARN,
                        ),
                    ],
                    on_success="review",
                    on_failure="review",
                ),
                PhaseSpec(
                    id="review",
                    name="Content Review",
                    order=2,
                    agents=["content-reviewer"],
                    quality_gates=[
                        QualityGateSpec(
                            name="review-completeness",
                            conditions=[ConditionSpec(expression="categories_checked >= 3")],
                            on_failure=OnFailureAction.BLOCK,
                        ),
                    ],
                    on_success="done",
                    on_failure="escalation",
                ),
                PhaseSpec(
                    id="escalation",
                    name="Escalation Review",
                    order=3,
                    agents=["escalation-handler"],
                    on_success="done",
                    on_failure="done",
                    requires_human=True,
                ),
                PhaseSpec(
                    id="done",
                    name="Complete",
                    order=4,
                    is_terminal=True,
                ),
            ],
        ),
        governance=GovernanceSpec(
            delegated_authority=DelegatedAuthoritySpec(
                auto_approve_threshold=0.9,
                review_threshold=0.5,
                abort_threshold=0.1,
            ),
            policies=[
                PolicySpec(
                    id="auto-approve-safe",
                    name="Auto-Approve Safe Content",
                    action="allow",
                    conditions=["confidence >= 0.9", "severity == 'none'"],
                    priority=100,
                    tags=["auto-approve"],
                ),
                PolicySpec(
                    id="flag-low-confidence",
                    name="Flag Low Confidence",
                    action="review",
                    conditions=["confidence < 0.5"],
                    priority=90,
                ),
            ],
        ),
        work_item_types=[
            WorkItemTypeSpec(
                id="content-submission",
                name="Content Submission",
                description="User-generated content for moderation",
                custom_fields=[
                    WorkItemFieldSpec(name="content_text", type=FieldType.TEXT, required=True),
                    WorkItemFieldSpec(
                        name="content_type",
                        type=FieldType.ENUM,
                        required=True,
                        values=["post", "comment", "message"],
                    ),
                    WorkItemFieldSpec(name="author_id", type=FieldType.STRING, required=True),
                ],
                artifact_types=[
                    ArtifactTypeSpec(
                        id="sentiment-report",
                        name="Sentiment Report",
                        file_extensions=[".json"],
                    ),
                ],
            ),
        ],
    )


@pytest.fixture
def tmp_dir():
    """Provide a temporary directory."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def studio_config(tmp_dir: Path) -> StudioConfig:
    """Studio config pointing at a temp workspace."""
    return StudioConfig(
        workspace_dir=tmp_dir,
        runtime_api_url="http://localhost:8000",
    )
