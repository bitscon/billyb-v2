# Phase 4 — Adapters: Using Agent Zero Inside Billy

    ## Goal
    Integrate selected Agent Zero components into Billy via adapters, while keeping Billy’s contracts stable.

    ## Deliverables
    - Adapter modules (names illustrative):
      - `AgentZeroToolRegistryAdapter`
      - `AgentZeroMemoryAdapter`
      - `AgentZeroTraceAdapter` (or trace exporter)
    - Config flags to enable/disable adapters per environment
    - End-to-end demo flow:
      - user message -> agent loop -> tool calls -> DockerRunner -> response
    - Documentation:
      - `docs/agent-zero-integration/adapters.md`

    ## Actions (step-by-step)

    ### 4.1 — Tool registry integration
    If reusing Agent Zero tool definitions:
    - Map Agent Zero tool metadata into Billy’s `ToolRegistry`:
      - name
      - description
      - args schema
      - permissions (network/secrets/files)
    - Ensure the final invocation path is:
      - Billy decides tool call
      - Billy executes tool through **Billy DockerRunner**
      - Agent Zero code (if used) only helps with schemas/validation/patterns, not execution

    **Success criteria**
    - Billy is still the authority for execution and policy enforcement.

    ### 4.2 — Memory integration
    If reusing Agent Zero memory patterns:
    - Implement a `MemoryStore` adapter that:
      - uses Agent Zero’s retrieval/summarization logic, or
      - ports the pattern and keeps Billy’s storage (preferred for ops control)
    - Define policies:
      - what gets stored
      - retention windows
      - per-persona memory namespaces
      - safe redaction rules

    **Success criteria**
    - Memory improves responses while staying predictable and compliant.

    ### 4.3 — Agent loop integration (optional and carefully scoped)
    If Agent Zero has a strong agent loop:
    - Do NOT replace Billy’s entire loop immediately.
    - Instead:
      - run Agent Zero’s planner as a “planning tool” behind Billy
      - or use it as an optional strategy module
    - Keep Billy responsible for:
      - tool execution (Docker)
      - permissions
      - traceability

    **Success criteria**
    - You can A/B test loop strategies without breaking Billy’s API.

    ### 4.4 — Trace and debugging integration
    - Make sure:
      - every adapter emits Billy trace events
      - event schema remains stable
    - Add:
      - correlation IDs
      - per-step durations
      - tool container IDs for deep debugging

    **Success criteria**
    - A single request produces a unified trace, even if some internals come from Agent Zero.

    ### 4.5 — Configuration + feature flags
    - Add config keys for:
      - enabling Agent Zero adapters
      - selecting memory provider
      - selecting tool registry source
      - enabling Docker execution policies
    - Ensure safe defaults:
      - adapters off by default in production unless explicitly enabled
      - Docker execution on (per your requirement) with baseline security policy

    **Success criteria**
    - You can roll out incrementally and roll back quickly.

    ## Definition of Done (DoD)
    - At least one Agent Zero component is used through an adapter in a production-like run.
    - Docker execution remains Billy-managed.
    - Feature flags exist and are documented.

    ## Risks & mitigations
    - Risk: Two sources of truth for tool definitions.
      - Mitigation: Pick one canonical registry; treat the other as import-only.
    - Risk: Memory adapter changes response behavior unexpectedly.
      - Mitigation: Add evaluation tests and rollout gradually.