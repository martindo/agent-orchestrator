# Getting Started

Set up and run Agent Orchestrator to build your own domain-specific AI workflow.

---

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/) installed
- At least one LLM API key (OpenAI, Anthropic, Google, or Grok) — or a local [Ollama](https://ollama.com) instance

---

## 1. Clone and Configure

```bash
git clone <your-repo-url> agent-orchestrator
cd agent-orchestrator

# Create your .env file from the example
cp .env.example .env
```

Edit `.env` and add your API keys:

```dotenv
# PostgreSQL (defaults work out of the box)
POSTGRES_USER=orchestrator
POSTGRES_PASSWORD=changeme
POSTGRES_DB=agent_orchestrator

# Add at least one LLM provider key
AGENT_ORCH_OPENAI_API_KEY=sk-proj-...
AGENT_ORCH_ANTHROPIC_API_KEY=sk-ant-...
AGENT_ORCH_GOOGLE_API_KEY=
AGENT_ORCH_GROK_API_KEY=
```

---

## 2. Start the Platform

```bash
docker compose up -d
```

This does three things:

1. **Builds the `api` container** from the Dockerfile (Python 3.11 + all LLM SDKs)
2. **Starts the `db` container** (PostgreSQL 16) and automatically:
   - Creates the `agent_orchestrator` database
   - Runs `db/init/01_schema.sql` to create all tables (settings, agents, workflows, governance, work items, audit, metrics, etc.)
   - Runs `db/init/02_seed.sql` to seed two built-in profiles: **content-moderation** and **software-dev**
3. **Starts the API server** on `http://localhost:8000` once the database is healthy

Verify everything is running:

```bash
docker compose ps

# Check the API is responding
curl http://localhost:8000/api/v1/health
```

Browse the interactive API docs at **http://localhost:8000/docs**.

---

## 3. Initialize a Workspace

The API server needs a workspace directory with YAML configuration. Create one from a built-in template:

```bash
docker compose run --rm api init /workspace --template content-moderation
```

This creates the workspace structure inside `./workspace/` on your host:

```
workspace/
├── settings.yaml              # Active profile, API keys, LLM endpoints
├── profiles/
│   └── content-moderation/
│       ├── agents.yaml        # Agent definitions (prompts, models, phases)
│       ├── workflow.yaml      # Phase pipeline and status lifecycle
│       ├── governance.yaml    # Policies and confidence thresholds
│       └── workitems.yaml     # Work item type definitions
```

Restart the API so it picks up the workspace:

```bash
docker compose restart api
```

---

## 4. Build Your Own Domain Workflow

To create a workflow for your domain (e.g., insurance claims, legal review, customer support), edit the four YAML files in `workspace/profiles/<your-profile>/`.

### Step 1: Define your agents (`agents.yaml`)

Each agent is an LLM with a specific role, system prompt, and assigned workflow phase.

```yaml
agents:
  - id: intake-agent
    name: Intake Processor
    description: Extracts key information from incoming claims
    system_prompt: |
      You are an insurance claims intake processor. Extract:
      - Claimant name and policy number
      - Date of incident
      - Description of damage
      - Estimated claim amount
      Return structured JSON.
    phases:
      - intake
    llm:
      provider: openai
      model: gpt-4o
      temperature: 0.1
      max_tokens: 2000
    concurrency: 3

  - id: adjuster-agent
    name: Claims Adjuster
    description: Evaluates claim validity and coverage
    system_prompt: |
      You are a claims adjuster. Given the intake data, evaluate:
      - Policy coverage applicability
      - Claim validity assessment
      - Recommended payout range
      Provide a confidence score and reasoning.
    phases:
      - evaluation
    llm:
      provider: anthropic
      model: claude-sonnet-4-20250514
      temperature: 0.2
      max_tokens: 4000
    concurrency: 2

  - id: fraud-detector
    name: Fraud Detection Agent
    description: Screens claims for fraud indicators
    phases:
      - fraud-check
    system_prompt: |
      You are a fraud detection specialist. Analyze the claim for:
      - Inconsistencies in the narrative
      - Red flags (frequency of claims, timing, amount patterns)
      - Fraud risk score (0.0 to 1.0)
    llm:
      provider: anthropic
      model: claude-sonnet-4-20250514
      temperature: 0.1
      max_tokens: 3000
    concurrency: 2
```

### Step 2: Define your workflow phases (`workflow.yaml`)

Phases form a directed graph. Each phase runs one or more agents, then transitions based on success or failure.

```yaml
name: Insurance Claims Pipeline
description: Intake -> Evaluate -> Fraud Check -> Decision

statuses:
  - id: submitted
    name: Submitted
    is_initial: true
    transitions_to: [processing]
  - id: processing
    name: Processing
    transitions_to: [approved, denied, escalated]
  - id: approved
    name: Approved
    is_terminal: true
  - id: denied
    name: Denied
    is_terminal: true
  - id: escalated
    name: Escalated
    is_terminal: true

phases:
  - id: intake
    name: Intake Processing
    order: 1
    agents: [intake-agent]
    on_success: evaluation
    on_failure: done

  - id: evaluation
    name: Claims Evaluation
    order: 2
    agents: [adjuster-agent]
    on_success: fraud-check
    on_failure: done

  - id: fraud-check
    name: Fraud Screening
    order: 3
    agents: [fraud-detector]
    on_success: done
    on_failure: done

  - id: done
    name: Complete
    order: 4
    agents: []
    is_terminal: true
```

### Step 3: Define governance policies (`governance.yaml`)

Policies control automatic approvals, escalations, and rejections based on agent output.

```yaml
delegated_authority:
  auto_approve_threshold: 0.9
  review_threshold: 0.5
  abort_threshold: 0.1

policies:
  - id: auto-approve-low-risk
    name: Auto-approve low risk claims
    action: allow
    conditions:
      - "confidence >= 0.9"
      - "fraud_score < 0.2"
    priority: 100

  - id: escalate-high-value
    name: Escalate high value claims
    action: escalate
    conditions:
      - "claim_amount >= 50000"
    priority: 200

  - id: flag-fraud-risk
    name: Flag fraud risk
    action: deny
    conditions:
      - "fraud_score >= 0.8"
    priority: 300
```

### Step 4: Define work item types (`workitems.yaml`)

Describe what data each work item carries.

```yaml
work_item_types:
  - id: insurance-claim
    name: Insurance Claim
    description: An insurance claim submitted for processing
    custom_fields:
      - name: claim_text
        type: text
        required: true
      - name: policy_number
        type: string
        required: true
      - name: claim_amount
        type: float
        required: true
      - name: claim_type
        type: enum
        required: true
        values: [auto, home, health, life, commercial]
```

### Step 5: Update `settings.yaml`

Point to your new profile:

```yaml
active_profile: "my-claims-profile"
api_keys:
  openai: ""       # loaded from AGENT_ORCH_OPENAI_API_KEY env var
  anthropic: ""    # loaded from AGENT_ORCH_ANTHROPIC_API_KEY env var
llm_endpoints:
  ollama: "http://host.docker.internal:11434"
log_level: "INFO"
persistence_backend: "file"
```

Restart to pick up the changes:

```bash
docker compose restart api
```

---

## 5. Submit Work and Run the Pipeline

### Start the engine

```bash
curl -X POST http://localhost:8000/api/v1/execution/start
```

### Submit a work item

```bash
curl -X POST http://localhost:8000/api/v1/workitems \
  -H "Content-Type: application/json" \
  -d '{
    "id": "claim-001",
    "type_id": "insurance-claim",
    "title": "Auto collision claim - Policy #P12345",
    "data": {
      "claim_text": "Rear-ended at a stoplight on Jan 15. Bumper and trunk damage.",
      "policy_number": "P12345",
      "claim_amount": 4500.00,
      "claim_type": "auto"
    },
    "priority": 3
  }'
```

### Monitor progress

```bash
# Check engine status
curl http://localhost:8000/api/v1/execution/status

# Track a specific work item
curl http://localhost:8000/api/v1/workitems/claim-001

# View audit trail
curl http://localhost:8000/api/v1/audit?work_id=claim-001

# View metrics
curl http://localhost:8000/api/v1/metrics
```

---

## 6. Useful Commands

```bash
# View logs
docker compose logs api -f
docker compose logs db -f

# Validate your configuration
curl -X POST http://localhost:8000/api/v1/config/validate

# Pause / resume processing
curl -X POST http://localhost:8000/api/v1/execution/pause
curl -X POST http://localhost:8000/api/v1/execution/resume

# Stop the engine
curl -X POST http://localhost:8000/api/v1/execution/stop

# Scale an agent's concurrency at runtime
curl -X POST "http://localhost:8000/api/v1/agents/intake-agent/scale?concurrency=5"

# List all agents
curl http://localhost:8000/api/v1/agents

# List workflow phases
curl http://localhost:8000/api/v1/workflow/phases

# View items pending human review
curl http://localhost:8000/api/v1/governance/reviews

# Open a psql shell to the database
docker compose exec db psql -U orchestrator -d agent_orchestrator

# Stop everything (data persists)
docker compose down

# Stop and delete all data (fresh start)
docker compose down -v
```

---

## 7. Built-in Profile Templates

Two profiles are seeded in the database and available as workspace templates:

| Template | Phases | Agents | Use case |
|----------|--------|--------|----------|
| `content-moderation` | classify → analyze → decide → complete | classifier, analyzer, reviewer | Content moderation pipelines |
| `software-dev` | plan → implement → test → review → document → deploy → complete | planner, architect, coder, tester, reviewer, doc-writer, security, deployer | Software development lifecycle |

Initialize from a template:

```bash
docker compose run --rm api init /workspace --template software-dev
```

---

## 8. Architecture at a Glance

```
                     ┌─────────────────┐
                     │   REST API       │  :8000/api/v1
                     │   (FastAPI)      │  /docs for Swagger UI
                     └────────┬────────┘
                              │
                 ┌────────────▼────────────┐
                 │   OrchestrationEngine    │
                 │                          │
                 │  WorkQueue → Pipeline    │
                 │  → PhaseExecutor         │
                 │  → AgentPool → LLM      │
                 │  → Governor → Audit      │
                 └────────────┬────────────┘
                              │
                 ┌────────────▼────────────┐
                 │   PostgreSQL             │  :5432
                 │   (schema + seed data)   │
                 └─────────────────────────┘
```

All domain logic lives in your YAML configuration. The engine is generic.

---

## Troubleshooting

**API container won't start?**
```bash
docker compose logs api
```

**Database connection issues?**
The `api` service waits for the `db` healthcheck. If the database is slow to start, the API will wait automatically. Check with:
```bash
docker compose ps
docker compose logs db
```

**Configuration validation errors?**
```bash
curl -X POST http://localhost:8000/api/v1/config/validate
```
This returns specific errors (e.g., agent references a phase that doesn't exist).

**Fresh start?**
```bash
docker compose down -v    # deletes database volume
docker compose up -d      # recreates everything from scratch
```

---

## MCP Integration (Optional)

Connect to external AI tools or expose platform capabilities via the [Model Context Protocol](https://modelcontextprotocol.io):

```bash
# Install MCP support
pip install "agent-orchestrator[mcp]"
```

Add `mcp.yaml` to your profile directory to configure MCP servers and/or enable the MCP server:

```yaml
# profiles/my-profile/mcp.yaml
client:
  servers:
    - server_id: github
      display_name: GitHub MCP
      transport: stdio
      command: npx
      args: ["-y", "@modelcontextprotocol/server-github"]
      env:
        GITHUB_PERSONAL_ACCESS_TOKEN: "${GITHUB_TOKEN}"

server:
  enabled: true
```

Start with MCP server enabled:
```bash
agent-orchestrator serve --workspace . --mcp
```

See [ARCHITECTURE.md](ARCHITECTURE.md#mcp-integration) and [SDK.md](SDK.md#mcpyaml) for full configuration reference.
