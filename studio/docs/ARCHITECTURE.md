# Agent-Orchestrator Studio — Architecture

## Overview

Studio is a **design-time companion** for Agent-Orchestrator.  It provides a visual interface for creating, editing, validating, and deploying YAML profile configurations that the Agent-Orchestrator runtime executes.

```
┌──────────────────────────────────────────────────────────┐
│                    STUDIO (Design-Time)                   │
│                                                          │
│  ┌────────────┐  ┌────────────┐  ┌───────────────────┐  │
│  │  React UI  │──│  FastAPI   │──│  Core Modules     │  │
│  │  (Vite)    │  │  Backend   │  │  (IR, Conversion, │  │
│  │  :5173     │  │  :8001     │  │   Generation...)  │  │
│  └────────────┘  └────────────┘  └───────────────────┘  │
│                        │                                 │
│                        ▼                                 │
│               ┌────────────────┐                         │
│               │  Profile Files │                         │
│               │  (YAML on disk)│                         │
│               └───────┬────────┘                         │
└───────────────────────┼──────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────┐
│              AGENT-ORCHESTRATOR (Runtime)                 │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ Config Loader │  │  Engine      │  │  LLM Adapters │  │
│  │ (reads YAML) │──│  (runs work) │──│  (calls LLMs) │  │
│  └──────────────┘  └──────────────┘  └───────────────┘  │
│          :8000                                           │
└──────────────────────────────────────────────────────────┘
```

## Module Map

### Backend (`studio/studio/`)

| Module | Purpose | Key Classes/Functions |
|--------|---------|----------------------|
| `ir/models.py` | Intermediate Representation — canonical data model | `TeamSpec`, `AgentSpec`, `PhaseSpec`, `WorkflowSpec`, `GovernanceSpec`, `PolicySpec`, `WorkItemTypeSpec` |
| `conversion/converter.py` | Bidirectional IR ↔ runtime ProfileConfig | `ir_to_profile()`, `profile_to_ir()`, `ir_to_profile_dict()` |
| `schemas/extractor.py` | JSON Schema extraction via `model_json_schema()` | `extract_all_schemas()`, `extract_component_schema()` |
| `generation/generator.py` | YAML file generation from IR | `generate_profile_yaml()`, `generate_component_yaml()`, `write_profile_to_directory()` |
| `templates/manager.py` | Import/export profile templates | `import_template()`, `export_template()`, `list_templates()` |
| `validation/validator.py` | Structural and runtime validation | `validate_team()`, `validate_team_via_runtime()`, `StudioValidationResult` |
| `conditions/builder.py` | Condition expression builder/parser | `build_condition()`, `parse_condition()`, `validate_condition()` |
| `graph/validator.py` | Workflow DAG validation | `validate_graph()`, `GraphValidationResult` |
| `connectors/discovery.py` | Runtime connector provider discovery | `discover_connectors()`, `ConnectorInfo` |
| `deploy/deployer.py` | Deploy profiles to runtime workspace | `deploy_profile()`, `DeployResult` |
| `extensions/generator.py` | Extension stub code generation | `generate_connector_stub()`, `generate_event_handler_stub()`, `generate_hook_stub()` |
| `manifest/tracker.py` | Regeneration boundary tracking | `ManifestTracker`, `FileOwnership` |
| `prompts/generator.py` | Coding-assistant prompt packs | `generate_prompt_pack()`, `PromptPack` |
| `config.py` | Studio configuration | `StudioConfig`, `load_config()` |
| `app.py` | FastAPI application factory | `create_app()` |
| `cli.py` | CLI entry point | `main()`, `serve`, `import`, `export`, `validate` |
| `exceptions.py` | Custom exception hierarchy | `StudioError` and 11 specific subclasses |

### API Routes (`studio/studio/routes/`)

| Route Module | Prefix | Endpoints |
|-------------|--------|-----------|
| `team_routes.py` | `/api/studio/teams` | POST (create), GET /current, PUT /current, POST /from-template |
| `schemas_routes.py` | `/api/studio/schemas` | GET (all), GET /{component} |
| `generation_routes.py` | `/api/studio` | GET /preview, GET /preview/{component} |
| `validation_routes.py` | `/api/studio/validate` | POST (studio-side), POST /runtime, POST /condition |
| `graph_routes.py` | `/api/studio/graph` | GET (structure), POST /validate |
| `condition_routes.py` | `/api/studio/conditions` | GET /operators, POST /build, POST /parse, POST /validate |
| `connector_routes.py` | `/api/studio/connectors` | GET (discover), GET /capabilities |
| `template_routes.py` | `/api/studio/templates` | GET (list), POST /import, POST /export |
| `deploy_routes.py` | `/api/studio/deploy` | POST (deploy) |
| `extension_routes.py` | `/api/studio/extensions` | POST /connector, POST /event-handler, POST /hook, POST /all |
| `prompt_routes.py` | `/api/studio/prompts` | POST /generate |

### Frontend (`studio/frontend/src/`)

| File | Purpose |
|------|---------|
| `App.tsx` | Main app shell with sidebar navigation |
| `store/teamStore.ts` | Zustand store — single source of truth for team state |
| `api/client.ts` | Typed API client (all endpoints) |
| `types.ts` | TypeScript types matching Python IR models |
| `pages/OverviewPage.tsx` | Create team / import template / summary |
| `pages/AgentsPage.tsx` | Agent CRUD with LLM config forms |
| `pages/WorkflowPage.tsx` | Phase/status CRUD + React Flow graph + Builder tab |
| `components/workflow/WorkflowBuilder.tsx` | Interactive visual workflow builder (ReactFlow canvas) |
| `components/workflow/nodes/BuilderPhaseNode.tsx` | Custom node: phase name, agent chips, success/failure handles |
| `components/workflow/edges/TransitionEdge.tsx` | Custom edge: green solid (success), red dashed (failure) |
| `components/workflow/PhaseFormModal.tsx` | Extracted phase edit form (shared by list view and builder) |
| `components/workflow/AgentFormModal.tsx` | Agent create/edit modal with auto-ID generation |
| `components/workflow/AgentPalette.tsx` | Draggable agent sidebar for the builder canvas |
| `components/workflow/ContextMenu.tsx` | Right-click context menu for nodes, edges, and canvas |
| `pages/GovernancePage.tsx` | Threshold sliders + policy CRUD |
| `pages/WorkItemsPage.tsx` | Work item type CRUD with fields/artifacts |
| `pages/PreviewPage.tsx` | YAML preview + validation results |
| `pages/DeployPage.tsx` | Deploy form with results display |

## Data Flow

### Create/Edit Flow

```
User edits form in React UI
  → Component calls useTeamStore action (e.g. updateAgent)
    → Store calls API client (PUT /api/studio/teams/current)
      → FastAPI route receives TeamSpec JSON
        → Route validates and stores in app.state.studio_state
          → Returns updated TeamSpec JSON
            → Store updates local state
              → React re-renders
```

### Generate/Preview Flow

```
User clicks "Preview YAML"
  → PreviewPage calls api.previewAll()
    → GET /api/studio/preview
      → generation/generator.py generates YAML from IR
        → conversion/converter.py: ir_to_profile_dict(team)
        → YAML builders format each component file
          → Returns {filename: yaml_content}
```

### Validate Flow

```
User clicks "Validate"
  → POST /api/studio/validate
    → validation/validator.py runs all structural checks
      → _validate_agents(): cross-refs, LLM config, duplicates
      → _validate_workflow(): transitions, terminal reachability
      → _validate_governance(): thresholds, policy actions
      → _validate_work_items(): field types, duplicates
    → Returns StudioValidationResult {errors, warnings, is_valid}
```

### Deploy Flow

```
User clicks "Deploy"
  → POST /api/studio/deploy
    → deploy/deployer.py:
      1. Validate if requested
      2. Check manifest for ownership conflicts
      3. Write YAML files to profiles/{name}/
      4. Update .studio-manifest.json
      5. Optionally trigger runtime reload (PUT /api/v1/config/profile)
    → Returns DeployResult {success, files_written, runtime_reloaded}
```

### Import Template Flow

```
User selects template
  → POST /api/studio/templates/import
    → templates/manager.py reads YAML files from profile dir
      → Parses each file into IR models directly
      → Assembles complete TeamSpec
    → TeamSpec set as current working team
```

## IR Model Hierarchy

```
TeamSpec
├── name, description
├── agents: AgentSpec[]
│   ├── id, name, description, system_prompt
│   ├── skills[], phases[]
│   ├── llm: LLMSpec (provider, model, temperature, max_tokens, endpoint)
│   ├── retry_policy: RetryPolicySpec
│   └── concurrency, enabled
├── workflow: WorkflowSpec
│   ├── name, description
│   ├── statuses: StatusSpec[] (id, name, is_initial, is_terminal, transitions_to)
│   └── phases: PhaseSpec[]
│       ├── id, name, description, order
│       ├── agents[], on_success, on_failure
│       ├── quality_gates: QualityGateSpec[]
│       │   ├── name, conditions: ConditionSpec[]
│       │   └── on_failure (block|warn|skip)
│       ├── entry_conditions[], exit_conditions[]
│       └── is_terminal, requires_human, parallel, skippable
├── governance: GovernanceSpec
│   ├── delegated_authority: DelegatedAuthoritySpec
│   │   └── auto_approve_threshold, review_threshold, abort_threshold
│   └── policies: PolicySpec[]
│       └── id, name, action, conditions[], priority, enabled, tags[]
├── work_item_types: WorkItemTypeSpec[]
│   ├── id, name, description
│   ├── custom_fields: WorkItemFieldSpec[] (name, type, required, values)
│   └── artifact_types: ArtifactTypeSpec[] (id, name, file_extensions)
└── manifest: AppManifestSpec | null
```

## Regeneration Boundaries

Studio tracks file ownership via `.studio-manifest.json`:

| File Type | Ownership | Overwrite Policy |
|-----------|-----------|-----------------|
| agents.yaml, workflow.yaml, governance.yaml, workitems.yaml | `studio` | Always regeneratable |
| app.yaml | `studio` | Always regeneratable |
| extensions/hooks/*.py | `user` (after first gen) | Never overwrite without `force=True` |
| extensions/handlers/*.py | `user` (after first gen) | Never overwrite without `force=True` |
| prompts/*.md | `studio` | Always regeneratable |

## Technology Choices

| Layer | Technology | Reason |
|-------|-----------|--------|
| Backend | Python 3.10+ / FastAPI | Same stack as runtime; can import runtime models directly |
| Frontend | React 18 + TypeScript 5 | Type safety, rich ecosystem |
| Build | Vite 5 | Fast HMR, modern defaults |
| Styling | Tailwind CSS 3.4 | Utility-first, no custom CSS needed |
| State | Zustand | Minimal boilerplate, TypeScript-native |
| Graph & Builder | @xyflow/react (React Flow) v12 | MIT licensed, well-maintained, powers both read-only graph and interactive builder |
| Forms | Native React (controlled inputs) | No extra dependency needed for this scope |
| API | fetch-based typed client | No axios needed for simple REST calls |
