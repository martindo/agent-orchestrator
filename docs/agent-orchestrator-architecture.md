# Agent Orchestrator Architecture

## Overview

Agent Orchestrator is a generic, domain-agnostic platform for orchestrating multi-agent AI workflows. It provides governance, auditing, observability, and contract enforcement without encoding any domain-specific logic.

**Version:** 0.6.0 (Phase 21 — Enterprise Runtime Foundation)
**Stack:** Python 3.11 · FastAPI · Pydantic v2 · PostgreSQL 16 · Docker Compose

---

## Architectural Principles

1. **Domain-agnostic core** — Zero hardcoded domain knowledge. All domain configuration lives in YAML profiles.
2. **Additive extensibility** — Domain modules extend the platform through registered contracts, providers, and plugins without modifying source code.
3. **Non-blocking governance** — Policy evaluation, contract validation, and audit logging never block the hot path.
4. **Single source of truth** — State is owned by one component; other components receive it by reference.
5. **Tamper-evident audit trail** — Hash-chained JSONL append-only log for all governance decisions and contract violations.

---

## Layer Map

```
┌─────────────────────────────────────────────────────────────┐
│  REST API (FastAPI)                                         │
│  routes.py  ·  app.py                                       │
├─────────────────────────────────────────────────────────────┤
│  CLI (Click)                                                │
│  commands.py                                                │
├─────────────────────────────────────────────────────────────┤
│  Core Engine                                                │
│  engine · pipeline · agent_pool · phase_executor · event_bus│
├────────────────────────┬────────────────────────────────────┤
│  Governance            │  Contract Framework (Phase 19)     │
│  governor              │  ContractRegistry                  │
│  audit_logger          │  ContractValidator                 │
│  review_queue          │  CapabilityContract                │
│                        │  ArtifactContract                  │
├────────────────────────┴────────────────────────────────────┤
│  Connector Framework                                        │
│  ConnectorService · ConnectorExecutor · ConnectorRegistry   │
│  ConnectorGovernanceService · ConnectorProviderDiscovery    │
│  Providers: web_search · documents · messaging              │
│             ticketing · repository                          │
├─────────────────────────────────────────────────────────────┤
│  Adapters                                                   │
│  LLMAdapter · MetricsCollector · WebhookAdapter             │
├─────────────────────────────────────────────────────────────┤
│  Persistence                                                │
│  SettingsStore · StateStore · ConfigHistory                 │
├─────────────────────────────────────────────────────────────┤
│  Configuration                                              │
│  ConfigurationManager · AgentManager · Validator            │
└─────────────────────────────────────────────────────────────┘
```

---

## Core Engine

**Package:** `agent_orchestrator.core`

| Component | Responsibility |
|---|---|
| `OrchestrationEngine` | Lifecycle controller (start/stop/pause/resume), work submission, context propagation, component wiring |
| `ExecutionContext` | Immutable context (app_id, run_id, tenant_id, deployment_mode) propagated through every operation |
| `PipelineManager` | Phase graph traversal, locking, skip flags |
| `AgentPool` | Concurrency-limited pool of agent executor instances |
| `PhaseExecutor` | Parallel or sequential agent execution within a phase |
| `AgentExecutor` | Single-agent LLM call with retry policy and prompt building |
| `WorkQueue` | Priority-ordered async work queue |
| `EventBus` | Async pub/sub with typed events (`AGENT_CREATED`, `WORK_SUBMITTED`, etc.) |

Work flows: `submit_work` → `create_run_context` → `WorkQueue` → `_processing_loop` → `PipelineManager` → `PhaseExecutor(context)` → `AgentPool` → `AgentExecutor` → LLM → result. Context (app_id, run_id) is propagated to all events, audit records, and metrics.

---

## Configuration System

**Package:** `agent_orchestrator.configuration`

Profiles are YAML directories loaded by `ConfigurationManager`. Each profile contains:

- `workflow.yaml` — phase graph definition
- `agents.yaml` — agent definitions with LLM config
- `governance.yaml` — policy definitions
- `settings.yaml` — provider API keys and endpoints

Profiles are hot-reloaded without engine restart. `AgentManager` provides full CRUD for agents with JSON persistence and config history.

---

## Governance

**Package:** `agent_orchestrator.governance`

| Component | Responsibility |
|---|---|
| `Governor` | Non-blocking policy evaluation against `PolicyConfig` rules |
| `AuditLogger` | Hash-chained append-only JSONL audit trail with tamper detection |
| `ReviewQueue` | Persistent human review queue for escalated decisions |

All audit records include: `sequence`, `record_type`, `action`, `summary`, `work_id`, `app_id`, `run_id`, `timestamp`, `hash`, `prev_hash`.

---

## Contract Framework (Phase 19)

**Package:** `agent_orchestrator.contracts`

The contract framework provides explicit interfaces for capability operations and workflow artifacts. It is a governance layer that sits above the connector framework and below domain modules.

### Components

| Component | Responsibility |
|---|---|
| `CapabilityContract` | Defines input/output schema, permissions, and failure semantics for a connector operation |
| `ArtifactContract` | Defines required fields, validation rules, provenance, and lifecycle states for artifacts |
| `ContractRegistry` | Thread-safe in-process registry for capability and artifact contracts |
| `ContractValidator` | Validates payloads against registered contracts; logs violations to audit trail |

### Registration Model

```
Domain Module Startup
        │
        ▼
ContractRegistry.register_capability_contract(...)
ContractRegistry.register_artifact_contract(...)
        │
        ▼
ContractValidator queries registry on each invocation
```

### Validation Flow

```
ConnectorService.execute()
        │
        ├── validate_capability_input(capability_type, operation, params)
        │       │
        │       ├── ContractRegistry.find_capability_contracts(...)
        │       │       → None if no contract → pass-through
        │       │
        │       └── ContractValidator._validate_schema(params, input_schema)
        │               → ContractValidationResult(is_valid, violations)
        │               → AuditLogger.append(contract_violation) if violations
        │
        ├── ConnectorExecutor.execute(provider, request)
        │
        └── validate_capability_output(capability_type, operation, payload)
                │
                └── ContractValidator._validate_schema(payload, output_schema)
```

### Domain Extension Boundary

The platform provides:
- `ContractRegistry` (storage)
- `ContractValidator` (validation machinery)
- `CapabilityContract` / `ArtifactContract` models (schema)
- REST endpoints for contract management

Domain modules provide:
- Contract definitions (registered at startup)
- Domain-specific `rule_type` extensions (via subclassing `ContractValidator`)

**The platform never includes domain-specific contract content.**

---

## Connector Framework

**Package:** `agent_orchestrator.connectors`

| Component | Responsibility |
|---|---|
| `ConnectorRegistry` | Thread-safe provider + config store |
| `ConnectorService` | Primary invocation abstraction (permission check → provider → audit) |
| `ConnectorExecutor` | Timeout, exponential backoff, cost metrics |
| `ConnectorGovernanceService` | Enable/disable connectors, scoping, effective permissions |
| `ConnectorProviderDiscovery` | Builtin + directory + entry-point plugin discovery |
| `ConnectorTraceStore` | Ring-buffer execution trace store |

Built-in capability types: `search`, `documents`, `messaging`, `ticketing`, `repository`, `telemetry`, `identity`, `external_api`, `file_storage`, `workflow_action`.

Built-in providers (11): Tavily, SerpAPI, Brave, Confluence, Slack, Teams, Email, Jira, Linear, GitHub, GitLab.

---

## Adapters

**Package:** `agent_orchestrator.adapters`

| Component | Responsibility |
|---|---|
| `LLMAdapter` | Multi-provider LLM routing (OpenAI, Anthropic, Google, Grok, Ollama) |
| `MetricsCollector` | JSONL execution metrics persistence |
| `WebhookAdapter` | Outbound webhook notifications on work item events |

---

## Persistence

**Package:** `agent_orchestrator.persistence`

| Component | Responsibility |
|---|---|
| `SettingsStore` | Atomic YAML reads/writes, env-var fallback for API keys |
| `StateStore` | JSON runtime state per work item |
| `ConfigHistory` | Timestamped config versions with restore capability |

---

## REST API

**Package:** `agent_orchestrator.api`

Base path: `/api/v1`

| Route Group | Prefix | Routes |
|---|---|---|
| health | `/health` | GET /health, /health/ready, /health/live |
| agents | `/agents` | Full CRUD, import/export |
| workflow | `/workflow` | Phases list, phase detail |
| workitems | `/workitems` | Submit, list, get, cancel |
| governance | `/governance` | Policy CRUD, review queue |
| execution | `/execution` | Start/stop/pause/resume, status |
| metrics | `/metrics` | Execution metrics |
| audit | `/audit` | Audit trail query |
| config | `/config` | Validate, settings, profiles |
| connectors | `/connectors` | Capabilities, providers, configs, traces, governance, discovery |
| contracts | `/contracts` | Capability contracts, artifact contracts, on-demand validation |

---

## Data Flow: Work Item Lifecycle

```
Client → POST /workitems
           │
           ▼
     OrchestrationEngine.submit_work()
           │
           ▼
     WorkQueue (priority-ordered)
           │
           ▼
     _processing_loop → _process_work_item()
           │
           ├── Governor.evaluate() [non-blocking]
           │
           ▼
     PipelineManager.get_next_phase()
           │
           ▼
     PhaseExecutor.execute_phase()
           │
           ├── AgentPool.get_executor()
           ├── AgentExecutor.execute()
           │       ├── LLMAdapter.complete()
           │       └── ConnectorService.execute() [if agent uses connectors]
           │               ├── ContractValidator.validate_capability_input()
           │               ├── ConnectorExecutor.execute()
           │               └── ContractValidator.validate_capability_output()
           │
           ├── AuditLogger.append() [hash-chained]
           └── EventBus.publish(WORK_COMPLETED)
```

---

## Security Boundaries

- **API keys** are stored in `SettingsStore` with env-var fallback; never logged.
- **Audit trail** is hash-chained to detect tampering.
- **Contract violations** are logged, not silently ignored.
- **Connector permissions** are evaluated per-invocation with deny-by-default scoping.
- **SQL**: all database access uses parameterised queries (future PostgreSQL phase).

---

## Extension Points

| Mechanism | How |
|---|---|
| New LLM provider | Implement `LLMProviderProtocol`, register with `LLMAdapter` |
| New connector provider | Implement `ConnectorProviderProtocol`, register with `ConnectorRegistry` |
| New connector plugin | Place in plugin directory or expose via entry point `agent_orchestrator.connectors` |
| Domain capability contract | Call `ContractRegistry.register_capability_contract()` at startup |
| Domain artifact contract | Call `ContractRegistry.register_artifact_contract()` at startup |
| Custom validation rules | Subclass `ContractValidator` and override `_apply_rule()` |
| New governance policy | Add `PolicyConfig` to `governance.yaml` |

---

## Deployment Profiles

Three deployment modes control platform behavior:

| Mode | Process Model | Storage | External Deps |
|---|---|---|---|
| `lite` | Single process | File / SQLite | None — `pip install` and run |
| `standard` | API + workers | PostgreSQL | PostgreSQL |
| `enterprise` | API + workers + auth | PostgreSQL | PostgreSQL + auth provider |

See [docs/INSTALL.md](INSTALL.md) for installation instructions per mode.

---

## Completed Phases

| Phase | Description | Tests |
|---|---|---|
| 1 | Project scaffold & configuration | 54 |
| 2 | Core engine | 33 |
| 3 | Persistence | 13 |
| 4 | Governance | 15 |
| 5 | Adapters | — |
| 6 | REST API | 16 |
| 7 | CLI & examples | — |
| 8 | Agent CRUD management | 39 |
| 9 | Connector capability framework | 50+ |
| 10 | Executor, tracing, discovery | 56 |
| 11 | Auth, normalized artifacts, cost | — |
| 12 | Web search providers | 43 |
| 13 | Documents (Confluence) | 40 |
| 14 | Messaging (Slack, Teams, Email) | 50 |
| 15 | Ticketing (Jira, Linear) | 48 |
| 16 | Repository (GitHub, GitLab) | 50 |
| 17 | Connector runtime governance | 44 |
| 18 | Automatic provider discovery | 56 |
| 19 | Contract framework | ~60 |
| **21** | **Enterprise Runtime Foundation** | **28** |
