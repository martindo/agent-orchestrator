# Installation Guide

Install and configure Agent Orchestrator for your organization's size and infrastructure requirements. The platform supports three deployment profiles — choose the one that fits.

---

## Deployment Profiles at a Glance

| | **Lite** | **Standard** | **Enterprise** |
|---|---|---|---|
| **Best for** | Solo devs, prototyping, small teams | Production teams, multi-service | Large orgs, multi-tenant, regulated |
| **Process model** | Single process | API + workers | API + workers + auth gateway |
| **Storage** | File / SQLite | PostgreSQL | PostgreSQL |
| **External deps** | None | PostgreSQL | PostgreSQL + auth provider |
| **Install command** | `pip install agent-orchestrator` | Docker Compose | Docker Compose + infra config |
| **Multi-app** | Single workspace | Single workspace | Multi-tenant workspaces |
| **Governance** | Full (local audit) | Full (DB-backed audit) | Full + quotas + RBAC (future) |

---

## Lite Mode

**Zero external dependencies.** One `pip install` and you're running.

### Prerequisites

- Python 3.10+
- At least one LLM API key (OpenAI, Anthropic, Google, Grok) — or a local [Ollama](https://ollama.com) instance

### Install

```bash
# Core only
pip install agent-orchestrator

# With all LLM provider SDKs
pip install "agent-orchestrator[llm]"

# With dev/test tools
pip install "agent-orchestrator[llm,dev]"
```

### Initialize a workspace

```bash
agent-orchestrator init my-workspace
cd my-workspace

# Or start from a built-in template
agent-orchestrator init --template content-moderation my-workspace
agent-orchestrator init --template software-dev my-workspace
```

### Configure API keys

Set keys via environment variables (recommended) or edit `settings.yaml` directly:

```bash
export AGENT_ORCH_OPENAI_API_KEY=sk-proj-...
export AGENT_ORCH_ANTHROPIC_API_KEY=sk-ant-...
```

### Run

```bash
# Validate configuration
agent-orchestrator validate my-workspace

# Start the API server (single process — engine + API together)
agent-orchestrator serve my-workspace
```

The server starts at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

### Verify

```bash
curl http://localhost:8000/api/v1/health
# {"status": "ok", "version": "0.1.0", ...}

curl http://localhost:8000/api/v1/context
# {"app_id": "default", "deployment_mode": "lite", ...}
```

### Settings for Lite mode

```yaml
# settings.yaml
active_profile: "my-profile"
deployment_mode: "lite"           # file/SQLite storage, no external deps
persistence_backend: "file"       # or "sqlite"
log_level: "INFO"
api_keys:
  openai: ""                      # filled from env vars
  anthropic: ""
llm_endpoints:
  ollama: "http://localhost:11434"
```

### When to use Lite

- Local development and prototyping
- Single-developer projects
- CI/CD pipeline agents
- Demos and evaluations
- Environments where you cannot install PostgreSQL or Docker

---

## Standard Mode

**Production-ready** with PostgreSQL for durable state and audit trails.

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/)
- At least one LLM API key

### Install

```bash
git clone <your-repo-url> agent-orchestrator
cd agent-orchestrator

# Create environment file
cp .env.example .env
```

### Configure

Edit `.env`:

```dotenv
# PostgreSQL
POSTGRES_USER=orchestrator
POSTGRES_PASSWORD=changeme
POSTGRES_DB=agent_orchestrator

# LLM provider keys (add at least one)
AGENT_ORCH_OPENAI_API_KEY=sk-proj-...
AGENT_ORCH_ANTHROPIC_API_KEY=sk-ant-...
AGENT_ORCH_GOOGLE_API_KEY=
AGENT_ORCH_GROK_API_KEY=
```

### Start

```bash
docker compose up -d
```

This starts three services:

| Service | Description | Port |
|---------|-------------|------|
| `api` | FastAPI server with all LLM SDKs | 8000 |
| `db` | PostgreSQL 16 (auto-creates schema and seeds profiles) | 5432 |
| `ollama` | Local LLM inference (optional) | 11434 |

### Initialize a workspace

```bash
docker compose run --rm api init /workspace --template content-moderation
docker compose restart api
```

### Verify

```bash
# Health check
curl http://localhost:8000/api/v1/health

# View deployment context
curl http://localhost:8000/api/v1/context
# {"deployment_mode": "standard", ...}

# Interactive API docs
open http://localhost:8000/docs
```

### Settings for Standard mode

```yaml
# settings.yaml
active_profile: "my-profile"
deployment_mode: "standard"
persistence_backend: "postgresql"
log_level: "INFO"
api_keys:
  openai: ""
  anthropic: ""
llm_endpoints:
  ollama: "http://ollama:11434"
```

### Submit work and monitor

```bash
# Start the engine
curl -X POST http://localhost:8000/api/v1/execution/start

# Submit a work item
curl -X POST http://localhost:8000/api/v1/workitems \
  -H "Content-Type: application/json" \
  -d '{
    "id": "item-001",
    "type_id": "task",
    "title": "Review this content",
    "data": {"text": "Content to process"},
    "priority": 3
  }'

# Track progress
curl http://localhost:8000/api/v1/workitems/item-001
curl http://localhost:8000/api/v1/execution/status
curl http://localhost:8000/api/v1/audit?work_id=item-001
curl http://localhost:8000/api/v1/metrics
```

### Operational commands

```bash
# View logs
docker compose logs api -f

# Validate configuration
curl -X POST http://localhost:8000/api/v1/config/validate

# Pause / resume / stop engine
curl -X POST http://localhost:8000/api/v1/execution/pause
curl -X POST http://localhost:8000/api/v1/execution/resume
curl -X POST http://localhost:8000/api/v1/execution/stop

# Scale agent concurrency at runtime
curl -X POST "http://localhost:8000/api/v1/agents/my-agent/scale?concurrency=5"

# Database shell
docker compose exec db psql -U orchestrator -d agent_orchestrator

# Stop (data persists)
docker compose down

# Fresh start (deletes all data)
docker compose down -v
```

### When to use Standard

- Production workloads for a single team or department
- Workflows that require durable state across restarts
- Environments where audit trails must survive process crashes
- Teams running multiple concurrent workflows

---

## Enterprise Mode

**Multi-tenant, governed, and scalable.** Builds on Standard with additional isolation and control features.

> **Note:** Enterprise mode currently uses the same infrastructure as Standard. The `enterprise` deployment mode flag is a forward declaration — it enables the runtime context model that future features (authentication, quotas, multi-tenant isolation, RBAC) will build on. Adopt it now to ensure your audit trails and metrics are tagged correctly from day one.

### Prerequisites

Same as Standard mode, plus:

- Organization-wide naming conventions for `app_id` and `tenant_id`
- A plan for API key management across teams

### Install

Follow the [Standard Mode](#standard-mode) installation steps, then update your settings:

```yaml
# settings.yaml
active_profile: "production"
deployment_mode: "enterprise"
persistence_backend: "postgresql"
log_level: "INFO"
```

### What Enterprise mode enables today

1. **Execution context tagging** — Every work item, event, audit record, and metric is tagged with `app_id`, `run_id`, and `tenant_id`
2. **Run identity** — Each submitted work item receives a unique `run_id` (UUID), enabling end-to-end tracing
3. **App scoping** — Work items can specify an `app_id` to namespace operations
4. **Audit filtering** — Query audit records by `app_id` and `run_id`:

```bash
curl "http://localhost:8000/api/v1/audit?app_id=claims-app&run_id=abc123"
```

5. **Context endpoint** — Inspect the current deployment context:

```bash
curl http://localhost:8000/api/v1/context
# {
#   "app_id": "default",
#   "deployment_mode": "enterprise",
#   "tenant_id": "default",
#   "environment": "development",
#   "profile_name": "production"
# }
```

### Submitting work with app scoping

```bash
curl -X POST http://localhost:8000/api/v1/workitems \
  -H "Content-Type: application/json" \
  -d '{
    "id": "claim-001",
    "type_id": "insurance-claim",
    "title": "Auto collision claim",
    "app_id": "claims-processing",
    "data": {"claim_text": "Rear-ended at stoplight"},
    "priority": 3
  }'
```

The response includes the auto-assigned `run_id`:

```json
{
  "id": "claim-001",
  "type_id": "insurance-claim",
  "title": "Auto collision claim",
  "status": "queued",
  "app_id": "claims-processing",
  "run_id": "a1b2c3d4e5f6..."
}
```

### Multi-department setup

For organizations running multiple domain apps on the same platform, use separate profiles per department:

```
workspace/
├── settings.yaml
├── profiles/
│   ├── claims-processing/       # Insurance claims team
│   │   ├── agents.yaml
│   │   ├── workflow.yaml
│   │   ├── governance.yaml
│   │   └── workitems.yaml
│   ├── content-moderation/      # Trust & Safety team
│   │   └── ...
│   └── customer-support/        # Support team
│       └── ...
```

Switch between profiles:

```bash
agent-orchestrator profile switch claims-processing --workspace .
# Or via API:
# Future: POST /config/profiles/switch
```

### When to use Enterprise

- Multiple teams or departments sharing the platform
- Regulated industries requiring scoped audit trails
- Organizations planning for multi-tenant isolation
- Environments that will need quotas and RBAC when those features ship

---

## Upgrading Between Modes

Modes are backward-compatible. Upgrading is a configuration change, not a migration.

### Lite to Standard

1. Install Docker and Docker Compose
2. Change `deployment_mode` from `"lite"` to `"standard"` in `settings.yaml`
3. Change `persistence_backend` from `"file"` to `"postgresql"`
4. Start with `docker compose up -d`
5. Re-initialize workspace: `docker compose run --rm api init /workspace`

### Standard to Enterprise

1. Change `deployment_mode` from `"standard"` to `"enterprise"` in `settings.yaml`
2. Restart: `docker compose restart api`
3. All new work items, events, and audit records will include full context tags

No data migration is required. Existing audit records without `app_id`/`run_id` fields continue to work — they simply have empty values for those fields.

---

## Python SDK Installation

For programmatic use without the CLI or REST API:

```python
from agent_orchestrator import (
    OrchestrationEngine, EngineState,
    WorkItem, WorkItemStatus,
    EventBus, Event, EventType,
    ConfigurationManager, ProfileConfig,
    ExecutionContext, DeploymentMode,
)
```

### Minimal example

```python
import asyncio
from pathlib import Path
from agent_orchestrator import ConfigurationManager, OrchestrationEngine, WorkItem

async def main():
    config = ConfigurationManager(Path("./my-workspace"))
    engine = OrchestrationEngine(config)
    await engine.start()

    # Context is now available
    print(engine.context)  # ExecutionContext(deployment_mode='lite', ...)

    item = WorkItem(id="w1", type_id="task", title="Hello")
    await engine.submit_work(item)
    print(item.run_id)  # auto-assigned UUID

    await engine.stop()

asyncio.run(main())
```

---

## LLM Provider Setup

The platform auto-registers LLM providers at startup based on available API keys and installed SDKs.

| Provider | API Key Env Var | SDK Package | Notes |
|----------|----------------|-------------|-------|
| OpenAI | `AGENT_ORCH_OPENAI_API_KEY` | `openai` | GPT-4o, GPT-4, GPT-3.5 |
| Anthropic | `AGENT_ORCH_ANTHROPIC_API_KEY` | `anthropic` | Claude Opus, Sonnet, Haiku |
| Google | `AGENT_ORCH_GOOGLE_API_KEY` | `google-generativeai` | Gemini Pro, Flash |
| Grok (xAI) | `AGENT_ORCH_GROK_API_KEY` | `openai` (shared) | Grok-2 via OpenAI SDK |
| Ollama | — (no key needed) | `httpx` | Local models (Llama, Mistral, etc.) |

Install all provider SDKs:

```bash
pip install "agent-orchestrator[llm]"
```

Or install individually:

```bash
pip install openai          # OpenAI + Grok
pip install anthropic       # Anthropic Claude
pip install google-generativeai  # Google Gemini
pip install httpx           # Ollama (already a core dependency)
```

---

## Troubleshooting

### pip install fails

```bash
# Ensure Python 3.10+
python --version

# Upgrade pip
pip install --upgrade pip

# Install from source
pip install -e ".[llm,dev]"
```

### Docker Compose won't start

```bash
docker compose logs api
docker compose logs db

# Ensure ports 8000 and 5432 are free
```

### Configuration validation errors

```bash
# CLI
agent-orchestrator validate my-workspace

# API
curl -X POST http://localhost:8000/api/v1/config/validate
```

Common errors:
- Agent references a phase that doesn't exist in `workflow.yaml`
- Phase `on_success`/`on_failure` points to unknown phase ID
- `enum` field missing `values` list
- Governance thresholds not ordered: `auto_approve > review > abort`

### Engine won't start

```bash
# Check engine state
curl http://localhost:8000/api/v1/execution/status

# Check logs
docker compose logs api -f
```

### Fresh start

```bash
# Lite mode — delete workspace state
rm -rf my-workspace/.state

# Docker mode — delete everything including database
docker compose down -v
docker compose up -d
```

---

## Next Steps

- [SDK Reference](../SDK.md) — Configuration files, CLI, REST API, Python SDK
- [Architecture](../ARCHITECTURE.md) — Detailed technical architecture
- [Getting Started](../GETTING_STARTED.md) — Build your first domain workflow
- [Extension Points](EXTENSION_POINTS.md) — Hooks, custom providers, connectors
- [Connector Providers](connector-provider-development.md) — Build connector plugins
