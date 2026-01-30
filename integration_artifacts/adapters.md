# Adapter Design Notes (Phase 4)

This document sketches the adapter modules that will bridge Billy’s contracts to Agent Zero’s implementations.  Each adapter implements one of the contracts defined in `boundary-contracts.md`.  Detailed implementation should occur in Phase 4 PRs.

## `AgentZeroToolRegistryAdapter`

Implements the `ToolRegistry` contract by delegating to Agent Zero’s tool loader.

### Responsibilities

- On initialization, locate the Agent Zero source directory (e.g. vendor the `python/helpers/extract_tools.py` file or install Agent Zero as a dependency).
- Call the loader to discover classes that subclass `Tool`.  For each tool:
  - Read its metadata (name, description, argument schema, required permissions).
  - Construct a `ToolSpec` object.
- Implement `list_tools()` to return all discovered `ToolSpec` instances.
- Implement `get_schema(tool_name)` to return a single `ToolSpec` or `None`.
- Implement `invoke_tool()` to **record** the intent to call a tool (see `register_tool_call()` contract).  Actual execution should be delegated to `ToolRunner`.

### Notes

- This adapter **does not** execute tools; it only provides metadata.  Execution is deferred to Billy’s own runner so that resource limits and security policies remain under Billy’s control.
- If Agent Zero’s tool loader expects certain environment variables or directory structure, configure it appropriately in Billy’s settings.

## `AgentZeroMemoryAdapter`

Implements the `MemoryStore` contract using Agent Zero’s memory API.

### Responsibilities

- Initialize Agent Zero’s memory subsystem (or vendor necessary modules) with the appropriate embedding model configuration.
- Implement `write(key, value, tags)` by calling the underlying memory API to store the data in the appropriate area (e.g. `Memory.Area.MAIN`).  Attach tags as metadata.
- Implement `query(query, k)` by converting the query to an embedding and retrieving the top‑`k` entries.  Return both the stored content and metadata (e.g. timestamps, tags, similarity scores).
- Implement `summarize(entries)` by calling Agent Zero’s summarisation functions (e.g. `memory_consolidation`) or reusing its summarisation prompt.  Summaries should be concise enough to fit in system prompts.

### Notes

- Each persona or session in Billy should correspond to a distinct memory subdirectory to avoid cross‑pollination.  Provide configuration options to specify the storage location.
- If Agent Zero’s memory API is asynchronous, ensure adapter methods await the underlying calls.

## `AgentZeroTraceAdapter`

Implements the `TraceSink` contract by formatting events according to Agent Zero’s log schema and writing them to Billy’s logging subsystem.

### Responsibilities

- Map Billy event types (`llm_call`, `tool_call`, `memory_write`, etc.) to Agent Zero’s log structure.  For example, include timestamps, agent IDs, event types, tool names and durations.
- Write events to a persistent store (e.g. a JSON lines file or a SQLite DB).  Optionally integrate with Agent Zero’s HTML log generator to produce human‑readable logs.
- Provide a no‑op implementation when tracing is disabled via configuration.

### Notes

- Do not import Agent Zero’s UI components; the adapter focuses solely on event structure.
- As an optional enhancement, support exporting traces in OpenTelemetry format so they can be visualized in existing observability tools.

## `AgentZeroPlannerAdapter` (optional)

Implements the `AgentLoop` contract by delegating planning to Agent Zero’s agent loop.  This adapter is experimental and may be used for A/B testing.

### Responsibilities

- Given a user input and persona, assemble the necessary context (charter, memory summaries, persona instructions) and call Agent Zero’s planner via its API.
- Translate the resulting tool calls into Billy’s tool registry and return the final answer.
- Track any decisions (tool usage, reasoning) using the `TraceSink` so results can be analysed.

### Notes

- Running Agent Zero inside Billy introduces the risk of competing loops and prompts.  Start with small experiments and ensure feature flags are in place.  If adopted, this adapter effectively turns Billy into a thin orchestrator while Agent Zero drives the agent loop.