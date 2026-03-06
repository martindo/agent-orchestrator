FROM python:3.11-slim

WORKDIR /app

# Install dependencies first for layer caching
COPY pyproject.toml .
RUN pip install --no-cache-dir ".[llm]"

# Copy source and built-in profiles
COPY src/ src/
COPY profiles/ profiles/

# Re-install in editable mode so the console script and profile paths resolve
RUN pip install --no-cache-dir -e ".[llm]"

EXPOSE 8000

# Default: serve a workspace mounted at /workspace
ENTRYPOINT ["agent-orchestrator"]
CMD ["serve", "/workspace", "--host", "0.0.0.0", "--port", "8000"]
