"""Jira ticketing connector provider.

Implements create_ticket, update_ticket, get_ticket, and search_tickets
against the Jira REST API v3. Supports Jira Cloud (Basic auth via
email + API token) and Jira Data Center (Bearer token / PAT).
"""
from __future__ import annotations

import base64
import logging

import httpx

from ...models import ConnectorCostInfo, ExternalReference
from ._base import BaseTicketingProvider, TicketingProviderError

logger = logging.getLogger(__name__)

_JIRA_FIELDS = "summary,description,status,priority,assignee,issuetype"


class JiraTicketingProvider(BaseTicketingProvider):
    """Jira-backed ticketing connector provider.

    Supports Jira Cloud (https://{domain}.atlassian.net) and Jira Data Center.
    Use email + api_token for Jira Cloud (Basic auth), or omit email and pass
    a Personal Access Token as api_token for Data Center (Bearer auth).

    Example::

        provider = JiraTicketingProvider(
            base_url="https://myorg.atlassian.net",
            api_token="ATATT3xFfGF0...",
            email="user@example.com",
            default_project="PROJ",
        )
    """

    def __init__(
        self,
        base_url: str,
        api_token: str,
        email: str | None = None,
        default_project: str | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("JiraTicketingProvider requires a non-empty base_url")
        if not api_token:
            raise ValueError("JiraTicketingProvider requires a non-empty api_token")
        self._base_url = base_url.rstrip("/")
        self._api_token = api_token
        self._email = email
        self._default_project = default_project

    @classmethod
    def from_env(cls) -> "JiraTicketingProvider | None":
        """Create an instance from environment variables.

        Required env vars: ``JIRA_BASE_URL``, ``JIRA_API_TOKEN``
        Optional env vars: ``JIRA_EMAIL``, ``JIRA_DEFAULT_PROJECT``

        Returns None if required env vars are not set.
        """
        import os
        base_url = os.environ.get("JIRA_BASE_URL", "")
        api_token = os.environ.get("JIRA_API_TOKEN", "")
        if not base_url or not api_token:
            return None
        return cls(
            base_url=base_url,
            api_token=api_token,
            email=os.environ.get("JIRA_EMAIL") or None,
            default_project=os.environ.get("JIRA_DEFAULT_PROJECT") or None,
        )

    @property
    def provider_id(self) -> str:
        """Unique provider identifier used for registry lookups."""
        return "ticketing.jira"

    @property
    def display_name(self) -> str:
        """Human-readable name shown in the registry descriptor."""
        return "Jira"

    def _auth_headers(self) -> dict[str, str]:
        """Build Authorization headers for the Jira REST API."""
        if self._email:
            credentials = base64.b64encode(
                f"{self._email}:{self._api_token}".encode()
            ).decode()
            return {
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        return {
            "Authorization": f"Bearer {self._api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _api_url(self, path: str) -> str:
        """Build a full Jira REST API v3 URL."""
        return f"{self._base_url}/rest/api/3/{path}"

    def _ticket_url(self, ticket_id: str) -> str:
        """Build the browser URL for a Jira issue key."""
        return f"{self._base_url}/browse/{ticket_id}"

    async def _create_ticket(
        self,
        summary: str,
        project: str | None,
        description: str | None,
        issue_type: str | None,
        priority: str | None,
        assignee: str | None,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Create a new Jira issue.

        Args:
            summary: Issue title / summary text.
            project: Jira project key (e.g. "PROJ"). Falls back to
                default_project if not provided.
            description: Optional issue description body.
            issue_type: Issue type name (default: "Task").
            priority: Priority name (e.g. "High").
            assignee: Jira accountId of the assignee.

        Returns:
            Tuple of (ExternalArtifact dict, None — no tracked API cost).

        Raises:
            TicketingProviderError: On HTTP or API errors.
        """
        project_key = project or self._default_project
        if not project_key:
            raise TicketingProviderError(
                "create_ticket requires a 'project' parameter or a configured default_project"
            )

        fields: dict = {
            "project": {"key": project_key},
            "summary": summary,
            "issuetype": {"name": issue_type or "Task"},
        }
        if description:
            fields["description"] = _build_adf(description)
        if priority:
            fields["priority"] = {"name": priority}
        if assignee:
            fields["assignee"] = {"accountId": assignee}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self._api_url("issue"),
                    headers=self._auth_headers(),
                    json={"fields": fields},
                )
                response.raise_for_status()
                data: dict = response.json()
        except httpx.HTTPError as exc:
            raise TicketingProviderError(f"Jira HTTP error: {exc}") from exc

        ticket_id: str = data.get("key", "")
        url = self._ticket_url(ticket_id) if ticket_id else None

        refs: list[ExternalReference] = [
            ExternalReference(
                provider=self.provider_id,
                resource_type="jira_issue",
                external_id=ticket_id,
                url=url,
                metadata={"project": project_key},
            )
        ]

        artifact = self._make_ticket_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            ticket_id=ticket_id,
            title=summary,
            description=description,
            status="To Do",
            priority=priority,
            assignee=assignee,
            url=url,
            raw_payload=data,
            resource_type="ticket",
            provenance={"provider": "jira", "project": project_key},
            references=refs,
        )

        logger.info("Jira create_ticket: key=%r project=%r", ticket_id, project_key)
        return artifact.model_dump(mode="json"), None

    async def _update_ticket(
        self,
        ticket_id: str,
        changes: dict,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Update an existing Jira issue.

        Args:
            ticket_id: Jira issue key (e.g. "PROJ-123").
            changes: Dict of Jira field names to new values.

        Returns:
            Tuple of (ExternalArtifact dict, None — no tracked API cost).

        Raises:
            TicketingProviderError: On HTTP or API errors.
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.put(
                    self._api_url(f"issue/{ticket_id}"),
                    headers=self._auth_headers(),
                    json={"fields": changes},
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise TicketingProviderError(f"Jira HTTP error: {exc}") from exc

        url = self._ticket_url(ticket_id)
        refs: list[ExternalReference] = [
            ExternalReference(
                provider=self.provider_id,
                resource_type="jira_issue",
                external_id=ticket_id,
                url=url,
            )
        ]

        priority: str | None = None
        if isinstance(changes.get("priority"), dict):
            priority = changes["priority"].get("name")

        artifact = self._make_ticket_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            ticket_id=ticket_id,
            title=changes.get("summary", ""),
            description=None,
            status=None,
            priority=priority,
            assignee=None,
            url=url,
            raw_payload={"ticket_id": ticket_id, "changes": changes},
            resource_type="ticket",
            provenance={"provider": "jira"},
            references=refs,
        )

        logger.info("Jira update_ticket: key=%r", ticket_id)
        return artifact.model_dump(mode="json"), None

    async def _get_ticket(
        self,
        ticket_id: str,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Retrieve a Jira issue by its key.

        Args:
            ticket_id: Jira issue key (e.g. "PROJ-123").

        Returns:
            Tuple of (ExternalArtifact dict, None — no tracked API cost).

        Raises:
            TicketingProviderError: On HTTP or API errors, including 404.
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    self._api_url(f"issue/{ticket_id}"),
                    headers=self._auth_headers(),
                    params={"fields": _JIRA_FIELDS},
                )
                response.raise_for_status()
                data: dict = response.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise TicketingProviderError(
                    f"Jira issue not found: {ticket_id}"
                ) from exc
            raise TicketingProviderError(f"Jira HTTP error: {exc}") from exc
        except httpx.HTTPError as exc:
            raise TicketingProviderError(f"Jira HTTP error: {exc}") from exc

        fields = data.get("fields", {})
        url = self._ticket_url(ticket_id)

        refs: list[ExternalReference] = [
            ExternalReference(
                provider=self.provider_id,
                resource_type="jira_issue",
                external_id=ticket_id,
                url=url,
            )
        ]

        artifact = self._make_ticket_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            ticket_id=ticket_id,
            title=fields.get("summary", ""),
            description=_extract_jira_description(fields.get("description")),
            status=_dict_name(fields.get("status")),
            priority=_dict_name(fields.get("priority")),
            assignee=_dict_display_name(fields.get("assignee")),
            url=url,
            raw_payload=data,
            resource_type="ticket",
            provenance={"provider": "jira"},
            references=refs,
        )

        logger.info("Jira get_ticket: key=%r", ticket_id)
        return artifact.model_dump(mode="json"), None

    async def _search_tickets(
        self,
        query: str,
        limit: int,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Search Jira issues using a JQL query string.

        Args:
            query: JQL query string (e.g. "project = PROJ AND status = Open").
            limit: Maximum number of results to return (default 25).

        Returns:
            Tuple of (ExternalArtifact dict with resource_type "ticket_list",
            None — no tracked API cost).

        Raises:
            TicketingProviderError: On HTTP or API errors.
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    self._api_url("search"),
                    headers=self._auth_headers(),
                    params={
                        "jql": query,
                        "maxResults": limit,
                        "fields": _JIRA_FIELDS,
                    },
                )
                response.raise_for_status()
                data: dict = response.json()
        except httpx.HTTPError as exc:
            raise TicketingProviderError(f"Jira HTTP error: {exc}") from exc

        issues: list[dict] = data.get("issues", [])
        total: int = data.get("total", len(issues))
        items = [_normalize_jira_issue(issue, self._base_url) for issue in issues]

        artifact = self._make_ticket_list_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            query=query,
            items=items,
            total=total,
            provenance={"provider": "jira", "query": query},
        )

        logger.info("Jira search_tickets: query=%r total=%d", query, total)
        return artifact.model_dump(mode="json"), None

    async def _transition_ticket(
        self,
        ticket_id: str,
        transition_name: str,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Transition a Jira issue to a new workflow state.

        Fetches available transitions, finds the one matching transition_name
        (case-insensitive), and executes it.

        Args:
            ticket_id: Jira issue key (e.g. "PROJ-123").
            transition_name: Target transition name (e.g. "In Progress", "Done").

        Returns:
            Tuple of (ExternalArtifact dict, None -- no tracked API cost).

        Raises:
            TicketingProviderError: When transition not found or on HTTP errors.
        """
        transitions_url = self._api_url(f"issue/{ticket_id}/transitions")

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    transitions_url,
                    headers=self._auth_headers(),
                )
                resp.raise_for_status()
                transitions = resp.json().get("transitions", [])

                target = next(
                    (t for t in transitions if t["name"].lower() == transition_name.lower()),
                    None,
                )
                if not target:
                    available = [t["name"] for t in transitions]
                    raise TicketingProviderError(
                        f"Transition '{transition_name}' not found for {ticket_id}. "
                        f"Available: {available}"
                    )

                resp = await client.post(
                    transitions_url,
                    headers=self._auth_headers(),
                    json={"transition": {"id": target["id"]}},
                )
                resp.raise_for_status()
        except TicketingProviderError:
            raise
        except httpx.HTTPError as exc:
            raise TicketingProviderError(f"Jira HTTP error: {exc}") from exc

        url = self._ticket_url(ticket_id)
        refs: list[ExternalReference] = [
            ExternalReference(
                provider=self.provider_id,
                resource_type="jira_issue",
                external_id=ticket_id,
                url=url,
            )
        ]

        artifact = self._make_ticket_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            ticket_id=ticket_id,
            title="",
            description=None,
            status=transition_name,
            priority=None,
            assignee=None,
            url=url,
            raw_payload={"ticket_id": ticket_id, "transitioned_to": transition_name},
            resource_type="ticket",
            provenance={"provider": "jira", "action": "transition"},
            references=refs,
        )

        logger.info("Jira transition_ticket: key=%r to=%r", ticket_id, transition_name)
        return artifact.model_dump(mode="json"), None

    async def _get_sprint_issues(
        self,
        sprint_id: int,
        board_id: int | None,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """List issues assigned to a Jira sprint.

        Uses the Jira Agile REST API endpoint.

        Args:
            sprint_id: Sprint ID.
            board_id: Board ID (unused for this endpoint, kept for interface).

        Returns:
            Tuple of (ExternalArtifact dict, None -- no tracked API cost).

        Raises:
            TicketingProviderError: On HTTP or API errors.
        """
        agile_url = f"{self._base_url}/rest/agile/1.0/sprint/{sprint_id}/issue"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    agile_url,
                    headers=self._auth_headers(),
                )
                response.raise_for_status()
                data: dict = response.json()
        except httpx.HTTPError as exc:
            raise TicketingProviderError(f"Jira HTTP error: {exc}") from exc

        issues: list[dict] = data.get("issues", [])
        total: int = data.get("total", len(issues))
        items = [_normalize_jira_issue(issue, self._base_url) for issue in issues]

        artifact = self._make_ticket_list_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            query=f"sprint={sprint_id}",
            items=items,
            total=total,
            provenance={"provider": "jira", "sprint_id": sprint_id},
        )

        logger.info("Jira get_sprint_issues: sprint_id=%d total=%d", sprint_id, total)
        return artifact.model_dump(mode="json"), None


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _dict_name(value: object) -> str | None:
    """Return value["name"] if value is a dict, otherwise None."""
    if isinstance(value, dict):
        return value.get("name")
    return None


def _dict_display_name(value: object) -> str | None:
    """Return value["displayName"] if value is a dict, otherwise None."""
    if isinstance(value, dict):
        return value.get("displayName")
    return None


def _build_adf(text: str) -> dict:
    """Wrap plain text in Atlassian Document Format (ADF) for Jira Cloud."""
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text}],
            }
        ],
    }


def _extract_jira_description(description: object) -> str | None:
    """Extract plain text from a Jira ADF description object or plain string."""
    if description is None:
        return None
    if isinstance(description, str):
        return description
    if not isinstance(description, dict):
        return None
    parts: list[str] = []
    for block in description.get("content", []):
        for inline in block.get("content", []):
            if inline.get("type") == "text":
                parts.append(inline.get("text", ""))
    return " ".join(parts) if parts else None


def _normalize_jira_issue(issue: dict, base_url: str) -> dict:
    """Convert a raw Jira issue dict to a compact ticket summary dict."""
    key: str = issue.get("key", "")
    fields = issue.get("fields", {})
    return {
        "ticket_id": key,
        "title": fields.get("summary", ""),
        "status": _dict_name(fields.get("status")),
        "priority": _dict_name(fields.get("priority")),
        "assignee": _dict_display_name(fields.get("assignee")),
        "url": f"{base_url}/browse/{key}" if key else None,
    }
