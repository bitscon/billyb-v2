# Proposed Boundary Contracts for Billy

To integrate Agent Zero components into Billy without rewriting Billy, we need clear **contracts** that define how parts of the system interact.  A contract is a Python interface (or Pydantic model) that specifies inputs, outputs and responsibilities.  Adapters can then implement these interfaces using Agent Zero’s modules or Billy’s own code.

Below are the recommended contracts.  They should live under a namespace such as `billy/core/contracts.py` and be referenced throughout the integration plan.

## `ToolRegistry`

Responsible for discovering and providing metadata about tools.

```python
from typing import List, Dict, Any, Optional

class ToolSpec(BaseModel):
    name: str
    description: str
    args_schema: Dict[str, Any]  # JSON‑schema like definition
    permissions: List[str]       # e.g. ["network", "filesystem"]

class ToolRegistry:
    async def list_tools(self) -> List[ToolSpec]:
        """Return metadata for all available tools."""

    async def get_schema(self, tool_name: str) -> Optional[ToolSpec]:
        """Return the ToolSpec for a single tool."""

    async def invoke_tool(self, tool_name: str, args: Dict[str, Any]) -> Any:
        """Invoke a tool synchronously or asynchronously and return its output."""
```

## `ToolRunner`

Responsible for executing a tool in the correct environment (local or Docker).  Separation of registration and execution allows Billy to reuse Agent Zero’s metadata while controlling execution policies.

```python
class ToolRunner:
    async def execute(self, tool_name: str, args: Dict[str, Any], *, use_docker: bool = False) -> Any:
        """Run the specified tool with arguments.  If `use_docker` is True, run in a Docker container."""

    async def set_policy(self, resource_limits: Dict[str, Any], network_policy: str) -> None:
        """Configure default resource limits and network policies."""
```

## `MemoryStore`

Responsible for persisting and retrieving conversational context and long‑term knowledge.

```python
from typing import List, Dict, Any

class MemoryStore:
    async def write(self, key: str, value: Any, tags: List[str] = []) -> None:
        """Persist a value under a key with optional tags."""

    async def query(self, query: str, *, k: int = 5) -> List[Dict[str, Any]]:
        """Retrieve the `k` most relevant entries to the query.  Should return both the stored value and metadata."""

    async def summarize(self, entries: List[Dict[str, Any]]) -> str:
        """Produce a compact summary of multiple entries for inclusion in prompts."""
```

## `TraceSink`

Responsible for emitting structured events.  Events should be recorded even if tracing is disabled at the UI; storing them enables later debugging.

```python
class TraceEvent(BaseModel):
    timestamp: float
    agent_id: str
    type: str           # e.g. "llm_call", "tool_call", "memory_write"
    data: Dict[str, Any]

class TraceSink:
    async def emit(self, event: TraceEvent) -> None:
        """Record a trace event."""

    async def flush(self) -> None:
        """Flush buffered events to persistent storage (if any)."""
```

## `AgentLoop`

Abstracts the high‑level reasoning process.  Billy remains the orchestrator and defines the loop; Agent Zero’s planner can be plugged in as an implementation of this interface.

```python
class AgentLoop:
    async def run(self, user_input: str, *, persona: str) -> str:
        """Given a user input and persona, return a response.  May call tools, memory and emit trace events."""

    async def register_tool_call(self, tool_name: str, args: Dict[str, Any]) -> None:
        """Record that the loop decided to call a tool.  Used for auditing and gating."""
```

## Notes

- All interfaces are asynchronous to allow non‑blocking I/O (e.g. network calls, Docker operations).
- Concrete adapters will implement these interfaces.  For instance, an `AgentZeroToolRegistryAdapter` would implement `ToolRegistry` by delegating to Agent Zero’s tool loader and normalising the schema into Billy’s format.
- These contracts should be refined after producing the architecture maps and reuse candidates.  They provide a starting point for Phase 1 and Phase 4 work.