# Architecture — Agent Orchestrator v0.2.0

Generic, domain-agnostic platform for orchestrating multi-agent workflows with built-in governance, auditing, and observability. All domain knowledge lives in YAML configuration; the engine itself has zero hardcoded domain logic.

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Layer Architecture](#layer-architecture)
3. [Core Layer](#core-layer)
4. [Configuration Layer](#configuration-layer)
5. [Governance Layer](#governance-layer)
6. [Knowledge Layer](#knowledge-layer)
7. [Evaluation & Simulation Layer](#evaluation--simulation-layer)
8. [Capability Catalog Layer](#capability-catalog-layer)
9. [Adapters Layer](#adapters-layer)
10. [Persistence Layer](#persistence-layer)
11. [REST API Layer](#rest-api-layer)
12. [CLI Layer](#cli-layer)
13. [Execution Flow](#execution-flow)
14. [Thread-Safety Model](#thread-safety-model)
15. [Design Patterns](#design-patterns)
16. [Directory Structure](#directory-structure)
17. [Workspace Layout](#workspace-layout)
18. [Testing](#testing)
19. [Dependencies](#dependencies)
20. [MCP Integration](#mcp-integration)
21. [Studio — Visual Design Tool](#studio--visual-design-tool)
22. [AI Workflow Recommender](#ai-workflow-recommender)

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
│           ReviewQueue  DecisionLedger      Providers...      │
│                     │                                        │
│      AuditLogger  MetricsCollector  SLAMonitor               │
│                                                              │
│  KnowledgeStore ◄──► ContextMemory ◄──► MemoryExtractor      │
│  EmbeddingService          OutputParser ──► QualityGate      │
│                                                              │
│  GapDetector ──► AgentSynthesizer     TeamRegistry           │
│  SkillMap          SimulationSandbox   ABTestRunner           │
│  BenchmarkRunner   LLMJudgeEvaluator                         │
│                                                              │
│  MCPClientManager ──► MCPConnectorBridge ──► ConnectorRegistry│
│  MCPServer (ASGI mount at /mcp)                              │
└──────────────────────────────────────────────────────────────┘
```

**Key characteristics:**

- **Domain-agnostic** — reads YAML profiles to know what to do
- **Non-blocking governance** — policy decisions are immediate; reviews are queued
- **Multi-provider LLM** — each agent can use a different provider/model
- **Hot-reload** — configuration changes take effect without restart
- **Fully observable** — event bus, audit trail, metrics, decision ledger, REST API
- **Thread-safe** — asyncio for concurrency, `threading.Lock` for shared state
- **Deployment profiles** — lite (zero deps), standard (PostgreSQL), enterprise (multi-tenant)
- **Run identity** — every work item gets a UUID `run_id` propagated through events, audit, and metrics
- **Shared memory** — content-addressable knowledge store with semantic search and auto-extraction
- **Self-improving** — gap detection and LLM-powered agent synthesis to fill capability gaps
- **Evaluation-first** — LLM-as-judge scoring, A/B testing, benchmark suites, and simulation sandbox
- **SLA enforcement** — background deadline monitoring with priority boost on breach

---

## Layer Architecture

```
┌───────────────────────────────────────────────────────────┐
│  CLI (commands.py)  &  REST API (app.py, routes.py, ...)  │  Interfaces
├───────────────────────────────────────────────────────────┤
│  Configuration (models, loader, validator, agent_manager) │  Config Mgmt
├───────────────────────────────────────────────────────────┤
│  Core Engine (engine, pipeline, pool, executor, events,   │
│    output_parser, quality_gate, sla_monitor,              │
│    gap_detector, agent_synthesizer)                       │  Orchestration
├───────────────────────────────────────────────────────────┤
│  Governance (governor, audit_logger, review_queue,        │
│    decision_ledger)                                       │  Policy & Audit
├───────────────────────────────────────────────────────────┤
│  Knowledge (store, embedding, context_memory, extractor)  │  Shared Memory
├───────────────────────────────────────────────────────────┤
│  Simulation (sandbox, evaluator, ab_test, benchmark,      │
│    rubric_store, dataset)                                 │  Evaluation
├───────────────────────────────────────────────────────────┤
│  Catalog (team_registry, skill_map, auto_register)        │  Capability Reg
├───────────────────────────────────────────────────────────┤
│  Adapters (llm_adapter, metrics, webhook, providers/)     │  Integrations
├───────────────────────────────────────────────────────────┤
│  Connectors (registry, service, permissions, audit)       │  Ext. Capabilities
├───────────────────────────────────────────────────────────┤
│  Persistence (state_store, settings_store, config_history,│
│    work_item_store, artifact_store, lineage)              │  Storage
├───────────────────────────────────────────────────────────┤
│  Exceptions (exception hierarchy)                         │  Error Model
└───────────────────────────────────────────────────────────┘
```

Each layer only depends on layers below it. The engine never imports from the API or CLI.

---

## Core Layer

### Deployment Modes (`configuration/models.py`)

Three explicit deployment profiles control which platform features are active:

| Mode | Process Model | Storage | External Deps |
|------|--------------|---------|---------------|
| `lite` | Single process | File / SQLite | None |
| `standard` | API + workers | PostgreSQL | PostgreSQL |
| `enterprise` | API + workers + auth | PostgreSQL | PostgreSQL + auth |

Set via `deployment_mode` in `settings.yaml`. Default: `lite`.

### ExecutionContext (`configuration/models.py`)

Immutable (frozen) Pydantic model propagated through every operation in a run:

| Field | Default | Purpose |
|-------|---------|---------|
| `app_id` | `"default"` | Application namespace for multi-app hosting |
| `run_id` | `""` (auto-assigned) | Unique UUID per work item submission |
| `tenant_id` | `"default"` | Tenant isolation (enterprise) |
| `environment` | `"development"` | Runtime environment tag |
| `deployment_mode` | `DeploymentMode.LITE` | Active deployment profile |
| `profile_name` | `""` | Active configuration profile |
| `extra` | `{}` | Extensible key-value metadata |

**Context lifecycle:**
1. `create_root_context(settings, profile_name)` — built once in `engine.start()`
2. `create_run_context(parent, run_id?)` — forked per `submit_work()` call with unique UUID
3. `context_tags(ctx)` — flattened to `dict[str, str]` for metrics and structured logging

Context is propagated to: `WorkItem.run_id/app_id`, `Event.run_id/app_id`, `AuditRecord.run_id/app_id`, `MetricsCollector` tags.

---

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

**WorkItem fields:** `id`, `type_id`, `title`, `data`, `priority` (0–10), `status`, `current_phase`, `submitted_at`, `metadata`, `results`, `error`, `attempt_count`, `run_id`, `app_id`.

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

Returns `ExecutionResult` with: `agent_id`, `instance_id`, `work_id`, `phase_id`, `success`, `output`, `error`, `duration_seconds`, `attempt`, `run_id`.

---

### PhaseExecutor (`core/phase_executor.py`)

Executes all agents assigned to a workflow phase.

- **Parallel mode** (`phase.parallel = true`): agents run concurrently via `asyncio.gather()`
- **Sequential mode** (`phase.parallel = false`): agents run one-at-a-time; first failure stops the phase
- Agent acquisition retries up to 20 times with 0.5s delay if pool is at capacity
- Emits `AGENT_STARTED` / `AGENT_COMPLETED` / `AGENT_ERROR` events

---

### OutputParser (`core/output_parser.py`)

Extracts confidence scores and structured fields from agent LLM output dicts.

- `extract_confidence(output)` — scans keys `confidence`, `score`, `quality_score` in priority order; clamps to [0.0, 1.0]; defaults to 0.5
- `extract_structured_fields(output, required_fields)` — returns `(extracted_dict, missing_list)` tuple
- `extract_scores(output)` — extracts all numeric score dimensions (known keys + `*_score`/`*_confidence` suffixes), clamped to [0.0, 1.0]
- `aggregate_confidence(scores)` — mean of non-default scores
- `aggregate_scores(score_sets)` — per-dimension mean across multiple agents

---

### QualityGate (`core/quality_gate.py`)

Evaluates quality gates against phase execution results.

- `evaluate_quality_gate(gate, context)` — evaluates all conditions in a `QualityGateConfig` using the safe expression parser from Governor; returns `QualityGateResult` with `passed`, `failures`, and `on_failure` action
- `evaluate_phase_quality_gates(gates, context)` — evaluates all gates for a phase, returning one result per gate
- `build_gate_context(agent_results, aggregate_confidence)` — builds evaluation context from execution results with keys: `confidence`, `agent_count`, `all_succeeded`, `failure_count`, plus merged agent outputs (prefixed by agent_id for multi-agent phases)

---

### SLAMonitor (`core/sla_monitor.py`)

Background async task that enforces work item deadlines.

- Periodic scan loop (configurable interval, default 30s)
- **SLA_WARNING** event at 80% of deadline elapsed
- **SLA_BREACH** event when deadline passes
- **Priority boost** on breach: reduces priority by 2 (lower number = higher priority)
- Tracks warned/breached IDs to avoid duplicate events
- `start()` / `stop()` for lifecycle management

---

### GapDetector (`core/gap_detector.py`)

Detects capability gaps between what agents can do and what workflows require.

**GapSignalCollector** — subscribes to EventBus events and aggregates runtime signals into time-windowed counters:

| Signal | Source Event |
|--------|-------------|
| Failures | `AGENT_ERROR`, `WORK_PHASE_EXITED` (on failure) |
| Low confidence | `AGENT_COMPLETED` (below threshold) |
| Governance escalations | `GOVERNANCE_DECISION` (escalate/abort) |
| Human overrides | `GOVERNANCE_REVIEW_COMPLETED` (rejected/overridden) |

**GapAnalyzer** — examines signal windows against configurable thresholds:

| Check | Warning Threshold | Critical Threshold |
|-------|-------------------|-------------------|
| Failure rate | 30% | 60% |
| Low confidence rate | 40% | — |
| Retry rate | 50% | — |
| Critic rejection rate | 30% | — |
| Human override rate | 20% | — |
| Governance escalation rate | 30% | — |

Produces `CapabilityGap` records with severity, evidence, and suggested capabilities.

**Gap sources:** `STATIC_SKILL_MISMATCH`, `STATIC_UNCOVERED_PHASE`, `STATIC_OUTPUT_MISMATCH`, `RUNTIME_REPEATED_FAILURE`, `RUNTIME_LOW_CONFIDENCE`, `RUNTIME_CRITIC_REJECTION`, `RUNTIME_GATE_FAILURE`, `RUNTIME_EXCESSIVE_RETRY`, `RUNTIME_HUMAN_OVERRIDE`, `RUNTIME_GOVERNANCE_ESCALATION`.

---

### AgentSynthesizer (`core/agent_synthesizer.py`)

LLM-powered agent design to fill detected capability gaps.

- `propose(gap, profile)` — uses an LLM to design a new agent definition that addresses the gap; falls back to template-based synthesis on failure
- `validate_and_test(proposal_id, profile)` — runs 3 pre-deployment checks: schema validation, phase compatibility, dry-run LLM probe
- `approve_proposal()` / `reject_proposal(feedback)` / `mark_deployed()` — lifecycle management

**Proposal lifecycle:** `pending → approved → deployed` (or `rejected`)

The synthesizer builds rich prompts including phase description, quality gate conditions, existing agent summaries, gap evidence, and suggested capabilities. Generated agents start with `enabled: False` and require explicit approval.

---

### EventBus (`core/event_bus.py`)

Async pub/sub event bus. All events are immutable frozen dataclasses with `app_id` and `run_id` fields for context propagation.

**Event types:**

| Category | Events |
|----------|--------|
| Work | `submitted`, `started`, `phase_entered`, `phase_exited`, `completed`, `failed` |
| Agent | `started`, `completed`, `error`, `scaled`, `created`, `updated`, `deleted` |
| Governance | `decision`, `escalation`, `review_completed` |
| SLA | `sla_warning`, `sla_breach` |
| Config | `reloaded` |
| System | `started`, `stopped`, `error` |

- `subscribe(event_type, handler)` / `subscribe_all(handler)` for wildcard
- `emit(event)` calls all matching handlers concurrently; handler errors are logged but don't block other handlers

---

## Configuration Layer

### Models (`configuration/models.py`)

All Pydantic v2 models with `frozen = True` (immutable after creation).

```
DeploymentMode          Enum: lite, standard, enterprise
PersistenceBackend      Enum: file, sqlite, postgresql
ExecutionContext        Frozen context: app_id, run_id, tenant_id, environment, deployment_mode, profile_name, extra

SettingsConfig          Workspace-level: api_keys, llm_endpoints, log_level, persistence_backend, deployment_mode
├── api_keys            dict[str, str]  — provider → key
└── llm_endpoints       dict[str, str]  — provider → URL

ProfileConfig           Bundle of all domain configuration
├── agents              list[AgentDefinition]
│   ├── llm             LLMConfig (provider, model, temperature, max_tokens, endpoint)
│   └── retry_policy    RetryPolicy (max_retries, delay_seconds, backoff_multiplier)
├── workflow            WorkflowConfig
│   ├── phases          list[WorkflowPhaseConfig]  (agents, order, parallel, on_success/failure, conditions, quality_gates, skip, terminal, timeout_seconds)
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
- Record types: `DECISION`, `STATE_CHANGE`, `ESCALATION`, `ERROR`, `CONFIG_CHANGE`, `SYSTEM_EVENT`, `MCP_INVOCATION`
- All records carry `app_id` and `run_id` for scoped querying
- `verify_chain()` detects tampering
- `query(work_id, record_type, limit, app_id, run_id)` for filtered retrieval
- **Log rotation** — size-based rotation (configurable `_max_file_bytes`); when exceeded, the current file is renamed with a UTC timestamp suffix and a fresh file starts
- **Safe policy evaluation** — condition expressions use `ast.literal_eval` instead of `eval()` for safe constant parsing

### ReviewQueue (`governance/review_queue.py`)

Queue for items requiring human review. Processing continues while items await review — reviews are informational/audit.

- **JSONL persistence** — review items are persisted to `reviews.jsonl` in the state directory for crash recovery
- **SLA deadlines** — each review item can carry a `review_deadline` timestamp
- **Engine polling** — engine periodically checks for completed reviews and integrates decisions

### DecisionLedger (`governance/decision_ledger.py`)

Cryptographic tamper-evident chain of agent decisions. Every decision record is immutable (frozen dataclass) and linked to the previous record via SHA-256 hash, forming a Merkle-style chain.

**DecisionRecord fields:**

| Field Group | Fields |
|-------------|--------|
| Identity | `decision_id`, `sequence`, `decision_type`, `outcome` |
| Context | `agent_id`, `work_item_id`, `phase_id`, `run_id`, `app_id` |
| Content hashes | `input_hash`, `output_hash` (SHA-256 of serialized data) |
| Reasoning | `reasoning_summary`, `tool_calls` |
| Governance | `confidence`, `policy_result`, `policy_id`, `warnings` |
| Review | `reviewer`, `review_notes` |
| Chain | `previous_hash`, `record_hash` |

**Decision types:** `AGENT_EXECUTION`, `GOVERNANCE_CHECK`, `QUALITY_GATE`, `CRITIC_EVALUATION`, `HUMAN_REVIEW`, `PHASE_COMPLETION`, `WORK_COMPLETION`, `ESCALATION`

**Outcomes:** `APPROVED`, `REJECTED`, `ESCALATED`, `COMPLETED`, `FAILED`, `SKIPPED`

**Key operations:**
- `record_decision(...)` — create and chain a new record
- `verify_chain()` — recompute all hashes and verify chain links; returns `(is_valid, records_verified)`
- `query(...)` — filter by work_item_id, agent_id, decision_type, outcome, phase_id, run_id, app_id
- `get_decision_chain(work_item_id)` — full chronological trace for a work item
- `summary()` — counts by type, outcome, unique agents/work items

---

## Connector Capability Framework

The connector framework provides a domain-agnostic way for agents and modules to invoke external systems (search, ticketing, repositories, messaging, etc.) through a uniform interface with built-in permission enforcement and audit logging.

### ConnectorRegistry (`connectors/registry.py`)

Thread-safe registry for connector providers and configuration.

- `register_provider(provider)` — registers a `ConnectorProviderProtocol` implementor
- `register_config(config)` — registers a `ConnectorConfig` (settings + permission policies)
- `find_providers_for_capability(capability_type)` — returns enabled providers matching the capability

### ConnectorService (`connectors/service.py`)

Primary invocation abstraction. Owned by `OrchestrationEngine` (available via `engine.connector_service`).

```
ConnectorService.execute(capability_type, operation, parameters, context)
  1. Resolve and validate capability_type
  2. Build ConnectorInvocationRequest
  3. evaluate_permission(request, policies)  → deny → PERMISSION_DENIED result
  4. _resolve_provider(capability_type, preferred_provider)  → none → UNAVAILABLE result
  5. provider.execute(request)  → exception → FAILURE result
  6. _maybe_audit(request, result)
  7. Return ConnectorInvocationResult
```

**`wrap_result_as_artifact`** — wraps a result in an `ExternalArtifact` envelope with provenance tracking for uniform handling across domain modules.

### ConnectorProviderProtocol (`connectors/registry.py`)

Structural protocol (no inheritance required):

```python
class ConnectorProviderProtocol(Protocol):
    async def execute(self, request: ConnectorInvocationRequest) -> ConnectorInvocationResult: ...
    def get_descriptor(self) -> ConnectorProviderDescriptor: ...
```

### CapabilityType Taxonomy

`search` | `documents` | `messaging` | `ticketing` | `repository` | `telemetry` | `identity` | `external_api` | `file_storage` | `workflow_action`

### Permission Evaluation (`connectors/permissions.py`)

`evaluate_permission(request, policies)` — evaluates an ordered list of `ConnectorPermissionPolicy` objects:

1. Skip disabled policies
2. Skip policies whose `allowed_modules` / `allowed_agent_roles` don't match context
3. Deny if capability or operation is in `denied_*` lists
4. Deny if not in `allowed_*` lists (when lists are non-empty)
5. Default: permit

### Audit Integration (`connectors/audit.py`)

`log_connector_invocation(audit_logger, request, result)` writes a `SYSTEM_EVENT` record containing capability type, connector ID, operation, parameter keys (not values), status, duration, and cost info.

---

## Knowledge Layer

Shared memory subsystem that enables agents to store, retrieve, and build upon knowledge across work items and runs.

### KnowledgeStore (`knowledge/store.py`)

File-based content-addressable knowledge store with SHA-256 deduplication.

**Storage layout:**
```
base_dir/knowledge/
  index.jsonl          — one JSON object per line (metadata, no content)
  embeddings.jsonl     — cached embedding vectors per content_hash
  {content_hash}.json  — full content dict
```

**MemoryRecord fields:** `memory_id`, `memory_type`, `title`, `content`, `content_hash`, `tags`, `confidence`, `source_agent_id`, `source_work_id`, `source_phase_id`, `source_run_id`, `app_id`, `timestamp`, `expires_at`, `superseded_by`, `version`, `metadata`.

**Memory types:** `EVIDENCE`, `DECISION`, `STRATEGY`, `ARTIFACT`, `CONVERSATION`

**Key operations:**
- `store(record)` — persist with content deduplication; auto-computes embedding if service available
- `retrieve(query)` — filter + relevance scoring; scores combine tag match (3x weight), keyword match (2x weight), and recency bonus (1.0 within 1 hour, decaying to 0.0 at 24 hours), all scaled by confidence
- `semantic_query(query_text, limit, min_similarity)` — embedding-based cosine similarity search
- `supersede(old_id, new_record)` — version chain: marks old record, stores new with incremented version
- `delete(memory_id)` — soft-delete by setting `expires_at` to now
- `cleanup_expired()` — remove expired records from the index (content files preserved for deduplication)

Thread-safe: All public methods use an internal lock.

### EmbeddingService (`knowledge/embedding.py`)

Async client for OpenAI-compatible embedding APIs.

- `embed(text)` — embed a single text, returns vector as `list[float]`
- `embed_batch(texts)` — batch embedding in a single API call
- `cosine_similarity(a, b)` — pure-Python cosine similarity function
- Uses lazy `httpx.AsyncClient` initialization; configurable model (default: `text-embedding-3-small`) and base URL

### ContextMemory (`knowledge/context_memory.py`)

Per-work-item conversation history backed by KnowledgeStore.

- `add_turn(work_id, agent_id, phase_id, role, content)` — stores each turn as a `CONVERSATION`-type memory record
- `get_history(work_id, limit)` — chronologically ordered conversation turns
- `get_agent_history(work_id, agent_id, limit)` — turns filtered by agent
- `format_history(records)` — human-readable transcript format: `[agent_id] role: content`

### MemoryExtractor (`knowledge/extractor.py`)

Auto-extracts structured memory records from agent output dicts.

- `extract_from_agent_output(...)` — inspects output for a `memories` key containing a list of `{type, title, content, tags?, confidence?}` entries; validates required fields and constructs `MemoryRecord` instances
- `extract_completion_memories(...)` — auto-generates two records on work item completion:
  - `DECISION` memory with final aggregated results
  - `STRATEGY` memory summarizing phase execution sequence

---

## Evaluation & Simulation Layer

Comprehensive evaluation framework for scoring, comparing, and benchmarking agent workflows.

### LLMJudgeEvaluator (`simulation/evaluator.py`)

Scores agent outputs using an LLM as an expert judge.

- `evaluate(rubric, agent_output, work_item_context)` — sends output + rubric dimensions to LLM, parses per-dimension scores (0.0-1.0) with reasoning
- `evaluate_batch(rubric, results)` — evaluate multiple outputs against the same rubric
- **Weighted aggregate** — `sum(score * weight) / sum(weights)` across dimensions
- **Graceful fallback** — returns 0.5 scores with explanation if LLM output cannot be parsed
- Handles markdown-fenced JSON responses

**EvalRubric** — frozen dataclass: `rubric_id`, `name`, `description`, `dimensions: tuple[EvalDimension, ...]`, `system_prompt`

**EvalDimension** — frozen dataclass: `name`, `description`, `weight`

### RubricStore (`simulation/rubric_store.py`)

JSONL-backed persistence for evaluation rubrics with built-in templates.

**Built-in rubrics:**

| Rubric | Dimensions |
|--------|-----------|
| `builtin-quality` | accuracy (1.0), completeness (1.0), coherence (0.8), relevance (0.8) |
| `builtin-safety` | safety (1.0), bias (1.0), toxicity (1.0), privacy (1.0) |

- CRUD: `save_rubric`, `load_rubric`, `list_rubrics`, `delete_rubric`
- Built-in rubrics cannot be deleted
- Upsert semantics: latest line per rubric_id wins on load

### ABTestRunner (`simulation/ab_test.py`)

Side-by-side comparison of two workflow variants.

- `run_test(config, historical_items)` — runs both variants through SimulationSandbox, then compares per-item and aggregate outcomes
- Per-item winner determined by: success status > confidence (with 0.01 tie-breaker tolerance)
- Overall winner: variant with more item-level wins
- `summarize(result)` — API-friendly summary dict

### DatasetStore (`simulation/dataset.py`)

JSONL-backed persistence for versioned evaluation datasets.

- `save_dataset` / `load_dataset` / `list_datasets` / `delete_dataset` — standard CRUD
- `create_from_work_items(name, items)` — snapshot work items into a reusable dataset with auto-generated ID

### SimulationSandbox (`simulation/sandbox.py`)

Safe, isolated execution environment for replaying historical work items against new workflows.

- `run_simulation(config, historical_items, execute_fn?)` — replays items, classifies each as `SAME`, `IMPROVED`, `REGRESSED`, `NEW_SUCCESS`, or `NEW_FAILURE`
- Improvement/regression thresholds: +/- 5% confidence delta
- Supports cancellation mid-run
- **JSONL persistence** — simulation results persisted to `simulations.jsonl` for historical comparison
- `list_simulations()` / `get_simulation(id)` / `cancel_simulation(id)` / `summary()`

### BenchmarkStore & BenchmarkRunner (`simulation/benchmark.py`)

Persistent benchmark suites for regression detection.

**BenchmarkStore** — JSONL-backed persistence for suites (`suites.jsonl`) and run results (`runs.jsonl`):
- `save_suite` / `load_suite` / `list_suites` / `delete_suite` — suite CRUD
- `save_run` / `get_runs(suite_id)` / `get_run(run_id)` — run result management

**BenchmarkRunner** — executes suites through SimulationSandbox:
- `run_suite(suite)` — runs each case, checking: status match, minimum confidence, expected output keys
- `create_suite_from_history(items, suite_name)` — converts completed work items into a benchmark suite (historical outcomes become expected results)

---

## Capability Catalog Layer

Organizational capability registry that tracks what the AI workforce can do and how well it performs.

### TeamRegistry (`catalog/registry.py`)

Thread-safe registry for capability registrations.

- `register(registration)` / `get(capability_id)` / `unregister(capability_id)` — CRUD
- `find(tags?, status?, profile_name?)` — filtered lookup
- `list_all()` / `summary()` — introspection

### SkillMap (`catalog/skill_map.py`)

Live registry of organizational skills with performance tracking and coverage analysis.

- `register_skill(skill)` / `get_skill(id)` / `find_skills(tags?, agent_id?, min_success_rate?, maturity?)` — skill management
- `record_execution(skill_id, agent_id, success, confidence, duration)` — aggregates per-skill and per-agent metrics
- `auto_register_from_profile(agents, phases)` — derives skills from agent `skills` tags and links to workflow phases
- `get_coverage()` — returns `SkillCoverage` with strong/weak/unassigned skill breakdowns (strong >= 85% success rate, weak < 60%)
- `get_agent_profile(agent_id)` — per-agent performance profile across all skills
- **Maturity levels** — `NASCENT`, `DEVELOPING`, `MATURE`, `EXPERT` (based on execution count and success rate)
- **JSONL persistence** — skill records persisted to `skills.jsonl`

### Auto-Registration (`catalog/auto_register.py`)

Derives `CapabilityRegistration` from a profile configuration on engine startup.

- `build_registration_from_profile(profile, settings)` — maps manifest fields, work item type schemas, workflow output fields, governance thresholds, and invocation modes into a discoverable capability registration
- Input/output schemas built from `custom_fields` and `expected_output_fields`
- Invocation modes: `ASYNC` and `EVENT_DRIVEN` always; `SYNC` added for single-phase workflows

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
| `AuditLogger` | JSONL | Hash-chained audit records (with size-based rotation) |
| `MetricsCollector` | JSONL | Execution metrics |
| `WorkItemStore` | JSONL | Work item persistence with full history (upsert semantics) |
| `ArtifactStore` | JSONL + files | Content-addressable artifact storage (SHA-256 dedup) |
| `DecisionLedger` | JSONL | SHA-256 hash-chained decision records |
| `KnowledgeStore` | JSONL + files | Content-addressable memory records with embeddings |
| `RubricStore` | JSONL | Evaluation rubric persistence |
| `DatasetStore` | JSONL | Versioned evaluation datasets |
| `BenchmarkStore` | JSONL | Benchmark suites and run results |
| `SimulationSandbox` | JSONL | Simulation result persistence |
| `SkillMap` | JSONL | Skill records with per-agent metrics |

### WorkItemStore (`persistence/work_item_store.py`)

JSONL-backed work item persistence with full status history.

- `save(work_item)` — append snapshot (upsert semantics — latest line per ID wins)
- `load(work_id)` — load specific item by ID
- `query(status?, type_id?, app_id?, run_id?, limit)` — filtered retrieval, newest first
- `get_incomplete()` — all non-terminal items for crash recovery
- Serializes full `WorkItem` including `history: list[WorkItemHistoryEntry]`, `deadline`, `urgency`, `sla_policy_id`, `routing_tags`

### ArtifactStore (`persistence/artifact_store.py`)

Content-addressable file-based artifact storage.

- `store(artifact)` — persist with SHA-256 deduplication; returns content hash
- `get_by_hash(content_hash)` — retrieve by content address
- `query(work_id?, phase_id?, agent_id?, artifact_type?, limit)` — metadata-filtered retrieval
- `get_chain(work_id)` — chronological artifact chain for a work item

**Artifact types:** `input`, `output`, `critic_feedback`

**Storage layout:**
```
base_dir/artifacts/
  index.jsonl          — one JSON object per line (metadata)
  {content_hash}.json  — artifact content
```

### LineageBuilder (`persistence/lineage.py`)

Unified chronological trace across all 4 data sources: WorkItemStore, DecisionLedger, ArtifactStore, and AuditLogger.

- `build_lineage(work_item_id)` — collects events from all sources, merges and sorts chronologically into a single `WorkItemLineage` timeline
- Each `LineageEvent` includes: `timestamp`, `source` (history/decision/artifact/audit), `event_type`, `phase_id`, `agent_id`, `detail`
- Verifies decision chain integrity as part of lineage construction

**SettingsStore API key security:**
- Env vars override YAML: `AGENT_ORCH_{PROVIDER}_API_KEY` (e.g., `AGENT_ORCH_OPENAI_API_KEY`)
- Keys sourced from env vars are never persisted to disk

**Atomic writes:** All stores write to a temp file then rename. SettingsStore creates a backup before overwriting and includes retry logic for Windows file locking.

---

## REST API Layer

FastAPI application created via `create_app()` factory. All routes under `/api/v1`.

| Group | Endpoints | Description |
|-------|-----------|-------------|
| Health | `GET /health`, `/health/ready`, `/health/live`, `/context` | Liveness, readiness, execution context |
| Agents | `GET/POST /agents`, `GET/PUT/DELETE /agents/{id}`, `POST /agents/{id}/scale`, `GET /agents/export`, `POST /agents/import` | Agent CRUD and scaling |
| Workflow | `GET /workflow/phases`, `GET /workflow/phases/{id}` | Workflow introspection |
| Work Items | `GET/POST /workitems`, `GET /workitems/{id}` | Work item submission and status |
| Governance | `GET/POST /governance/policies`, `GET /governance/reviews` | Policy management and review queue |
| Execution | `GET /execution/status`, `POST /execution/start\|stop\|pause\|resume` | Engine lifecycle control |
| Metrics | `GET /metrics`, `GET /metrics/agents/{id}` | Aggregated and per-agent metrics |
| Audit | `GET /audit` | Query audit trail (filters: `work_id`, `record_type`, `limit`) |
| Config | `GET /config/profiles`, `GET /config/profile/export`, `POST /config/validate`, `GET /config/history` | Configuration management |
| Connectors | `GET /connectors/capabilities`, `GET /connectors/providers` | Connector introspection |
| Knowledge | `GET /knowledge/stats`, `GET/POST /knowledge`, `GET/DELETE /knowledge/{id}`, `POST /knowledge/{id}/supersede` | Knowledge store CRUD and search (6 endpoints) |
| Catalog | `GET/POST /catalog/capabilities`, `GET/PUT/DELETE /catalog/capabilities/{id}`, `GET /catalog/summary`, `POST /catalog/capabilities/{id}/invoke` | Capability registry (7 endpoints) |
| Skills | `GET /skills`, `GET /skills/{id}`, `POST /skills`, `DELETE /skills/{id}`, `POST /skills/{id}/record`, `GET /skills/coverage/report`, `GET /skills/agent/{id}/profile`, `GET /skills/summary` | Skill map management (8 endpoints) |
| Decision Ledger | `GET /ledger/decisions`, `GET /ledger/decisions/chain/{id}`, `GET /ledger/decisions/agent/{id}`, `GET /ledger/verify`, `GET /ledger/summary` | Decision chain queries (5 endpoints) |
| Lineage | `GET /work-items/{id}/lineage`, `GET /work-items/{id}/decisions`, `GET /work-items/{id}/artifacts` | Work item traceability (3 endpoints) |
| Simulations | `GET /simulations/summary`, `GET /simulations`, `GET/POST /simulations`, `POST /simulations/{id}/cancel`, `POST /simulations/replay` | Simulation sandbox (6 endpoints) |
| Benchmarks | `GET/POST /benchmarks/suites`, `GET/DELETE /benchmarks/suites/{id}`, `POST /benchmarks/suites/{id}/run`, `POST /benchmarks/suites/from-history`, `GET /benchmarks/suites/{id}/runs`, `GET /benchmarks/runs/{id}` | Benchmark regression testing (8 endpoints) |
| Evaluation | `GET/POST /evals/rubrics`, `GET/DELETE /evals/rubrics/{id}`, `POST /evals/evaluate`, `POST /evals/ab-test`, `GET/POST /evals/datasets`, `GET/DELETE /evals/datasets/{id}` | LLM-as-judge evaluation (10 endpoints) |

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
   CLI/API ──► create_run_context() → assign run_id/app_id
               WorkQueue.push(item)
               emit(WORK_SUBMITTED, app_id=, run_id=)

2. DEQUEUE
   Processing loop ──► WorkQueue.pop()
                        reconstruct run context from item
                        emit(WORK_STARTED, app_id=, run_id=)

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
| `ReviewQueue` | Review items dict, JSONL persistence |
| `DecisionLedger` | Sequence counter, JSONL writes (RLock) |
| `MetricsCollector` | Counters, file writes |
| `SettingsStore` | YAML reads/writes |
| `StateStore` | JSON reads/writes |
| `ConfigurationManager` | Settings/profile cache |
| `AgentManager` | Agent dict, persistence |
| `EventBus` | Subscriber registry |
| `KnowledgeStore` | JSONL index, content files, embeddings cache |
| `EmbeddingService` | httpx client lifecycle |
| `GapSignalCollector` | Signal window dict |
| `AgentSynthesizer` | Proposal dict |
| `TeamRegistry` | Registration dict (RLock) |
| `SkillMap` | Skill dict, JSONL persistence (RLock) |
| `WorkItemStore` | JSONL file reads/writes |
| `ArtifactStore` | JSONL index, content files |
| `SimulationSandbox` | Simulation result dict (RLock) |
| `RubricStore` | JSONL file reads/writes |
| `DatasetStore` | JSONL file reads/writes |
| `BenchmarkStore` | JSONL file reads/writes |

**Key invariant:** Locks are never held across `await` boundaries.

---

## Design Patterns

| Pattern | Where | Purpose |
|---------|-------|---------|
| Dependency Injection | `AgentExecutor(llm_call_fn=...)`, `OrchestrationEngine(config_manager, event_bus)` | Testability, loose coupling |
| State Machine | `EngineState`, `WorkItemStatus`, `AgentState`, `SimulationStatus` | Explicit lifecycle management |
| Observer / Pub-Sub | `EventBus`, `GapSignalCollector` | Decouple producers from consumers |
| Strategy | `PhaseExecutor` parallel vs sequential | Configurable execution mode |
| Adapter | `LLMAdapter` + `LLMProviderProtocol` | Uniform interface over multiple LLM SDKs |
| Chain of Responsibility | `Governor` policy evaluation | Priority-ordered policy matching |
| Factory | `create_app()`, `AgentPool._create_instance()`, `create_artifact()` | Encapsulate construction |
| Protocol (structural typing) | `LLMProviderProtocol` | No inheritance required for providers |
| Frozen DTOs | All Pydantic config models, `DecisionRecord`, `EvalRubric` | Safe sharing across threads |
| Append-Only Log | `AuditLogger`, `DecisionLedger` with hash chaining | Tamper-evident compliance trail |
| Content-Addressable Storage | `KnowledgeStore`, `ArtifactStore` (SHA-256) | Deduplication, integrity verification |
| Sliding Window | `GapSignalCollector` time-windowed counters | Runtime signal aggregation |
| Judge Pattern | `LLMJudgeEvaluator` | LLM-as-expert-evaluator for output scoring |
| Supersession Chain | `KnowledgeStore.supersede()` | Version management without destructive updates |

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
│   │   ├── routes.py                    Core REST route definitions
│   │   ├── catalog_routes.py            Capability registry endpoints (7)
│   │   ├── knowledge_routes.py          Knowledge store endpoints (6)
│   │   ├── skillmap_routes.py           Skill map endpoints (8)
│   │   ├── ledger_routes.py             Decision ledger endpoints (5)
│   │   ├── lineage_routes.py            Work item lineage endpoints (3)
│   │   ├── simulation_routes.py         Simulation sandbox endpoints (6)
│   │   ├── benchmark_routes.py          Benchmark suite endpoints (8)
│   │   └── eval_routes.py              Evaluation & A/B test endpoints (10)
│   │
│   ├── configuration/
│   │   ├── models.py                    Pydantic v2 config models (frozen)
│   │   ├── loader.py                    ConfigurationManager, YAML/JSON I/O
│   │   ├── validator.py                 Profile validation rules
│   │   └── agent_manager.py            Agent CRUD with persistence
│   │
│   ├── core/
│   │   ├── engine.py                    OrchestrationEngine (central coordinator)
│   │   ├── context.py                   ExecutionContext helpers (create, fork, tags)
│   │   ├── work_queue.py                Priority async work queue
│   │   ├── pipeline_manager.py          Phase graph traversal
│   │   ├── agent_pool.py                Agent instance pool with concurrency
│   │   ├── agent_executor.py            Single-agent execution + retries
│   │   ├── phase_executor.py            Multi-agent phase execution
│   │   ├── event_bus.py                 Async pub/sub event bus
│   │   ├── output_parser.py             Confidence/score extraction from LLM output
│   │   ├── quality_gate.py              Phase quality gate evaluation
│   │   ├── sla_monitor.py               Background SLA deadline monitoring
│   │   ├── gap_detector.py              Runtime capability gap detection
│   │   ├── agent_synthesizer.py         LLM-powered agent design for gap filling
│   │   └── work_item_factory.py         Work item construction helpers
│   │
│   ├── governance/
│   │   ├── governor.py                  Policy engine (non-blocking, ast.literal_eval)
│   │   ├── audit_logger.py              Hash-chained JSONL audit trail (with log rotation)
│   │   ├── review_queue.py              Human review queue (JSONL persistence, SLA deadlines)
│   │   └── decision_ledger.py           SHA-256 hash-chained decision chain
│   │
│   ├── knowledge/
│   │   ├── __init__.py                  Public API exports
│   │   ├── models.py                    MemoryType, MemoryRecord, MemoryQuery
│   │   ├── store.py                     Content-addressable KnowledgeStore
│   │   ├── embedding.py                 EmbeddingService + cosine_similarity
│   │   ├── context_memory.py            Per-work-item conversation history
│   │   └── extractor.py                 MemoryExtractor (agent output → memories)
│   │
│   ├── simulation/
│   │   ├── __init__.py                  Public API exports
│   │   ├── models.py                    SimulationConfig/Result, BenchmarkCase/Result
│   │   ├── sandbox.py                   SimulationSandbox (replay + compare)
│   │   ├── evaluator.py                 LLMJudgeEvaluator, EvalRubric, EvalResult
│   │   ├── rubric_store.py              JSONL rubric persistence + built-in templates
│   │   ├── ab_test.py                   ABTestRunner (side-by-side comparison)
│   │   ├── dataset.py                   DatasetStore for versioned eval datasets
│   │   ├── benchmark.py                 BenchmarkStore + BenchmarkRunner
│   │   └── executor.py                  Simulation execution bridge
│   │
│   ├── catalog/
│   │   ├── __init__.py                  Public API exports
│   │   ├── models.py                    CapabilityRegistration, InvocationMode, etc.
│   │   ├── skill_models.py              SkillRecord, SkillMetrics, SkillCoverage, SkillMaturity
│   │   ├── registry.py                  TeamRegistry (thread-safe capability lookup)
│   │   ├── skill_map.py                 SkillMap (live performance tracking + coverage)
│   │   └── auto_register.py             Profile → CapabilityRegistration derivation
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
│   ├── connectors/
│   │   ├── __init__.py                  Public API exports
│   │   ├── models.py                    12 Pydantic v2 frozen models (CapabilityType, ConnectorStatus, etc.)
│   │   ├── registry.py                  Thread-safe ConnectorRegistry + ConnectorProviderProtocol
│   │   ├── service.py                   ConnectorService (execute, wrap_result_as_artifact)
│   │   ├── permissions.py               evaluate_permission() — ordered policy evaluation
│   │   └── audit.py                     log_connector_invocation() — AuditLogger bridge
│   │
│   ├── mcp/
│   │   ├── __init__.py                  Public API exports (lazy-guarded)
│   │   ├── models.py                    9 Pydantic v2 frozen models (transport, config, tool/resource/prompt info)
│   │   ├── exceptions.py                MCPError hierarchy (connection, tool call, resource, config)
│   │   ├── client_manager.py            MCPClientManager — session lifecycle, discovery, invocation
│   │   ├── bridge.py                    MCPToolConnectorProvider + MCPConnectorBridge
│   │   ├── client_prompts.py            MCPPromptResolver — fetch prompts from external servers
│   │   ├── server.py                    create_mcp_server() + create_mcp_asgi_app() factory
│   │   ├── server_tools.py              Dynamic tool generation from ConnectorRegistry
│   │   ├── server_resources.py          Resource handlers (status, workitems, audit, config)
│   │   ├── server_prompts.py            Prompt handlers from agent definitions
│   │   ├── server_governance.py         GovernedToolDispatcher — governance-checked dispatch
│   │   └── server_session.py            MCPSessionRegistry with TTL
│   │
│   ├── persistence/
│   │   ├── __init__.py                  Public API exports
│   │   ├── settings_store.py           YAML settings (atomic writes, env fallback)
│   │   ├── state_store.py              JSON runtime state
│   │   ├── config_history.py           Config versioning with restore
│   │   ├── work_item_store.py          JSONL work item persistence (upsert, history, crash recovery)
│   │   ├── artifact_store.py           Content-addressable artifact storage (SHA-256 dedup)
│   │   └── lineage.py                  Unified lineage builder (4-source merge)
│   │
│   └── profiles/                       Built-in profile templates
│       ├── content-moderation/
│       └── software-dev/
│
└── tests/
    ├── conftest.py                      Shared fixtures
    ├── unit/                            52 test files, 1343+ tests
    │   ├── test_core.py                 Engine, queue, pool, pipeline, executor, events
    │   ├── test_configuration.py        Models, loader, validator
    │   ├── test_governance.py           Governor, audit, review queue
    │   ├── test_persistence.py          State store, settings store, config history
    │   ├── test_api.py                  REST API endpoints
    │   ├── test_agent_manager.py        Agent CRUD operations
    │   ├── test_providers.py            LLM provider mocked tests
    │   ├── test_output_parser.py        Confidence/score extraction
    │   ├── test_quality_gate.py         Quality gate evaluation
    │   ├── test_sla_monitor.py          SLA deadline monitoring
    │   ├── test_gap_detector.py         Gap signal collection and analysis
    │   ├── test_agent_synthesizer.py    LLM-powered agent synthesis
    │   ├── test_knowledge_store.py      Knowledge store CRUD and retrieval
    │   ├── test_memory_extractor.py     Memory extraction from agent output
    │   ├── test_engine_knowledge.py     Engine-knowledge integration
    │   ├── test_decision_ledger.py      Decision chain integrity
    │   ├── test_team_registry.py        Capability registration
    │   ├── test_auto_register.py        Auto-registration from profiles
    │   ├── test_skill_map.py            Skill tracking and coverage
    │   ├── test_simulation.py           Simulation sandbox
    │   ├── test_eval_system.py          LLM judge, rubrics, datasets, A/B tests
    │   ├── test_work_item_store.py      Work item persistence
    │   ├── test_artifact_store.py       Artifact store CRUD
    │   ├── test_work_queue.py           Work queue operations
    │   ├── test_work_item_factory.py    Work item construction
    │   ├── test_catalog_routes.py       Catalog API endpoints
    │   ├── test_skillmap_routes.py      Skill map API endpoints
    │   ├── test_ledger_routes.py        Ledger API endpoints
    │   ├── test_lineage_routes.py       Lineage API endpoints
    │   ├── test_simulation_routes.py    Simulation API endpoints
    │   ├── test_benchmark_routes.py     Benchmark API endpoints
    │   └── ...                          (connectors, MCP, providers, etc.)
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
│       ├── workitems.yaml              list[WorkItemTypeConfig]
│       └── mcp.yaml                    MCPProfileConfig (optional — MCP client/server config)
│
├── .agent-orchestrator/                Runtime persistence
│   ├── work_items.jsonl               Work item snapshots (upsert)
│   └── benchmarks/
│       ├── suites.jsonl               Benchmark suite configs
│       └── runs.jsonl                 Benchmark run results
│
└── .state/                             Runtime state (created on start)
    ├── audit/                          Hash-chained JSONL audit logs (with rotation)
    ├── reviews.jsonl                   Review queue persistence
    ├── decisions/
    │   └── decisions.jsonl            Hash-chained decision ledger
    ├── knowledge/
    │   ├── index.jsonl                Memory record metadata
    │   ├── embeddings.jsonl           Cached embedding vectors
    │   └── {hash}.json                Content files (SHA-256 addressed)
    ├── artifacts/
    │   ├── index.jsonl                Artifact metadata
    │   └── {hash}.json                Artifact content files
    ├── skills/
    │   └── skills.jsonl               Skill map state
    ├── simulations/
    │   └── simulations.jsonl          Simulation results
    ├── rubrics.jsonl                   Evaluation rubrics
    ├── datasets.jsonl                  Evaluation datasets
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

1343+ tests across 52 test files, all passing. All tests use mocked dependencies — no real API calls.

```
pytest tests/ -v            # run all tests
pytest tests/ --cov         # with coverage
```

| Test File | Tests | Covers |
|-----------|-------|--------|
| `test_core.py` | 50 | Engine lifecycle, queue, pool, pipeline, executor, events |
| `test_configuration.py` | 54 | Config models, loader, validator, built-in profiles |
| `test_governance.py` | 19 | Governor decisions, audit hash chain, review queue |
| `test_persistence.py` | 13 | State store, settings store, config history |
| `test_api.py` | 73 | Core REST endpoints (health, CRUD, execution, governance, metrics, audit) |
| `test_agent_manager.py` | 34 | Agent CRUD, import/export, profile component export |
| `test_providers.py` | 21 | All 5 LLM providers, registration, adapter routing |
| `test_execution_context.py` | 28 | DeploymentMode, ExecutionContext, context helpers, audit filtering |
| `test_connectors.py` | 107 | Connector models, registry, service, permissions, audit |
| `test_contracts.py` | 59 | Contract models, registry, validator, service integration |
| `test_*_providers.py` | 227 | Web search, documents, messaging, ticketing, repository providers |
| `test_connector_governance.py` | 44 | Enable/disable, scoping, policies, discovery, permissions |
| `test_provider_discovery.py` | 43 | Auto-discovery, lazy loading, from_env, entry points |
| `test_mcp_models.py` | 18 | MCP Pydantic model creation, validation, defaults, frozen behavior |
| `test_mcp_client_manager.py` | 18 | MCP client session lifecycle with mocked SDK |
| `test_mcp_bridge.py` | 14 | MCP-to-connector registration, execute flow |
| `test_mcp_server.py` | 14 | Session registry, TTL, max sessions |
| `test_mcp_server_governance.py` | 7 | Governed tool dispatcher resolutions, audit |
| `test_output_parser.py` | 30 | Confidence extraction, score aggregation, field parsing |
| `test_quality_gate.py` | 13 | Gate evaluation, context building, multi-gate phases |
| `test_sla_monitor.py` | 17 | SLA warning/breach events, priority boost, lifecycle |
| `test_gap_detector.py` | 15 | Signal collection, window management, threshold analysis |
| `test_agent_synthesizer.py` | 14 | LLM synthesis, fallback, validation, proposal lifecycle |
| `test_knowledge_store.py` | 19 | Store/retrieve/supersede/delete, relevance scoring, expiry |
| `test_memory_extractor.py` | 8 | Agent output extraction, completion memories |
| `test_knowledge_improvements.py` | 46 | Embedding integration, semantic search, advanced queries |
| `test_engine_knowledge.py` | 4 | Engine ↔ knowledge store integration |
| `test_decision_ledger.py` | 18 | Record/verify/query, chain integrity, tamper detection |
| `test_team_registry.py` | 18 | Capability registration, find, unregister |
| `test_auto_register.py` | 13 | Profile → registration derivation, schema building |
| `test_skill_map.py` | 23 | Skill CRUD, metrics, coverage, auto-registration |
| `test_simulation.py` | 20 | Sandbox execution, outcome classification, persistence |
| `test_eval_system.py` | 55 | LLM judge evaluator, rubrics, datasets, A/B tests, benchmarks |
| `test_work_item_store.py` | 14 | Work item persistence, query, crash recovery |
| `test_artifact_store.py` | 13 | Artifact store, dedup, chain retrieval |
| `test_work_queue.py` | 14 | Queue operations, priority, dedup |
| `test_work_item_factory.py` | 20 | Work item construction helpers |
| `test_catalog_routes.py` | 18 | Catalog REST endpoints |
| `test_skillmap_routes.py` | 13 | Skill map REST endpoints |
| `test_ledger_routes.py` | 8 | Decision ledger REST endpoints |
| `test_lineage_routes.py` | 13 | Lineage REST endpoints |
| `test_simulation_routes.py` | 7 | Simulation REST endpoints |
| `test_benchmark_routes.py` | 20 | Benchmark REST endpoints |
| `test_engine_governance.py` | 10 | Engine ↔ governance integration |
| `test_capability_validation.py` | 11 | Capability validation |
| `test_critic_agent.py` | 11 | Critic agent evaluation |

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

**MCP** (optional — `pip install agent-orchestrator[mcp]`):
```
mcp>=1.0                 Model Context Protocol SDK
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
├── WorkItemError             Work item submission errors
├── KnowledgeError            Knowledge store operations
├── ConnectorError            Connector-related errors
├── ContractError             Contract registration / resolution errors
│   └── ContractViolationError  Contract validation halt
└── MCPError                  MCP-related errors
    ├── MCPConnectionError    Server connection failures
    ├── MCPToolCallError      Tool invocation failures
    ├── MCPResourceError      Resource read failures
    └── MCPConfigurationError Invalid config or missing SDK
```

---

## MCP Integration

MCP (Model Context Protocol) support adds bidirectional interoperability with the AI ecosystem. MCP is a protocol adapter — it does not replace the REST API, connector framework, or governance system.

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  MCP Server (Streamable HTTP on /mcp)                       │
│  server.py · server_tools.py · server_resources.py          │
│  server_prompts.py · server_governance.py · server_session.py│
├─────────────────────────────────────────────────────────────┤
│  MCP Client                                                 │
│  client_manager.py · bridge.py · client_prompts.py          │
├─────────────────────────────────────────────────────────────┤
│  Shared Models & Config                                     │
│  models.py · exceptions.py                                  │
├─────────────────────────────────────────────────────────────┤
│  Existing Platform (unchanged)                              │
│  ConnectorService · ConnectorRegistry · Governor            │
│  AuditLogger · ContractValidator · OrchestrationEngine      │
└─────────────────────────────────────────────────────────────┘
```

### MCP Client

Agents consume tools, resources, and prompts from external MCP servers:

- **MCPClientManager** — manages connections to external MCP servers (stdio, Streamable HTTP, SSE transports). All `mcp` SDK imports are lazy; the platform works without the package.
- **MCPConnectorBridge** — discovers tools from connected servers and registers each as a `ConnectorProviderProtocol` in `ConnectorRegistry`. This gives MCP tools the same permission checks, contract validation, and audit logging as native connectors.
- **MCPToolConnectorProvider** — wraps one MCP tool. Provider ID: `mcp.{server_id}.{tool_name}`.
- **MCPPromptResolver** — fetches prompt templates from external servers for agent prompt building.

### MCP Server

The platform exposes its governed capabilities to external AI clients:

- **Dynamic tools** from `ConnectorRegistry` — each registered provider's operations become MCP tools.
- **Static orchestration tools** — `orchestrator_get_status`, `orchestrator_submit_workitem`, `orchestrator_list_workitems`, `orchestrator_get_workitem`, `orchestrator_list_agents`, `orchestrator_engine_pause`, `orchestrator_engine_resume`.
- **Resources** — `orchestrator://status`, `orchestrator://workitems`, `orchestrator://audit`, `orchestrator://config/agents`, `orchestrator://config/workflow`, `orchestrator://config/governance`, `orchestrator://connectors`.
- **Prompts** — one per `AgentDefinition` in the active profile (`agent_{id}`).
- **GovernedToolDispatcher** — all tool calls flow through Governor evaluation and audit logging with `MCP_INVOCATION` record type.
- **MCPSessionRegistry** — tracks active client sessions with configurable TTL and max session limits.

### Configuration

MCP is configured via `mcp.yaml` in the profile directory:

```yaml
client:
  servers:
    - server_id: github
      display_name: GitHub MCP Server
      transport: stdio
      command: npx
      args: ["-y", "@modelcontextprotocol/server-github"]
      env:
        GITHUB_PERSONAL_ACCESS_TOKEN: "${GITHUB_TOKEN}"
      capability_type_override: repository
      auto_connect: true
  default_capability_type: external_api
  tool_prefix: mcp

server:
  enabled: true
  mount_path: "/mcp"
  session_ttl_seconds: 3600
  max_sessions: 100
  audit_all_invocations: true
```

### Key Principle

Every MCP tool call (client or server) flows through `ConnectorService.execute()` — getting permission checks, contract validation, and audit logging for free. MCP is opt-in: no `mcp.yaml` = no MCP; no `mcp` package installed = MCP features silently disabled.

---

## Studio — Visual Design Tool

Studio is a separate FastAPI + React application for visually designing agent team profiles without editing YAML by hand. It runs on port 8001 alongside the runtime on port 8000.

### Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  Browser (React 18 + TypeScript + Vite + Tailwind)           │
│                                                              │
│  Sidebar ──► Pages (Overview, Agents, Workflow, Governance,  │
│              Work Items, Preview, Deploy, Settings,          │
│              AI Recommend)                                    │
│                                                              │
│  Zustand Store (teamStore.ts)                                │
│  ├── team: TeamSpec | null                                   │
│  ├── currentView: View                                       │
│  └── CRUD actions → API client → backend                     │
└──────────────────────┬───────────────────────────────────────┘
                       │ fetch(/api/studio/*)
                       ▼
┌──────────────────────────────────────────────────────────────┐
│  Studio Backend (FastAPI, port 8001)                          │
│                                                              │
│  Route Modules:                                              │
│  ├── team_routes         — Team CRUD, current team state     │
│  ├── schemas_routes      — JSON schema extraction            │
│  ├── generation_routes   — YAML file generation & preview    │
│  ├── validation_routes   — Profile validation (Studio+RT)    │
│  ├── graph_routes        — Workflow DAG visualization         │
│  ├── connector_routes    — Connector discovery from runtime  │
│  ├── template_routes     — Template import/export            │
│  ├── deploy_routes       — Profile deployment to runtime     │
│  ├── condition_routes    — Condition expression builder      │
│  ├── extension_routes    — Python stub generation            │
│  ├── prompt_routes       — System prompt generation          │
│  ├── settings_routes     — LLM API key management            │
│  └── recommend_routes    — AI Workflow Recommender            │
│                                                              │
│  Shared State:                                               │
│  ├── app.state.studio_config  (StudioConfig, immutable)      │
│  └── app.state.studio_state   (dict, mutable: current_team)  │
│                                                              │
│  IR Models (studio/ir/models.py):                            │
│  ├── TeamSpec ──► AgentSpec, WorkflowSpec, GovernanceSpec     │
│  ├── PhaseSpec, StatusSpec, PolicySpec, WorkItemTypeSpec      │
│  └── 1-to-1 mapping with runtime Pydantic models             │
│                                                              │
│  Conversion Layer:                                           │
│  └── IR ↔ runtime ProfileConfig (for validation + YAML gen)  │
└──────────────────────────────────────────────────────────────┘
```

### IR (Intermediate Representation)

Studio editors work with IR models (`studio/ir/models.py`), not runtime models directly. All IR models are Pydantic `BaseModel` with `frozen=True` (immutable, hashable, thread-safe). Field names mirror runtime model fields so the conversion layer is a straightforward mapping.

**Root model:** `TeamSpec` — contains `agents`, `workflow` (phases + statuses), `governance` (policies + delegated authority), `work_item_types`, and optional `manifest`.

### Frontend State Management

A single Zustand store (`teamStore.ts`) is the source of truth:

- **View routing** — `currentView` drives a switch-based page renderer (no router library)
- **Team state** — `team: TeamSpec | null`, loaded from / synced to backend via REST
- **CRUD pattern** — each resource (agent, phase, status, policy, work item type) has `add/update/remove` actions that call `updateTeam()` with the modified team object
- **Bulk operations** — `bulkAddAgentsAndPhases()` for applying recommendations with ID-collision deduplication

### Key Services

| Service | Location | Purpose |
|---------|----------|---------|
| **Converter** | `studio/conversion/converter.py` | IR ↔ runtime Pydantic model mapping |
| **Graph Validator** | `studio/graph/validator.py` | Phase DAG cycle detection + validation |
| **Generator** | `studio/generation/generator.py` | LLM-powered config generation |
| **Condition Builder** | `studio/conditions/builder.py` | Visual condition expression editor |
| **Prompt Generator** | `studio/prompts/generator.py` | System prompt generation |
| **Deployer** | `studio/deploy/deployer.py` | Package + deploy profiles to runtime |
| **Template Manager** | `studio/templates/manager.py` | Import/export profile templates (YAML) |
| **Recommendation Engine** | `studio/recommend/engine.py` | Suggest agent archetypes from descriptions or codebase analysis |

### Docker Deployment

Studio uses a multi-stage Docker build:

1. **Stage 1 (frontend-build):** Node 20-alpine builds the React/Vite frontend
2. **Stage 2 (backend):** Python 3.11-slim installs the parent `agent-orchestrator[llm]` package, then studio dependencies, and copies compiled frontend assets to `/app/frontend/dist/`

The backend serves the compiled frontend as static files. A single container on port 8001 serves both.

```yaml
# studio/docker-compose.yml
services:
  studio:
    build:
      context: ..
      dockerfile: studio/Dockerfile
    ports: ["8001:8001"]
    environment:
      STUDIO_RUNTIME_URL: http://api:8000
      STUDIO_WORKSPACE_DIR: /workspace
```

---

## AI Workflow Recommender

The recommender suggests agents and phases based on either a project description (greenfield) or an existing codebase analysis. No LLM API calls — greenfield uses keyword heuristics, codebase uses structural mapping. The user's own coding assistant performs codebase analysis.

### Architecture

```
┌─ RecommendPage.tsx ─────────────────────────────────────────┐
│                                                              │
│  ┌── Greenfield Tab ──┐  ┌── Existing Codebase Tab ──────┐  │
│  │ description input   │  │ 1. Generate prompt            │  │
│  │ → POST /greenfield  │  │ 2. User runs in Claude Code   │  │
│  └─────────────────────┘  │ 3. Paste JSON → POST /from-cb │  │
│                            └──────────────────────────────┘  │
│                                                              │
│  ┌── RecommendReviewPanel ────────────────────────────────┐  │
│  │  AgentRecommendCard[]  (checkbox, confidence, edit)     │  │
│  │  PhaseRecommendCard[]  (checkbox, agents, transitions)  │  │
│  │  [Apply Selected] → bulkAddAgentsAndPhases()            │  │
│  └─────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
                       │
                       ▼
┌─ Backend ────────────────────────────────────────────────────┐
│                                                              │
│  POST /api/studio/recommend/greenfield                       │
│  POST /api/studio/recommend/codebase-prompt                  │
│  POST /api/studio/recommend/from-codebase                    │
│                                                              │
│  ┌── engine.py ──────────────────────────────────────────┐   │
│  │                                                        │   │
│  │  recommend_from_description(text)                      │   │
│  │    → tokenize → score archetypes by keyword overlap    │   │
│  │    → boost management agents when 2+ agents matched    │   │
│  │    → generate wired phases from matched archetypes     │   │
│  │                                                        │   │
│  │  recommend_from_codebase(analysis_json)                │   │
│  │    → structural mapping:                               │   │
│  │      APIs → backend-dev + reviewer                     │   │
│  │      Frontend → frontend-dev                           │   │
│  │      No tests → tester (high confidence)               │   │
│  │      CI/CD → devops                                    │   │
│  │      High-severity issues → security scanner           │   │
│  │      Multiple components → architect                   │   │
│  │                                                        │   │
│  │  generate_codebase_prompt(description?, focus_areas?)  │   │
│  │    → returns prompt + instructions for coding assistant │   │
│  └────────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌── archetypes.py ──────────────────────────────────────┐   │
│  │  12 agent archetypes:                                  │   │
│  │  PM, Architect, Backend Dev, Frontend Dev,             │   │
│  │  Code Reviewer, Security Scanner, Tester, DevOps,      │   │
│  │  Data Analyst, Content Moderator, Researcher,          │   │
│  │  Technical Writer                                      │   │
│  │                                                        │   │
│  │  Each has: id, name, description, system_prompt,       │   │
│  │  keywords[], default_phase, category, skills[]         │   │
│  └────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

### Archetype Catalog

Each archetype is a reusable agent template with keyword triggers:

| Archetype | Category | Default Phase | Keyword Examples |
|-----------|----------|---------------|-----------------|
| PM / Requirements | management | requirements | product, requirements, user stories |
| Architect | management | design | architecture, system design, api design |
| Backend Dev | development | implementation | api, backend, server, database, python |
| Frontend Dev | development | implementation | frontend, ui, react, angular, web app |
| Code Reviewer | review | review | code review, quality, best practices |
| Security Scanner | review | security | security, audit, vulnerability, owasp |
| Tester | review | testing | test, qa, pytest, jest, e2e |
| DevOps | ops | deployment | deploy, ci/cd, docker, terraform |
| Data Analyst | development | analysis | data, analytics, dashboard, etl |
| Content Moderator | development | moderation | moderation, content, filter, safety |
| Researcher | development | research | research, search, analysis, synthesis |
| Technical Writer | ops | documentation | documentation, docs, technical writing |

### Scoring Algorithm (Greenfield)

1. Tokenize description into lowercase words
2. For each archetype, count keyword matches (full match = 1.0, partial/substring = 0.5, multi-word keyword with all words present = 0.7)
3. Score = `matches / min(keyword_count, 4) * 0.5` — capped denominator prevents archetypes with many keywords from being disadvantaged
4. Include archetypes scoring > 0.3
5. When 2+ non-management agents matched, boost management archetypes (PM, Architect) to 0.5

### Structural Mapping (Codebase)

Uses the CodebaseAnalysis JSON schema (returned by the user's coding assistant) and applies deterministic rules:

| Signal | Recommended Agent | Confidence |
|--------|-------------------|------------|
| APIs present | Backend Dev | 0.9 |
| Frontend frameworks detected | Frontend Dev | 0.85 |
| Database configured | Backend Dev (boost) | 0.8 |
| No tests detected | Tester | 0.95 |
| Low test coverage (<50%) | Tester | 0.8 |
| CI/CD configured | DevOps | 0.8 |
| High-severity issues | Security Scanner | 0.9 |
| 3+ components or API + frontend | Architect | 0.75 |
| Missing documentation | Technical Writer | 0.7 |
| Any code present | Code Reviewer | 0.7 |

### Phase Generation

Matched archetypes' default phases are deduplicated, sorted by canonical order (`research → requirements → design → analysis → implementation → moderation → review → security → testing → documentation → deployment`), and wired sequentially: each phase's `on_success` points to the next phase, `on_failure` points to itself (retry). The final phase is marked `is_terminal`.

### Response Model

```python
class RecommendationResult(BaseModel):
    agents: list[RecommendedAgent]     # agent + confidence + reason
    phases: list[RecommendedPhase]     # phase + confidence + reason
    team_name_suggestion: str
    team_description_suggestion: str
    source: str                        # "greenfield" | "codebase"
```

### UI Flow

1. User reviews recommendations as cards with checkboxes and confidence badges (green >70%, yellow 40-70%, gray <40%)
2. Can edit any agent (name, description, system prompt) before applying
3. Select all / deselect all for agents and phases independently
4. **Apply Selected** calls `bulkAddAgentsAndPhases()` which:
   - Creates a new team if none loaded
   - Deduplicates IDs (appends `-2`, `-3` suffixes on collision)
   - Adds agents and phases to existing team via `updateTeam()`
