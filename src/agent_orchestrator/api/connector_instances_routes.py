"""REST routes for direct connector instance actions.

Provides a lightweight action-based interface for GitHub, Jira, and Slack
connectors. Each connector is instantiated from environment variables on
each request.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/connectors/instances", tags=["connector-instances"])


@router.get("/available")
async def list_available_connectors() -> dict[str, Any]:
    """List configured connector instances and their capabilities."""
    return {
        "connectors": [
            {
                "id": "github",
                "name": "GitHub",
                "capabilities": [
                    "repos",
                    "issues",
                    "pull_requests",
                    "file_content",
                    "review_comments",
                ],
                "configured": bool(os.environ.get("GITHUB_API_TOKEN")),
            },
            {
                "id": "jira",
                "name": "Jira",
                "capabilities": [
                    "search",
                    "create_issue",
                    "update_issue",
                    "transitions",
                    "sprints",
                ],
                "configured": bool(os.environ.get("JIRA_BASE_URL")),
            },
            {
                "id": "slack",
                "name": "Slack",
                "capabilities": [
                    "send_message",
                    "notifications",
                    "channels",
                    "file_upload",
                ],
                "configured": bool(os.environ.get("SLACK_BOT_TOKEN")),
            },
        ]
    }


def _get_github_connector() -> Any:
    """Instantiate a GitHubRepositoryProvider from env vars.

    Raises:
        HTTPException: When GITHUB_API_TOKEN is not configured.
    """
    from agent_orchestrator.connectors.providers.repository.github import (
        GitHubRepositoryProvider,
    )

    token = os.environ.get("GITHUB_API_TOKEN", "")
    if not token:
        raise HTTPException(status_code=503, detail="GITHUB_API_TOKEN not configured")
    return GitHubRepositoryProvider(api_token=token)


def _get_jira_connector() -> Any:
    """Instantiate a JiraTicketingProvider from env vars.

    Raises:
        HTTPException: When JIRA_BASE_URL or JIRA_API_TOKEN is not configured.
    """
    from agent_orchestrator.connectors.providers.ticketing.jira import (
        JiraTicketingProvider,
    )

    base_url = os.environ.get("JIRA_BASE_URL", "")
    api_token = os.environ.get("JIRA_API_TOKEN", "")
    if not base_url or not api_token:
        raise HTTPException(
            status_code=503,
            detail="JIRA_BASE_URL and JIRA_API_TOKEN must be configured",
        )
    return JiraTicketingProvider(
        base_url=base_url,
        api_token=api_token,
        email=os.environ.get("JIRA_EMAIL") or None,
        default_project=os.environ.get("JIRA_DEFAULT_PROJECT") or None,
    )


def _get_slack_connector() -> Any:
    """Instantiate a SlackMessagingProvider from env vars.

    Raises:
        HTTPException: When SLACK_BOT_TOKEN is not configured.
    """
    from agent_orchestrator.connectors.providers.messaging.slack import (
        SlackMessagingProvider,
    )

    token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not token:
        raise HTTPException(status_code=503, detail="SLACK_BOT_TOKEN not configured")
    return SlackMessagingProvider(
        bot_token=token,
        default_channel=os.environ.get("SLACK_DEFAULT_CHANNEL") or None,
    )


@router.post("/github/{action}")
async def github_action(action: str, body: dict[str, Any]) -> dict[str, Any]:
    """Execute a GitHub connector action.

    Supported actions: list-repos, create-issue, list-issues, create-pr,
    get-file, add-review-comment.

    Args:
        action: Action name (URL path parameter).
        body: Action-specific parameters as JSON body.

    Returns:
        Action result dict.
    """
    from agent_orchestrator.connectors.models import (
        CapabilityType,
        ConnectorInvocationRequest,
    )

    connector = _get_github_connector()

    action_map: dict[str, tuple[str, dict[str, Any]]] = {
        "list-repos": ("search_repo", {"query": body.get("query", ""), "limit": body.get("limit", 30)}),
        "create-issue": (
            "create_issue",
            {
                "repo_id": body.get("owner", "") + "/" + body.get("repo", "") if "owner" in body else body.get("repo_id", ""),
                "title": body.get("title", ""),
                "body": body.get("body", ""),
                "labels": body.get("labels"),
            },
        ),
        "list-issues": (
            "list_issues",
            {
                "repo_id": body.get("owner", "") + "/" + body.get("repo", "") if "owner" in body else body.get("repo_id", ""),
                "state": body.get("state", "open"),
                "limit": body.get("limit", 30),
            },
        ),
        "create-pr": (
            "create_pull_request",
            {
                "repo_id": body.get("owner", "") + "/" + body.get("repo", "") if "owner" in body else body.get("repo_id", ""),
                "title": body.get("title", ""),
                "head": body.get("head", ""),
                "base": body.get("base", "main"),
                "body": body.get("body", ""),
            },
        ),
        "get-file": (
            "get_file",
            {
                "repo_id": body.get("owner", "") + "/" + body.get("repo", "") if "owner" in body else body.get("repo_id", ""),
                "path": body.get("path", ""),
                "ref": body.get("ref", "main"),
            },
        ),
        "add-review-comment": (
            "add_review_comment",
            {
                "repo_id": body.get("owner", "") + "/" + body.get("repo", "") if "owner" in body else body.get("repo_id", ""),
                "pr_id": str(body.get("pr_number", body.get("pr_id", ""))),
                "body": body.get("body", ""),
            },
        ),
    }

    if action not in action_map:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown GitHub action: {action}. Available: {list(action_map.keys())}",
        )

    operation, params = action_map[action]
    request = ConnectorInvocationRequest(
        capability_type=CapabilityType.REPOSITORY,
        operation=operation,
        parameters=params,
    )
    result = await connector.execute(request)
    return result.model_dump(mode="json")


@router.post("/jira/{action}")
async def jira_action(action: str, body: dict[str, Any]) -> dict[str, Any]:
    """Execute a Jira connector action.

    Supported actions: search, create-issue, update-issue, get-issue,
    transition, sprint-issues.

    Args:
        action: Action name (URL path parameter).
        body: Action-specific parameters as JSON body.

    Returns:
        Action result dict.
    """
    from agent_orchestrator.connectors.models import (
        CapabilityType,
        ConnectorInvocationRequest,
    )

    connector = _get_jira_connector()

    action_map: dict[str, tuple[str, dict[str, Any]]] = {
        "search": (
            "search_tickets",
            {"query": body.get("jql", body.get("query", "")), "limit": body.get("max_results", 25)},
        ),
        "create-issue": (
            "create_ticket",
            {
                "summary": body.get("summary", ""),
                "project": body.get("project_key", body.get("project")),
                "description": body.get("description", ""),
                "issue_type": body.get("issue_type", "Task"),
                "priority": body.get("priority"),
                "assignee": body.get("assignee"),
            },
        ),
        "update-issue": (
            "update_ticket",
            {
                "ticket_id": body.get("issue_key", body.get("ticket_id", "")),
                "changes": body.get("fields", body.get("changes", {})),
            },
        ),
        "get-issue": (
            "get_ticket",
            {"ticket_id": body.get("issue_key", body.get("ticket_id", ""))},
        ),
        "transition": (
            "transition_ticket",
            {
                "ticket_id": body.get("issue_key", body.get("ticket_id", "")),
                "transition_name": body.get("transition_name", ""),
            },
        ),
        "sprint-issues": (
            "get_sprint_issues",
            {
                "sprint_id": body.get("sprint_id", 0),
                "board_id": body.get("board_id"),
            },
        ),
    }

    if action not in action_map:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown Jira action: {action}. Available: {list(action_map.keys())}",
        )

    operation, params = action_map[action]
    request = ConnectorInvocationRequest(
        capability_type=CapabilityType.TICKETING,
        operation=operation,
        parameters=params,
    )
    result = await connector.execute(request)
    return result.model_dump(mode="json")


@router.post("/slack/{action}")
async def slack_action(action: str, body: dict[str, Any]) -> dict[str, Any]:
    """Execute a Slack connector action.

    Supported actions: send-message, notify, list-channels, upload-file.

    Args:
        action: Action name (URL path parameter).
        body: Action-specific parameters as JSON body.

    Returns:
        Action result dict.
    """
    from agent_orchestrator.connectors.models import (
        CapabilityType,
        ConnectorInvocationRequest,
    )

    connector = _get_slack_connector()

    action_map: dict[str, tuple[str, dict[str, Any]]] = {
        "send-message": (
            "send_message",
            {
                "destination": body.get("channel", ""),
                "content": body.get("text", body.get("content", "")),
            },
        ),
        "notify": (
            "send_notification",
            {
                "destination": body.get("channel", ""),
                "title": body.get("title", ""),
                "content": body.get("message", body.get("content", "")),
                "color": body.get("color", "#36a64f"),
                "fields": body.get("fields"),
            },
        ),
        "list-channels": (
            "list_channels",
            {"limit": body.get("limit", 100)},
        ),
        "upload-file": (
            "upload_file",
            {
                "destination": body.get("channel", ""),
                "content": body.get("content", ""),
                "filename": body.get("filename", ""),
                "title": body.get("title", ""),
            },
        ),
    }

    if action not in action_map:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown Slack action: {action}. Available: {list(action_map.keys())}",
        )

    operation, params = action_map[action]
    request = ConnectorInvocationRequest(
        capability_type=CapabilityType.MESSAGING,
        operation=operation,
        parameters=params,
    )
    result = await connector.execute(request)
    return result.model_dump(mode="json")
