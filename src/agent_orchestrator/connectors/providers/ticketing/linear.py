"""Linear ticketing connector provider.

Implements create_ticket, update_ticket, get_ticket, and search_tickets
against the Linear GraphQL API using a personal API key.
"""
from __future__ import annotations

import logging

import httpx

from ...models import ConnectorCostInfo, ExternalReference
from ._base import BaseTicketingProvider, TicketingProviderError

logger = logging.getLogger(__name__)

_LINEAR_API_URL = "https://api.linear.app/graphql"

# Linear priority integers: 0=No priority, 1=Urgent, 2=High, 3=Medium, 4=Low
_PRIORITY_LABEL_TO_INT: dict[str, int] = {
    "urgent": 1,
    "high": 2,
    "medium": 3,
    "low": 4,
    "none": 0,
}


class LinearTicketingProvider(BaseTicketingProvider):
    """Linear-backed ticketing connector provider.

    Uses the Linear GraphQL API with a personal API key. The api_key is sent
    directly in the Authorization header (Linear's preferred format).

    Example::

        provider = LinearTicketingProvider(
            api_key="lin_api_xxxxxxxxxxxx",
            default_team_id="abc123-team-uuid",
        )
    """

    def __init__(
        self,
        api_key: str,
        default_team_id: str | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("LinearTicketingProvider requires a non-empty api_key")
        self._api_token = api_key
        self._default_team_id = default_team_id

    @classmethod
    def from_env(cls) -> "LinearTicketingProvider | None":
        """Create an instance from environment variables.

        Required env var: ``LINEAR_API_KEY``
        Optional env var: ``LINEAR_DEFAULT_TEAM_ID``

        Returns None if ``LINEAR_API_KEY`` is not set.
        """
        import os
        api_key = os.environ.get("LINEAR_API_KEY", "")
        if not api_key:
            return None
        return cls(
            api_key=api_key,
            default_team_id=os.environ.get("LINEAR_DEFAULT_TEAM_ID") or None,
        )

    @property
    def provider_id(self) -> str:
        """Unique provider identifier used for registry lookups."""
        return "ticketing.linear"

    @property
    def display_name(self) -> str:
        """Human-readable name shown in the registry descriptor."""
        return "Linear"

    def _auth_headers(self) -> dict[str, str]:
        """Build Authorization headers for the Linear GraphQL API."""
        return {
            "Authorization": self._api_token,
            "Content-Type": "application/json",
        }

    async def _graphql(self, query: str, variables: dict) -> dict:
        """Execute a GraphQL request and return the data payload.

        Args:
            query: GraphQL query or mutation string.
            variables: Variable bindings for the query.

        Returns:
            The ``data`` field from the GraphQL response.

        Raises:
            TicketingProviderError: On HTTP errors or GraphQL errors.
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    _LINEAR_API_URL,
                    headers=self._auth_headers(),
                    json={"query": query, "variables": variables},
                )
                response.raise_for_status()
                result: dict = response.json()
        except httpx.HTTPError as exc:
            raise TicketingProviderError(f"Linear HTTP error: {exc}") from exc

        errors = result.get("errors")
        if errors:
            raise TicketingProviderError(
                f"Linear GraphQL error: {errors[0].get('message', 'unknown')}"
            )
        return result.get("data", {})

    async def _create_ticket(
        self,
        summary: str,
        project: str | None,
        description: str | None,
        issue_type: str | None,  # Linear has no issue types; ignored
        priority: str | None,
        assignee: str | None,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Create a new Linear issue.

        Args:
            summary: Issue title.
            project: Linear team ID (UUID). Falls back to default_team_id.
            description: Optional issue description (Markdown supported).
            issue_type: Not used by Linear; accepted for interface compatibility.
            priority: Priority label ("urgent", "high", "medium", "low").
            assignee: Linear user ID (UUID) of the assignee.

        Returns:
            Tuple of (ExternalArtifact dict, None — no tracked API cost).

        Raises:
            TicketingProviderError: On HTTP or GraphQL errors.
        """
        team_id = project or self._default_team_id
        if not team_id:
            raise TicketingProviderError(
                "create_ticket requires a 'project' (team ID) or a configured default_team_id"
            )

        issue_input: dict = {"teamId": team_id, "title": summary}
        if description:
            issue_input["description"] = description
        if priority:
            priority_int = _PRIORITY_LABEL_TO_INT.get(priority.lower())
            if priority_int is not None:
                issue_input["priority"] = priority_int
        if assignee:
            issue_input["assigneeId"] = assignee

        mutation = """
        mutation IssueCreate($input: IssueCreateInput!) {
            issueCreate(input: $input) {
                success
                issue {
                    id identifier title description
                    state { name }
                    priorityLabel
                    assignee { displayName }
                    url
                }
            }
        }
        """
        data = await self._graphql(mutation, {"input": issue_input})
        issue_create = data.get("issueCreate", {})
        if not issue_create.get("success"):
            raise TicketingProviderError("Linear issueCreate returned success=false")

        issue = issue_create.get("issue", {})
        ticket_id: str = issue.get("identifier") or issue.get("id", "")
        url: str | None = issue.get("url")

        refs: list[ExternalReference] = [
            ExternalReference(
                provider=self.provider_id,
                resource_type="linear_issue",
                external_id=ticket_id,
                url=url,
                metadata={"team_id": team_id},
            )
        ]

        artifact = self._make_ticket_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            ticket_id=ticket_id,
            title=issue.get("title", summary),
            description=issue.get("description"),
            status=_nested_name(issue.get("state")),
            priority=issue.get("priorityLabel"),
            assignee=_nested_display_name(issue.get("assignee")),
            url=url,
            raw_payload=issue,
            resource_type="ticket",
            provenance={"provider": "linear", "team_id": team_id},
            references=refs,
        )

        logger.info("Linear create_ticket: id=%r team=%r", ticket_id, team_id)
        return artifact.model_dump(mode="json"), None

    async def _update_ticket(
        self,
        ticket_id: str,
        changes: dict,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Update an existing Linear issue.

        The ``ticket_id`` must be the Linear issue UUID (obtainable from
        ``get_ticket``'s raw_payload ``id`` field). Human-readable identifiers
        such as "TEAM-123" are not accepted by the issueUpdate mutation.

        Args:
            ticket_id: Linear issue UUID.
            changes: Dict with optional keys: title, description, priority
                (label string), assigneeId.

        Returns:
            Tuple of (ExternalArtifact dict, None — no tracked API cost).

        Raises:
            TicketingProviderError: On HTTP or GraphQL errors.
        """
        update_input = _build_linear_update_input(changes)

        mutation = """
        mutation IssueUpdate($id: String!, $input: IssueUpdateInput!) {
            issueUpdate(id: $id, input: $input) {
                success
                issue {
                    id identifier title description
                    state { name }
                    priorityLabel
                    url
                }
            }
        }
        """
        data = await self._graphql(mutation, {"id": ticket_id, "input": update_input})
        issue_update = data.get("issueUpdate", {})
        if not issue_update.get("success"):
            raise TicketingProviderError("Linear issueUpdate returned success=false")

        issue = issue_update.get("issue", {})
        identifier: str = issue.get("identifier") or ticket_id
        url: str | None = issue.get("url")

        refs: list[ExternalReference] = [
            ExternalReference(
                provider=self.provider_id,
                resource_type="linear_issue",
                external_id=identifier,
                url=url,
            )
        ]

        artifact = self._make_ticket_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            ticket_id=identifier,
            title=issue.get("title", ""),
            description=issue.get("description"),
            status=_nested_name(issue.get("state")),
            priority=issue.get("priorityLabel"),
            assignee=None,
            url=url,
            raw_payload=issue,
            resource_type="ticket",
            provenance={"provider": "linear"},
            references=refs,
        )

        logger.info("Linear update_ticket: id=%r", identifier)
        return artifact.model_dump(mode="json"), None

    async def _get_ticket(
        self,
        ticket_id: str,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Retrieve a Linear issue by identifier or UUID.

        Args:
            ticket_id: Linear issue identifier (e.g. "TEAM-123") or UUID.

        Returns:
            Tuple of (ExternalArtifact dict, None — no tracked API cost).

        Raises:
            TicketingProviderError: When the issue is not found or on errors.
        """
        query = """
        query Issue($id: String!) {
            issue(id: $id) {
                id identifier title description
                state { name }
                priorityLabel
                assignee { displayName }
                url
            }
        }
        """
        data = await self._graphql(query, {"id": ticket_id})
        issue = data.get("issue")
        if not issue:
            raise TicketingProviderError(f"Linear issue not found: {ticket_id}")

        identifier: str = issue.get("identifier") or issue.get("id", ticket_id)
        url: str | None = issue.get("url")

        refs: list[ExternalReference] = [
            ExternalReference(
                provider=self.provider_id,
                resource_type="linear_issue",
                external_id=identifier,
                url=url,
            )
        ]

        artifact = self._make_ticket_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            ticket_id=identifier,
            title=issue.get("title", ""),
            description=issue.get("description"),
            status=_nested_name(issue.get("state")),
            priority=issue.get("priorityLabel"),
            assignee=_nested_display_name(issue.get("assignee")),
            url=url,
            raw_payload=issue,
            resource_type="ticket",
            provenance={"provider": "linear"},
            references=refs,
        )

        logger.info("Linear get_ticket: id=%r", identifier)
        return artifact.model_dump(mode="json"), None

    async def _search_tickets(
        self,
        query: str,
        limit: int,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Search Linear issues by title substring.

        Args:
            query: Text to search for in issue titles (case-insensitive).
            limit: Maximum number of results to return (default 25).

        Returns:
            Tuple of (ExternalArtifact dict with resource_type "ticket_list",
            None — no tracked API cost).

        Raises:
            TicketingProviderError: On HTTP or GraphQL errors.
        """
        gql_query = """
        query SearchIssues($filter: IssueFilter, $first: Int) {
            issues(filter: $filter, first: $first) {
                nodes {
                    id identifier title description
                    state { name }
                    priorityLabel
                    assignee { displayName }
                    url
                }
                totalCount
            }
        }
        """
        data = await self._graphql(
            gql_query,
            {
                "filter": {"title": {"containsIgnoreCase": query}},
                "first": limit,
            },
        )
        issues_data = data.get("issues", {})
        nodes: list[dict] = issues_data.get("nodes", [])
        total: int = issues_data.get("totalCount", len(nodes))

        items = [_normalize_linear_node(node) for node in nodes]

        artifact = self._make_ticket_list_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            query=query,
            items=items,
            total=total,
            provenance={"provider": "linear", "query": query},
        )

        logger.info("Linear search_tickets: query=%r total=%d", query, total)
        return artifact.model_dump(mode="json"), None


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _nested_name(value: object) -> str | None:
    """Return value["name"] when value is a dict, otherwise None."""
    if isinstance(value, dict):
        return value.get("name")
    return None


def _nested_display_name(value: object) -> str | None:
    """Return value["displayName"] when value is a dict, otherwise None."""
    if isinstance(value, dict):
        return value.get("displayName")
    return None


def _build_linear_update_input(changes: dict) -> dict:
    """Map a generic changes dict to a Linear IssueUpdateInput dict."""
    update_input: dict = {}
    if "title" in changes:
        update_input["title"] = changes["title"]
    if "summary" in changes:
        update_input["title"] = changes["summary"]
    if "description" in changes:
        update_input["description"] = changes["description"]
    if "priority" in changes:
        p = changes["priority"]
        if isinstance(p, str):
            update_input["priority"] = _PRIORITY_LABEL_TO_INT.get(p.lower(), 0)
        elif isinstance(p, int):
            update_input["priority"] = p
    if "assignee" in changes:
        update_input["assigneeId"] = changes["assignee"]
    return update_input


def _normalize_linear_node(node: dict) -> dict:
    """Convert a raw Linear issue node to a compact ticket summary dict."""
    identifier: str = node.get("identifier") or node.get("id", "")
    return {
        "ticket_id": identifier,
        "title": node.get("title", ""),
        "status": _nested_name(node.get("state")),
        "priority": node.get("priorityLabel"),
        "assignee": _nested_display_name(node.get("assignee")),
        "url": node.get("url"),
    }
