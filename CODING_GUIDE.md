# CoderSwarm Coding Guide

This guide defines coding standards and rules to follow when writing code. Following these rules reduces bugs, improves maintainability, and minimizes issues found in code reviews.

---

## 1. SOLID Principles

### 1.1 Single Responsibility Principle (SRP)
- Each class/module should have ONE reason to change
- Functions should do ONE thing well
- If a function exceeds 50 lines, consider breaking it up
- If a class has more than 5-7 public methods, consider splitting it

```python
# BAD: Function does too many things
def process_story(story_id, state):
    # Validates input
    # Fetches from database
    # Transforms data
    # Sends to API
    # Updates UI
    # Logs results
    pass

# GOOD: Single responsibility functions
def validate_story(story_id: str) -> bool: ...
def fetch_story(story_id: str) -> Story: ...
def transform_story(story: Story) -> dict: ...
def submit_story(data: dict) -> Response: ...
```

### 1.2 Open/Closed Principle (OCP)
- Classes should be open for extension, closed for modification
- Use protocols/abstract base classes for extensibility
- Prefer composition over inheritance

```python
# GOOD: Extensible via protocol
from typing import Protocol

class AgentProtocol(Protocol):
    def execute(self, state: dict) -> dict: ...

# New agents implement the protocol without modifying existing code
class ReviewerAgent:
    def execute(self, state: dict) -> dict: ...
```

### 1.3 Liskov Substitution Principle (LSP)
- Subtypes must be substitutable for their base types
- Don't override methods to do nothing or throw unexpected exceptions

### 1.4 Interface Segregation Principle (ISP)
- Many small, specific interfaces are better than one large interface
- Clients shouldn't depend on methods they don't use

```python
# BAD: Fat interface
class WorkerProtocol(Protocol):
    def start(self): ...
    def stop(self): ...
    def pause(self): ...
    def resume(self): ...
    def get_metrics(self): ...
    def reset_metrics(self): ...

# GOOD: Segregated interfaces
class RunnableProtocol(Protocol):
    def start(self): ...
    def stop(self): ...

class MetricsProtocol(Protocol):
    def get_metrics(self): ...
    def reset_metrics(self): ...
```

### 1.5 Dependency Inversion Principle (DIP)
- Depend on abstractions, not concretions
- High-level modules shouldn't depend on low-level modules

```python
# BAD: Direct dependency on concrete class
class Orchestrator:
    def __init__(self):
        self.database = PostgresDatabase()  # Concrete!

# GOOD: Depend on abstraction
class Orchestrator:
    def __init__(self, database: DatabaseProtocol):
        self.database = database
```

---

## 2. Exception Handling

### 2.1 Never Swallow Exceptions Silently

```python
# BAD: Silent swallow
try:
    result = risky_operation()
except Exception:
    pass  # Silent failure!

# BAD: Log and continue without context
try:
    result = risky_operation()
except Exception as e:
    logger.warning(f"Failed: {e}")
    return None  # Caller doesn't know about failure

# GOOD: Log with traceback and handle appropriately
try:
    result = risky_operation()
except SpecificError as e:
    logger.error(f"Operation failed: {e}", exc_info=True)
    raise  # Re-raise or raise a more specific error

# GOOD: If you must continue, be explicit about fallback
try:
    result = risky_operation()
except SpecificError as e:
    logger.warning(f"Using fallback due to: {e}", exc_info=True)
    result = fallback_value
    if result is None:
        raise ConfigurationError(f"No fallback available: {e}") from e
```

### 2.2 Catch Specific Exceptions

```python
# BAD: Catches everything including KeyboardInterrupt, SystemExit
try:
    process_data()
except Exception:
    handle_error()

# GOOD: Catch specific exceptions
try:
    process_data()
except (ValueError, TypeError) as e:
    handle_validation_error(e)
except IOError as e:
    handle_io_error(e)
```

### 2.3 Always Include Traceback in Error Logs

```python
# BAD: Loses traceback
except Exception as e:
    logger.error(f"Error: {e}")

# GOOD: Preserves traceback
except Exception as e:
    logger.error(f"Error: {e}", exc_info=True)
```

### 2.4 Use Custom Exceptions for Domain Errors

```python
# Define in a central exceptions module
class CoderSwarmError(Exception):
    """Base exception for all CoderSwarm errors."""
    pass

class ConfigurationError(CoderSwarmError):
    """Invalid or missing configuration."""
    pass

class DispatchError(CoderSwarmError):
    """Failed to dispatch work to agent."""
    pass
```

---

## 3. Logging vs Print

### 3.1 Never Use print() for Logging

```python
# BAD: Print statements
print(f"Processing {item_id}")
print(f"DEBUG: state = {state}")

# GOOD: Use logger
logger.info(f"Processing {item_id}")
logger.debug(f"State: {state}")
```

### 3.2 Use Appropriate Log Levels

| Level | Use For |
|-------|---------|
| `DEBUG` | Detailed diagnostic info (variable values, flow tracing) |
| `INFO` | Confirmation that things work as expected |
| `WARNING` | Something unexpected but not an error |
| `ERROR` | Error that prevented an operation |
| `CRITICAL` | System-wide failure |

```python
logger.debug(f"Entering function with args: {args}")
logger.info(f"Successfully processed {count} items")
logger.warning(f"Retry {attempt}/3 after transient error")
logger.error(f"Failed to connect to database", exc_info=True)
```

### 3.3 Create Module-Level Loggers

```python
# At top of each module
import logging
logger = logging.getLogger(__name__)
```

---

## 4. Type Hints

### 4.1 Always Use Type Hints

```python
# BAD: No type hints
def process(data, options):
    ...

# GOOD: Full type hints
def process(data: dict[str, Any], options: ProcessOptions) -> ProcessResult:
    ...
```

### 4.2 Use Python 3.10+ Style

```python
# OLD STYLE (avoid)
from typing import List, Dict, Optional, Union
def func(items: List[str]) -> Optional[Dict[str, int]]:
    ...

# NEW STYLE (preferred)
def func(items: list[str]) -> dict[str, int] | None:
    ...
```

### 4.3 Use TypeVar for Generic Functions

```python
from typing import TypeVar

T = TypeVar("T")

def first(items: list[T]) -> T | None:
    return items[0] if items else None
```

---

## 5. Thread Safety

### 5.1 Protect Mutable Shared State with Locks

```python
# BAD: Unprotected shared state
class Counter:
    def __init__(self):
        self.count = 0  # Accessed by multiple threads!

    def increment(self):
        self.count += 1  # Race condition!

# GOOD: Lock-protected state
class Counter:
    def __init__(self):
        self._count = 0
        self._lock = threading.Lock()

    def increment(self):
        with self._lock:
            self._count += 1
```

### 5.2 Use notify_all() for Condition Variables

```python
# BAD: May miss waiters
self._condition.notify()

# GOOD: Wakes all waiters
self._condition.notify_all()
```

### 5.3 Always Use try/finally for Resource Cleanup

```python
# BAD: Resource leak on exception
def process(self, item):
    resource = self.acquire()
    result = do_work(resource, item)  # If this throws, resource leaks!
    self.release(resource)
    return result

# GOOD: Guaranteed cleanup
def process(self, item):
    resource = self.acquire()
    try:
        return do_work(resource, item)
    finally:
        self.release(resource)
```

### 5.4 Document Thread Safety

```python
class WorkQueue:
    """
    Thread-safe work queue.

    All public methods are safe to call from multiple threads.
    """
```

---

## 6. Code Organization

### 6.1 Put Reusable Code in Packages

```
# BAD: Utility code scattered in application
app/
  utils.py  # 500 lines of mixed utilities
  helpers.py  # More utilities

# GOOD: Separate packages
coderswarm-packages/
  coderswarm_core/  # Shared utilities
  coderswarm_scaling/  # Scaling infrastructure
app/
  # Application code only
```

### 6.2 Avoid Circular Imports

```python
# BAD: Circular import
# module_a.py
from module_b import B
class A:
    def use_b(self): return B()

# module_b.py
from module_a import A  # Circular!
class B:
    def use_a(self): return A()

# GOOD: Use protocols or restructure
# protocols.py
class AProtocol(Protocol): ...
class BProtocol(Protocol): ...

# Or use lazy imports
def use_a(self):
    from module_a import A  # Import when needed
    return A()
```

### 6.3 Keep Functions Short (< 50 lines)

```python
# BAD: 200-line function
def run_workflow():
    # ... 200 lines of initialization
    # ... 200 lines of main loop
    # ... 100 lines of cleanup

# GOOD: Composed of small functions
def run_workflow():
    state = initialize_workflow()
    result = execute_main_loop(state)
    cleanup_workflow(state)
    return result
```

### 6.4 Use Constants Instead of Magic Strings/Numbers

```python
# BAD: Magic values
if status == "in_progress":
    timeout = 30

# GOOD: Named constants
class Status(Enum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"

DEFAULT_TIMEOUT_SECONDS = 30

if status == Status.IN_PROGRESS:
    timeout = DEFAULT_TIMEOUT_SECONDS
```

---

## 7. Singleton Pattern

### 7.1 Use the Standard Singleton Base Class

```python
from core.singleton import Singleton

class ConfigManager(Singleton):
    def _initialize(self, config_path: str = None):
        """Called once on first instantiation."""
        self.config = load_config(config_path)
```

### 7.2 Make Singletons Testable

```python
class MySingleton(Singleton):
    @classmethod
    def reset_instance(cls):
        """Reset for testing."""
        cls._instance = None
        cls._initialized = False

# In tests
def test_singleton():
    MySingleton.reset_instance()
    instance = MySingleton()
    # ... test ...
    MySingleton.reset_instance()  # Cleanup
```

---

## 8. API Design

### 8.1 Validate Inputs at Boundaries

```python
# BAD: No validation
def process_story(story_id: str, state: dict):
    story = fetch_story(story_id)  # May fail deep in call stack

# GOOD: Validate early
def process_story(story_id: str, state: dict):
    if not story_id:
        raise ValueError("story_id is required")
    if not isinstance(state, dict):
        raise TypeError(f"state must be dict, got {type(state)}")
    ...
```

### 8.2 Return Consistent Types

```python
# BAD: Returns different types
def get_user(user_id: str):
    if user_id in cache:
        return cache[user_id]  # Returns User
    return None  # Returns None
    # Sometimes raises UserNotFoundError

# GOOD: Consistent return type
def get_user(user_id: str) -> User:
    """Get user by ID.

    Raises:
        UserNotFoundError: If user doesn't exist
    """
    if user_id in cache:
        return cache[user_id]
    raise UserNotFoundError(user_id)

# Or use Optional explicitly
def get_user(user_id: str) -> User | None:
    """Get user by ID, or None if not found."""
    return cache.get(user_id)
```

### 8.3 Use Dataclasses for Data Containers

```python
# BAD: Plain dict
result = {
    "success": True,
    "data": {...},
    "error": None,
}

# GOOD: Typed dataclass
@dataclass
class Result:
    success: bool
    data: dict[str, Any]
    error: str | None = None
```

---

## 9. Testing

### 9.1 Write Tests for Critical Paths

Priority for test coverage:
1. Core business logic
2. Error handling paths
3. Edge cases
4. Integration points

### 9.2 Use Fixtures for Common Setup

```python
@pytest.fixture
def coordinator():
    """Fresh coordinator for each test."""
    ScalingCoordinator.reset_instance()
    coord = get_scaling_coordinator()
    coord.configure(enabled=True)
    yield coord
    coord.shutdown()
    ScalingCoordinator.reset_instance()
```

### 9.3 Test Error Conditions

```python
def test_handles_timeout():
    with pytest.raises(TimeoutError):
        slow_operation(timeout=0.001)

def test_handles_invalid_input():
    with pytest.raises(ValueError, match="must be positive"):
        process_count(-1)
```

---

## 10. Documentation

### 10.1 Write Docstrings for Public APIs

```python
def dispatch_work(
    story_id: str,
    agent_type: AgentType,
    priority: int = 0,
) -> DispatchResult:
    """
    Dispatch work to an agent for processing.

    Args:
        story_id: Unique identifier for the story
        agent_type: Type of agent to handle the work
        priority: Priority level (0=normal, 1=high, 2=urgent)

    Returns:
        DispatchResult containing status and assigned agent

    Raises:
        DispatchError: If no agents available
        ValueError: If story_id is empty

    Example:
        result = dispatch_work("US-123", AgentType.REVIEWER)
        print(f"Assigned to {result.agent_id}")
    """
```

### 10.2 Document Thread Safety and Side Effects

```python
def update_state(self, key: str, value: Any) -> None:
    """
    Update shared state.

    Thread-safe: Uses internal lock.
    Side effects: Notifies all state observers.
    """
```

---

## 11. Performance

### 11.1 Avoid Blocking in Async/Generator Contexts

```python
# BAD: Blocks the event loop
async def fetch_data():
    time.sleep(1)  # Blocks!
    return data

# GOOD: Use async sleep
async def fetch_data():
    await asyncio.sleep(1)
    return data

# For generators/threads, use event-based waiting
def consumer_loop(self):
    while self._running:
        # BAD: Fixed sleep ignores shutdown
        time.sleep(1)

        # GOOD: Interruptible wait
        self._shutdown_event.wait(timeout=1)
```

### 11.2 Don't Copy Large Objects Unnecessarily

```python
# BAD: Copies entire state on every call
def process(state: dict) -> dict:
    new_state = state.copy()  # O(n) copy
    new_state["key"] = value
    return new_state

# GOOD: Mutate in place when safe, or use structural sharing
def process(state: dict) -> dict:
    state["key"] = value  # If mutation is acceptable
    return state
```

---

## 12. Security

### 12.1 Never Log Secrets

```python
# BAD: Logs API key
logger.debug(f"Connecting with key: {api_key}")

# GOOD: Mask sensitive data
logger.debug(f"Connecting with key: {api_key[:4]}...")
```

### 12.2 Validate External Input

```python
# BAD: Trusts user input
def execute_query(user_input: str):
    db.execute(f"SELECT * FROM users WHERE name = '{user_input}'")

# GOOD: Parameterized queries
def execute_query(user_input: str):
    db.execute("SELECT * FROM users WHERE name = ?", [user_input])
```

---

## 13. Checklist Before Submitting Code

- [ ] All functions have type hints
- [ ] No print() statements (use logger)
- [ ] Exceptions are not swallowed silently
- [ ] Shared mutable state is protected with locks
- [ ] Resources are cleaned up in finally blocks
- [ ] Functions are < 50 lines
- [ ] No magic strings/numbers (use constants)
- [ ] Critical paths have tests
- [ ] Public APIs have docstrings
- [ ] No circular imports

---

## 14. Single Source of Truth (State Management)

### 14.1 Never Have Multiple State Copies That Need Syncing

Multiple state objects that need to stay synchronized is a major source of bugs. When state diverges, systems break in subtle, hard-to-debug ways.

```python
# BAD: Multiple state objects that need syncing
class ModuleA:
    _state: dict = {}  # Module A's state

class ModuleB:
    _state: dict = {}  # Module B's state - needs to stay in sync!

class ModuleC:
    def __init__(self):
        self._state = {}  # Yet another copy!

# Problem: When ModuleA updates _state, ModuleB and ModuleC don't see it
# Result: Bugfix tracking added in A, but B thinks there are no bugfixes
```

```python
# GOOD: Single shared state object
class StateManager:
    """Single source of truth for all state."""
    _instance = None
    _state: dict = {}

    @classmethod
    def get_state(cls) -> dict:
        return cls._state

# All modules use the same state
state = StateManager.get_state()
```

### 14.2 Pass State by Reference, Never Copy Unless Necessary

```python
# BAD: Copying state loses updates from other components
def update_state(self, state: dict):
    self._state = state.copy()  # Copy loses connection to original!

# Later...
original_state["new_key"] = "value"  # This change is NOT visible in self._state!

# BAD: Caching and merging creates stale data
def update_state(self, state: dict):
    cached = self._state.copy()  # Save old
    self._state = state
    self._state.update(cached)  # Old overwrites new!

# GOOD: Use the passed state directly
def update_state(self, state: dict):
    self._state = state  # Same object reference
```

### 14.3 Document Which Component Owns the State

```python
# GOOD: Clear ownership documented
class Orchestrator:
    """
    Owns the workflow state dict.

    State Ownership:
    - Orchestrator: Creates and owns the state dict
    - EventHandler: References state via update_state_reference()
    - CallbackHandler: References state via update_state()

    All components share ONE dict instance. Updates are immediately
    visible to all components.
    """
    def __init__(self):
        self.state = {}  # THE source of truth
```

### 14.4 If Sync Is Unavoidable, Make It Explicit and Atomic

```python
# If you must have derived state, make sync explicit
class DerivedCache:
    """
    Derived cache that must be explicitly refreshed.

    WARNING: This is a cache, not a source of truth.
    Call refresh() before reading if source may have changed.
    """
    def __init__(self, source: StateManager):
        self._source = source
        self._cache = {}

    def refresh(self):
        """Explicitly sync cache from source."""
        with self._lock:
            self._cache = self._compute_derived(self._source.get_state())

    def get(self, key: str):
        # Consider if refresh is needed
        return self._cache.get(key)
```

### 14.5 Common State Sync Anti-Patterns

| Anti-Pattern | Problem | Fix |
|--------------|---------|-----|
| Module-level `_state = {}` in multiple modules | Updates in one module invisible to others | Use single shared state manager |
| `self._state = state.copy()` | Loses connection to original | `self._state = state` (reference) |
| Caching old state and merging back | Overwrites newer updates | Don't cache, use shared reference |
| Polling to detect changes | Slow, can miss updates | Use callbacks/events or shared state |
| Different state dicts for "performance" | Eventually diverge | Profile first, optimize only if needed |

### 14.6 Real Example: The Bug We Fixed

```python
# THE BUG: OrchestratorCallbackHandler was caching pipeline state
def update_state(self, state: dict):
    cached_pipeline = self._state.get("story_pipeline", {}).copy()  # Cached!
    self._state = state
    # Merged cached (stale) over new state - lost event handler's updates!
    self._state["story_pipeline"] = {**state.get("story_pipeline", {}), **cached_pipeline}

# THE FIX: Just use the passed state
def update_state(self, state: dict):
    self._state = state  # Event handler's updates are preserved
```

---

## Quick Reference

| Anti-Pattern | Fix |
|--------------|-----|
| `except Exception: pass` | Log with `exc_info=True`, re-raise or handle specifically |
| `print(f"debug: {x}")` | `logger.debug(f"...")` |
| `any` type hint | `Any` from typing |
| `condition.notify()` | `condition.notify_all()` |
| 200-line function | Break into 4-5 smaller functions |
| `from typing import List` | Use `list[T]` directly (Python 3.10+) |
| Unprotected shared state | Add `threading.Lock()` |
| Resource without cleanup | Use `try/finally` or context manager |
| Magic string `"pending"` | `Status.PENDING` enum |
| Scattered utility code | Move to shared package |
