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
```

### Architecture
- `src/agent_orchestrator/core/` — engine, work queue, pipeline, agent pool, phase executor, event bus
- `src/agent_orchestrator/configuration/` — models, loader, validator, agent manager
- `src/agent_orchestrator/governance/` — governor, audit logger, review queue
- `src/agent_orchestrator/adapters/` — LLM adapter, providers, metrics, webhooks
- `src/agent_orchestrator/persistence/` — settings store, state store, config history
- `src/agent_orchestrator/api/` — FastAPI app and routes
- `src/agent_orchestrator/cli/` — Click CLI commands

### Key Documentation
- `ARCHITECTURE.md` — detailed technical architecture
- `SDK.md` — configuration and API reference
- `GETTING_STARTED.md` — setup and domain workflow guide
