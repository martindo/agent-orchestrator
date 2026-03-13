# Extension Points

This document describes the four primary extension patterns available to apps built on agent-orchestrator. Each pattern is already implemented in the platform — apps simply wire into them.

---

## 1. Phase Context Hook

**What it does:** Injects custom data into phase execution. The engine calls your function before each phase, passing the work item and phase config. Your function returns a dict that is forwarded to the phase executor as additional context.

**Signature:**

```python
def my_hook(work_item: WorkItem, phase: WorkflowPhaseConfig) -> dict[str, Any]:
    ...
```

**Wiring:**

```python
from agent_orchestrator import OrchestrationEngine, ConfigurationManager, EventBus

def my_phase_hook(work_item, phase):
    return {"extra_instructions": "Be concise.", "max_sources": 5}

mgr = ConfigurationManager(workspace_path)
mgr.load()
engine = OrchestrationEngine(mgr, EventBus(), phase_context_hook=my_phase_hook)
```

**Manifest registration** (optional):

```yaml
# app.yaml
hooks:
  process: "myapp.helpers.hooks:process_hook"
```

**Reference:** `src/agent_orchestrator/core/engine.py` — constructor `phase_context_hook` parameter and `_process_work_item()` method.

---

## 2. Event Bus Subscriptions

**What it does:** React to engine events without modifying engine code. The EventBus provides typed pub/sub — subscribe to any `EventType` and your async handler is called when that event fires.

**Available event types:**
- `work.*` — submitted, started, phase_entered, phase_exited, completed, failed
- `agent.*` — started, completed, error, scaled, created, updated, deleted
- `governance.*` — decision, escalation, review_completed
- `config.*` — reloaded
- `system.*` — started, stopped, error

**Wiring:**

```python
from agent_orchestrator import EventBus, Event, EventType

bus = EventBus()

async def on_work_completed(event: Event) -> None:
    print(f"Work item {event.data['work_item_id']} completed!")

bus.subscribe(EventType.WORK_COMPLETED, on_work_completed)
```

**Reference:** `src/agent_orchestrator/core/event_bus.py`

---

## 3. Custom LLM Providers

**What it does:** Add support for any LLM backend by implementing the `LLMProviderProtocol`.

**Protocol:**

```python
from typing import Protocol

class LLMProviderProtocol(Protocol):
    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float = 0.3,
        max_tokens: int = 4000,
        **kwargs,
    ) -> str:
        ...
```

**Wiring:**

Implement the protocol and pass a custom `llm_call_fn` to the engine, or register a new provider in the adapter's provider registry.

**Built-in providers:** OpenAI, Anthropic, Google, Grok, Ollama.

**Reference:** `src/agent_orchestrator/adapters/llm_adapter.py` — `LLMProviderProtocol` and `LLMAdapter`

---

## 4. Connectors & Contracts

**What it does:** Register capability providers (e.g., web search, ticketing, messaging) through a governed connector system with capability contracts.

**Concepts:**
- **Connector**: A provider that implements a specific capability (e.g., `WebSearchProvider`)
- **Contract**: Defines the interface a connector must satisfy, with validation and failure semantics
- **Governance**: Connectors are subject to the same governance policies as agent actions

**Wiring:**

```python
from agent_orchestrator.connectors.registry import ConnectorRegistry
from agent_orchestrator.contracts.registry import ContractRegistry

# Register a connector
registry = ConnectorRegistry()
registry.register("web_search", my_search_provider)

# Define and register a contract
contract_registry = ContractRegistry()
contract_registry.register(my_capability_contract)
```

**Reference:**
- `src/agent_orchestrator/connectors/` — connector registry and base providers
- `src/agent_orchestrator/contracts/` — contract definitions and registry

---

## See Also

- [SDK.md](../SDK.md) — Full configuration and API reference, including the "Building Apps" section
- [profiles/research-team/](../profiles/research-team/) — Reference implementation using phase hooks and connectors
