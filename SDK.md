# SDK and Configuration Guide

Complete reference for configuring, deploying, and integrating with agent-orchestrator.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Installation](#installation)
3. [Workspace Setup](#workspace-setup)
4. [Configuration Files](#configuration-files)
   - [settings.yaml](#settingsyaml)
   - [agents.yaml](#agentsyaml)
   - [workflow.yaml](#workflowyaml)
   - [governance.yaml](#governanceyaml)
   - [workitems.yaml](#workitemsyaml)
5. [LLM Provider Setup](#llm-provider-setup)
6. [CLI Reference](#cli-reference)
7. [REST API Reference](#rest-api-reference)
8. [Python SDK](#python-sdk)
9. [Built-in Profile Templates](#built-in-profile-templates)
10. [Validation Rules](#validation-rules)
11. [Building Apps](#building-apps)

---

## Quick Start

```bash
# Install with LLM support
pip install -e ".[llm]"

# Initialize a workspace from a built-in template
agent-orchestrator init --template content-moderation my-workspace
cd my-workspace

# Set your API keys (choose one or more)
export AGENT_ORCH_OPENAI_API_KEY=sk-...
export AGENT_ORCH_ANTHROPIC_API_KEY=sk-ant-...

# Validate configuration
agent-orchestrator validate .

# Start the REST API server
agent-orchestrator serve .

# In another terminal — start the engine and submit work
curl -X POST http://localhost:8000/api/v1/execution/start
curl -X POST http://localhost:8000/api/v1/workitems \
  -H "Content-Type: application/json" \
  -d '{"id": "item-1", "type_id": "task", "title": "Review this content"}'
```

---

## Installation

**Core only** (no LLM SDKs):
```bash
pip install -e .
```

**With LLM providers:**
```bash
pip install -e ".[llm]"
```

This installs: `openai` (covers OpenAI + Grok), `anthropic`, `google-generativeai`, `httpx` (for Ollama).

**With dev tools:**
```bash
pip install -e ".[llm,dev]"
```

---

## Workspace Setup

A workspace is a directory that holds all configuration for your orchestration domain. Create one with `init`:

```bash
agent-orchestrator init my-workspace
```

This creates:

```
my-workspace/
├── settings.yaml                  # Workspace settings (API keys, active profile)
├── profiles/
│   └── default/
│       ├── agents.yaml            # Agent definitions
│       ├── workflow.yaml          # Workflow phases and statuses
│       ├── governance.yaml        # Governance policies and thresholds
│       └── workitems.yaml         # Work item type definitions
├── .state/                        # Runtime state (auto-created on start)
├── .history/                      # Configuration version history
└── .audit/                        # Audit log directory
```

Use `--template` to start from a built-in profile:

```bash
agent-orchestrator init --template content-moderation my-workspace
agent-orchestrator init --template software-dev my-workspace
```

---

## Configuration Files

### settings.yaml

Workspace-level settings shared across all profiles. This is the only file at the workspace root.

```yaml
# Which profile to load on startup
active_profile: "my-profile"

# API keys for LLM providers
# Keys can also be set via environment variables (see below)
api_keys:
  openai: "sk-..."
  anthropic: "sk-ant-..."
  google: "AIza..."
  grok: "xai-..."

# Custom LLM endpoints (for self-hosted models)
llm_endpoints:
  ollama: "http://localhost:11434"

# Logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL
log_level: "INFO"

# Storage backend: file, sqlite, or postgresql
persistence_backend: "file"

# Deployment mode: lite, standard, or enterprise
deployment_mode: "lite"
```

#### Environment Variable Fallback

API keys can be provided via environment variables instead of (or in addition to) `settings.yaml`. Environment variables take precedence and are **never written to disk**.

| Variable | Provider |
|----------|----------|
| `AGENT_ORCH_OPENAI_API_KEY` | OpenAI |
| `AGENT_ORCH_ANTHROPIC_API_KEY` | Anthropic |
| `AGENT_ORCH_GOOGLE_API_KEY` | Google Gemini |
| `AGENT_ORCH_GROK_API_KEY` | xAI Grok |

```bash
# Set keys via environment (recommended for production)
export AGENT_ORCH_OPENAI_API_KEY=sk-proj-...
export AGENT_ORCH_ANTHROPIC_API_KEY=sk-ant-api03-...

# settings.yaml can leave api_keys empty — env vars will fill them
```

#### Field Reference

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `active_profile` | string | *required* | Name of the profile directory to load |
| `api_keys` | dict | `{}` | Map of provider name to API key |
| `llm_endpoints` | dict | `{}` | Map of provider name to endpoint URL |
| `log_level` | string | `"INFO"` | One of: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `persistence_backend` | string | `"file"` | One of: `file`, `sqlite`, `postgresql` |
| `deployment_mode` | string | `"lite"` | One of: `lite`, `standard`, `enterprise` |

---

### agents.yaml

Defines the agents available in a profile. Each agent has a system prompt, LLM configuration, and is assigned to one or more workflow phases.

```yaml
agents:
  - id: sentiment-analyzer
    name: Sentiment Analyzer
    description: Analyzes content sentiment and emotional tone
    system_prompt: |
      You are a sentiment analysis agent. Analyze the provided content for:
      - Overall sentiment (positive, negative, neutral, mixed)
      - Emotional tone (anger, fear, joy, sadness, surprise, disgust)
      - Confidence score (0.0 to 1.0)
      Return structured analysis with confidence scores.
    skills:
      - sentiment-analysis
      - nlp
    phases:
      - analysis
    llm:
      provider: openai
      model: gpt-4o
      temperature: 0.1
      max_tokens: 2000
    concurrency: 3
    retry_policy:
      max_retries: 2
      delay_seconds: 1.0
      backoff_multiplier: 2.0
    enabled: true

  - id: content-reviewer
    name: Content Reviewer
    description: Reviews content against community guidelines
    system_prompt: |
      You are a content moderation reviewer. Evaluate the provided content
      against community guidelines. Provide a verdict (approve, flag, reject)
      with detailed reasoning and confidence score.
    phases:
      - review
    llm:
      provider: anthropic
      model: claude-sonnet-4-20250514
      temperature: 0.2
      max_tokens: 3000
    concurrency: 2
```

#### Agent Field Reference

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `id` | string | *required* | Unique identifier (referenced by workflow phases) |
| `name` | string | *required* | Display name |
| `description` | string | `""` | Human-readable description |
| `system_prompt` | string | *required* | System prompt sent to the LLM |
| `skills` | list[string] | `[]` | Skill tags (informational) |
| `phases` | list[string] | *required* | Workflow phase IDs this agent runs in |
| `llm` | object | *required* | LLM configuration (see below) |
| `concurrency` | int | `1` | Max concurrent instances (1–100) |
| `retry_policy` | object | see below | Retry behavior on failure |
| `enabled` | bool | `true` | Whether the agent is active |

#### LLM Configuration

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `provider` | string | *required* | `openai`, `anthropic`, `google`, `ollama`, `grok`, or `custom` |
| `model` | string | *required* | Model identifier (e.g., `gpt-4o`, `claude-sonnet-4-20250514`, `llama3`) |
| `temperature` | float | `0.3` | Sampling temperature (0.0–2.0) |
| `max_tokens` | int | `4000` | Maximum output tokens (1–200,000) |
| `endpoint` | string | `null` | Override endpoint URL for self-hosted models |

#### Retry Policy

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_retries` | int | `3` | Number of retry attempts on failure |
| `delay_seconds` | float | `1.0` | Initial delay between retries |
| `backoff_multiplier` | float | `2.0` | Multiplier for exponential backoff |

Retry delays: 1s, 2s, 4s (with default settings and 3 retries).

---

### workflow.yaml

Defines the phase graph that work items flow through, plus the status lifecycle.

```yaml
name: Content Moderation Pipeline
description: Multi-phase content moderation workflow

# Status lifecycle for work items
statuses:
  - id: submitted
    name: Submitted
    is_initial: true
    transitions_to: [analyzing]

  - id: analyzing
    name: Analyzing
    transitions_to: [in_review, auto_approved]

  - id: in_review
    name: In Review
    transitions_to: [approved, rejected, escalated]

  - id: escalated
    name: Escalated
    transitions_to: [approved, rejected]

  - id: approved
    name: Approved
    is_terminal: true

  - id: rejected
    name: Rejected
    is_terminal: true

# Processing phases — the directed graph
phases:
  - id: analysis
    name: Sentiment Analysis
    description: Automated sentiment and tone analysis
    order: 1
    agents: [sentiment-analyzer]
    parallel: false
    quality_gates:
      - name: confidence-gate
        description: Ensure analysis confidence meets threshold
        conditions:
          - expression: "confidence >= 0.5"
            description: Minimum confidence for reliable analysis
        on_failure: warn
    on_success: review
    on_failure: review

  - id: review
    name: Content Review
    order: 2
    agents: [content-reviewer]
    parallel: false
    on_success: done
    on_failure: escalation

  - id: escalation
    name: Escalation Review
    order: 3
    agents: [escalation-handler]
    requires_human: true
    on_success: done
    on_failure: done

  - id: done
    name: Complete
    order: 4
    agents: []
    is_terminal: true
```

#### Status Field Reference

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `id` | string | *required* | Unique status identifier |
| `name` | string | *required* | Display name |
| `description` | string | `""` | Human-readable description |
| `is_initial` | bool | `false` | Starting status (exactly one required) |
| `is_terminal` | bool | `false` | End status (at least one required) |
| `transitions_to` | list[string] | `[]` | Valid next status IDs |

#### Phase Field Reference

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `id` | string | *required* | Unique phase identifier |
| `name` | string | *required* | Display name |
| `description` | string | `""` | Human-readable description |
| `order` | int | *required* | Execution order (for display/ordering) |
| `agents` | list[string] | `[]` | Agent IDs that run in this phase |
| `parallel` | bool | `false` | Run agents concurrently (`true`) or sequentially (`false`) |
| `on_success` | string | `""` | Next phase ID when all agents succeed |
| `on_failure` | string | `""` | Fallback phase ID when an agent fails |
| `is_terminal` | bool | `false` | Marks the end of the pipeline |
| `skippable` | bool | `false` | Whether this phase can be skipped |
| `skip` | bool | `false` | Runtime toggle to skip this phase |
| `requires_human` | bool | `false` | Indicates human review is expected |
| `entry_conditions` | list[object] | `[]` | Conditions to check before entering phase |
| `exit_conditions` | list[object] | `[]` | Conditions to check before exiting phase |
| `quality_gates` | list[object] | `[]` | Post-phase quality checks |

#### Quality Gate

```yaml
quality_gates:
  - name: test-coverage
    description: Minimum test coverage threshold
    conditions:
      - expression: "coverage >= 0.8"
        description: At least 80% code coverage
      - expression: "tests_passed == tests_total"
        description: All tests pass
    on_failure: block    # block, warn, or skip
```

#### Phase Graph Rules

- `on_success` and `on_failure` must reference existing phase IDs
- At least one phase must have `is_terminal: true`
- Terminal phases must be reachable from the first phase
- A phase with no agents acts as a pass-through or terminal

---

### governance.yaml

Defines automated governance policies and confidence thresholds for decision-making.

```yaml
# Delegated authority — confidence-based thresholds
delegated_authority:
  auto_approve_threshold: 0.9    # >= 0.9 → auto-approve
  review_threshold: 0.5          # >= 0.5 → allow with warning
  abort_threshold: 0.1           # < 0.1  → abort processing

  # Override thresholds for specific work types
  work_type_overrides:
    hate_speech:
      auto_approve_threshold: 0.99
      review_threshold: 0.7
    security:
      auto_approve_threshold: 0.95
      review_threshold: 0.7

# Named policies — checked in priority order (highest first)
policies:
  - id: auto-approve-safe
    name: Auto-Approve Safe Content
    description: Automatically approve content with high confidence
    scope: global
    action: allow
    conditions:
      - "confidence >= 0.9"
      - "severity == 'none'"
    priority: 100
    enabled: true
    tags: [auto-approve, safe-content]

  - id: escalate-hate-speech
    name: Escalate Hate Speech
    description: Immediately escalate detected hate speech
    action: escalate
    conditions:
      - "category == 'hate_speech'"
      - "confidence >= 0.6"
    priority: 200
    tags: [escalation, hate-speech]

  - id: reject-critical
    name: Reject High Severity
    description: Auto-reject confirmed critical violations
    action: deny
    conditions:
      - "severity == 'critical'"
      - "confidence >= 0.95"
    priority: 300
    tags: [auto-reject, critical]

  - id: flag-low-confidence
    name: Flag Low Confidence
    description: Queue for human review when confidence is low
    action: review
    conditions:
      - "confidence < 0.5"
    priority: 90
    tags: [review-queue]
```

#### Delegated Authority Thresholds

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `auto_approve_threshold` | float | `0.8` | Confidence >= this → `ALLOW` |
| `review_threshold` | float | `0.5` | Confidence >= this → `ALLOW_WITH_WARNING` |
| `abort_threshold` | float | `0.2` | Confidence < this → `ABORT` |
| `work_type_overrides` | dict | `{}` | Per-type threshold overrides |

Threshold ordering must be: `auto_approve > review > abort`.

Between `review` and `abort` thresholds → `QUEUE_FOR_REVIEW`.

#### Policy Field Reference

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `id` | string | *required* | Unique policy identifier |
| `name` | string | *required* | Display name |
| `description` | string | `""` | What this policy does |
| `scope` | string | `"global"` | Policy scope |
| `action` | string | *required* | One of: `allow`, `deny`, `review`, `warn`, `escalate` |
| `conditions` | list[string] | `[]` | Expressions that must all match (AND logic) |
| `priority` | int | `0` | Higher priority = checked first |
| `enabled` | bool | `true` | Whether this policy is active |
| `tags` | list[string] | `[]` | Organizational tags |

#### Condition Expressions

Conditions are safe expressions evaluated against execution context. Supported operators:

```
>=   <=   !=   ==   >   <   in
```

Examples:
```yaml
conditions:
  - "confidence >= 0.8"
  - "severity == 'none'"
  - "category == 'hate_speech'"
  - "failure_count >= 3"
  - "risk_level in ['low', 'medium']"
  - "finding_severity in ['HIGH', 'CRITICAL']"
```

Only context keys are accessible — no arbitrary code execution.

---

### workitems.yaml

Defines the types of work items your system processes, including custom fields and artifact types.

```yaml
work_item_types:
  - id: content-submission
    name: Content Submission
    description: User-generated content submitted for moderation
    custom_fields:
      - name: content_text
        type: text
        required: true

      - name: content_type
        type: enum
        required: true
        values: [post, comment, message, review, profile]

      - name: author_id
        type: string
        required: true

      - name: platform
        type: enum
        required: false
        values: [web, mobile, api]

      - name: language
        type: string
        required: false
        default: "en"

      - name: report_count
        type: integer
        required: false
        default: 0

    artifact_types:
      - id: sentiment-report
        name: Sentiment Analysis Report
        file_extensions: [.json]

      - id: moderation-report
        name: Moderation Report
        file_extensions: [.json, .md]
```

#### Work Item Type Field Reference

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `id` | string | *required* | Unique type identifier (referenced when submitting items) |
| `name` | string | *required* | Display name |
| `description` | string | `""` | Human-readable description |
| `custom_fields` | list[object] | `[]` | Custom field definitions |
| `artifact_types` | list[object] | `[]` | Output artifact definitions |

#### Custom Field Types

| `type` | Description | Requires `values`? |
|--------|-------------|-------------------|
| `string` | Short text | No |
| `text` | Long text | No |
| `integer` | Whole number | No |
| `float` | Decimal number | No |
| `boolean` | true/false | No |
| `enum` | One of a fixed set | **Yes** — must provide `values` list |

#### Custom Field Definition

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | *required* | Field name |
| `type` | string | `"string"` | One of: `string`, `text`, `integer`, `float`, `boolean`, `enum` |
| `required` | bool | `false` | Whether the field is mandatory |
| `default` | any | `null` | Default value |
| `values` | list[string] | `null` | Allowed values (required for `enum` type) |

#### Artifact Type Definition

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `id` | string | *required* | Unique artifact type identifier |
| `name` | string | *required* | Display name |
| `description` | string | `""` | Description |
| `file_extensions` | list[string] | `[]` | Expected file extensions (e.g., `.json`, `.md`) |

---

## LLM Provider Setup

The engine auto-registers providers at startup based on what API keys and SDKs are available. Missing SDKs are skipped with a warning.

### OpenAI

```yaml
# settings.yaml
api_keys:
  openai: "sk-proj-..."

# agents.yaml — per agent
llm:
  provider: openai
  model: gpt-4o          # or gpt-4-turbo, gpt-3.5-turbo, etc.
  temperature: 0.3
  max_tokens: 4000
```

### Anthropic

```yaml
api_keys:
  anthropic: "sk-ant-api03-..."

llm:
  provider: anthropic
  model: claude-sonnet-4-20250514    # or claude-opus-4-1, etc.
  temperature: 0.3
  max_tokens: 4000
```

The Anthropic provider automatically extracts any system message and passes it via the dedicated `system` parameter (Anthropic API format).

### Google Gemini

```yaml
api_keys:
  google: "AIza..."

llm:
  provider: google
  model: gemini-1.5-pro    # or gemini-1.5-flash, gemini-pro
  temperature: 0.3
  max_tokens: 4000
```

The Google provider wraps the synchronous SDK in `asyncio.to_thread()` for non-blocking execution.

### Grok (xAI)

```yaml
api_keys:
  grok: "xai-..."

llm:
  provider: grok
  model: grok-2
  temperature: 0.3
  max_tokens: 4000
```

Uses the OpenAI SDK pointed at `https://api.x.ai/v1`.

### Ollama (Local)

No API key required. Just have Ollama running.

```yaml
# settings.yaml
llm_endpoints:
  ollama: "http://localhost:11434"   # default if omitted

# agents.yaml
llm:
  provider: ollama
  model: llama3          # or mistral, neural-chat, codellama, etc.
  temperature: 0.3
```

### Mixing Providers

Different agents can use different providers within the same profile:

```yaml
agents:
  - id: analyst
    llm:
      provider: openai
      model: gpt-4o
    # ...

  - id: reviewer
    llm:
      provider: anthropic
      model: claude-sonnet-4-20250514
    # ...

  - id: local-summarizer
    llm:
      provider: ollama
      model: llama3
    # ...
```

---

## CLI Reference

### Workspace Commands

```bash
# Initialize workspace (optionally from template)
agent-orchestrator init [--template content-moderation|software-dev] [WORKSPACE]

# Validate configuration
agent-orchestrator validate [--workspace .]

# Start engine in headless mode (Ctrl+C to stop)
agent-orchestrator start [--workspace .]

# Submit a work item
agent-orchestrator submit --title "Review this" --type-id task [--priority 5] [--workspace .]
agent-orchestrator submit --file workitem.json [--workspace .]

# Start REST API server
agent-orchestrator serve [--workspace .] [--host 0.0.0.0] [--port 8000]

# Export workspace config as ZIP
agent-orchestrator export WORKSPACE [--output workspace-export.zip]

# Import workspace config from ZIP
agent-orchestrator import BUNDLE [--workspace .]
```

### Profile Commands

```bash
# List available profiles
agent-orchestrator profile list [--workspace .]

# Switch active profile
agent-orchestrator profile switch my-profile [--workspace .]

# Create a new empty profile
agent-orchestrator profile create my-profile [--workspace .]

# Export profile components
agent-orchestrator profile export \
  --component agents|workflow|governance|workitems|all \
  --format yaml|json \
  [--output path] \
  [--workspace .]
```

### Agent Commands

```bash
# List agents in active profile
agent-orchestrator agent list [--workspace .]

# Get agent details
agent-orchestrator agent get my-agent [--workspace .]

# Create a new agent
agent-orchestrator agent create \
  --id my-agent \
  --name "My Agent" \
  --system-prompt "You are a helpful agent." \
  --phases phase-1,phase-2 \
  --provider openai \
  --model gpt-4o \
  --concurrency 2 \
  [--workspace .]

# Update an agent
agent-orchestrator agent update my-agent \
  --name "Updated Name" \
  --concurrency 3 \
  --enabled \
  [--workspace .]

# Delete an agent
agent-orchestrator agent delete my-agent [--workspace .]

# Import agents from file
agent-orchestrator agent import agents-export.yaml [--workspace .]

# Export agents to file
agent-orchestrator agent export --format yaml --output agents.yaml [--workspace .]
```

---

## REST API Reference

Base URL: `http://localhost:8000/api/v1`

Interactive docs available at `http://localhost:8000/docs` when running `agent-orchestrator serve`.

### Health

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/health/ready` | Readiness probe |
| `GET` | `/health/live` | Liveness probe |
| `GET` | `/context` | Current execution context |

```bash
curl http://localhost:8000/api/v1/health
# {"status": "ok", "version": "0.1.0", "timestamp": "2026-02-28T..."}

curl http://localhost:8000/api/v1/context
# {"app_id": "default", "deployment_mode": "lite", "tenant_id": "default", "environment": "development", "profile_name": "my-profile"}
```

### Execution Control

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/execution/status` | Get engine state, queue/pipeline/agent stats |
| `POST` | `/execution/start` | Start the engine |
| `POST` | `/execution/stop` | Stop the engine |
| `POST` | `/execution/pause` | Pause processing |
| `POST` | `/execution/resume` | Resume processing |

```bash
# Start the engine
curl -X POST http://localhost:8000/api/v1/execution/start
# {"status": "started"}

# Check status
curl http://localhost:8000/api/v1/execution/status
# {"state": "running", "queue": {...}, "pipeline": {...}, "agents": {...}}

# Pause and resume
curl -X POST http://localhost:8000/api/v1/execution/pause
curl -X POST http://localhost:8000/api/v1/execution/resume

# Stop
curl -X POST http://localhost:8000/api/v1/execution/stop
```

### Work Items

| Method | Path | Description | Status |
|--------|------|-------------|--------|
| `GET` | `/workitems` | List all work items | 200 |
| `POST` | `/workitems` | Submit a work item | 201 |
| `GET` | `/workitems/{work_id}` | Get work item by ID | 200 / 404 |

#### Submit a work item

```bash
curl -X POST http://localhost:8000/api/v1/workitems \
  -H "Content-Type: application/json" \
  -d '{
    "id": "item-001",
    "type_id": "content-submission",
    "title": "Review user post",
    "data": {
      "content_text": "This is the content to moderate.",
      "content_type": "post",
      "author_id": "user-42"
    },
    "priority": 3
  }'
```

**Request body:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `id` | string | *required* | Unique work item ID |
| `type_id` | string | *required* | Work item type (from `workitems.yaml`) |
| `title` | string | *required* | Human-readable title |
| `data` | object | `{}` | Payload data passed to agents |
| `priority` | int | `5` | Priority (0 = highest, 10 = lowest) |
| `app_id` | string | `"default"` | Application namespace for multi-app scoping |

**Response:**

```json
{
  "id": "item-001",
  "type_id": "content-submission",
  "title": "Review user post",
  "status": "pending",
  "current_phase": "",
  "app_id": "default",
  "run_id": "a1b2c3d4e5f6..."
}
```

### Agents

| Method | Path | Description | Status |
|--------|------|-------------|--------|
| `GET` | `/agents` | List all agents | 200 |
| `GET` | `/agents/{agent_id}` | Get agent details | 200 / 404 |
| `POST` | `/agents` | Create agent | 201 / 409 / 422 |
| `PUT` | `/agents/{agent_id}` | Update agent | 200 / 404 / 422 |
| `DELETE` | `/agents/{agent_id}` | Delete agent | 200 / 404 |
| `POST` | `/agents/{agent_id}/scale?concurrency=N` | Scale concurrency | 200 / 400 |
| `GET` | `/agents/export?fmt=yaml` | Export all agents | 200 |
| `POST` | `/agents/import` | Import agents (file upload) | 200 / 422 |

#### Create an agent

```bash
curl -X POST http://localhost:8000/api/v1/agents \
  -H "Content-Type: application/json" \
  -d '{
    "id": "my-agent",
    "name": "My Agent",
    "system_prompt": "You are a helpful assistant.",
    "phases": ["analysis"],
    "llm": {
      "provider": "openai",
      "model": "gpt-4o",
      "temperature": 0.3,
      "max_tokens": 4000
    },
    "concurrency": 2,
    "retry_policy": {
      "max_retries": 3,
      "delay_seconds": 1.0,
      "backoff_multiplier": 2.0
    }
  }'
```

#### Update an agent

```bash
curl -X PUT http://localhost:8000/api/v1/agents/my-agent \
  -H "Content-Type: application/json" \
  -d '{
    "concurrency": 5,
    "enabled": false
  }'
```

#### Scale concurrency at runtime

```bash
curl -X POST "http://localhost:8000/api/v1/agents/my-agent/scale?concurrency=4"
```

### Workflow

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/workflow/phases` | List all workflow phases |
| `GET` | `/workflow/phases/{phase_id}` | Get phase details |

```bash
curl http://localhost:8000/api/v1/workflow/phases
# [{"id": "analysis", "name": "Sentiment Analysis", "order": 1, ...}, ...]
```

### Governance

| Method | Path | Description | Status |
|--------|------|-------------|--------|
| `GET` | `/governance/policies` | List active policies | 200 |
| `POST` | `/governance/policies` | Create a policy at runtime | 201 |
| `GET` | `/governance/reviews` | List items in review queue | 200 |

#### Create a policy at runtime

```bash
curl -X POST http://localhost:8000/api/v1/governance/policies \
  -H "Content-Type: application/json" \
  -d '{
    "id": "block-spam",
    "name": "Block Spam",
    "action": "deny",
    "conditions": ["category == '\''spam'\''", "confidence >= 0.8"],
    "priority": 150,
    "tags": ["spam", "auto-reject"]
  }'
```

**Policy actions:** `allow`, `deny`, `review`, `warn`, `escalate`

### Metrics

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/metrics` | Aggregated execution metrics |
| `GET` | `/metrics/agents/{agent_id}` | Per-agent metrics |

```bash
curl http://localhost:8000/api/v1/metrics
# {"total_entries": 42, "counters": {"phase.completed": 15, "work.completed": 5}}
```

### Audit

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/audit` | Query audit trail |

**Query parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `work_id` | string | `null` | Filter by work item ID |
| `record_type` | string | `null` | Filter by type (see below) |
| `limit` | int | `100` | Max records to return |
| `app_id` | string | `null` | Filter by application ID |
| `run_id` | string | `null` | Filter by run ID |

**Record types:** `decision`, `state_change`, `escalation`, `error`, `config_change`, `system_event`

```bash
# Get all audit records for a work item
curl "http://localhost:8000/api/v1/audit?work_id=item-001"

# Get only error records
curl "http://localhost:8000/api/v1/audit?record_type=error&limit=50"
```

### Configuration

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/config/profiles` | List available profiles |
| `GET` | `/config/profile/export?component=all` | Export profile config |
| `POST` | `/config/validate` | Validate current configuration |
| `GET` | `/config/history` | Configuration change history |

**Export components:** `agents`, `workflow`, `governance`, `workitems`, `all`

```bash
# List profiles
curl http://localhost:8000/api/v1/config/profiles
# {"profiles": ["default", "content-moderation"], "active": "content-moderation"}

# Export agents config
curl "http://localhost:8000/api/v1/config/profile/export?component=agents"

# Validate configuration
curl -X POST http://localhost:8000/api/v1/config/validate
# {"is_valid": true, "errors": [], "warnings": []}
```

---

## Python SDK

Use the Python classes directly for programmatic control.

### Engine Lifecycle

```python
from pathlib import Path
from agent_orchestrator.configuration.loader import ConfigurationManager
from agent_orchestrator.core.engine import OrchestrationEngine
from agent_orchestrator.core.work_queue import WorkItem

# Load configuration
config = ConfigurationManager(Path("./my-workspace"))
config.load()

# Create and start engine
engine = OrchestrationEngine(config)
await engine.start()

# Submit work
item = WorkItem(
    id="item-1",
    type_id="content-submission",
    title="Review this post",
    data={"content_text": "Hello world", "author_id": "user-1"},
    priority=3,
)
await engine.submit_work(item)

# Check status
status = engine.get_status()
print(status["state"])  # "running"

# Pause / resume / stop
await engine.pause()
await engine.resume()
await engine.stop()
```

### Event Subscriptions

```python
from agent_orchestrator.core.event_bus import Event, EventType

async def on_work_completed(event: Event):
    print(f"Work completed: {event.data['work_id']}")

engine.event_bus.subscribe(EventType.WORK_COMPLETED, on_work_completed)
engine.event_bus.subscribe(EventType.WORK_FAILED, on_work_failed)

# Subscribe to all events
engine.event_bus.subscribe_all(log_all_events)
```

### Custom LLM Callback

Inject your own LLM function instead of using the built-in providers:

```python
async def my_llm_fn(system_prompt, user_prompt, llm_config):
    # Call your own LLM service
    response = await my_custom_api(system_prompt, user_prompt)
    return {
        "response": response.text,
        "model": llm_config.model,
        "confidence": response.confidence,
    }

engine = OrchestrationEngine(config, llm_call_fn=my_llm_fn)
```

### Custom LLM Provider

Implement the provider protocol and register it:

```python
from agent_orchestrator.adapters.llm_adapter import LLMAdapter, LLMProviderProtocol

class MyProvider:
    """Must implement the complete() method."""

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str,
        **kwargs,
    ) -> dict[str, Any]:
        # messages = [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]
        result = await call_my_service(messages, model, **kwargs)
        return {
            "response": result.text,
            "model": model,
            "usage": {"input_tokens": result.in_tokens, "output_tokens": result.out_tokens},
        }

# Register the provider
settings = config.get_settings()
adapter = LLMAdapter(settings)
adapter.register_provider("my-provider", MyProvider())

# Agents can now use provider: my-provider in their LLM config
```

### Configuration Validation

```python
from agent_orchestrator.configuration.validator import validate_profile

config = ConfigurationManager(Path("./my-workspace"))
config.load()

profile = config.get_profile()
settings = config.get_settings()
result = validate_profile(profile, settings)

if not result.is_valid:
    for error in result.errors:
        print(f"ERROR: {error}")
for warning in result.warnings:
    print(f"WARNING: {warning}")
```

### Agent Management

```python
# Via AgentManager
from agent_orchestrator.configuration.agent_manager import AgentManager

manager = AgentManager(config)
agents = manager.list_agents()
agent = manager.get_agent("my-agent")

# Create
new_agent = manager.create_agent({
    "id": "new-agent",
    "name": "New Agent",
    "system_prompt": "You are helpful.",
    "phases": ["analysis"],
    "llm": {"provider": "openai", "model": "gpt-4o"},
})

# Update
updated = manager.update_agent("new-agent", {"concurrency": 3})

# Delete
manager.delete_agent("new-agent")

# Import / export
manager.import_agents(Path("agents.yaml"))
manager.export_agents(Path("exported-agents.yaml"), fmt="yaml")
```

### REST API App

Run the API programmatically:

```python
import uvicorn
from agent_orchestrator.api.app import create_app

app = create_app(workspace_dir=Path("./my-workspace"))
uvicorn.run(app, host="0.0.0.0", port=8000)
```

---

## Built-in Profile Templates

### content-moderation

A 3-phase content moderation pipeline with sentiment analysis, policy review, and escalation handling.

**Agents:**

| Agent | Provider | Model | Concurrency | Phase |
|-------|----------|-------|-------------|-------|
| `sentiment-analyzer` | openai | gpt-4o | 3 | analysis |
| `content-reviewer` | anthropic | claude-sonnet-4-20250514 | 2 | review |
| `escalation-handler` | anthropic | claude-sonnet-4-20250514 | 1 | escalation |

**Phase graph:**

```
analysis ──success──► review ──success──► done
    │                   │
    └──failure──► review └──failure──► escalation ──► done
```

**Governance highlights:**
- Auto-approve: confidence >= 0.9 and severity == 'none'
- Escalate: hate speech with confidence >= 0.6
- Reject: critical severity with confidence >= 0.95
- Review: confidence < 0.5
- Stricter thresholds for hate_speech and violence categories

**Work item types:** `content-submission` (with content_text, content_type, author_id, platform, language fields), `appeal` (with original_decision_id, appeal_reason fields)

### software-dev

An 8-phase software development lifecycle from requirements through deployment.

**Agents:**

| Agent | Provider | Model | Concurrency | Phases |
|-------|----------|-------|-------------|--------|
| `pm` | anthropic | claude-sonnet-4-20250514 | 1 | requirements |
| `architect` | anthropic | claude-sonnet-4-20250514 | 1 | design |
| `backend-dev` | anthropic | claude-sonnet-4-20250514 | 2 | implementation, bugfix |
| `frontend-dev` | openai | gpt-4o | 2 | implementation, bugfix |
| `reviewer` | anthropic | claude-sonnet-4-20250514 | 1 | review |
| `security-scanner` | anthropic | claude-sonnet-4-20250514 | 1 | security |
| `tester` | openai | gpt-4o | 2 | testing |
| `devops` | openai | gpt-4o | 1 | deployment |

**Phase graph:**

```
requirements ──► design ──► implementation ──► review ──► security ──► testing ──► deployment ──► complete
                    │         (parallel)         │          │            │             │
                    └────────── ◄── bugfix ◄─────┘──────────┘────────────┘─────────────┘
                                  (parallel)
```

**Quality gates:**
- Design: `components_defined >= 1`
- Review: `critical_issues == 0`
- Security: `critical_count == 0` and `high_count == 0`
- Testing: `coverage >= 0.8` and `tests_passed == tests_total`

**Work item types:** `user-story` (with acceptance_criteria, story_points, requires_backend/frontend fields), `bug-report` (with steps_to_reproduce, severity, affected_component fields)

---

## Validation Rules

Run `agent-orchestrator validate` or `POST /config/validate` to check your configuration. The validator checks:

### 1. Agent-Phase References
- Every agent's `phases` list must reference phase IDs that exist in `workflow.yaml`
- Every phase's `agents` list must reference agent IDs that exist in `agents.yaml`

### 2. Phase Graph Integrity
- `on_success` and `on_failure` must reference existing phase IDs
- At least one phase must be marked `is_terminal: true`
- Terminal phases must be reachable from the initial phase

### 3. Status Transitions
- `transitions_to` must reference existing status IDs
- Exactly one status must have `is_initial: true`
- At least one status must have `is_terminal: true`

### 4. LLM Provider Keys
- Every enabled agent's `provider` must have a corresponding key in `settings.yaml` `api_keys`
- Exception: `ollama` and `custom` providers don't need API keys

### 5. Governance Thresholds
- Must satisfy: `auto_approve_threshold > review_threshold > abort_threshold`
- Policy `action` must be one of: `allow`, `deny`, `review`, `warn`, `escalate`

### 6. Field Definitions
- `enum` fields must include a `values` list

Errors block startup. Warnings are informational and logged.

---

## Building Apps

Agent-orchestrator is designed to be a platform you build domain-specific apps on top of. This section covers the developer experience tools available.

### Public SDK Imports

All primary types are exported from the top-level package:

```python
from agent_orchestrator import (
    OrchestrationEngine, EngineState, WorkItem, WorkItemStatus,
    EventBus, Event, EventType,
    ConfigurationManager, ProfileConfig, AgentDefinition,
    WorkflowConfig, LLMConfig, SettingsConfig,
    Governor, GovernanceDecision, Resolution, AuditLogger,
    AppManifest,
    ExecutionContext, DeploymentMode,
)
```

### App Manifest (`app.yaml`)

An optional `app.yaml` in your profile directory declares metadata, dependencies, and hooks:

```yaml
name: my-app
version: "1.0.0"
description: My domain-specific app
platform_version: "0.1.0"
requires:
  providers: [openai, anthropic]
  connectors: [web_search]
produces:
  work_item_types: [research-query]
  artifact_types: [research-report]
hooks:
  process: "myapp.helpers.hooks:process_hook"
author: "Your Name"
```

The manifest is loaded automatically and attached to `ProfileConfig.manifest`. Profiles without `app.yaml` work exactly as before.

### Test Helpers

Install with `pip install agent-orchestrator[testing]` and use factory functions:

```python
from agent_orchestrator.testing import (
    make_work_item, make_agent, make_profile, make_workspace, mock_llm_fn,
)

def test_my_workflow():
    item = make_work_item(title="Review PR #42")
    agent = make_agent(id="reviewer", phases=["review"])
    profile = make_profile(agents=[agent])
    assert len(profile.agents) == 1

def test_with_workspace(tmp_path):
    workspace = make_workspace(tmp_path)
    # workspace is a real directory with settings.yaml and a profile
```

### Scaffolding with `new-app`

Generate a complete app skeleton:

```bash
agent-orchestrator new-app my-app --workspace workspace
agent-orchestrator new-app my-app --workspace workspace --with-hooks
```

This creates:
```
profiles/my-app/
  app.yaml           # manifest
  agents.yaml        # one starter agent
  workflow.yaml      # two-phase workflow
  governance.yaml    # default governance
  workitems.yaml     # one work item type
  helpers/           # for domain code
    __init__.py
  tests/
    conftest.py      # imports test helpers
    test_example.py  # shows the testing pattern
```

### Extension Points

See [docs/EXTENSION_POINTS.md](docs/EXTENSION_POINTS.md) for detailed documentation on:

1. **Phase context hooks** — inject custom data into phase execution
2. **Event bus subscriptions** — react to engine events
3. **Custom LLM providers** — implement `LLMProviderProtocol`
4. **Connectors & contracts** — register capability providers
