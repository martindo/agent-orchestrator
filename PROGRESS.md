# agent-orchestrator Progress

## Status: Phase 34 Complete — All Platform Features Implemented

Last updated: 2026-03-14

## Completed

- [x] Phase 1: Project Scaffold & Configuration System
  - models.py — 20 Pydantic v2 models (frozen, validated)
  - loader.py — YAML loading, profile management, ConfigurationManager
  - validator.py — Cross-reference, phase graph, LLM provider, status transition validation
  - Profile templates: content-moderation (3 agents, 4 phases), software-dev (8 agents, 9 phases)
  - Tests: 54 tests (test_configuration.py)

- [x] Phase 2: Core Engine
  - engine.py — OrchestrationEngine (start/stop/pause/resume, hot-reload)
  - pipeline_manager.py — Configurable phase graph, skip flags, locking
  - phase_executor.py — Parallel/sequential agent execution within phases
  - agent_pool.py — Concurrency-limited agent pool with scaling
  - agent_executor.py — LLM call with retry policy, prompt building
  - event_bus.py — Async pub/sub with typed events
  - work_queue.py — Priority-ordered async work queue
  - Tests: 33 tests (test_core.py)

- [x] Phase 3: Persistence
  - settings_store.py — Atomic YAML writes, env var fallback for API keys
  - state_store.py — JSON-based runtime state persistence
  - config_history.py — Timestamped config versioning with restore
  - Tests: 13 tests (test_persistence.py)

- [x] Phase 4: Governance Integration
  - governor.py — Non-blocking policy evaluation, delegated authority thresholds
  - review_queue.py — Persistent queue for human review
  - audit_logger.py — Hash-chained append-only JSONL audit trail
  - Tests: 15 tests (test_governance.py)

- [x] Phase 5: Adapters
  - llm_adapter.py — Multi-provider LLM routing with protocol
  - metrics_adapter.py — Execution metrics collection and persistence
  - webhook_adapter.py — Outbound webhook notifications
  - providers/ — OpenAI, Anthropic, Google, Grok, Ollama provider implementations

- [x] Phase 6: REST API
  - app.py — FastAPI application factory
  - routes.py — 9 route groups (health, agents, workflow, workitems, governance, execution, metrics, audit, config)
  - Tests: 16 tests (test_api.py)

- [x] Phase 7: CLI & Examples
  - commands.py — Full CLI (init, validate, profile, start, submit, serve, export, import)
  - Built-in profiles: content-moderation, software-dev

- [x] Phase 8: Agent CRUD Management
  - agent_manager.py — Thread-safe AgentManager with full CRUD (create/list/get/update/delete/import/export)
  - loader.py — Extended with _read_json/_write_json/_read_config_file/_write_config_file
  - EventBus — AGENT_CREATED, AGENT_UPDATED, AGENT_DELETED event types
  - AgentPool — update_definition() and unregister_definition() for runtime updates
  - Engine — register_agent(), update_agent(), unregister_agent() coordinating manager + pool + events
  - REST API — Full CRUD endpoints (GET/POST/PUT/DELETE /agents, /agents/import, /agents/export)
  - CLI — `agent list|get|create|update|delete|import|export` command group
  - Config history — Changes recorded via ConfigHistory for undo capability
  - Profile component export — export agents/workflow/governance/workitems from loaded profile
    - ConfigurationManager: get_profile_component(), export_profile_component(), export_profile_to_directory()
    - REST API: GET /config/profile/export?component=agents|workflow|governance|workitems|all
    - CLI: `profile export --component <name> --format yaml|json --output <path>`
  - Tests: 50 tests (test_agent_manager.py, test_api.py, test_core.py)

- [x] Phase 9: Connector Capability Framework
  - connectors/models.py — 12 Pydantic v2 frozen models (CapabilityType, ConnectorStatus, ConnectorInvocationRequest/Result, ExternalArtifact, ConnectorPermissionPolicy, ConnectorConfig, etc.)
  - connectors/registry.py — Thread-safe ConnectorRegistry (providers + configs), ConnectorProviderProtocol (structural typing)
  - connectors/service.py — ConnectorService (execute, wrap_result_as_artifact, list_available_capabilities, list_providers)
  - connectors/permissions.py — evaluate_permission() — ordered policy evaluation with module/role scoping
  - connectors/audit.py — log_connector_invocation() bridges connectors to platform AuditLogger
  - connectors/__init__.py — Public API exports
  - exceptions.py — ConnectorError added to exception hierarchy
  - core/engine.py — ConnectorRegistry + ConnectorService initialized on start, connector_service property
  - api/routes.py — GET /connectors/capabilities, GET /connectors/providers
  - Tests: 50+ tests (test_connectors.py)

- [x] Phase 10: Connector Executor, Tracing & Enhanced Discovery
  - connectors/trace.py — ConnectorExecutionTrace + ConnectorTraceStore (thread-safe ring buffer, query API)
  - connectors/executor.py — ConnectorExecutor with asyncio timeout, exponential backoff retry, error normalization, cost metric emission, trace recording
  - connectors/models.py — ConnectorRetryPolicy, ConnectorRateLimit; new optional fields on ConnectorProviderDescriptor and ConnectorConfig
  - connectors/registry.py — find_provider_for_operation() with preferred-provider, operation-declaration, and capability fallback selection
  - connectors/service.py — Refactored to use ConnectorExecutor; added get_traces(), get_trace_summary(), get_configs()
  - api/routes.py — GET /connectors/providers/{id}, /connectors/capabilities/{type}/providers, /connectors/configs, /connectors/traces, /connectors/traces/summary
  - Tests: 30 new tests

- [x] Phase 11: Auth Abstraction, Normalized Artifacts, Approval Gating & Cost Metadata
  - connectors/auth.py — AuthType (6 values), ConnectorAuthConfig, ConnectorSessionContext, build_session_context(); credential-reference model (env var names only, never raw credentials)
  - connectors/normalized.py — 7 capability-specific normalized artifact schemas (SearchResultArtifact, DocumentArtifact, MessageArtifact, TicketArtifact, RepositoryArtifact, TelemetryArtifact, IdentityArtifact)
  - connectors/models.py — ConnectorStatus.REQUIRES_APPROVAL; ConnectorCostMetadata; ConnectorPermissionPolicy.requires_approval field
  - connectors/permissions.py — PermissionOutcome enum (ALLOW/DENY/REQUIRES_APPROVAL); PermissionEvaluationResult; evaluate_permission_detailed()
  - connectors/service.py — REQUIRES_APPROVAL outcome handling; get_connector_auth_config()
  - Tests: 49 new tests

- [x] Phase 12: Web Search Connector Providers (Tavily + SerpAPI + Brave)
  - connectors/providers/web_search/_base.py — BaseWebSearchProvider ABC
  - connectors/providers/web_search/tavily.py — TavilySearchProvider (AI-optimized, $0.004/$0.008/search)
  - connectors/providers/web_search/serpapi.py — SerpAPISearchProvider (Google/Bing-backed, $0.005/search)
  - connectors/providers/web_search/brave.py — BraveSearchProvider (independent index, $0.003/search)
  - All three: search(), fetch_page(), extract_content() operations; SearchResultArtifact + DocumentArtifact normalization
  - Tests: 43 tests (test_web_search_providers.py)

- [x] Phase 13: Documents Capability Provider (Confluence)
  - connectors/providers/documents/_base.py — BaseDocumentsProvider ABC
  - connectors/providers/documents/confluence.py — ConfluenceDocumentsProvider: REST API v1 search (CQL), get_document, extract_section; Basic auth and Bearer auth
  - Tests: ~40 tests (test_documents_providers.py)

- [x] Phase 14: Messaging Capability Providers (Slack + Teams + Email)
  - connectors/providers/messaging/_base.py — BaseMessagingProvider ABC
  - connectors/providers/messaging/slack.py — SlackMessagingProvider: chat.postMessage, DM, thread creation
  - connectors/providers/messaging/teams.py — TeamsMessagingProvider: Incoming Webhook (MessageCard schema)
  - connectors/providers/messaging/email.py — EmailMessagingProvider: smtplib STARTTLS in asyncio executor
  - Tests: ~50 tests (test_messaging_providers.py)

- [x] Phase 15: Ticketing Capability Providers (Jira + Linear)
  - connectors/providers/ticketing/_base.py — BaseTicketingProvider ABC
  - connectors/providers/ticketing/jira.py — JiraTicketingProvider: REST API v3, JQL search, ADF format
  - connectors/providers/ticketing/linear.py — LinearTicketingProvider: GraphQL API, priority mapping
  - Tests: 48 tests (test_ticketing_providers.py)

- [x] Phase 16: Repository Capability Providers (GitHub + GitLab)
  - connectors/providers/repository/_base.py — BaseRepositoryProvider ABC
  - connectors/providers/repository/github.py — GitHubRepositoryProvider: GitHub API v3
  - connectors/providers/repository/gitlab.py — GitLabRepositoryProvider: GitLab REST API, self-hosted support
  - Tests: 50 tests (test_repository_providers.py)

- [x] Phase 17: Connector Runtime Governance
  - connectors/governance_service.py — ConnectorGovernanceService: enable/disable connectors, update scoping, add/remove policies, discover(module, role), get_effective_permissions; ConnectorDiscoveryItem, EffectivePermissions frozen dataclasses
  - connectors/service.py — _check_config_access() for enabled flag and module/role scoping
  - core/engine.py — ConnectorGovernanceService initialized eagerly; connector_governance_service property
  - api/routes.py — 8 governance endpoints (CRUD configs, enable/disable, scoping, policies, discovery, permissions)
  - Tests: 44 tests (test_connector_governance.py)

- [x] Phase 18: Automatic Provider Discovery & Plugin Architecture
  - connectors/discovery.py — ConnectorProviderDiscovery: builtin package scan, external directories, entry points; DiscoveryResult, ProviderLoadError, LazyConnectorProvider, make_lazy_provider()
  - All 11 builtin providers — from_env() classmethod: reads env vars, returns None if credentials missing, instance if configured
  - connectors/models.py — configuration_schema field on ConnectorProviderDescriptor
  - core/engine.py — discover_builtin_providers() in _initialize_components; connector_discovery property; rediscover_providers()
  - api/routes.py — GET /connectors/discovery/status, POST /connectors/discovery/refresh
  - Tests: 56 tests (test_provider_discovery.py)

- [x] Phase 19: Contract Framework
  - contracts/models.py — 10 Pydantic v2 frozen models: CapabilityContract, ArtifactContract, ArtifactValidationRule, ContractViolation, ContractValidationResult, ContractTimeoutPolicy, ContractRetryPolicy; enums for ReadWriteClassification, AuditRequirement, FailureSemantic, ContractViolationSeverity, LifecycleState
  - contracts/registry.py — Thread-safe ContractRegistry: register/get/find/list/unregister for CapabilityContract and ArtifactContract
  - contracts/validator.py — ContractValidator: validate_capability_input(), validate_capability_output(), validate_artifact(); JSON Schema fragment validation; 6 ArtifactValidationRule types; optional AuditLogger integration
  - connectors/service.py — _validate_input_contract() integrated before provider lookup
  - Tests: 59 tests (test_contracts.py)

- [x] Phase 20: Connector Execute Endpoint (platform-side complete)
  - api/routes.py — ConnectorExecuteRequest model + POST /api/v1/connectors/execute route; resolves CapabilityType, delegates to ConnectorService.execute(), returns serialized ConnectorInvocationResult
  - Tests: 10 tests in test_api.py (success, permission_denied, unavailable, unknown capability, no engine, cost_info, all capability types)
  - Note: OrchestratorClient and search layer migration are external-project scope

- [x] Phase 21: Enterprise Runtime Foundation
  - configuration/models.py — DeploymentMode enum (lite/standard/enterprise), ExecutionContext frozen model (app_id, run_id, tenant_id, environment, deployment_mode, profile_name, extra), PersistenceBackend.POSTGRESQL
  - core/context.py — create_root_context(), create_run_context(), context_tags() pure helpers
  - core/work_queue.py — WorkItem extended with run_id, app_id
  - core/agent_executor.py — ExecutionResult extended with run_id; execute()/execute_once() gain context param
  - core/phase_executor.py — execute_phase() and helpers gain context param
  - core/pipeline_manager.py — PipelineEntry extended with run_id, app_id
  - core/event_bus.py — Event extended with app_id, run_id
  - governance/audit_logger.py — AuditRecord extended with app_id, run_id; query gains app_id/run_id params
  - core/engine.py — Root context in start(); run context forked in submit_work() with UUID run_id; context propagated to events, audit records, metrics
  - api/routes.py — GET /api/v1/context endpoint; WorkItemRequest/Response gain app_id/run_id
  - __init__.py — ExecutionContext, DeploymentMode exported
  - Tests: 28 tests (test_execution_context.py)

- [x] Phase 22: MCP Integration (Model Context Protocol)
  - mcp/models.py — 9 Pydantic v2 frozen models: MCPTransportType, MCPServerConfig, MCPClientConfig, MCPServerHostConfig, MCPProfileConfig, MCPToolInfo, MCPResourceInfo, MCPPromptInfo, MCPSessionInfo
  - mcp/exceptions.py — MCPError hierarchy: MCPConnectionError, MCPToolCallError, MCPResourceError, MCPConfigurationError
  - mcp/client_manager.py — MCPClientManager: session lifecycle (stdio/streamable_http/sse), tool/resource/prompt discovery, call_tool/read_resource/get_prompt
  - mcp/bridge.py — MCPToolConnectorProvider (wraps MCP tool as ConnectorProviderProtocol), MCPConnectorBridge (discovery to registration)
  - mcp/client_prompts.py — MCPPromptResolver for agent prompt building
  - mcp/server.py — create_mcp_server() + create_mcp_asgi_app() via FastMCP + Streamable HTTP
  - mcp/server_tools.py — Dynamic tool generation from ConnectorRegistry + static orchestration tools
  - mcp/server_resources.py — 7 resources (status, workitems, audit, config/agents, config/workflow, config/governance, connectors)
  - mcp/server_prompts.py — One MCP prompt per AgentDefinition
  - mcp/server_governance.py — GovernedToolDispatcher: Governor.evaluate() + ConnectorService.execute() + AuditLogger.append()
  - mcp/server_session.py — MCPSessionRegistry with TTL eviction and max session limits
  - pyproject.toml — `mcp = ["mcp>=1.0"]` optional dependency
  - configuration/loader.py — _load_mcp_config() for mcp.yaml
  - core/engine.py — _initialize_mcp() in start(), disconnect in stop()
  - cli/commands.py — --mcp flag on serve command
  - Tests: 71 tests (test_mcp_models, test_mcp_client_manager, test_mcp_bridge, test_mcp_server, test_mcp_server_governance)

- [x] Phase 23: Knowledge System, Gap Detection & Agent Synthesis
  - knowledge/models.py — MemoryType enum, MemoryRecord and MemoryQuery dataclasses
  - knowledge/store.py — KnowledgeStore with JSONL index + content-addressed JSON files, SHA-256 dedup, thread-safe
  - knowledge/extractor.py — MemoryExtractor for explicit agent memories and auto-extraction on completion
  - api/knowledge_routes.py — 6 REST endpoints (query, store, get, delete, supersede, stats)
  - Engine integration: KnowledgeStore init, knowledge injection into phase context, AGENT_COMPLETED/WORK_COMPLETED event handlers
  - agent_executor.py — _format_knowledge() helper, knowledge section in _build_user_prompt()
  - event_bus.py — MEMORY_STORED, MEMORY_RETRIEVED, GAP_DETECTED event types
  - exceptions.py — KnowledgeError
  - configuration/models.py — WorkflowPhaseConfig extended with required_capabilities and expected_output_fields
  - configuration/validator.py — validate_capability_coverage() pass: explicit skill check, output-field vs gate mismatch, empty-phase warning
  - core/gap_detector.py — CapabilityGap frozen dataclass, GapSource (10 values), GapSeverity (3 values), SignalWindow, GapDetectionThresholds, GapSignalCollector (EventBus subscriber, sliding-window counters), GapAnalyzer (threshold analysis)
  - core/agent_synthesizer.py — SynthesisProposal frozen model, AgentSynthesizer (LLM-powered propose() + fallback template synthesis, proposal lifecycle: pending/approved/rejected/deployed)
  - core/engine.py — GapSignalCollector, GapAnalyzer, AgentSynthesizer initialized in start(); static gap detection at startup and on reload; runtime analysis after WORK_PHASE_EXITED
  - api/routes.py — 7 endpoints: GET /gaps, /gaps/summary, /gaps/{id}, POST /synthesis/propose, GET /synthesis/proposals, POST /synthesis/proposals/{id}/approve, /synthesis/proposals/{id}/reject
  - Tests: 67 tests (test_knowledge_store.py, test_memory_extractor.py, test_engine_knowledge.py, test_capability_validation.py, test_gap_detector.py, test_agent_synthesizer.py)

- [x] Phase 24: Capability / Team Registry
  - catalog/models.py — InvocationMode, SecurityClassification, MemoryUsagePolicy enums + CapabilityRegistration frozen model
  - catalog/registry.py — TeamRegistry with thread-safe register/get/find/list_all/unregister/summary
  - catalog/auto_register.py — build_registration_from_profile() deriving schema from custom_fields + expected_output_fields
  - api/catalog_routes.py — 7 REST endpoints (list, get, register, update, delete, summary, invoke)
  - Engine integration: _team_registry field, auto-registration in _initialize_components, team_registry property
  - event_bus.py — CAPABILITY_REGISTERED, CAPABILITY_INVOKED event types
  - exceptions.py — CatalogError
  - Tests: 49 tests (test_team_registry.py, test_auto_register.py, test_catalog_routes.py)

- [x] Phase 25: Cryptographic Decision Ledger
  - governance/decision_ledger.py — DecisionType/DecisionOutcome enums, frozen DecisionRecord dataclass, DecisionLedger with SHA-256 hash chaining (previous_hash + record_hash), JSONL persistence, verify_chain(), query by work_item/agent/type/outcome/phase/run, get_decision_chain, get_agent_decisions, summary
  - api/ledger_routes.py — 5 REST endpoints (query, chain/{work_item_id}, agent/{agent_id}, verify, summary)
  - Engine integration: _decision_ledger field, _initialize_decision_ledger
  - event_bus.py — DECISION_RECORDED event type
  - exceptions.py — LedgerError, SimulationError
  - Tests: 28 tests (test_decision_ledger.py, test_ledger_routes.py)

- [x] Phase 26: Organizational Skill Map
  - catalog/skill_models.py — SkillMaturity enum, SkillMetrics (success_rate, confidence, maturity derivation), SkillRecord (agents, phases, knowledge_sources, per-agent metrics), SkillCoverage
  - catalog/skill_map.py — SkillMap: thread-safe CRUD, find with filters, record_execution, auto_register_from_profile, get_coverage (strong/weak/unassigned), get_agent_profile, JSONL persistence
  - api/skillmap_routes.py — 8 REST endpoints (list, get, register, delete, record, coverage/report, agent profile, summary)
  - Engine integration: _skill_map field, _initialize_skill_map with auto-registration from profile agents/skills
  - event_bus.py — SKILL_UPDATED event type
  - Tests: 30 tests (test_skill_map.py, test_skillmap_routes.py)

- [x] Phase 27: Agent Simulation / Sandbox
  - simulation/__init__.py — Package exports
  - simulation/models.py — SimulationConfig, SimulationResult, ComparisonResult, SimulationOutcome, SimulationStatus
  - simulation/sandbox.py — SimulationSandbox: replay historical work items against new workflows, outcome classification (same/improved/regressed/new_success/new_failure), dry-run mode
  - api/simulation_routes.py — 5 REST endpoints (list, get, run, cancel, summary)
  - Engine integration: _simulation_sandbox field
  - event_bus.py — SIMULATION_COMPLETED event type
  - Tests: 19 tests (test_simulation.py, test_simulation_routes.py)

- [x] Phase 28: Output Parsing, Quality Gates & Work-Item Factory
  - core/output_parser.py — extract_confidence() with fallback, extract_structured_fields() for required field validation, aggregate_confidence() for multi-agent score aggregation
  - core/quality_gate.py — evaluate_quality_gate() against execution context, evaluate_phase_quality_gates() for batch evaluation; leverages Governor condition evaluation
  - core/work_item_factory.py — create_work_item() factory with field type validation (TEXT/STRING/INTEGER/FLOAT/BOOLEAN/ENUM), strict vs lenient mode, default value injection
  - Engine integration: output_parser called in _process_work_item(); quality_gate called in phase_executor
  - Tests: tests in test_output_parser.py, test_quality_gate.py, test_work_item_factory.py

- [x] Phase 29: SLA Monitoring & Work-Item Persistence
  - core/sla_monitor.py — SLAMonitor: background async task monitoring work item deadlines; emits SLA_WARNING (80% elapsed), SLA_BREACH (past deadline), SLA_ESCALATION events; priority boost on breach; deduplication
  - event_bus.py — SLA_WARNING, SLA_BREACH, SLA_ESCALATION event types
  - persistence/work_item_store.py — WorkItemStore: JSONL-backed persistence with upsert semantics; query by status/type_id/app_id/run_id; get_incomplete() for crash recovery; summary()
  - persistence/artifact_store.py — ArtifactStore: content-addressable file-based storage (SHA-256 hashing); JSONL index + individual content files; deduplication; query by work_id/phase_id/agent_id/artifact_type
  - Engine integration: SLAMonitor started/stopped with lifecycle; WorkItemStore and ArtifactStore initialized in _initialize_components
  - Tests: 17 tests (test_sla_monitor.py) + 18 tests (test_work_item_store.py) + tests in test_artifact_store.py

- [x] Phase 30: Work-Item Lineage Tracing
  - persistence/lineage.py — LineageBuilder: unified chronological timeline across 4 data sources (WorkItem history, DecisionLedger, ArtifactStore, AuditLogger); LineageEvent and WorkItemLineage dataclasses; decision chain integrity verification; graceful degradation
  - api/lineage_routes.py — 3 REST endpoints (full lineage, decision chain, artifacts)
  - Engine integration: constructed on-demand from engine stores
  - Tests: 13 tests (test_lineage_routes.py)

- [x] Phase 31: Benchmark Suites & Regression Testing
  - simulation/benchmark.py — BenchmarkStore (JSONL persistence for suites and run results), BenchmarkRunner (execute suites, compare actual vs expected outcomes)
  - simulation/models.py — BenchmarkCase, BenchmarkSuiteConfig, BenchmarkCaseResult, BenchmarkRunResult dataclasses
  - api/benchmark_routes.py — 8 REST endpoints (list/create/get/delete suites, run suite, create from history, list/get runs)
  - Engine integration: benchmark_store and benchmark_runner properties
  - Tests: 20 tests (test_benchmark_routes.py)

- [x] Phase 32: Audit Gap Fixes
  - governance/review_queue.py — JSONL persistence for review items (no more in-memory-only loss)
  - governance/governor.py — Safe policy evaluation (no eval/exec of arbitrary expressions)
  - governance/audit_logger.py — Log rotation support; audit file size management
  - adapters/webhook_adapter.py — Full webhook delivery implementation (httpx-based POST with retries)
  - core/phase_executor.py — Phase timeout enforcement via asyncio.wait_for
  - core/agent_executor.py — Multi-dimensional scoring (beyond single confidence float)
  - governance/review_queue.py — Review SLA tracking (deadline, escalation)
  - persistence/ — Score history persistence for trend analysis
  - core/work_queue.py — WorkItemHistoryEntry for lifecycle state tracking
  - Tests: tests in test_engine_governance.py, test_critic_agent.py, test_work_queue.py

- [x] Phase 33: Memory Improvements
  - knowledge/embedding.py — EmbeddingService: OpenAI-compatible embedding API client; cosine_similarity() for vector comparison
  - knowledge/context_memory.py — ContextMemory: per-work-item conversation history tracking; stores CONVERSATION memory records in KnowledgeStore
  - knowledge/store.py — Enhanced relevance scoring in retrieve(); semantic query support; memory expiry cleanup (cleanup_expired)
  - knowledge/models.py — CONVERSATION MemoryType added
  - Tests: tests in test_knowledge_improvements.py (embedding, context memory, relevance scoring, expiry cleanup, semantic query)

- [x] Phase 34: Eval System (LLM-as-Judge, Rubrics, A/B Testing, Datasets)
  - simulation/evaluator.py — LLM-as-judge evaluator: EvalDimension, EvalRubric, EvalResult dataclasses; configurable rubric-based scoring (0.0-1.0 per dimension with reasoning); fallback scoring on LLM failure
  - simulation/rubric_store.py — RubricStore: JSONL persistence for EvalRubric instances; built-in rubric templates (DEFAULT_QUALITY_RUBRIC and others)
  - simulation/ab_test.py — ABTestConfig, ABTestResult, ABTestHarness: compare two workflow variants head-to-head via SimulationSandbox; per-item and aggregate outcome comparison
  - simulation/dataset.py — EvalDataset dataclass, DatasetStore: JSONL persistence for reusable evaluation datasets; CRUD operations
  - simulation/executor.py — SimulationExecutor: wraps PhaseExecutor for sandbox-compatible execution; creates ephemeral WorkItems from historical data
  - api/eval_routes.py — eval_router: REST endpoints for rubric CRUD, evaluate, A/B tests, dataset management
  - Engine integration: rubric_store, dataset_store, evaluator properties
  - Tests: tests in test_eval_system.py (evaluator, rubric store, A/B tests, datasets, routes)

## Studio (All 14 Phases + Settings Page Complete)

- [x] P1: Studio Scaffold — pyproject.toml, app.py, config.py, cli.py, exceptions.py, CORS config
- [x] P2: IR Models — 17 Pydantic models in studio/ir/models.py covering all runtime types
- [x] P3: Schema Extraction — schemas/extractor.py: extract_all_schemas(), extract_component_schema()
- [x] P4: YAML Generation — generation/generator.py: generate all YAML files matching runtime loader
- [x] P5: Runtime Validation — validation/validator.py: 4 validation passes + runtime integration
- [x] P6: Connector Discovery — connectors/discovery.py: query runtime /connectors/providers
- [x] P7: Condition Expressions — conditions/builder.py: build, parse, validate expressions
- [x] P8: Workflow Graph Validation — graph/validator.py: DAG analysis, orphan detection, reachability
- [x] P9: Deploy Profiles — deploy/deployer.py: write files + trigger runtime reload
- [x] P10: Extension Stubs — extensions/generator.py: connector, event handler, hook stubs
- [x] P11: Prompt Packs — prompts/generator.py: 5 prompt types for coding assistants
- [x] P12: V1 Frontend — React 18 + TypeScript + Tailwind: 8 pages (Overview, Agents, Workflow, Governance, WorkItems, Preview, Deploy, Settings), API client, Zustand store, React Flow graph
- [x] P13: Template Import/Export — templates/manager.py: round-trip tested (import, export, reimport)
- [x] P14: Regeneration Boundaries — manifest/tracker.py: .studio-manifest.json ownership tracking
- [x] Settings Page — SettingsPage.tsx + settings_routes.py: LLM API key management (masked display), provider endpoint config, live model fetching from provider APIs; keys stored in memory + optional YAML persistence

**Studio Backend:** 32 Python files (studio/ package) + 13 route files (studio/routes/)
**Studio Frontend:** 13 TypeScript/TSX files (8 pages, API client, store, common components)
**Studio Tests:** 95 tests passing
**Studio Docs:** ARCHITECTURE.md, USER_GUIDE.md, INSTALL.md

## Test Summary

- **Runtime tests:** 1356 passing
- **Studio tests:** 95 passing
- **Total:** 1451 tests

## Known Issues

- (none)

## Architecture Highlights

- Zero hardcoded domain knowledge — all in YAML profiles
- Non-blocking governance — decisions are immediate, reviews queued
- EventBus decoupling — engine emits events, consumers subscribe independently
- Hot-reload — config changes take effect without restart
- Hash-chained audit trail — tamper-evident JSONL ledger
- Per-agent LLM config — each agent specifies its own provider/model
- Profile switching — change active profile to switch entire domain
- MCP integration — expose/consume tools via Model Context Protocol
- Content-addressable artifact storage — SHA-256 dedup
- Cryptographic decision ledger — SHA-256 hash chaining with verification
- LLM-as-judge evaluation — rubric-based scoring with A/B test harness
