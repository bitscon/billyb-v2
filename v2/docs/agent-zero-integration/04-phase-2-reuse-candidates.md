# Phase 2 — Select Reuse Candidates & Build Spikes

    ## Goal
    Select specific Agent Zero components/patterns to reuse and validate feasibility via small spikes.

    ## Deliverables
    - Updated `docs/agent-zero-integration/01-comparison.md` with chosen components
    - `docs/agent-zero-integration/artifacts/reuse-selection.md`
    - One or more spike PRs demonstrating integration feasibility:
      - Tool registry adapter spike
      - Memory adapter spike
      - Trace export adapter spike

    ## Actions (step-by-step)

    ### 2.1 — Prioritize candidates (value vs effort)
    From Phase 0’s candidate list:
    - Score each candidate with the rubric:
      - Value, effort, security, maintenance, coupling, testability
    - Pick:
      - 1 “quick win” (1–3 days)
      - 1 “core enabler” (foundation for later)
      - 1 “stretch” (optional)

    **Success criteria**
    - The chosen list is small and defensible.

    ### 2.2 — Decide reuse approach per component
    For each selected component, choose:
    - Adapter integration
    - Vendor module
    - Dependency
    - Re-implement

    Document:
    - Why this approach
    - Expected maintenance cost
    - Versioning strategy (pin commit? tag? submodule? vendoring policy?)

    **Success criteria**
    - Every reused component has a sustainable strategy.

    ### 2.3 — Build spike #1: Tool framework reuse
    Objective:
    - Billy can list tools and invoke one tool through an adapter.

    Actions:
    - Implement a thin “AgentZeroToolRegistryAdapter” (name illustrative)
    - Map Agent Zero tool schema to Billy tool schema
    - Handle:
      - argument validation
      - tool metadata (name/description)
      - errors -> Billy error format
    - Add a basic test:
      - register mock tool
      - invoke tool
      - confirm outputs + trace events

    **Success criteria**
    - A demo endpoint can call a tool through the adapter end-to-end.

    ### 2.4 — Build spike #2: Memory pattern reuse (optional if too big)
    Objective:
    - Billy can call a “memory provider” that uses Agent Zero patterns (summarize/store/retrieve) or vice versa.

    Actions:
    - Implement:
      - Memory write hook
      - Memory retrieval hook for a prompt turn
    - Validate:
      - no private data leakage by default
      - deterministic policies for what gets stored

    **Success criteria**
    - A test conversation shows retrieval improves output and doesn’t bloat context.

    ### 2.5 — Spike #3: Trace/debugging reuse
    Objective:
    - Standardize structured events so you can later build a step inspector UI.

    Actions:
    - Define minimal event schema:
      - request_start
      - llm_call_start/stop
      - tool_call_start/stop
      - memory_read/write
      - request_end
    - Ensure adapters emit trace events.

    **Success criteria**
    - One request produces a coherent trace timeline.

    ## Definition of Done (DoD)
    - Selected components documented with reuse method.
    - At least one successful spike merged (or ready PR) proving reuse works.

    ## Risks & mitigations
    - Risk: Agent Zero internals not designed for import/reuse.
      - Mitigation: Vendor small parts or re-implement patterns.
    - Risk: Schema mismatch causing brittle adapters.
      - Mitigation: Keep Billy schema canonical; transform at edges only.