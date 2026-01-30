# Phase 0 — Repo Audit & Inventory

    ## Goal
    Create a concrete inventory of Billy and Agent Zero components so we can compare them accurately and identify 
reusable parts.

    ## Inputs
    - Billy repo (this repo / branch you’re working on)
    - Agent Zero repo (external)

    ## Deliverables
    - `docs/agent-zero-integration/artifacts/billy-inventory.md`
    - `docs/agent-zero-integration/artifacts/agent-zero-inventory.md`
    - `docs/agent-zero-integration/artifacts/reuse-candidates.md`
    - A minimal “glossary” mapping terms (tool, action, skill, memory, persona, agent loop)

    ## Actions (step-by-step)

    ### 0.1 — Identify Billy’s runtime entrypoints
    - Find:
      - Server entrypoint(s)
      - Client entrypoint(s)
      - Agent loop implementation(s)
      - Tool/action invocation layer
      - Memory/storage layer
      - Persona configuration and loading
    - Record:
      - Paths to key files
      - How configuration is loaded (env, config file, DB)
      - How auth/secrets are handled

    **Success criteria**
    - You can explain “how a message becomes tool calls and responses” in Billy with file references.

    ### 0.2 — Identify Agent Zero’s runtime entrypoints
    - Find:
      - Main app entrypoint
      - Agent loop
      - Tool registry
      - Memory subsystem
      - UI and API boundaries
    - Record:
      - How tools are defined and discovered
      - How tools run (local process, container, remote)
      - Any built-in sandbox policies

    **Success criteria**
    - You can explain Agent Zero’s “happy path” execution flow with file references.

    ### 0.3 — Dependency and coupling scan (both repos)
    For each repo:
    - Identify:
      - Core dependencies (LLM SDKs, vector DB, web framework, queue, etc.)
      - OS-level dependencies (docker, chromium, ffmpeg, etc.)
      - Tight couplings (UI coupled to runtime; tool impl coupled to agent loop)

    **Success criteria**
    - You know what can be imported as a library vs what is app-embedded.

    ### 0.4 — Produce a candidate reuse list
    Create a table in `artifacts/reuse-candidates.md` with columns:
    - Component (name)
    - Repo (Billy / Agent Zero)
    - Location (paths)
    - What it does
    - Reuse value
    - Integration approach (adapter/vendor/dependency/re-implement)
    - Risks

    **Success criteria**
    - At least 5–15 candidates are listed, with realistic integration approaches.

    ## Definition of Done (DoD)
    - Inventory docs exist and are accurate.
    - Key runtime flows are mapped to actual source files.
    - Candidate reuse list exists with initial scoring.

    ## Risks & mitigations
    - Risk: Misidentifying “core loop” due to indirection.
      - Mitigation: Run the app with debug logs and trace a single request end-to-end.
    - Risk: Underestimating coupling.
      - Mitigation: Build a minimal spike import of one candidate module in isolation.