# CLAUDE.md

## Project Overview

Agent Orchestrator — a generic, domain-agnostic platform for orchestrating multi-agent workflows with built-in governance, auditing, and observability.

### Tech Stack
- **Backend**: Python 3.11 + FastAPI + Pydantic v2
- **Database**: PostgreSQL 16
- **LLM Providers**: OpenAI, Anthropic, Google, Grok, Ollama
- **Infrastructure**: Docker Compose (api + db + ollama)

### Common Commands

```bash
# Start all services
docker compose up -d --build

# Initialize a workspace
docker compose run --rm api init /workspace --template content-moderation

# Run tests
cd agent-orchestrator && python -m pytest tests/ -v

# Validate configuration
curl -X POST http://localhost:8000/api/v1/config/validate

# Start with MCP server enabled
agent-orchestrator serve --workspace . --mcp
```

### Architecture
- `src/agent_orchestrator/core/` — engine, work queue, pipeline, agent pool, phase executor, event bus
- `src/agent_orchestrator/configuration/` — models, loader, validator, agent manager
- `src/agent_orchestrator/governance/` — governor, audit logger, review queue
- `src/agent_orchestrator/adapters/` — LLM adapter, providers, metrics, webhooks
- `src/agent_orchestrator/persistence/` — settings store, state store, config history
- `src/agent_orchestrator/mcp/` — MCP client, server, bridge, governance, session management
- `src/agent_orchestrator/api/` — FastAPI app and routes
- `src/agent_orchestrator/cli/` — Click CLI commands

### Studio (Visual Designer)
- `studio/` — A design-time visual tool for building agent team profiles
- **Tech**: React 18 + TypeScript 5 + Vite + Tailwind + Zustand + ReactFlow v12
- **Backend**: Python 3.11 + FastAPI (port 8001)
- **Visual Workflow Builder**: Interactive canvas (Workflow → Builder tab) for creating agents and phases, wiring transitions via drag-and-drop, and assigning agents to phases
- **Auto-ID**: Agent and phase IDs are auto-generated from names (kebab-case slugs)
- **Key files**: `studio/frontend/src/components/workflow/WorkflowBuilder.tsx` (canvas), `studio/frontend/src/pages/WorkflowPage.tsx` (4 tabs: Phases, Statuses, Graph, Builder)

```bash
# Start Studio via Docker
docker compose -f studio/docker-compose.yml up -d --build
# Studio UI: http://localhost:8001
```

### Key Documentation
- `ARCHITECTURE.md` — detailed technical architecture
- `SDK.md` — configuration and API reference
- `GETTING_STARTED.md` — setup and domain workflow guide
- `studio/docs/USER_GUIDE.md` — Studio user guide (includes Builder docs)
- `studio/docs/ARCHITECTURE.md` — Studio architecture and module map
- `studio/docs/INSTALL.md` — Studio installation and project structure
