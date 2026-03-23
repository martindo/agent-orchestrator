# Agent-Orchestrator Studio — Installation Guide

## Prerequisites

- **Python 3.10+** — Backend runtime
- **Node.js 18+** and **npm** — Frontend build
- **Agent-Orchestrator** — The runtime this tool generates profiles for (optional but recommended)

## Quick Start

### 1. Install the Backend

From the repository root:

```bash
cd studio
pip install -e .
```

This installs the `studio` CLI command and all Python dependencies:
- FastAPI, uvicorn (web server)
- Pydantic v2 (data models)
- PyYAML (YAML generation)
- httpx (HTTP client for runtime API)
- click (CLI framework)

### 2. Install the Frontend

```bash
cd studio/frontend
npm install
```

### 3. Start the Development Servers

In two terminals:

**Terminal 1 — Backend (port 8001):**
```bash
cd studio
studio serve --workspace /path/to/agent-orchestrator --port 8001
```

**Terminal 2 — Frontend (port 5173):**
```bash
cd studio/frontend
npm run dev
```

Open **http://localhost:5173** in your browser.

The Vite dev server proxies `/api/studio/*` requests to the backend on port 8001.

## Configuration

Studio reads configuration from environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `STUDIO_RUNTIME_URL` | `http://localhost:8000` | Agent-Orchestrator runtime API URL |
| `STUDIO_WORKSPACE_DIR` | Current directory | Workspace root containing `profiles/` |
| `STUDIO_PROFILES_DIR` | `{workspace}/profiles` | Override profiles directory location |
| `STUDIO_PORT` | `8001` | Studio backend server port |
| `STUDIO_FRONTEND_ORIGIN` | `http://localhost:5173` | CORS origin for React dev server |
| `STUDIO_LOG_LEVEL` | `INFO` | Python log level (DEBUG, INFO, WARNING, ERROR) |

### Example

```bash
export STUDIO_WORKSPACE_DIR=/path/to/agent-orchestrator
export STUDIO_RUNTIME_URL=http://localhost:8000
studio serve
```

## CLI Commands

```bash
# Start the Studio server
studio serve [--port PORT] [--host HOST] [--workspace DIR] [--runtime-url URL]

# Import and display a profile template
studio import profiles/content-moderation
studio import profiles/content-moderation --format json

# Export a profile to a new directory
studio export /tmp/my-profile --template profiles/content-moderation

# Validate a profile
studio validate profiles/content-moderation
```

## Production Build

Build the React frontend for production:

```bash
cd studio/frontend
npm run build
```

This creates `studio/frontend/dist/` which the FastAPI backend serves automatically as static files. After building, only the backend server is needed:

```bash
studio serve --workspace /path/to/agent-orchestrator
# Open http://localhost:8001
```

## Running with Agent-Orchestrator

For the full workflow (Studio + Runtime):

```bash
# Terminal 1: Start the runtime
cd agent-orchestrator
docker compose up -d

# Terminal 2: Start Studio pointing at the runtime
cd studio
studio serve --workspace ../agent-orchestrator --runtime-url http://localhost:8000
```

Studio will:
- Read profile templates from the runtime's `profiles/` directory
- Deploy generated profiles back to that directory
- Query the runtime for available connector providers
- Trigger config reload when deploying

## Running Tests

```bash
cd studio
python -m pytest tests/ -v
```

## Project Structure

```
studio/
├── pyproject.toml          # Python project config
├── studio/                 # Backend Python package
│   ├── app.py              # FastAPI app factory
│   ├── cli.py              # CLI entry point
│   ├── config.py           # Configuration
│   ├── exceptions.py       # Custom exceptions
│   ├── ir/                 # IR models
│   ├── conversion/         # IR ↔ ProfileConfig
│   ├── schemas/            # JSON Schema extraction
│   ├── generation/         # YAML generation
│   ├── templates/          # Template import/export
│   ├── validation/         # Profile validation
│   ├── conditions/         # Condition expressions
│   ├── graph/              # Workflow graph analysis
│   ├── connectors/         # Connector discovery
│   ├── deploy/             # Profile deployment
│   ├── extensions/         # Extension stub generation
│   ├── manifest/           # Regeneration tracking
│   ├── prompts/            # Prompt pack generation
│   └── routes/             # API route modules
├── tests/                  # Python test suite
├── frontend/               # React frontend
│   ├── src/
│   │   ├── api/            # API client
│   │   ├── store/          # Zustand state store
│   │   ├── components/     # Reusable components
│   │   │   ├── common/     # Modal, shared UI
│   │   │   └── workflow/   # Visual Builder components
│   │   │       ├── WorkflowBuilder.tsx   # Main builder canvas
│   │   │       ├── AgentPalette.tsx      # Draggable agent sidebar
│   │   │       ├── AgentFormModal.tsx    # Agent create/edit modal
│   │   │       ├── PhaseFormModal.tsx    # Phase create/edit modal
│   │   │       ├── ContextMenu.tsx       # Right-click menus
│   │   │       ├── nodes/               # Custom ReactFlow nodes
│   │   │       └── edges/               # Custom ReactFlow edges
│   │   └── pages/          # Page components
│   ├── package.json
│   ├── tsconfig.json
│   └── vite.config.ts
└── docs/                   # Documentation
    ├── ARCHITECTURE.md
    ├── USER_GUIDE.md
    └── INSTALL.md
```
