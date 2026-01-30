# Phase 1 — Architecture Map & Boundary Definition

    ## Goal
    Define clean boundaries in Billy so Agent Zero components can plug in without forcing a rewrite.

    ## Deliverables
    - `docs/agent-zero-integration/artifacts/billy-architecture-map.md`
    - `docs/agent-zero-integration/artifacts/agent-zero-architecture-map.md`
    - `docs/agent-zero-integration/artifacts/boundary-contracts.md` (interfaces)
    - A diagram (optional): `docs/agent-zero-integration/artifacts/diagrams/*.png` or `*.mmd`

    ## Actions (step-by-step)

    ### 1.1 — Document Billy’s “agent execution pipeline”
    Write the sequence for a typical interaction:
    1. User input arrives (API/UI)
    2. Persona/context assembly happens
    3. LLM call(s)
    4. Tool selection and execution
    5. Memory read/write
    6. Response assembly + streaming
    7. Trace/log emission

    Include:
    - Where errors are handled
    - Where retries/backoff occur
    - Where token/context limits are managed

    **Success criteria**
    - A new contributor can follow the code path without guessing.

    ### 1.2 — Document Agent Zero’s pipeline the same way
    Produce the same sequence for Agent Zero:
    - Pay special attention to:
      - Tool schema and invocation mechanics
      - Memory hooks
      - Any planning/reflection loops
      - Any sandboxing boundary

    **Success criteria**
    - You can pinpoint which parts are “framework” vs “application.”

    ### 1.3 — Define Billy’s stable interfaces (“contracts”)
    Create or refine contracts in `boundary-contracts.md` for:
    - `ToolRegistry`:
      - list tools
      - get schema
      - invoke tool (sync/async)
    - `ToolRunner`:
      - execute locally OR in Docker
      - enforce timeouts/resource limits
    - `MemoryStore`:
      - write memory
      - query memory
      - summarize/compact
    - `TraceSink`:
      - structured events for every step
    - `AgentLoop`:
      - given input+context, return output and tool calls

    **Success criteria**
    - Billy can swap implementations without changing application logic.

    ### 1.4 — Choose integration boundaries
    Pick where Agent Zero will plug in. Recommended:
    - Keep Billy’s:
      - API/UI
      - Auth/secrets
      - Persona management
      - Docker execution substrate (Phase 3)
    - Reuse from Agent Zero (via adapters):
      - Tool schema/registry patterns
      - Memory patterns
      - Trace event formats and debugging concepts

    **Success criteria**
    - There is a clear “adapter seam” with minimal blast radius.

    ## Definition of Done (DoD)
    - Architecture maps exist.
    - Stable interface contracts exist.
    - A written integration boundary decision exists.

    ## Risks & mitigations
    - Risk: Designing interfaces that mirror Agent Zero too closely.
      - Mitigation: Define Billy interfaces based on Billy needs; adapt Agent Zero to them.
    - Risk: Over-abstracting early.
      - Mitigation: Start with interfaces required for 1–2 reuse candidates only.