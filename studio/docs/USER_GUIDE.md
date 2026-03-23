# Agent-Orchestrator Studio — User Guide

## What Studio Does

Studio is a visual tool for building **agent team profiles** that run on Agent-Orchestrator.  A profile defines:

1. **Agents** — AI agents with specific roles, LLM configurations, and skills
2. **Workflow** — A pipeline of phases that agents execute in sequence
3. **Governance** — Rules for auto-approving, reviewing, or rejecting work
4. **Work Item Types** — The domain-specific data your agents process

Studio generates valid YAML configuration files and deploys them to the Agent-Orchestrator runtime.

---

## Getting Started

### Creating a New Team

1. Open Studio at http://localhost:5173
2. On the **Overview** page, enter a team name and description
3. Click **Create Team**

### Importing from a Template

Instead of starting from scratch, import one of the shipped templates:

1. On the **Overview** page, click **Import Template**
2. Select one:
   - `content-moderation` — Content moderation pipeline with sentiment analysis
   - `software-dev` — Software development workflow
   - `research-team` — Research and analysis team
3. The entire profile loads into Studio for editing

---

## Editing Agents

Agents can be created from the **Agents** page, or directly from the **Builder** canvas (see below).

### Adding an Agent

1. Click **Add Agent** (or right-click the Builder canvas → **Create New Agent**)
2. Fill in:
   - **Name** — Display name (e.g. "Research Analyst"). The **ID** is auto-generated from the name as a kebab-case slug (e.g. `research-analyst`). Click "edit" next to the ID if you need a custom one.
   - **Description** — What this agent does
   - **System Prompt** — The instructions sent to the LLM (this is the most important field — it defines the agent's behavior)
   - **Skills** — Comma-separated capability tags (e.g. `nlp, sentiment-analysis`)
   - **Phases** — Select which workflow phases this agent participates in
   - **LLM Config**:
     - Provider: `openai`, `anthropic`, `google`, `ollama`, `grok`
     - Model: e.g. `gpt-4o`, `claude-sonnet-4-20250514`
     - Temperature: 0.0 (deterministic) to 2.0 (creative)
     - Max Tokens: response length limit
   - **Concurrency** — How many parallel instances (1-100)
   - **Retry Policy** — What to do on LLM call failures
3. Click **Save** (or **Create Agent** when creating from the Builder)

### Best Practices for Agent Design

- **One responsibility per agent** — An agent should do one thing well
- **Specific system prompts** — Tell the agent exactly what to analyze, what format to return, what criteria to use
- **Match model to task** — Use powerful models (GPT-4o, Claude) for complex analysis; use faster models for simple classification
- **Set temperature appropriately** — Low (0.1-0.3) for analysis/classification, higher (0.5-0.8) for creative tasks

---

## Editing the Workflow

Navigate to the **Workflow** page.  Four tabs are available: **Phases**, **Statuses**, **Graph**, and **Builder**.

### Phases

Phases are the steps in your processing pipeline.

1. Click **Add Phase** (or right-click the Builder canvas → **Add New Phase Here**)
2. Fill in:
   - **Name** — Display name (e.g. "Research & Analysis"). The **ID** is auto-generated as a kebab-case slug. Click "edit" next to the ID if you need a custom one.
   - **Order** — Execution order (1, 2, 3...)
   - **Agents** — Which agents run in this phase
   - **On Success** — Next phase if this one succeeds
   - **On Failure** — Fallback phase if this one fails
   - **Quality Gates** — Conditions that must pass (see below)
   - **Is Terminal** — Check this for the final "done" phase
   - **Requires Human** — Check if human approval is needed

### Quality Gates

Quality gates are checks that run after a phase completes:

- Each gate has one or more **conditions** (expressions like `confidence >= 0.8`)
- If conditions fail, the gate's **on_failure** action fires:
  - `block` — Stop the pipeline
  - `warn` — Log warning, continue
  - `skip` — Skip this check entirely

### Statuses

Statuses define the lifecycle states of work items (e.g. `submitted → analyzing → approved`).

- Mark exactly **one** status as `is_initial`
- Mark **one or more** as `is_terminal`
- Define `transitions_to` for each non-terminal status

### Workflow Graph

The **Graph** tab shows a read-only visual DAG of your phases:
- **Green edges** = on_success transitions
- **Red edges** = on_failure transitions
- **Terminal phases** are highlighted
- The graph auto-validates for orphans, unreachable terminals, and invalid references

### Visual Workflow Builder

The **Builder** tab provides an interactive canvas for visually creating and editing the entire workflow. It is the recommended way to build workflows from scratch.

#### Canvas Basics
- **Right-click** anywhere on the canvas to add phases or create agents
- **Scroll wheel** to zoom in/out
- **Click + drag** on empty space to pan
- **Controls** widget (bottom-left) has zoom +/- and fit-to-view buttons
- **MiniMap** (bottom-right) shows an overview when nodes exist

#### Creating Phases
- **Right-click canvas** → **Add New Phase Here** — the phase node appears where you clicked
- **Double-click** a phase node to edit it
- **Delete key** removes selected nodes/edges

#### Connecting Phases (Transitions)
Each phase node has two source handles at the bottom:
- **Green handle** (left) = on_success transition
- **Red handle** (right) = on_failure transition

Drag from a source handle to the top (target) handle of another phase to create a transition. Success edges are solid green; failure edges are dashed red.

- **Right-click an edge** to switch its type (success/failure) or remove it

#### Managing Agents on the Canvas
- **Left sidebar** lists all agents as draggable cards
- **Drag** an agent card onto a phase node to assign it
- **Right-click a phase node** → **Assign Agent** / **Remove Agent** submenus
- **Right-click a phase node** → **Create New Agent for Phase** creates an agent and auto-assigns it
- Click **"+ New"** in the sidebar header, or **right-click canvas** → **Create New Agent** to create agents
- **Hover** an agent card in the sidebar to see edit/delete buttons

#### Node Context Menu (right-click a phase node)
- Edit Phase, Set/Unset Terminal, Set/Unset Requires Human
- Assign/Remove agents
- Create New Agent for Phase
- Delete Phase

#### Sync with Other Tabs
The Builder reads from the same data store as all other tabs. Phases created on the Phases tab appear as nodes on the canvas, and vice versa. Agent changes sync with the Agents page.

---

## Editing Governance

Navigate to the **Governance** page.

### Delegated Authority

Three threshold sliders control automatic decisions:

- **Auto-Approve Threshold** (default 0.8) — Confidence above this → auto-approve
- **Review Threshold** (default 0.5) — Confidence below this → human review queue
- **Abort Threshold** (default 0.2) — Confidence below this → abort

**Important**: Auto-approve > Review > Abort (thresholds must be in descending order).

### Policies

Policies are ordered rules that override the default thresholds:

1. Click **Add Policy**
2. Fill in:
   - **ID** — Unique slug
   - **Name** — Display name
   - **Action** — `allow`, `deny`, `review`, `warn`, `escalate`
   - **Conditions** — Expression strings (e.g. `confidence >= 0.9`, `category == 'hate_speech'`)
   - **Priority** — Higher priority = evaluated first
   - **Tags** — Metadata tags

**Policy evaluation order**: Policies are checked in priority order (highest first).  The first matching policy determines the outcome.

---

## Editing Work Item Types

Navigate to the **Work Items** page.

Work item types define the domain-specific data your agents process.

### Adding a Work Item Type

1. Click **Add Work Item Type**
2. Fill in:
   - **ID** — Unique slug (e.g. `content-submission`)
   - **Name** — Display name
   - **Custom Fields** — Domain-specific data fields:
     - Name, Type (`string`, `text`, `integer`, `float`, `enum`, `boolean`), Required
     - For `enum` type: specify allowed values
   - **Artifact Types** — Output files the workflow produces:
     - ID, Name, File extensions (e.g. `.json`, `.md`)

---

## Previewing YAML

Navigate to the **Preview** page.

- See the generated YAML for each file: `agents.yaml`, `workflow.yaml`, `governance.yaml`, `workitems.yaml`
- Click **Refresh** to regenerate after making changes
- Click **Validate** to run structural validation:
  - **Errors** (red) — Must be fixed before deploying
  - **Warnings** (yellow) — Non-blocking but worth reviewing

---

## Deploying a Profile

Navigate to the **Deploy** page.

1. Enter a **profile name** (directory name for the profile)
2. Configure:
   - **Validate first** — Run validation before writing (recommended)
   - **Trigger reload** — Tell the running runtime to switch to this profile
3. Click **Deploy**
4. Results show:
   - Files written to disk
   - Whether the runtime was reloaded
   - Any errors or warnings

### After Deployment

The runtime picks up the new profile from `profiles/{name}/`.  If trigger-reload was enabled and the runtime was running, it switches automatically.

---

## Condition Expressions

Conditions are used in quality gates, phase entry/exit conditions, and governance policies.

### Format

```
<field> <operator> <value>
```

### Supported Operators

| Operator | Meaning |
|----------|---------|
| `>=` | Greater than or equal |
| `<=` | Less than or equal |
| `!=` | Not equal |
| `==` | Equal |
| `>` | Greater than |
| `<` | Less than |
| `in` | Is in list |

### Examples

```
confidence >= 0.8
severity == 'none'
category == 'hate_speech'
risk_level in ['high', 'critical']
categories_checked >= 3
```

---

## Extension Stubs

Studio can generate Python code skeletons for extending your profile:

### Connector Providers

Integrate external services (Slack, Jira, custom APIs):

1. Go to any extension generation endpoint or use the API
2. Provide: provider ID, display name, capability type
3. Studio generates a fully-typed Python class with `get_descriptor()` and `execute()` methods
4. Edit the TODO sections to add your integration logic

### Event Handlers

React to workflow events (notifications, metrics, logging):

- Subscribe to events like `work_item.submitted`, `phase.completed`
- Generated stub includes a `handle()` method with event type routing

### Phase Context Hooks

Inject data before a phase runs:

- Load external data, previous phase results, or reference data
- Generated stub includes the hook function signature and return contract

### Regeneration Safety

Extension stubs are marked as **user-owned** after first generation.  Studio will never overwrite them on subsequent deploys unless you use `force=True`.

---

## Prompt Packs

Studio generates coding-assistant prompts for Claude Code, Cursor, etc.:

- **Agent tuning** — Improve system prompts and model selection
- **Quality gate tuning** — Refine conditions and thresholds
- **Extension implementation** — Fill in connector/handler/hook stubs

Each prompt includes full profile context so the coding assistant understands your domain.

---

## API Reference

All endpoints are under `/api/studio/`.  See `docs/ARCHITECTURE.md` for the complete route table.

### Key Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/teams` | Create new team |
| GET | `/teams/current` | Get current team |
| PUT | `/teams/current` | Update current team |
| POST | `/templates/import` | Import from template |
| POST | `/validate` | Validate team |
| GET | `/preview` | Preview all YAML |
| GET | `/graph` | Get workflow graph |
| POST | `/deploy` | Deploy to runtime |
| POST | `/conditions/build` | Build condition expression |
| POST | `/extensions/connector` | Generate connector stub |
