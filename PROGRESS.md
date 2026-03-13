# agent-orchestrator Progress

## Status: Phase 20 In Progress — ai-research refactor (Phase 1 of 4 complete)

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

- [x] Phase 6: REST API
  - app.py — FastAPI application factory
  - routes.py — 9 route groups (health, agents, workflow, workitems, governance, execution, metrics, audit, config)
  - Tests: 16 tests (test_api.py)

- [x] Phase 7: CLI & Examples
  - commands.py — Full CLI (init, validate, profile, start, submit, serve, export, import)
  - Built-in profiles: content-moderation, software-dev

- [x] Phase 8: Agent CRUD Management
  - agent_manager.py — Thread-safe AgentManager with full CRUD (create/list/get/update/delete/import/export)
  - JSON support — loader.py extended with _read_json/_write_json/_read_config_file/_write_config_file
  - EventBus — AGENT_CREATED, AGENT_UPDATED, AGENT_DELETED event types
  - AgentPool — update_definition() and unregister_definition() for runtime updates
  - Engine — register_agent(), update_agent(), unregister_agent() coordinating manager + pool + events
  - REST API — Full CRUD endpoints (GET/POST/PUT/DELETE /agents, /agents/import, /agents/export)
  - CLI — `agent list|get|create|update|delete|import|export` command group
  - Config history — Changes recorded via ConfigHistory for undo capability
  - Tests: 39 new tests (test_agent_manager.py, test_api.py, test_core.py)
  - Profile component export — export agents/workflow/governance/workitems from loaded profile
    - ConfigurationManager: get_profile_component(), export_profile_component(), export_profile_to_directory()
    - REST API: GET /config/profile/export?component=agents|workflow|governance|workitems|all
    - CLI: `profile export --component <name> --format yaml|json --output <path>`
    - Round-trip tested: exported agents can be re-imported via AgentManager
    - Tests: 11 new tests (TestProfileComponentExport)

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
  - api/app.py — connectors_router registered
  - docs/connector-architecture.md — Full architecture reference
  - Tests: 50+ tests (test_connectors.py) covering models, registry, service, permissions, audit, no-domain-field invariant

- [x] Phase 10: Connector Capability Framework — Executor, Tracing, and Enhanced Discovery
  - connectors/trace.py — ConnectorExecutionTrace + ConnectorTraceStore (thread-safe ring buffer, query API)
  - connectors/executor.py — ConnectorExecutor with asyncio timeout, exponential backoff retry, error normalization, cost metric emission, trace recording
  - connectors/models.py — ConnectorRetryPolicy, ConnectorRateLimit; new optional fields on ConnectorProviderDescriptor (version, auth_required, parameter_schemas, result_schema_hint) and ConnectorConfig (retry_policy, rate_limit, version)
  - connectors/registry.py — find_provider_for_operation() with preferred-provider, operation-declaration, and capability fallback selection
  - connectors/service.py — Refactored to use ConnectorExecutor; added get_traces(), get_trace_summary(), get_configs(); retry policy read from ConnectorConfig
  - connectors/__init__.py — Exports for ConnectorRetryPolicy, ConnectorRateLimit, ConnectorExecutionTrace, ConnectorTraceStore, ConnectorExecutor, ConnectorExecutorError
  - core/engine.py — ConnectorService initialized with metrics collector
  - api/routes.py — Added GET /connectors/providers/{id}, /connectors/capabilities/{type}/providers, /connectors/configs, /connectors/traces, /connectors/traces/summary
  - docs/connector-framework.md — Comprehensive capability model, invocation flow, artifact envelope, cost tracking, retry config, tracing, and provider extension guide
  - docs/connector-architecture.md — Added ConnectorExecutor, ConnectorTraceStore, provider selection, and extension boundary sections
  - Tests: 30 new tests (total ~336+)

- [x] Phase 11: Connector Capability Framework — Auth Abstraction, Normalized Artifacts, Approval Gating, and Cost Metadata
  - connectors/auth.py — AuthType (6 values), ConnectorAuthConfig, ConnectorSessionContext, build_session_context(); credential-reference model (env var names only, never raw credentials); to_log_summary() for safe logging
  - connectors/normalized.py — 7 capability-specific normalized artifact schemas (SearchResultArtifact, DocumentArtifact, MessageArtifact, TicketArtifact, RepositoryArtifact, TelemetryArtifact, IdentityArtifact); NormalizedArtifactBase; get_normalized_type(); try_normalize() (best-effort, never raises)
  - connectors/models.py — ConnectorStatus.REQUIRES_APPROVAL; ConnectorCostMetadata (billing_label, cost_center, unit_price, currency, notes); ConnectorPermissionPolicy.requires_approval field; ConnectorProviderDescriptor.auth_type field (str, avoids circular import); ConnectorConfig.auth_config (dict) and cost_metadata fields
  - connectors/permissions.py — PermissionOutcome enum (ALLOW/DENY/REQUIRES_APPROVAL); PermissionEvaluationResult dataclass; evaluate_permission_detailed() with approval-gated write detection; _requires_write_approval() helper; existing evaluate_permission() unchanged
  - connectors/service.py — execute() updated to use evaluate_permission_detailed(); REQUIRES_APPROVAL outcome returns ConnectorStatus.REQUIRES_APPROVAL result; get_connector_auth_config() method added
  - connectors/__init__.py — Exports for all new types: AuthType, ConnectorAuthConfig, ConnectorSessionContext, build_session_context, all normalized artifact classes, get_normalized_type, try_normalize, ConnectorCostMetadata, PermissionOutcome, PermissionEvaluationResult, evaluate_permission_detailed
  - docs/connector-framework.md — Added sections: Authentication Abstraction, Normalized Capability Artifacts, why threat_intel is not in platform taxonomy, Approval-Gated Write Operations, Cost Metadata
  - Tests: 49 new tests (total ~435)

- [x] Phase 12: Web Search Connector Providers (Tavily + SerpAPI + Brave)
  - connectors/providers/web_search/_base.py — BaseWebSearchProvider ABC with execute() dispatch, _fetch_page() via httpx, _normalize_search() → SearchResultArtifact
  - connectors/providers/web_search/tavily.py — TavilySearchProvider (primary, AI-optimized, basic/advanced depth, $0.004/$0.008/search)
  - connectors/providers/web_search/serpapi.py — SerpAPISearchProvider (secondary, Google/Bing-backed via SerpAPI, $0.005/search)
  - connectors/providers/web_search/brave.py — BraveSearchProvider (tertiary, independent index, privacy-preserving, $0.003/search)
  - All three: search(), fetch_page(), extract_content() operations; SearchResultArtifact + DocumentArtifact normalization; ConnectorCostInfo populated on every search; ConnectorProviderProtocol structurally satisfied
  - pyproject.toml — httpx moved to core dependencies
  - docs/connectors/web-search.md — Full provider guide with configuration, operations, cost, permissions, module integration
  - Tests: 43 new tests (test_web_search_providers.py) covering descriptor shape, search normalization, cost info, fetch_page, extract_content, unknown op → NOT_FOUND, HTTP errors → FAILURE, empty key validation, protocol structural check

- [x] Phase 13: Documents Capability Provider (Confluence)
  - connectors/providers/documents/_base.py — BaseDocumentsProvider ABC: execute() dispatch for search_documents/get_document/extract_section; _make_document_artifact() static helper producing ExternalArtifact envelope with DocumentArtifact normalized_payload and ExternalReference links; DocumentsProviderError
  - connectors/providers/documents/confluence.py — ConfluenceDocumentsProvider: REST API v1 search (CQL with optional space scoping), get_document (full body.storage expand), extract_section (section extraction from Confluence storage markup via heading/anchor match); Basic auth (Cloud email+token) and Bearer auth (Server PAT); _extract_section_from_storage() pure function
  - connectors/providers/__init__.py — ConfluenceDocumentsProvider added to top-level exports
  - docs/connectors/documents.md — Full provider guide: auth modes, operations, ExternalArtifact output shapes, module integration, adding future providers
  - Tests: ~40 new tests (test_documents_providers.py)

- [x] Phase 14: Messaging Capability Providers (Slack + Teams + Email)
  - connectors/providers/messaging/_base.py — BaseMessagingProvider ABC: execute() dispatch for send_message/notify_user/create_thread (all read_only=False); _make_message_artifact() static helper producing ExternalArtifact envelope with MessageArtifact normalized_payload; MessagingProviderError
  - connectors/providers/messaging/slack.py — SlackMessagingProvider: chat.postMessage, conversations.open for DM, thread creation via initial post; ExternalReference with message ts; Slack ok=False error handling
  - connectors/providers/messaging/teams.py — TeamsMessagingProvider: Incoming Webhook (MessageCard schema); notify_user falls back to @mention in channel; thread via title+text card; "1" response validation
  - connectors/providers/messaging/email.py — EmailMessagingProvider: smtplib STARTTLS in asyncio executor; MIMEMultipart with Message-ID; notify_user treats user_id as email address; create_thread uses title as Subject
  - connectors/providers/__init__.py — SlackMessagingProvider, TeamsMessagingProvider, EmailMessagingProvider added to exports
  - docs/connectors/messaging.md — Full provider guide: write-op approval gating, auth/config per provider, operation param tables, ExternalArtifact output shapes, Teams webhook limitations, module integration
  - Tests: ~50 new tests (test_messaging_providers.py)

- [x] Phase 15: Ticketing Capability Providers (Jira + Linear)
  - connectors/providers/ticketing/_base.py — BaseTicketingProvider ABC: execute() → _dispatch() for create_ticket/update_ticket (read_only=False), get_ticket/search_tickets (read_only=True); _make_ticket_artifact() and _make_ticket_list_artifact() static helpers; TicketingProviderError
  - connectors/providers/ticketing/jira.py — JiraTicketingProvider: Basic auth (email+token) and Bearer (PAT); ADF description format; create/update/get/search via Jira REST API v3; JQL search; _extract_jira_description() for ADF→text
  - connectors/providers/ticketing/linear.py — LinearTicketingProvider: GraphQL API; priority mapping (urgent/high/medium/low/none → 1-4/0); IssueCreate/IssueUpdate/Issue mutations; search via containsIgnoreCase filter
  - connectors/providers/__init__.py — JiraTicketingProvider, LinearTicketingProvider added to exports
  - docs/connectors/ticketing.md — Full provider guide: auth, operations, ExternalArtifact output shapes, write-op approval gating, Linear GraphQL notes
  - Tests: 48 new tests (test_ticketing_providers.py)

- [x] Phase 16: Repository Capability Providers (GitHub + GitLab)
  - connectors/providers/repository/_base.py — BaseRepositoryProvider ABC: all 4 operations read_only=True; _make_repo_artifact(), _make_repo_list_artifact(), _make_file_artifact(), _make_commit_list_artifact(), _make_pr_artifact() static helpers; RepositoryProviderError
  - connectors/providers/repository/github.py — GitHubRepositoryProvider: Bearer token + GitHub API v3; search_repo (Search API), get_file (contents endpoint, base64 decode), list_commits, get_pull_request; _get() centralizes HTTP + 404; directory listing error
  - connectors/providers/repository/gitlab.py — GitLabRepositoryProvider: PRIVATE-TOKEN or Bearer auth; numeric/namespace repo_id encoding; file path URL-encoding; merge request IID for get_pull_request; self-hosted base_url support
  - connectors/providers/__init__.py — GitHubRepositoryProvider, GitLabRepositoryProvider added to exports
  - docs/connectors/repository.md — Full provider guide: auth scopes, operations, ExternalArtifact output shapes, GitLab vs GitHub differences, provider registration
  - Tests: 50 new tests (test_repository_providers.py)

- [x] Phase 17: Connector Runtime Governance
  - connectors/governance_service.py — ConnectorGovernanceService wrapping ConnectorRegistry: enable_connector/disable_connector (frozen model copy + re-register), update_scoping (selective module/role field updates), add_policy/remove_policy (policy list manipulation), discover(module_name, agent_role) (enabled + scope filtering + provider availability), get_effective_permissions (per-operation evaluate_permission_detailed); ConnectorDiscoveryItem and EffectivePermissions frozen dataclasses with as_dict()
  - connectors/service.py — _check_config_access() added: checks enabled flag and module/role scoping before policy evaluation; no configs → allow; all disabled → UNAVAILABLE; no scope match → PERMISSION_DENIED; _collect_policies() now accepts context dict and respects scoping
  - connectors/__init__.py — ConnectorGovernanceService, ConnectorGovernanceError, ConnectorDiscoveryItem, EffectivePermissions exported
  - core/engine.py — ConnectorGovernanceService initialized eagerly alongside registry; connector_governance_service property added
  - api/routes.py — 8 new governance endpoints: POST /connectors/configs, GET /connectors/configs/{id}, POST /connectors/configs/{id}/enable, POST /connectors/configs/{id}/disable, PUT /connectors/configs/{id}/scoping, POST /connectors/configs/{id}/policies, DELETE /connectors/configs/{id}/policies/{policy_id}, GET /connectors/discovery, GET /connectors/configs/{id}/permissions
  - docs/connector-governance.md — Full governance reference: lifecycle, scoping, permission policies, discovery, effective permissions, REST API reference
  - Tests: 44 new tests (test_connector_governance.py): enable/disable, scoping, policy CRUD, discover with module/role context, effective permissions, config-not-found errors, ConnectorService config-level access enforcement

- [x] Phase 21: Enterprise Runtime Foundation — Execution Context, Run Identity & Deployment Profiles
  - configuration/models.py — DeploymentMode enum (lite/standard/enterprise), ExecutionContext frozen model (app_id, run_id, tenant_id, environment, deployment_mode, profile_name, extra), PersistenceBackend extended with POSTGRESQL, SettingsConfig extended with deployment_mode
  - core/context.py — New file: create_root_context(), create_run_context(), context_tags() — pure helpers, no shared state
  - core/work_queue.py — WorkItem extended with run_id="" and app_id="default"
  - core/agent_executor.py — ExecutionResult extended with run_id=""; execute()/execute_once() gain context param
  - core/phase_executor.py — execute_phase(), _execute_parallel(), _execute_sequential(), _execute_single_agent() gain context param
  - core/pipeline_manager.py — PipelineEntry extended with run_id="" and app_id="default"
  - core/event_bus.py — Event frozen dataclass extended with app_id="" and run_id=""
  - governance/audit_logger.py — AuditRecord extended with app_id="" and run_id=""; append() and query() gain app_id/run_id params
  - core/engine.py — Root context created in start(); run context forked in submit_work() with UUID run_id; context propagated to all events, audit records, and metrics tags in _process_work_item()
  - api/routes.py — GET /api/v1/context endpoint; WorkItemRequest gains app_id; WorkItemResponse gains app_id/run_id; ExecutionContextResponse model
  - api/app.py — app.state.execution_context set from engine.context during create_app()
  - __init__.py — ExecutionContext and DeploymentMode added to public exports
  - docs/INSTALL.md — New comprehensive installation guide covering lite, standard, and enterprise deployment modes
  - Tests: 28 new tests (test_execution_context.py) covering models, immutability, context helpers, data structure extensions, audit query filtering, public exports
  - All 800 tests passing, fully backward-compatible (all new fields have safe defaults)

- [~] Phase 20: ai-research Connector Refactor — expose execute endpoint (Phase 1/4 complete)
  - api/routes.py — ConnectorExecuteRequest model + POST /api/v1/connectors/execute route; resolves CapabilityType, delegates to ConnectorService.execute(), returns serialized ConnectorInvocationResult; non-2xx statuses are embedded in result (caller checks status field)
  - tests/unit/test_api.py — 10 new tests: success, all fields passed, permission_denied, unavailable, unknown capability_type (422), no engine (503), no connector service (503), cost_info included, empty context → None, all 5 core capability types accepted
  - Remaining: Phase 2 (OrchestratorClient in ai-research), Phase 3 (replace search layer), Phase 4 (update tests)

- [x] Phase 19: Contract Framework
  - contracts/models.py — 10 Pydantic v2 frozen models and enums: CapabilityContract, ArtifactContract, ArtifactValidationRule, ContractViolation, ContractValidationResult, ContractTimeoutPolicy, ContractRetryPolicy; ReadWriteClassification, AuditRequirement, FailureSemantic, ContractViolationSeverity, LifecycleState
  - contracts/registry.py — Thread-safe ContractRegistry: register/get/find/list/unregister for both CapabilityContract and ArtifactContract; summary() for introspection
  - contracts/validator.py — ContractValidator: validate_capability_input(), validate_capability_output(), validate_artifact(); JSON Schema fragment validation (required fields, type checking); 6 ArtifactValidationRule types (min_length, max_length, allowed_values, type_check, required_if, pattern); provenance checking; optional AuditLogger integration (SYSTEM_EVENT on violations); non-blocking by design
  - contracts/__init__.py — Clean public API with all models, enums, ContractRegistry, ContractValidator exported
  - connectors/service.py — _validate_input_contract() integrated; input validation runs before provider lookup so contract violations are raised before any execution attempt
  - docs/agent-orchestrator-architecture.md — New architecture reference document (v0.5.0) with layer map, component descriptions, and contract framework section
  - Tests: 59 new tests (test_contracts.py) covering all models, registry CRUD, all validator paths including schema validation, artifact rules, provenance, audit logging, and ConnectorService integration

- [x] Phase 18: Automatic Provider Discovery and Plugin Architecture
  - connectors/discovery.py — ConnectorProviderDiscovery: discovers providers from the builtin package (pkgutil.walk_packages), external directories (rglob .py), and entry points (importlib.metadata); DiscoveryResult dataclass (registered/skipped/errors with as_dict()/summary()); ProviderLoadError dataclass; LazyConnectorProvider (defers construction to first execute() call, returns UNAVAILABLE on init failure); make_lazy_provider() helper
  - All 11 builtin providers — from_env() classmethod added: reads env vars, returns None if credentials missing (never raises for missing creds), returns instance if configured; covers TavilySearchProvider, SerpAPISearchProvider, BraveSearchProvider, ConfluenceDocumentsProvider, SlackMessagingProvider, TeamsMessagingProvider, EmailMessagingProvider, JiraTicketingProvider, LinearTicketingProvider, GitHubRepositoryProvider, GitLabRepositoryProvider
  - connectors/models.py — configuration_schema field added to ConnectorProviderDescriptor (dict, default empty)
  - core/engine.py — ConnectorProviderDiscovery initialized eagerly; discover_builtin_providers() called in _initialize_components() after ConnectorService init; connector_discovery property; last_discovery_result property; rediscover_providers(plugin_directory) method
  - connectors/__init__.py — ConnectorProviderDiscovery, DiscoveryResult, ProviderLoadError, LazyConnectorProvider, make_lazy_provider exported
  - api/routes.py — GET /connectors/discovery/status (last discovery result), POST /connectors/discovery/refresh (re-run discovery, optional plugin_directory param)
  - docs/connector-provider-development.md — Full provider development guide: interface, from_env() contract, descriptor fields, operation descriptors, plugin directories, entry points, lazy initialization, error isolation, env var reference table, testing patterns
  - docs/connector-framework.md — Added "Automatic Provider Discovery" section and completed REST API reference table
  - Tests: 56 new tests (test_provider_discovery.py): DiscoveryResult, _looks_like_provider, _instantiate, _try_register_class (all error paths), _scan_module, discover_directory (real file, faulty file, underscore skip), discover_builtin_providers (no crash, env-driven registration, deduplication), discover_entry_points, LazyConnectorProvider (descriptor hint, factory deferral, single call, failure isolation), make_lazy_provider, from_env() on all 11 builtin providers (with/without credentials), configuration_schema field

## Test Summary
- Total: 800 tests
- All passing

## Packages Extracted to coderswarm-packages
- (none yet — all code is domain-specific to agent-orchestrator)

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
