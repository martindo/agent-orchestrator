# Architecture — Agent Orchestrator v0.1.0

Generic, domain-agnostic platform for orchestrating multi-agent workflows with built-in governance, auditing, and observability. All domain knowledge lives in YAML configuration; the engine itself has zero hardcoded domain logic.

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Layer Architecture](#layer-architecture)
3. [Core Layer](#core-layer)
4. [Configuration Layer](#configuration-layer)
5. [Governance Layer](#governance-layer)
6. [Adapters Layer](#adapters-layer)
7. [Persistence Layer](#persistence-layer)
8. [REST API Layer](#rest-api-layer)
9. [CLI Layer](#cli-layer)
10. [Execution Flow](#execution-flow)
11. [Thread-Safety Model](#thread-safety-model)
12. [Design Patterns](#design-patterns)
13. [Directory Structure](#directory-structure)
14. [Workspace Layout](#workspace-layout)
15. [Testing](#testing)
16. [Dependencies](#dependencies)

---

## System Overview

```
User
 │
 ├── CLI (init, serve, submit, validate, agent/profile CRUD)
 │
 └── REST API (/api/v1/*)
      │
      ▼
┌──────────────────────────────────────────────────────────────┐
│                    OrchestrationEngine                       │
│                                                              │
│  WorkQueue ──► PipelineManager ──► PhaseExecutor             │
│                     │                    │                    │
│                     │              AgentPool ◄──► AgentExec   │
│                     │                    │            │       │
│               Governor ◄────────────────┘      LLMAdapter    │
│                     │                          ┌──┴──┐       │
│               ReviewQueue                  Providers...      │
│                     │                                        │
│          AuditLogger  MetricsCollector                        │
└──────────────────────────────────────────────────────────────┘
```

**Key characteristics:**

- **Domain-agnostic** — reads YAML profiles to know what to do
- **Non-blocking governance** — policy decisions are immediate; reviews are queued
- **Multi-provider LLM** — each agent can use a different provider/model
- **Hot-reload** — configuration changes take effect without restart
- **Fully observable** — event bus, audit trail, metrics, REST API
- **Thread-safe** — asyncio for concurrency, `threading.Lock` for shared state

---

## Layer Architecture

```
┌───────────────────────────────────────────────────────────┐
│  CLI (commands.py)  &  REST API (app.py, routes.py)       │  Interfaces
├───────────────────────────────────────────────────────────┤
│  Configuration (models, loader, validator, agent_manager) │  Config Mgmt
├───────────────────────────────────────────────────────────┤
│  Core Engine (engine, pipeline, pool, executor, events)   │  Orchestration
├───────────────────────────────────────────────────────────┤
│  Governance (governor, audit_logger, review_queue)        │  Policy & Audit
├───────────────────────────────────────────────────────────┤
│  Adapters (llm_adapter, metrics, webhook, providers/)     │  Integrations
├───────────────────────────────────────────────────────────┤
│  Persistence (state_store, settings_store, config_history)│  Storage
├───────────────────────────────────────────────────────────┤
│  Exceptions (exception hierarchy)                         │  Error Model
└───────────────────────────────────────────────────────────┘
```

Each layer only depends on layers below it. The engine never imports from the API or CLI.

---

## Core Layer

### OrchestrationEngine (`core/engine.py`)

Central coordinator. Owns the full lifecycle: start → process → stop.

| State | Description |
|-------|-------------|
| `IDLE` | Created but not started |
| `STARTING` | Loading config, initializing components |
| `RUNNING` | Processing work items |
| `PAUSED` | Queue polling paused |
| `STOPPING` | Cancelling tasks, draining |
| `STOPPED` | Fully shut down |

**Initialization sequence** (`_initialize_components`):

1. `WorkQueue` — priority-ordered async queue
2. `PipelineManager` — phase graph from workflow config
3. `AgentPool` — registers enabled agent definitions
4. `LLMAdapter` — created from settings, providers auto-registered
5. `AgentExecutor` — receives `adapter.call` as callback
6. `PhaseExecutor` — receives pool, executor, event bus
7. `AgentManager` — agent CRUD operations
8. `Governor` — governance policy engine
9. `ReviewQueue` — human review queue
10. `AuditLogger` — hash-chained JSONL audit trail
11. `MetricsCollector` — execution metrics

**State ownership:** The engine owns lifecycle transitions. WorkQueue owns ordering. PipelineManager owns phase positions. AgentPool owns agent instances. Each component owns its own lock.

---

### WorkQueue (`core/work_queue.py`)

Priority-ordered async work queue backed by `asyncio.PriorityQueue`.

- Items ordered by priority (0 = highest); ties broken by submission time (FIFO)
- Duplicate IDs rejected
- `pop(timeout)` returns `None` on timeout rather than blocking forever

**WorkItem fields:** `id`, `type_id`, `title`, `data`, `priority` (0–10), `status`, `current_phase`, `submitted_at`, `metadata`, `results`, `error`, `attempt_count`.

**Statuses:** `PENDING → QUEUED → IN_PROGRESS → COMPLETED | FAILED | CANCELLED`

---

### PipelineManager (`core/pipeline_manager.py`)

Tracks work items through a directed phase graph.

- Each work item gets a `PipelineEntry` that records current phase, lock state, attempt counts, and phase history
- **Phase transitions:** `on_success` / `on_failure` edges, terminal phases, skip support
- **Locking:** items must be locked before execution and unlocked after
- Phase results: `SUCCESS`, `FAILURE`, `SKIPPED`

---

### AgentPool (`core/agent_pool.py`)

Manages agent instances with per-definition concurrency limits.

- Instances created on demand up to `concurrency` limit
- `acquire(definition_id, work_id)` returns an idle instance or creates a new one
- `release(instance_id, success)` returns instance to idle state (or error state on failure)
- `scale(definition_id, concurrency)` dynamically adjusts limits
- `shutdown()` transitions all instances to `SHUTDOWN`

**Agent states:** `IDLE → RUNNING → IDLE | ERROR | SHUTDOWN`

---

### AgentExecutor (`core/agent_executor.py`)

Executes a single agent against a work item. Stateless — all context passed via parameters.

**Prompt construction:**
- **System prompt** from `AgentDefinition.system_prompt`
- **User prompt** built from work item title, type, phase, data, and phase context

**Retry logic:**
- Configured per-agent via `RetryPolicy` (max_retries, delay_seconds, backoff_multiplier)
- Exponential backoff: `delay × backoff^(attempt - 1)`

**LLM call:** Delegated to injected `llm_call_fn` callback (dependency injection).

Returns `ExecutionResult` with: `agent_id`, `instance_id`, `work_id`, `phase_id`, `success`, `output`, `error`, `duration_seconds`, `attempt`.

---

### PhaseExecutor (`core/phase_executor.py`)

Executes all agents assigned to a workflow phase.

- **Parallel mode** (`phase.parallel = true`): agents run concurrently via `asyncio.gather()`
- **Sequential mode** (`phase.parallel = false`): agents run one-at-a-time; first failure stops the phase
- Agent acquisition retries up to 20 times with 0.5s delay if pool is at capacity
- Emits `AGENT_STARTED` / `AGENT_COMPLETED` / `AGENT_ERROR` events

---

### EventBus (`core/event_bus.py`)

Async pub/sub event bus. All events are immutable frozen dataclasses.

**Event types:**

| Category | Events |
|----------|--------|
| Work | `submitted`, `started`, `phase_entered`, `phase_exited`, `completed`, `failed` |
| Agent | `started`, `completed`, `error`, `scaled`, `created`, `updated`, `deleted` |
| Governance | `decision`, `escalation`, `review_completed` |
| Config | `reloaded` |
| System | `started`, `stopped`, `error` |

- `subscribe(event_type, handler)` / `subscribe_all(handler)` for wildcard
- `emit(event)` calls all matching handlers concurrently; handler errors are logged but don't block other handlers

---

## Configuration Layer

### Models (`configuration/models.py`)

All Pydantic v2 models with `frozen = True` (immutable after creation).

```
SettingsConfig          Workspace-level: api_keys, llm_endpoints, log_level, persistence_backend
├── api_keys            dict[str, str]  — provider → key
└── llm_endpoints       dict[str, str]  — provider → URL

ProfileConfig           Bundle of all domain configuration
├── agents              list[AgentDefinition]
│   ├── llm             LLMConfig (provider, model, temperature, max_tokens, endpoint)
│   └── retry_policy    RetryPolicy (max_retries, delay_seconds, backoff_multiplier)
├── workflow            WorkflowConfig
│   ├── phases          list[WorkflowPhaseConfig]  (agents, order, parallel, on_success/failure, conditions, quality_gates, skip, terminal)
│   └── statuses        list[StatusConfig]  (is_initial, is_terminal, transitions_to)
├── governance          GovernanceConfig
│   ├── delegated_authority  (auto_approve/review/abort thresholds)
│   └── policies        list[PolicyConfig]  (conditions, action, priority)
└── work_item_types     list[WorkItemTypeConfig]
```

### Loader (`configuration/loader.py`)

`ConfigurationManager` manages loading, hot-reload, and profile switching.

- `load()` → reads `settings.yaml` + active profile directory
- `reload()` → re-reads from disk (hot-reload)
- `switch_profile(name)` → changes active profile, reloads
- `get_profile_component(component)` / `export_profile_component()` → per-component access

### Validator (`configuration/validator.py`)

Pure functions that return `ValidationResult` (errors + warnings):

1. `validate_agent_phase_references` — agents reference existing phases and vice versa
2. `validate_phase_graph` — reachability, terminal phases, valid transitions
3. `validate_llm_providers` — agents have API keys (except Ollama)
4. `validate_status_transitions` — transition targets exist, initial status present
5. `validate_governance` — threshold ordering, policy actions
6. `validate_profile` — runs all above

### AgentManager (`configuration/agent_manager.py`)

CRUD for agent definitions with persistence and version history.

- `create_agent` / `update_agent` / `delete_agent` — validates, persists to YAML, records history
- `import_agents(file_path)` / `export_agents(output_path, fmt)` — bulk operations
- Engine coordinates AgentManager (config) + AgentPool (runtime) + EventBus (notification)

---

## Governance Layer

### Governor (`governance/governor.py`)

Non-blocking policy evaluation at phase transitions. **Never blocks.**

**Decision flow:**
1. Check policies in priority order (highest priority first)
2. First matching policy returns its action as a `GovernanceDecision`
3. If no policy matches, fall back to delegated authority thresholds:
   - `confidence >= auto_approve` → `ALLOW`
   - `confidence >= review` → `ALLOW_WITH_WARNING`
   - `confidence >= abort` → `QUEUE_FOR_REVIEW`
   - `confidence < abort` → `ABORT`

**Condition evaluation:** Safe expression parser supporting `>=`, `<=`, `!=`, `==`, `>`, `<`, `in`. Only context keys are accessible — no arbitrary code execution.

**Resolutions:** `ALLOW`, `ALLOW_WITH_WARNING`, `QUEUE_FOR_REVIEW`, `ABORT`

### AuditLogger (`governance/audit_logger.py`)

Append-only, hash-chained JSONL audit trail.

- Each `AuditRecord` includes a SHA-256 hash linking it to the previous record
- Record types: `DECISION`, `STATE_CHANGE`, `ESCALATION`, `ERROR`, `CONFIG_CHANGE`, `SYSTEM_EVENT`
- `verify_chain()` detects tampering
- `query(work_id, record_type, limit)` for filtered retrieval

### ReviewQueue (`governance/review_queue.py`)

Queue for items requiring human review. Processing continues while items await review — reviews are informational/audit.

---

## Adapters Layer

### LLMAdapter (`adapters/llm_adapter.py`)

Multi-provider router. Each agent's `LLMConfig` specifies a provider name; the adapter dispatches to the matching registered provider.

- `register_provider(name, provider)` — providers implement `LLMProviderProtocol`
- `call(system_prompt, user_prompt, llm_config)` — builds messages list, dispatches to provider
- Falls back to a mock response if no provider is registered for the requested name

```python
@runtime_checkable
class LLMProviderProtocol(Protocol):
    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str,
        **kwargs: Any,
    ) -> dict[str, Any]: ...
```

### LLM Providers (`adapters/providers/`)

| Provider | SDK | Notes |
|----------|-----|-------|
| `OpenAIProvider` | `openai.AsyncOpenAI` | Standard chat completions |
| `AnthropicProvider` | `anthropic.AsyncAnthropic` | Extracts system message to dedicated `system=` param |
| `GoogleProvider` | `google.generativeai` | Sync SDK wrapped in `asyncio.to_thread()` |
| `GrokProvider` | `openai.AsyncOpenAI` | OpenAI SDK with `base_url="https://api.x.ai/v1"` |
| `OllamaProvider` | `httpx.AsyncClient` | POST to `/api/chat`, no API key |

All imports are conditional (`try/except ImportError`) — missing SDKs skip gracefully. Install with `pip install agent-orchestrator[llm]`.

**Engine auto-registration** (`_register_providers`):
- For each provider with an API key in `settings.api_keys` → import, instantiate, register
- Ollama always registered (uses endpoint from `settings.llm_endpoints`, defaults to `localhost:11434`)
- Missing SDK → log warning, skip

### MetricsCollector (`adapters/metrics_adapter.py`)

Appends `MetricEntry` records to JSONL. Supports `record(name, value, tags)` and `increment(name)` counters.

### WebhookAdapter (`adapters/webhook_adapter.py`)

Outbound webhook delivery for event notifications.

---

## Persistence Layer

| Store | Format | Purpose |
|-------|--------|---------|
| `SettingsStore` | YAML | Workspace settings with atomic writes and env-var fallback |
| `StateStore` | JSON | Runtime state (crash recovery) |
| `ConfigHistory` | JSONL | Timestamped config versioning with restore |
| `AuditLogger` | JSONL | Hash-chained audit records |
| `MetricsCollector` | JSONL | Execution metrics |

**SettingsStore API key security:**
- Env vars override YAML: `AGENT_ORCH_{PROVIDER}_API_KEY` (e.g., `AGENT_ORCH_OPENAI_API_KEY`)
- Keys sourced from env vars are never persisted to disk

**Atomic writes:** All stores write to a temp file then rename. SettingsStore creates a backup before overwriting and includes retry logic for Windows file locking.

---

## REST API Layer

FastAPI application created via `create_app()` factory. All routes under `/api/v1`.

| Group | Endpoints | Description |
|-------|-----------|-------------|
| Health | `GET /health`, `/health/ready`, `/health/live` | Liveness and readiness probes |
| Agents | `GET/POST /agents`, `GET/PUT/DELETE /agents/{id}`, `POST /agents/{id}/scale`, `GET /agents/export`, `POST /agents/import` | Agent CRUD and scaling |
| Workflow | `GET /workflow/phases`, `GET /workflow/phases/{id}` | Workflow introspection |
| Work Items | `GET/POST /workitems`, `GET /workitems/{id}` | Work item submission and status |
| Governance | `GET/POST /governance/policies`, `GET /governance/reviews` | Policy management and review queue |
| Execution | `GET /execution/status`, `POST /execution/start\|stop\|pause\|resume` | Engine lifecycle control |
| Metrics | `GET /metrics`, `GET /metrics/agents/{id}` | Aggregated and per-agent metrics |
| Audit | `GET /audit` | Query audit trail (filters: `work_id`, `record_type`, `limit`) |
| Config | `GET /config/profiles`, `GET /config/profile/export`, `POST /config/validate`, `GET /config/history` | Configuration management |

---

## CLI Layer

Entry point: `agent-orchestrator` (console script) or `python -m agent_orchestrator`.

```
agent-orchestrator
├── init [workspace]              Initialize workspace (--template content-moderation|software-dev)
├── validate [workspace]          Validate configuration
├── start [workspace]             Start engine headless
├── submit [workspace]            Submit work item (--title, --type-id, --file, --priority)
├── serve [workspace]             Start REST API server (--host, --port)
├── export [workspace]            Export config as zip
├── import [bundle]               Import config from zip
├── profile
│   ├── list                      List profiles
│   ├── switch [name]             Switch active profile
│   ├── create [name]             Create new profile
│   └── export                    Export profile component (--component, --format)
└── agent
    ├── list                      List agents
    ├── get [agent_id]            Get agent details
    ├── create                    Create agent (--id, --name, --provider, --model, ...)
    ├── update [agent_id]         Update agent
    ├── delete [agent_id]         Delete agent
    ├── import [file]             Import agents from YAML/JSON
    └── export                    Export agents (--format yaml|json)
```

Built-in profile templates: `content-moderation`, `software-dev`.

---

## Execution Flow

```
1. SUBMIT
   CLI/API ──► WorkQueue.push(item)
               emit(WORK_SUBMITTED)

2. DEQUEUE
   Processing loop ──► WorkQueue.pop()
                        emit(WORK_STARTED)

3. PIPELINE ENTRY
   PipelineManager.enter_pipeline(item) → initial phase

4. PHASE LOOP (until terminal or failure)
   │
   ├── GOVERNANCE CHECK
   │   Governor.evaluate(context)
   │   ├── ABORT → fail item, emit(WORK_FAILED), stop
   │   ├── QUEUE_FOR_REVIEW → enqueue review, continue
   │   └── ALLOW / ALLOW_WITH_WARNING → continue
   │
   ├── LOCK
   │   PipelineManager.lock_for_execution(work_id)
   │
   ├── EXECUTE PHASE
   │   PhaseExecutor.execute_phase(phase, item)
   │   │
   │   └── For each agent in phase (parallel or sequential):
   │       ├── AgentPool.acquire(agent_id)
   │       ├── AgentExecutor.execute(instance, item, phase)
   │       │   ├── Build system + user prompts
   │       │   ├── LLMAdapter.call() → Provider.complete()
   │       │   └── Retry on failure (exponential backoff)
   │       ├── AgentPool.release(instance_id)
   │       └── emit(AGENT_STARTED / AGENT_COMPLETED / AGENT_ERROR)
   │
   ├── ADVANCE
   │   PipelineManager.complete_phase(work_id, result)
   │   → follow on_success or on_failure edge to next phase
   │
   └── RECORD
       MetricsCollector.record(phase.duration)
       AuditLogger.append(state_change)

5. COMPLETE
   item.status = COMPLETED | FAILED
   emit(WORK_COMPLETED | WORK_FAILED)
   AuditLogger.append(completion)
```

---

## Thread-Safety Model

Every stateful component protects its own data with `threading.Lock()`. Async coordination uses `asyncio`.

| Component | Lock Scope |
|-----------|-----------|
| `OrchestrationEngine` | State transitions (`_state`) |
| `WorkQueue` | Item registry; `asyncio.PriorityQueue` for async pop |
| `PipelineManager` | Phase entries, locks |
| `AgentPool` | Instance registry, definitions |
| `Governor` | Policy list |
| `AuditLogger` | JSONL file writes, sequence counter |
| `ReviewQueue` | Review items dict |
| `MetricsCollector` | Counters, file writes |
| `SettingsStore` | YAML reads/writes |
| `StateStore` | JSON reads/writes |
| `ConfigurationManager` | Settings/profile cache |
| `AgentManager` | Agent dict, persistence |
| `EventBus` | Subscriber registry |

**Key invariant:** Locks are never held across `await` boundaries.

---

## Design Patterns

| Pattern | Where | Purpose |
|---------|-------|---------|
| Dependency Injection | `AgentExecutor(llm_call_fn=...)`, `OrchestrationEngine(config_manager, event_bus)` | Testability, loose coupling |
| State Machine | `EngineState`, `WorkItemStatus`, `AgentState` | Explicit lifecycle management |
| Observer / Pub-Sub | `EventBus` | Decouple producers from consumers |
| Strategy | `PhaseExecutor` parallel vs sequential | Configurable execution mode |
| Adapter | `LLMAdapter` + `LLMProviderProtocol` | Uniform interface over multiple LLM SDKs |
| Chain of Responsibility | `Governor` policy evaluation | Priority-ordered policy matching |
| Factory | `create_app()`, `AgentPool._create_instance()` | Encapsulate construction |
| Protocol (structural typing) | `LLMProviderProtocol` | No inheritance required for providers |
| Frozen DTOs | All Pydantic config models | Safe sharing across threads |
| Append-Only Log | `AuditLogger` with hash chaining | Tamper-evident compliance trail |

---

## Directory Structure

```
agent-orchestrator/
├── pyproject.toml
├── ARCHITECTURE.md
│
├── src/agent_orchestrator/
│   ├── __init__.py
│   ├── exceptions.py                    Exception hierarchy
│   │
│   ├── cli/
│   │   └── commands.py                  Click CLI (init, serve, submit, agent/profile CRUD)
│   │
│   ├── api/
│   │   ├── app.py                       FastAPI factory (create_app)
│   │   └── routes.py                    All REST route definitions
│   │
│   ├── configuration/
│   │   ├── models.py                    Pydantic v2 config models (frozen)
│   │   ├── loader.py                    ConfigurationManager, YAML/JSON I/O
│   │   ├── validator.py                 Profile validation rules
│   │   └── agent_manager.py            Agent CRUD with persistence
│   │
│   ├── core/
│   │   ├── engine.py                    OrchestrationEngine (central coordinator)
│   │   ├── work_queue.py                Priority async work queue
│   │   ├── pipeline_manager.py          Phase graph traversal
│   │   ├── agent_pool.py                Agent instance pool with concurrency
│   │   ├── agent_executor.py            Single-agent execution + retries
│   │   ├── phase_executor.py            Multi-agent phase execution
│   │   └── event_bus.py                 Async pub/sub event bus
│   │
│   ├── governance/
│   │   ├── governor.py                  Policy engine (non-blocking)
│   │   ├── audit_logger.py              Hash-chained JSONL audit trail
│   │   └── review_queue.py             Human review queue
│   │
│   ├── adapters/
│   │   ├── __init__.py                  Re-exports (LLMAdapter, providers, etc.)
│   │   ├── llm_adapter.py              Multi-provider LLM router
│   │   ├── metrics_adapter.py          Execution metrics collector
│   │   ├── webhook_adapter.py          Outbound webhook delivery
│   │   └── providers/
│   │       ├── __init__.py             Lazy conditional imports
│   │       ├── openai_provider.py      OpenAI (AsyncOpenAI)
│   │       ├── anthropic_provider.py   Anthropic (AsyncAnthropic)
│   │       ├── google_provider.py      Google Gemini (sync → asyncio.to_thread)
│   │       ├── grok_provider.py        xAI Grok (OpenAI SDK, custom base_url)
│   │       └── ollama_provider.py      Ollama (httpx async HTTP)
│   │
│   ├── persistence/
│   │   ├── settings_store.py           YAML settings (atomic writes, env fallback)
│   │   ├── state_store.py              JSON runtime state
│   │   └── config_history.py           Config versioning with restore
│   │
│   └── profiles/                       Built-in profile templates
│       ├── content-moderation/
│       └── software-dev/
│
└── tests/
    ├── conftest.py                      Shared fixtures
    ├── unit/
    │   ├── test_core.py                 Engine, queue, pool, pipeline, executor, events
    │   ├── test_configuration.py        Models, loader, validator
    │   ├── test_governance.py           Governor, audit, review queue
    │   ├── test_persistence.py          State store, settings store, config history
    │   ├── test_api.py                  REST API endpoints
    │   ├── test_agent_manager.py        Agent CRUD operations
    │   └── test_providers.py            LLM provider mocked tests
    └── integration/
```

---

## Workspace Layout

Created by `agent-orchestrator init`:

```
workspace/
├── settings.yaml                       SettingsConfig
│   ├── active_profile: "my-profile"
│   ├── api_keys: {openai: "", anthropic: "", ...}
│   ├── llm_endpoints: {ollama: "http://localhost:11434"}
│   └── log_level: "INFO"
│
├── profiles/
│   └── my-profile/
│       ├── agents.yaml                 list[AgentDefinition]
│       ├── workflow.yaml               WorkflowConfig (phases + statuses)
│       ├── governance.yaml             GovernanceConfig (thresholds + policies)
│       └── workitems.yaml              list[WorkItemTypeConfig]
│
└── .state/                             Runtime state (created on start)
    ├── audit/                          Hash-chained JSONL audit logs
    └── metrics.jsonl                   Execution metrics
```

**Environment variables** override YAML API keys:
- `AGENT_ORCH_OPENAI_API_KEY`
- `AGENT_ORCH_ANTHROPIC_API_KEY`
- `AGENT_ORCH_GOOGLE_API_KEY`
- `AGENT_ORCH_GROK_API_KEY`

Keys sourced from environment are never persisted to disk.

---

## Testing

254 tests, all passing. All tests use mocked dependencies — no real API calls.

```
pytest tests/ -v            # run all tests
pytest tests/ --cov         # with coverage
```

| Test File | Tests | Covers |
|-----------|-------|--------|
| `test_core.py` | 33 | Engine lifecycle, queue, pool, pipeline, executor, events |
| `test_configuration.py` | 36 | Config models, loader, validator, built-in profiles |
| `test_governance.py` | 15 | Governor decisions, audit hash chain, review queue |
| `test_persistence.py` | 13 | State store, settings store, config history |
| `test_api.py` | 94 | All REST endpoints (health, CRUD, execution, governance, metrics, audit) |
| `test_agent_manager.py` | 42 | Agent CRUD, import/export, profile component export |
| `test_providers.py` | 21 | All 5 LLM providers, registration, adapter routing |

---

## Dependencies

**Core** (always required):
```
pydantic>=2.0       Config models and validation
pyyaml>=6.0         YAML configuration files
fastapi>=0.100      REST API framework
uvicorn>=0.20       ASGI server
click>=8.0          CLI framework
```

**LLM providers** (optional — `pip install agent-orchestrator[llm]`):
```
openai>=1.0              OpenAI + Grok (xAI)
anthropic>=0.30          Anthropic Claude
google-generativeai>=0.5 Google Gemini
httpx>=0.27              Ollama HTTP client
```

**Dev** (`pip install agent-orchestrator[dev]`):
```
pytest>=7.0
pytest-asyncio>=0.21
pytest-cov>=4.0
```

---

## Exception Hierarchy

```
OrchestratorError             Base exception
├── ConfigurationError        Invalid configuration
├── ProfileError              Profile not found / invalid
├── ValidationError           Validation failures
├── WorkflowError             Phase graph / pipeline errors
├── AgentError                Agent not found / execution errors
├── GovernanceError           Policy evaluation errors
├── PersistenceError          File I/O / state errors
└── WorkItemError             Work item submission errors
```
