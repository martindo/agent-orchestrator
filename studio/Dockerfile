# =============================================================================
# Agent-Orchestrator Studio — Multi-stage Docker build
# =============================================================================
# Build context must be the REPO ROOT (set via docker-compose or -f flag).
#
#   docker build -f studio/Dockerfile -t agent-orchestrator-studio .
#
# Stage 1: compile React/Vite frontend
# Stage 2: Python backend serving the compiled frontend
# =============================================================================

##
## Stage 1 — Build the React frontend
##
FROM node:20-alpine AS frontend-build

WORKDIR /build

COPY studio/frontend/package.json studio/frontend/package-lock.json* ./
RUN npm install

COPY studio/frontend/ .
RUN npm run build


##
## Stage 2 — Python backend + compiled frontend
##
FROM python:3.11-slim

WORKDIR /app

# Install the parent agent-orchestrator package first (needed for schema
# extraction, runtime validation, and template import/export).
COPY pyproject.toml /parent/pyproject.toml
COPY src/ /parent/src/
COPY profiles/ /parent/profiles/
RUN pip install --no-cache-dir -e "/parent[llm]"

# Install Studio Python dependencies
COPY studio/pyproject.toml ./pyproject.toml
RUN pip install --no-cache-dir .

# Copy Studio source
COPY studio/studio/ ./studio/

# Copy built frontend assets
COPY --from=frontend-build /build/dist ./frontend/dist/

# Re-install in editable mode so the console_script entry point resolves
RUN pip install --no-cache-dir -e .

EXPOSE 8004

ENTRYPOINT ["studio"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8004"]
