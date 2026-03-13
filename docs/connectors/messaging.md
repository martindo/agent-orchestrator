# Messaging Capability Providers

The messaging capability (`CapabilityType.MESSAGING`) covers write-oriented operations: sending messages, notifying users, and creating threads. Three providers are included:

| Provider | Class | Transport | DM Support |
|---|---|---|---|
| Slack | `SlackMessagingProvider` | Slack Web API (HTTPS) | Yes — via `conversations.open` |
| Microsoft Teams | `TeamsMessagingProvider` | Incoming Webhook (HTTPS) | No — @mention fallback |
| Email | `EmailMessagingProvider` | SMTP with STARTTLS | Yes — user_id is email address |

## Write Operation Permissions

All three operations (`send_message`, `notify_user`, `create_thread`) have `read_only=False`. This means they pass through the approval gating layer in `evaluate_permission_detailed()`. When a `ConnectorPermissionPolicy` has `requires_approval=True`, these operations return `ConnectorStatus.REQUIRES_APPROVAL` instead of executing.

Example approval policy:

```python
from agent_orchestrator.connectors.models import CapabilityType, ConnectorPermissionPolicy

approval_policy = ConnectorPermissionPolicy(
    description="Require approval for all messaging",
    allowed_capability_types=[CapabilityType.MESSAGING],
    requires_approval=True,
    read_only=False,
)
```

Attach this policy to a `ConnectorConfig` to gate messaging ops through human review.

## Provider Configuration

### Slack

**Constructor:**

```python
from agent_orchestrator.connectors.providers import SlackMessagingProvider

provider = SlackMessagingProvider(
    bot_token="xoxb-...",          # required
    default_channel="#general",    # optional, not currently used in dispatch
)
```

**Recommended environment variables:**

| Variable | Used for |
|---|---|
| `SLACK_BOT_TOKEN` | `bot_token` |

**Required bot OAuth scopes:** `chat:write`, `im:write`, `channels:read`

---

### Microsoft Teams

**Constructor:**

```python
from agent_orchestrator.connectors.providers import TeamsMessagingProvider

provider = TeamsMessagingProvider(
    webhook_url="https://outlook.office.com/webhook/...",  # required
    sender_name="Agent Orchestrator",                       # optional display name
)
```

**Recommended environment variables:**

| Variable | Used for |
|---|---|
| `TEAMS_WEBHOOK_URL` | `webhook_url` |

**Creating an incoming webhook in Teams:**
1. Go to the target channel > Settings > Connectors
2. Search for "Incoming Webhook" and click Configure
3. Name it and optionally upload an icon, then click Create
4. Copy the webhook URL — this is your `webhook_url`

**Limitation:** Incoming webhooks post to a fixed channel. `notify_user` cannot send DMs; it prepends `@<user_id>` to the message content and posts to the webhook channel.

---

### Email (SMTP)

**Constructor:**

```python
from agent_orchestrator.connectors.providers import EmailMessagingProvider

provider = EmailMessagingProvider(
    smtp_host="smtp.gmail.com",        # required
    username="agent@example.com",       # required — also used for SMTP login
    password="app-password",            # required
    from_address="agent@example.com",   # required — From header value
    smtp_port=587,                      # default: 587
    use_tls=True,                       # default: True (STARTTLS)
)
```

**Recommended environment variables:**

| Variable | Used for |
|---|---|
| `SMTP_HOST` | `smtp_host` |
| `SMTP_USERNAME` | `username` |
| `SMTP_PASSWORD` | `password` |
| `SMTP_FROM_ADDRESS` | `from_address` |

**Note:** `notify_user` treats `user_id` as an email address (recipient).

## Registry Registration and Usage

```python
from agent_orchestrator.connectors.registry import ConnectorRegistry
from agent_orchestrator.connectors.service import ConnectorService
from agent_orchestrator.connectors.providers import SlackMessagingProvider
from agent_orchestrator.connectors.models import (
    CapabilityType,
    ConnectorConfig,
    ConnectorInvocationRequest,
)

# Create and register provider
registry = ConnectorRegistry()
slack = SlackMessagingProvider(bot_token="xoxb-...")
registry.register_provider(slack)

# Register config (optional — for permission policies, retry, rate limits)
config = ConnectorConfig(
    connector_id="messaging.slack",
    display_name="Slack",
    capability_type=CapabilityType.MESSAGING,
    provider_id="messaging.slack",
)
registry.register_config(config)

# Execute via ConnectorService
service = ConnectorService(registry=registry)
request = ConnectorInvocationRequest(
    capability_type=CapabilityType.MESSAGING,
    operation="send_message",
    parameters={"destination": "C12345", "content": "Hello from the orchestrator!"},
)
result = await service.execute(request, module="security-investigation")
print(result.status)       # ConnectorStatus.SUCCESS
print(result.payload)      # ExternalArtifact dict
```

## Operations

### `send_message`

Send a message to a channel, inbox, or address.

| Parameter | Required | Description |
|---|---|---|
| `destination` | Yes | Channel ID (Slack), webhook label (Teams), or email address (Email) |
| `content` | Yes | Message body text |

Returns `resource_type = "message"`.

---

### `notify_user`

Send a direct notification to a specific user.

| Parameter | Required | Description |
|---|---|---|
| `user_id` | Yes | Slack user ID (`U12345`), mention string (Teams), or email address |
| `content` | Yes | Notification body text |

Returns `resource_type = "notification"`.

- **Slack:** Opens a DM via `conversations.open`, then posts `chat.postMessage`
- **Teams:** Posts to the webhook channel with `@<user_id>` prefix
- **Email:** Sends to `user_id` as the To address

---

### `create_thread`

Create a new message thread with a title and initial content.

| Parameter | Required | Description |
|---|---|---|
| `destination` | Yes | Channel ID (Slack/Teams) or email address |
| `title` | Yes | Thread subject / bold heading |
| `content` | Yes | Thread body text |

Returns `resource_type = "thread"`.

- **Slack:** Posts initial message with `*title*\ncontent`; the `ts` becomes the `thread_ts` for replies
- **Teams:** Posts MessageCard with `title` and `text` fields
- **Email:** Sends email with `title` as the `Subject` header

## Output Shapes

All operations return an `ExternalArtifact` envelope with a `MessageArtifact`-shaped `normalized_payload`.

### `send_message` output (`resource_type = "message"`)

```json
{
  "artifact_id": "...",
  "source_connector": "messaging.slack",
  "provider": "messaging.slack",
  "capability_type": "messaging",
  "resource_type": "message",
  "raw_payload": {
    "ok": true,
    "channel": "C12345",
    "ts": "1699000000.000100"
  },
  "normalized_payload": {
    "artifact_id": "...",
    "source_connector": "messaging.slack",
    "provider": "messaging.slack",
    "capability_type": "messaging",
    "message_id": "1699000000.000100",
    "channel": "C12345",
    "sender": "bot",
    "recipients": ["C12345"],
    "subject": null,
    "body": "Hello from the orchestrator!"
  },
  "references": [
    {
      "provider": "messaging.slack",
      "resource_type": "slack_message",
      "external_id": "1699000000.000100",
      "url": null,
      "metadata": {"channel": "C12345"}
    }
  ],
  "provenance": {"provider": "slack"}
}
```

### `notify_user` output (`resource_type = "notification"`)

```json
{
  "source_connector": "messaging.email",
  "provider": "messaging.email",
  "capability_type": "messaging",
  "resource_type": "notification",
  "normalized_payload": {
    "capability_type": "messaging",
    "message_id": "<uuid@agent-orchestrator>",
    "channel": "user@example.com",
    "sender": "agent@example.com",
    "recipients": ["user@example.com"],
    "subject": null,
    "body": "You have a notification"
  },
  "provenance": {"provider": "email", "smtp_host": "smtp.example.com"}
}
```

### `create_thread` output (`resource_type = "thread"`)

```json
{
  "source_connector": "messaging.teams",
  "provider": "messaging.teams",
  "capability_type": "messaging",
  "resource_type": "thread",
  "normalized_payload": {
    "capability_type": "messaging",
    "message_id": "<uuid>",
    "channel": "general",
    "sender": "Agent Orchestrator",
    "recipients": ["general"],
    "subject": "Incident Alert",
    "body": "A new incident has been detected."
  },
  "provenance": {"provider": "teams"}
}
```

## Approval Gating Example

To require human approval before any message is sent:

```python
from agent_orchestrator.connectors.models import (
    CapabilityType,
    ConnectorConfig,
    ConnectorPermissionPolicy,
)

approval_policy = ConnectorPermissionPolicy(
    description="Require approval for all messaging",
    allowed_capability_types=[CapabilityType.MESSAGING],
    requires_approval=True,
    read_only=False,
)

config = ConnectorConfig(
    connector_id="messaging.slack",
    display_name="Slack (Approval Required)",
    capability_type=CapabilityType.MESSAGING,
    provider_id="messaging.slack",
    permission_policies=[approval_policy],
)
```

When a messaging operation is attempted, `ConnectorService.execute()` returns a result with `status=ConnectorStatus.REQUIRES_APPROVAL`. The operation is not executed until a human approves it via the review queue.

## Module Integration Notes

### Research Team (`profiles/research-team/`)

Add a Slack connector to notify analysts when a research cycle completes:

```yaml
connectors:
  - connector_id: "messaging.slack"
    capability_type: "messaging"
    provider_id: "messaging.slack"
    scoped_modules: ["research-team"]
```

Agents can call `send_message` to post summaries to a `#research-results` channel.

### Security Investigation

Use `notify_user` to page on-call engineers when a critical finding is detected. Pair with `requires_approval=True` for high-severity alerts that need human sign-off before escalation.

### Software Dev Team (`profiles/software-dev/`)

Use `create_thread` to post incident threads to `#incidents` when CI/CD pipelines fail. The initial thread post (`ts`) serves as the parent for all follow-up context in Slack.
