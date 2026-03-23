# MCP Integration Guide

Model Context Protocol (MCP) integration for Agent Orchestrator. MCP adds bidirectional AI ecosystem interoperability — consume tools from external MCP servers and expose platform capabilities to external AI clients.

---

## Overview

MCP is a **protocol adapter** — it does not replace the REST API, connector framework, or governance system. Every MCP tool call flows through the existing `ConnectorService.execute()` pipeline, getting permission checks, contract validation, and audit logging for free.

**Two directions:**

| Direction | What it does | Example |
|-----------|-------------|---------|
| **MCP Client** | Agents consume tools/resources/prompts from external MCP servers | GitHub, Slack, filesystem MCP servers |
| **MCP Server** | Platform exposes governed capabilities to external AI clients | Claude Desktop, Cursor, other MCP clients |

**Dependency:** `pip install "agent-orchestrator[mcp]"` — the `mcp` package is optional. Without it, all MCP features are silently disabled.

---

## Installation

```bash
# Add MCP support to existing installation
pip install "agent-orchestrator[mcp]"

# Or install everything
pip install "agent-orchestrator[llm,mcp,dev]"
```

---

## Configuration

Create `mcp.yaml` in your profile directory:

```yaml
# profiles/my-profile/mcp.yaml

client:
  servers:
    - server_id: github
      display_name: GitHub MCP Server
      transport: stdio
      command: npx
      args: ["-y", "@modelcontextprotocol/server-github"]
      env:
        GITHUB_PERSONAL_ACCESS_TOKEN: "${GITHUB_TOKEN}"
      capability_type_override: repository
      auto_connect: true

    - server_id: custom-api
      display_name: Custom API Bridge
      transport: streamable_http
      url: "http://localhost:8080/mcp"
      credential_env_var: CUSTOM_API_TOKEN
      headers:
        X-Org-Id: "acme"

  default_capability_type: external_api
  tool_prefix: mcp

server:
  enabled: true
  mount_path: "/mcp"
  session_ttl_seconds: 3600
  max_sessions: 100
  audit_all_invocations: true
```

---

## MCP Client

### How it works

1. On engine start, `MCPClientManager` connects to all configured servers with `auto_connect: true`
2. `MCPConnectorBridge` discovers tools from each connected server
3. Each tool is wrapped as an `MCPToolConnectorProvider` and registered in `ConnectorRegistry`
4. Provider ID format: `mcp.{server_id}.{tool_name}` (e.g., `mcp.github.list_repos`)
5. Agents call MCP tools through `ConnectorService.execute()` — same as native connectors

### Transport types

| Transport | Use case | Required fields |
|-----------|----------|-----------------|
| `stdio` | Local MCP servers launched as subprocesses | `command`, `args` |
| `streamable_http` | Remote HTTP-based MCP servers | `url` |
| `sse` | Legacy SSE-based servers (deprecated) | `url` |

### Environment variable resolution

Environment variables in `env` values are resolved at connect time:

```yaml
env:
  GITHUB_TOKEN: "${GITHUB_TOKEN}"       # resolved from process env
  STATIC_VALUE: "not-a-reference"       # used as-is
```

### Capability type mapping

Each MCP tool is mapped to a `CapabilityType` for the connector framework:

1. **Server override:** `capability_type_override` on the server config
2. **Config default:** `default_capability_type` on the client config
3. **Fallback:** `external_api`

Valid values: `search`, `documents`, `messaging`, `ticketing`, `repository`, `telemetry`, `identity`, `external_api`, `file_storage`, `workflow_action`.

### Python usage

```python
from agent_orchestrator.mcp.client_manager import MCPClientManager
from agent_orchestrator.mcp.models import MCPClientConfig, MCPServerConfig, MCPTransportType

config = MCPClientConfig(servers=[
    MCPServerConfig(
        server_id="github",
        display_name="GitHub",
        transport=MCPTransportType.STDIO,
        command="npx",
        args=["-y", "@modelcontextprotocol/server-github"],
    ),
])

manager = MCPClientManager(config)
await manager.connect_all()

# Discover tools
tools = await manager.discover_tools("github")

# Call a tool directly
result = await manager.call_tool("github", "list_repos", {"org": "acme"})

# Or through the connector framework (recommended — gets governance)
from agent_orchestrator.mcp.bridge import MCPConnectorBridge
bridge = MCPConnectorBridge(manager, connector_registry, config)
await bridge.register_all_tools()
# Now agents call tools via ConnectorService.execute()
```

---

## MCP Server

### How it works

1. If `server.enabled: true`, the MCP server ASGI app is mounted on FastAPI at `mount_path`
2. External AI clients connect via Streamable HTTP transport
3. The server dynamically generates tools from `ConnectorRegistry`
4. All tool calls flow through `GovernedToolDispatcher` (Governor + audit)

### Enabling

**Via configuration:**
```yaml
server:
  enabled: true
```

**Via CLI flag:**
```bash
agent-orchestrator serve --workspace . --mcp
```

### Exposed tools

**Static orchestration tools** (always available):

| Tool | Description |
|------|-------------|
| `orchestrator_get_status` | Engine status (queue, pipeline, agents) |
| `orchestrator_list_workitems` | All work items in pipeline |
| `orchestrator_get_workitem` | Single work item by ID |
| `orchestrator_submit_workitem` | Submit new work item |
| `orchestrator_list_agents` | Agent definitions from active profile |
| `orchestrator_engine_pause` | Pause processing |
| `orchestrator_engine_resume` | Resume processing |

**Dynamic connector tools** — one per registered connector provider operation. Tool names follow the pattern `connector_{provider_id}_{operation}`.

### Exposed resources

| URI | Description |
|-----|-------------|
| `orchestrator://status` | Engine status JSON |
| `orchestrator://workitems` | Work items list |
| `orchestrator://audit` | Recent audit records (last 50) |
| `orchestrator://config/agents` | Agent definitions |
| `orchestrator://config/workflow` | Workflow configuration |
| `orchestrator://config/governance` | Governance configuration |
| `orchestrator://connectors` | Registered connector providers |

### Exposed prompts

One prompt per `AgentDefinition` in the active profile:
- Name: `agent_{agent.id}`
- Content: agent's `system_prompt`
- Arguments: `work_item_title` (optional), `work_item_data` (optional)

### Governance

All MCP server tool calls flow through `GovernedToolDispatcher`:

1. **Governor.evaluate()** — applies governance policies
2. **Resolution handling:**
   - `ALLOW` → execute tool
   - `ALLOW_WITH_WARNING` → execute + log warning
   - `QUEUE_FOR_REVIEW` → return review ID (client can poll)
   - `ABORT` → return error with governance reason
3. **Audit** — every invocation is recorded with `MCP_INVOCATION` record type

### Session management

`MCPSessionRegistry` tracks active client sessions with:
- Configurable TTL (`session_ttl_seconds`)
- Max session limit (`max_sessions`)
- Automatic eviction of expired sessions

---

## Backward Compatibility

- `mcp` field defaults to `None` on `ProfileConfig` — existing profiles unchanged
- `mcp` is an optional dependency — core platform works without it
- MCP server only mounts when `server.enabled: true` in config
- MCP client only connects when `mcp.yaml` exists with server entries
- All engine changes guarded by null checks
- `MCP_INVOCATION` is a new additive value on `RecordType` enum

---

## File Reference

| File | Purpose |
|------|---------|
| `mcp/__init__.py` | Public exports (lazy-guarded) |
| `mcp/models.py` | 9 Pydantic v2 frozen models |
| `mcp/exceptions.py` | MCPError hierarchy |
| `mcp/client_manager.py` | Session lifecycle, discovery, invocation |
| `mcp/bridge.py` | MCP-to-connector bridge |
| `mcp/client_prompts.py` | Prompt resolution from external servers |
| `mcp/server.py` | Server factory functions |
| `mcp/server_tools.py` | Dynamic tool generation |
| `mcp/server_resources.py` | Resource handlers |
| `mcp/server_prompts.py` | Prompt handlers from agent definitions |
| `mcp/server_governance.py` | Governed tool dispatcher |
| `mcp/server_session.py` | Session registry with TTL |
