# Platform Capability Audit

Comprehensive audit of Agent-Orchestrator's current capabilities, mapped against nine governance and evaluation primitives.

**Audit date:** 2026-03-13
**Codebase state:** 871 tests passing, MCP integration complete, 11 built-in connector providers.

---

## Capability Matrix

| # | Primitive | Status | Maturity |
|---|-----------|--------|----------|
| 1 | Workflow orchestration | **Implemented** | Production-ready |
| 2 | Agent lifecycle management | **Implemented** | Production-ready |
| 3 | Decision logging / decision ledger | **Implemented** | Production-ready |
| 4 | Critic or evaluation loops | **Not implemented** | — |
| 5 | Evidence artifacts / evidence storage | **Partial** | Foundation only |
| 6 | Policy enforcement / approval gates | **Implemented** | Functional with gaps |
| 7 | Memory or knowledge storage | **Not implemented** | — |
| 8 | Scoring or evaluation interfaces | **Partial** | Hard-coded, not extensible |
| 9 | Human approval workflows | **Partial** | Enqueue-only, no resolution |

---

## Detailed Findings

### 1. Workflow Orchestration

**Status:** Implemented — production-ready

**Implementation location:**
- `src/agent_orchestrator/core/pipeline.py` — `PipelineManager`
- `src/agent_orchestrator/core/work_queue.py` — `WorkQueue`
- `src/agent_orchestrator/core/phase_executor.py` — `PhaseExecutor`
- `src/agent_orchestrator/core/engine.py` — `OrchestrationEngine`

**Key classes/modules:**
- `PipelineManager`: DAG-like phase navigation with `on_success`/`on_failure` routing, phase skipping, thread-safe locking, phase history tracking
- `WorkQueue`: Priority queue (heapq) with O(log n) insert, deduplication, position lookup, requeue support
- `PhaseExecutor`: Parallel or sequential agent execution within a phase, configurable via `parallel_execution` flag
- `OrchestrationEngine`: Top-level coordinator — start/stop/pause/resume lifecycle, work item submission, processing loop

**Current limitations:**
- Phase transitions are binary (success/failure) — no conditional branching based on output content
- No built-in support for loops or cycles in the phase graph (DAG only, no re-entry)
- No phase-level timeout enforcement (agent-level retries exist but phase wallclock is unbounded)
- Phase execution result is pass/fail based on whether agents completed without exception — no quality assessment of agent output

---

### 2. Agent Lifecycle Management

**Status:** Implemented — production-ready

**Implementation location:**
- `src/agent_orchestrator/core/agent_pool.py` — `AgentPool`
- `src/agent_orchestrator/core/agent_executor.py` — `AgentExecutor`
- `src/agent_orchestrator/configuration/agent_manager.py` — `AgentManager`
- `src/agent_orchestrator/adapters/llm_adapter.py` — `LLMAdapter`

**Key classes/modules:**
- `AgentPool`: Concurrency-controlled agent execution with semaphore per agent, dynamic scaling at runtime (`scale_agent()`), creation/deletion of agents
- `AgentExecutor`: LLM call with retry + exponential backoff, injected `llm_call_fn` for testability
- `AgentManager`: CRUD operations persisted to disk (YAML/JSON), runtime agent definition management
- `LLMAdapter`: Multi-provider routing (OpenAI, Anthropic, Google, Grok, Ollama), auto-registration based on available API keys/SDKs

**Current limitations:**
- No agent health monitoring or heartbeat mechanism
- No agent versioning — replacing an agent definition is destructive
- Concurrency scaling is per-agent, not per-phase or per-workflow
- No warm-up or readiness probes for agents before accepting work

---

### 3. Decision Logging / Decision Ledger

**Status:** Implemented — production-ready

**Implementation location:**
- `src/agent_orchestrator/governance/audit_logger.py` — `AuditLogger`, `RecordType`
- `src/agent_orchestrator/governance/governor.py` — `Governor` (emits decisions)
- `src/agent_orchestrator/connectors/governance_service.py` — `ConnectorGovernanceService`

**Key classes/modules:**
- `AuditLogger`: Append-only JSONL file with SHA-256 hash chaining (16-char truncated). Each record contains: `record_id`, `timestamp`, `record_type`, `work_item_id`, `agent_id`, `phase_id`, `data`, `previous_hash`, `record_hash`, optional `app_id`/`run_id`
- `RecordType` enum: `GOVERNANCE_DECISION`, `PHASE_TRANSITION`, `AGENT_ACTION`, `SYSTEM_EVENT`, `WORK_ITEM_CHANGE`, `CONNECTOR_INVOCATION`, `MCP_INVOCATION`
- Hash chain provides tamper-evidence — each record's hash includes the previous record's hash

**Current limitations:**
- File-based only (JSONL) — no database-backed audit storage
- No audit log rotation or archival
- No cryptographic signing (hash chain detects tampering but doesn't prove authorship)
- Query capabilities are limited to sequential scan of JSONL file
- No export format (e.g., no CSV, no integration with SIEM systems)

---

### 4. Critic or Evaluation Loops

**Status:** Not implemented

**Implementation location:** N/A

**Key classes/modules:** None exist.

**What's missing:**
- No mechanism for an agent to evaluate another agent's output
- `PhaseExecutor` determines phase success by whether agents completed without raising exceptions — it does not inspect output quality
- No feedback loop where a critic agent can reject output and trigger re-execution
- No configurable quality gates between phases
- No output schema validation against expected structure (contracts exist for connectors but not for agent LLM output)

**Closest existing mechanism:** The `Governor.evaluate()` method receives a confidence score, but this score is hard-coded to `0.5` in all engine call sites (`engine.py:_process_work_item`). There is no actual confidence extraction from agent output.

---

### 5. Evidence Artifacts / Evidence Storage

**Status:** Partial — foundation exists but no dedicated evidence system

**Implementation location:**
- `src/agent_orchestrator/governance/audit_logger.py` — stores decision records (not artifacts)
- `src/agent_orchestrator/connectors/trace_store.py` — `TraceStore`
- `src/agent_orchestrator/persistence/state_store.py` — `StateStore`

**Key classes/modules:**
- `TraceStore`: In-memory ring buffer (1000 entries) storing connector invocation traces. Not persisted across restarts.
- `StateStore`: File-based persistence of engine state (running/paused/stopped, queue contents). Not designed for artifact storage.
- Work item `data` field: arbitrary dict that carries input/output through the pipeline — functions as ad-hoc evidence but has no schema, versioning, or retrieval API

**Current limitations:**
- No dedicated artifact store (binary blobs, documents, screenshots)
- No evidence linking (associating multiple artifacts with a single decision)
- No versioned evidence chain (artifact at intake vs. after evaluation vs. after fraud check)
- TraceStore is volatile — lost on restart, capped at 1000 entries
- No content-addressable storage for deduplication
- Agent LLM responses are not stored as artifacts — they flow through the pipeline and are lost after processing

---

### 6. Policy Enforcement / Approval Gates

**Status:** Implemented — functional with gaps

**Implementation location:**
- `src/agent_orchestrator/governance/governor.py` — `Governor`
- `src/agent_orchestrator/governance/review_queue.py` — `ReviewQueue`
- `src/agent_orchestrator/connectors/governance_service.py` — `ConnectorGovernanceService`
- `src/agent_orchestrator/mcp/server_governance.py` — `GovernedToolDispatcher`

**Key classes/modules:**
- `Governor`: Two-tier evaluation: (1) policy matching — conditions parsed and evaluated with sandboxed `eval()`, first-match-wins by priority; (2) delegated authority — confidence-based thresholds (`auto_approve_threshold` > `review_threshold` > `abort_threshold`)
- `GovernanceResolution` enum: `ALLOW`, `ALLOW_WITH_WARNING`, `QUEUE_FOR_REVIEW`, `ABORT`
- `ConnectorGovernanceService`: Permission policies for connector operations (ALLOW/DENY/REQUIRES_APPROVAL), scoping by capability type and provider, write-operation default gating
- `GovernedToolDispatcher` (MCP): Routes MCP tool calls through Governor before execution

**Current limitations:**
- Policy conditions use `eval()` — sandboxed with restricted builtins but still a potential security surface
- Confidence score is hard-coded to `0.5` in engine calls — Governor's threshold system is never meaningfully exercised
- No policy versioning or policy-as-code workflow
- No temporal policies (e.g., "deny after business hours")
- No per-agent or per-phase policy scoping — policies apply globally
- `QUEUE_FOR_REVIEW` resolution enqueues but the review workflow is incomplete (see #9)

---

### 7. Memory or Knowledge Storage

**Status:** Not implemented

**Implementation location:** N/A

**Key classes/modules:** None exist.

**What's missing:**
- No vector store or embedding-based retrieval
- No conversation memory across work items
- No knowledge base that agents can query
- No RAG (Retrieval-Augmented Generation) pipeline
- No shared context between agents beyond what's in the work item `data` dict
- No long-term learning from past decisions

**Closest existing mechanism:** The `phase_context_hook` extension point allows injecting arbitrary context into phase execution, but this is a caller-provided function — the platform itself stores no knowledge.

---

### 8. Scoring or Evaluation Interfaces

**Status:** Partial — infrastructure exists but scoring is not exercised

**Implementation location:**
- `src/agent_orchestrator/governance/governor.py` — `Governor.evaluate(confidence=...)`
- `src/agent_orchestrator/adapters/metrics.py` — `MetricsCollector`

**Key classes/modules:**
- `Governor.evaluate()`: Accepts a `confidence` float parameter and compares against thresholds. The interface is correct but the caller always passes `0.5`.
- `MetricsCollector`: Collects timing metrics (phase duration, agent duration, queue wait time) to JSONL. No quality or scoring metrics.
- `GovernanceConfig.delegated_authority`: Defines `auto_approve_threshold`, `review_threshold`, `abort_threshold` — the scoring bands exist in config but are not fed real scores.

**Current limitations:**
- No scoring extraction from agent output (no structured output parsing)
- No multi-dimensional scoring (e.g., accuracy + completeness + risk)
- No score aggregation across phases
- No score history or trending
- No evaluation rubrics or scoring templates
- MetricsCollector tracks operational metrics only — no quality metrics

---

### 9. Human Approval Workflows

**Status:** Partial — enqueue-only, no resolution workflow

**Implementation location:**
- `src/agent_orchestrator/governance/review_queue.py` — `ReviewQueue`
- `src/agent_orchestrator/api/routes/` — governance review endpoints

**Key classes/modules:**
- `ReviewQueue`: In-memory queue with `enqueue(review_item)` and `complete_review(review_id, decision, reviewer)`. Items have: `review_id`, `work_item_id`, `agent_id`, `phase_id`, `reason`, `data`, `status` (pending/completed).
- API endpoints: `GET /api/v1/governance/reviews` (list pending), `GET /api/v1/governance/reviews/{id}` (get one)
- `Governor.evaluate()` returns `QUEUE_FOR_REVIEW` when confidence is between review and abort thresholds

**Current limitations:**
- No `POST /api/v1/governance/reviews/{id}/approve` or `/reject` endpoint — reviews can be listed but not acted upon via API
- `complete_review()` exists in code but is not wired to any API route
- Review queue is in-memory — lost on restart
- No reviewer assignment or routing
- No SLA tracking or escalation on stale reviews
- No notification mechanism (webhook, email, Slack) when review is needed
- Work items that enter `QUEUE_FOR_REVIEW` are effectively stuck — the engine does not poll for review completion

---

## Summary

### What Agent-Orchestrator supports well

1. **Workflow orchestration** is production-ready — DAG-based phase routing with parallel agent execution, priority queuing, and full lifecycle management (start/stop/pause/resume).

2. **Agent lifecycle management** is solid — dynamic creation/deletion, concurrency control with semaphores, runtime scaling, multi-provider LLM routing with retry and backoff.

3. **Decision logging** is strong — hash-chained append-only audit trail with tamper evidence, 7 record types, app_id/run_id filtering for enterprise scoping.

4. **Connector governance** is well-designed — permission evaluation, contract validation, execution with retries/timeouts, and full audit logging form a complete invocation pipeline.

5. **Extensibility** is well-architected — phase context hooks, event bus (29 event types), protocol-based LLM providers, connector plugin discovery, and MCP integration provide clean extension surfaces without modifying core code.

6. **Configuration-driven design** — all domain logic lives in YAML (agents, workflow, governance, work items). The engine is genuinely generic and domain-agnostic.

### What capabilities are missing for evaluation and governance

1. **Critic/evaluation loops** — The most significant gap. There is no mechanism for output quality assessment, no feedback loops, no quality gates between phases. Phase success is binary (exception or not), with no inspection of what agents actually produced.

2. **Real scoring** — The Governor's threshold system is well-designed but starved of input. The engine hard-codes `confidence=0.5` in every call. No scoring extraction from agent output exists. The entire delegated authority model is effectively dormant.

3. **Evidence storage** — Agent outputs flow through the pipeline but are not captured as retrievable artifacts. The TraceStore is volatile and capped. There is no way to reconstruct what an agent saw and produced for a given decision after the fact.

4. **Memory/knowledge** — No shared knowledge base, no RAG, no cross-work-item learning. Agents are stateless across invocations with no mechanism to accumulate expertise.

5. **Human approval completion** — Reviews can be enqueued but not resolved. The `complete_review()` method exists but has no API route. Work items stuck in review have no path forward without manual database intervention.

### What should be built next

**Priority 1 — Unlock the existing governance system:**
- Extract confidence/scoring from agent output (structured output parsing)
- Pass real scores to `Governor.evaluate()` instead of hard-coded `0.5`
- Wire `complete_review()` to API endpoints (`POST /reviews/{id}/approve`, `/reject`)
- Add review completion polling to the engine processing loop

**Priority 2 — Add evaluation loops:**
- Implement a `CriticAgent` pattern — a designated agent that evaluates another agent's output against a rubric
- Add quality gate configuration to phases (min confidence, required fields, output schema)
- Support phase re-execution on critic rejection (bounded retry with backoff)

**Priority 3 — Evidence and artifact storage:**
- Capture agent inputs and outputs as versioned artifacts linked to work item + phase
- Persist TraceStore to disk or database
- Add content-addressable artifact retrieval API

**Priority 4 — Scoring framework:**
- Multi-dimensional scoring model (configurable dimensions per work item type)
- Score aggregation across phases
- Score history and trending in MetricsCollector

**Priority 5 — Memory and knowledge:**
- Agent-scoped memory (persisted key-value or vector store)
- Cross-work-item knowledge accumulation
- RAG integration point in the phase context hook

---

## Appendix: Full Capability Map

| Component | Location | Key Classes | Test Coverage |
|-----------|----------|-------------|---------------|
| Orchestration engine | `core/engine.py` | `OrchestrationEngine` | Yes |
| Work queue | `core/work_queue.py` | `WorkQueue` | Yes |
| Pipeline manager | `core/pipeline.py` | `PipelineManager` | Yes |
| Phase executor | `core/phase_executor.py` | `PhaseExecutor` | Yes |
| Agent pool | `core/agent_pool.py` | `AgentPool` | Yes |
| Agent executor | `core/agent_executor.py` | `AgentExecutor` | Yes |
| Event bus | `core/event_bus.py` | `EventBus`, `EventType` | Yes |
| Governor | `governance/governor.py` | `Governor`, `GovernanceResolution` | Yes |
| Audit logger | `governance/audit_logger.py` | `AuditLogger`, `RecordType` | Yes |
| Review queue | `governance/review_queue.py` | `ReviewQueue` | Yes |
| Connector registry | `connectors/registry.py` | `ConnectorRegistry`, `ConnectorProviderProtocol` | Yes |
| Connector service | `connectors/service.py` | `ConnectorService` | Yes |
| Connector governance | `connectors/governance_service.py` | `ConnectorGovernanceService` | Yes |
| Connector executor | `connectors/executor.py` | `ConnectorExecutor` | Yes |
| Connector discovery | `connectors/discovery.py` | `ConnectorProviderDiscovery` | Yes |
| Contract registry | `contracts/registry.py` | `ContractRegistry` | Yes |
| Contract validator | `contracts/validator.py` | `ContractValidator` | Yes |
| Trace store | `connectors/trace_store.py` | `TraceStore` | Yes |
| Configuration loader | `configuration/loader.py` | `ConfigurationManager` | Yes |
| Configuration models | `configuration/models.py` | `ProfileConfig`, `SettingsConfig` | Yes |
| Agent manager | `configuration/agent_manager.py` | `AgentManager` | Yes |
| LLM adapter | `adapters/llm_adapter.py` | `LLMAdapter`, `LLMProviderProtocol` | Yes |
| Metrics collector | `adapters/metrics.py` | `MetricsCollector` | Yes |
| Webhook adapter | `adapters/webhook_adapter.py` | `WebhookAdapter` | Stub only |
| Settings store | `persistence/settings_store.py` | `SettingsStore` | Yes |
| State store | `persistence/state_store.py` | `StateStore` | Yes |
| Config history | `persistence/config_history.py` | `ConfigHistory` | Yes |
| REST API | `api/app.py`, `api/routes/` | FastAPI app, 66 endpoints | Yes |
| CLI | `cli/commands.py` | Click commands | Yes |
| MCP client | `mcp/client_manager.py` | `MCPClientManager` | Yes |
| MCP bridge | `mcp/bridge.py` | `MCPConnectorBridge`, `MCPToolConnectorProvider` | Yes |
| MCP server | `mcp/server.py` | `create_mcp_server`, `create_mcp_asgi_app` | Yes |
| MCP governance | `mcp/server_governance.py` | `GovernedToolDispatcher` | Yes |
| MCP sessions | `mcp/server_session.py` | `MCPSessionRegistry` | Yes |
