## 1. Core Architectural Principle
Billy v2 is built on a strict separation between reasoning and execution. Reasoning modes can analyze, explain, and draft, while execution-capable modes can only act after explicit gates are satisfied.

Explicit gating exists to keep authority with the human and to make every state transition auditable. Execution power is never implied by context, intent, or prior interaction.

Inference is intentionally avoided for power transitions. The system does not infer permission, does not infer unsafe actions, and does not infer execution parameters when a gate is required.

## 2. System Pipeline Overview
The architecture is organized as a staged pipeline with one code path and one tool path:

ERM -> CDM -> APP -> CAM  
           ↘  
            TDM -> Tool Approval -> TRM -> TEM

The branch starts after reasoning and drafting because code artifacts and tool artifacts are governed differently. The pipeline reconverges at the same control model: explicit approval, immutable records, and gated execution.

Code execution authority is isolated in CAM. Tool execution authority is isolated in TEM. Registration (TRM) is intentionally separate from execution (TEM) so visibility does not imply power.

## 3. Mode Responsibilities
### ERM
Allowed:
- Analyze system behavior and constraints in read-only form
- Produce structured engineering reasoning

Forbidden:
- File mutation
- Tool execution
- State mutation
- Privilege escalation

### CDM
Allowed:
- Produce immutable code draft artifacts
- Define proposed file operations as draft payloads
- Produce deterministic draft hashes

Forbidden:
- Applying code
- Executing code
- Implicitly expanding scope beyond the draft artifact

### APP
Allowed:
- Validate and approve immutable code drafts
- Record append-only approval artifacts

Forbidden:
- Applying approved code
- Mutating approved records
- Approving non-draft or drifted artifacts

### CAM
Allowed:
- Apply approved code drafts after validation gates pass
- Enforce scope boundaries defined by the approved draft
- Record append-only application attempts

Forbidden:
- Applying unapproved drafts
- Scope expansion beyond approved file operations
- Implicit retries, autonomous healing, or ungated execution

### TDM
Allowed:
- Produce immutable tool definition drafts
- Define tool contract, side effects, and safety constraints
- Produce canonical tool draft hashes

Forbidden:
- Tool registration
- Tool execution
- Runtime wiring changes through draft generation

### Tool Approval
Allowed:
- Validate and approve immutable tool definition drafts
- Record append-only tool approval artifacts

Forbidden:
- Registering tools
- Executing tools
- Approving drifted or non-TDM artifacts

### TRM
Allowed:
- Register approved tool definitions into internal inventory
- Mark tools as visible metadata for reasoning and drafting
- Persist append-only registration audit records

Forbidden:
- Tool execution
- Implicit permission grants
- Runtime behavior changes beyond inert registration metadata

### TEM
Allowed:
- Execute registered and approved tools only after full validation and explicit confirmation
- Validate payload schema and declared side-effect scope before execution
- Record append-only tool execution forensics

Forbidden:
- Execution without confirmation
- Tool chaining
- Parameter inference
- Silent retries or autonomous fallback behavior

## 4. Execution Invariants
Non-negotiable invariants:
- Execution authority is mode-bound and never inferred
- Immutable artifact hashes must match before approval or execution
- Approval records and execution records are append-only
- Registered does not mean executable
- Visibility does not mean permission
- Missing any gate hard-stops execution

Tool execution invariant:
- approved -> registered -> invoked -> validated -> confirmed -> executed

If any stage is absent, mismatched, stale, or drifted, execution is rejected.

## 5. Safety and Audit Model
Billy uses append-only audit structures for approvals, applications, registrations, and executions. These records capture decision points and outcomes without destructive updates.

Canonical hashing is used to verify artifact integrity. Code drafts and tool drafts are validated against stored hashes before approval and again before power-granting transitions.

Immutability is enforced at the artifact level. Draft content is treated as frozen once created; approval and execution gates depend on identity and hash stability. New intent requires a new artifact identity.

## 6. Frozen Ground Rule
These modes are stable infrastructure. Their boundaries, gate semantics, and authority model are treated as foundational behavior.

New behavior must be introduced as new modes or explicitly scoped protocol extensions. Existing modes must not be implicitly repurposed, expanded, or relaxed.

## 7. What This Architecture Enables
This structure provides deterministic control over where execution power lives and when it is reachable. Reasoning can evolve without automatically increasing execution authority.

It enables safe growth by isolating responsibilities, preserving audit trails, and making authority transitions explicit. It also allows new capabilities to be added without destabilizing existing safety boundaries.
