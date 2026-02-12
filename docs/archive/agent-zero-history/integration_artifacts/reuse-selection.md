# Reuse Selection (Phase 2 Outcome)

This document records the specific Agent Zero components selected for reuse in Billy v2 after applying the scoring rubric (value, effort, security, maintenance, coupling, testability).  It also captures the chosen integration approach and rationale.  The goal is to focus on a small number of high‑leverage components that deliver immediate value.

## Selected components

| Category | Component | Reason for selection | Integration approach | Notes |
| --- | --- | --- | --- | --- |
| **Quick win** | **Tool registry & schema** (`extract_tools.py` + `python/tools`) | Billy has no mechanism for defining or discovering tools.  Reusing Agent Zero’s dynamic loader allows us to expose tools quickly without inventing a new schema. | **Adapter**: Implement `ToolRegistry` to call Agent Zero’s loader, translate tool metadata into Billy’s `ToolSpec`, and return a stub that can later invoke Billy’s own `ToolRunner`. | Low coupling: we reuse only the discovery and metadata, not the execution.  Avoids copying the entire tool system. |
| **Core enabler** | **Vector‑store memory subsystem** (`helpers/memory.py`, `memory_consolidation.py`) | Persistent, searchable memory is essential for multi‑turn conversations and improving responses.  Agent Zero provides a robust FAISS‑based implementation. | **Adapter**: Implement `MemoryStore` by delegating reads/writes and summaries to Agent Zero’s memory API.  Optionally vendor small helper functions. | Requires adding FAISS and LangChain dependencies to Billy.  Need to isolate memory per persona and ensure data is stored in Billy’s data directory. |
| **Stretch** | **Logging & tracing** (`helpers/log.py`, `helpers/print_style.py`) | Structured events will improve debuggability and support future UI/telemetry. | **Re‑implement**: Define `TraceSink` in Billy and emit events following Agent Zero’s event schema.  Use Agent Zero’s event names (e.g. `llm_call`, `tool_call`) for consistency. | Could be partially vendored, but re‑implementing allows tailoring to Billy’s needs and avoiding UI coupling. |

## Deferred components

The following components were evaluated but deferred to later phases due to higher complexity or lower immediate value:

| Component | Reason for deferral |
| --- | --- |
| **Planner / agent loop** | Agent Zero’s planner is powerful but tightly integrated with its prompts and tool system.  Importing it wholesale would require rewriting Billy’s charter and prompt structure.  We will instead experiment with using the planner as a “planning tool” in Phase 4, allowing A/B testing without replacing Billy’s core loop. |
| **Docker helpers** | Billy will develop its own `DockerRunner` in Phase 3, inspired by Agent Zero’s approach.  Copying the helper verbatim may introduce assumptions about container layout that do not apply. |
| **Prompt & extension system** | Billy currently uses a concise charter; adopting Agent Zero’s complex prompt and extension system would be a large cultural shift.  We will instead design our own prompt templates for tools and rely on Billy’s charter for persona guidance. |

## Versioning strategy

For each reused component, pin the Agent Zero commit hash and document it in `docs/agent-zero-integration/artifacts/reuse-candidates.md`.  When Agent Zero releases new versions, update and re‑evaluate each component.  Vendored code should include attribution and automated tests to detect behavioural changes.