## 1. Purpose
This maturity model defines how Billy’s authority should expand over time, and under what conditions. It provides a planning framework for adding capability without weakening control, auditability, or safety boundaries.

## 2. Introduction to Maturity Models
Maturity models describe staged capability growth where each level adds authority only after lower-level controls are stable and measurable. For general concepts, see [maturity model](https://en.wikipedia.org/wiki/Maturity_model) and [Capability Maturity Model Integration (CMMI)](https://en.wikipedia.org/wiki/Capability_Maturity_Model_Integration).

## 3. Billy’s Maturity Ladder — Conceptual Levels
Levels in this file are conceptual macro-levels. Implementation release levels and tags are defined in `MATURITY.md`.
### 3.1 Level 1 — Augmented Reasoning
- Key authority boundary:
  Reasoning is allowed; state-changing action is not.
- Can:
  Analyze, explain, compare options, and identify risk.
- Cannot:
  Draft executable artifacts, approve, apply, register, or execute anything.

### 3.2 Level 2 — Controlled Drafting
- Key authority boundary:
  Drafting is allowed; drafts remain inert until explicit approval.
- Can:
  Produce structured draft artifacts with clear scope and declared intent.
- Cannot:
  Convert drafts into actions, bypass approval, or mutate system state.

### 3.3 Level 3 — Explicit Action
- Key authority boundary:
  Action is possible only from approved artifacts under strict gate checks.
- Can:
  Perform bounded actions when explicit approval and integrity checks pass.
- Cannot:
  Infer intent, expand scope, or execute without explicit action triggers.

### 3.4 Level 4 — Structured Workflow
- Key authority boundary:
  Multiple governed pipelines can coexist while preserving explicit gates.
- Can:
  Support end-to-end governed flows for code and tool lifecycles with audit logs and immutable checkpoints.
- Cannot:
  Collapse stages, treat registration as execution permission, or skip confirmation where required.

### 3.5 Level 5 — Safe Autonomy
- Key authority boundary:
  Limited autonomous behavior is policy-scoped, reversible, and continuously audited.
- Can:
  Execute pre-authorized classes of actions within strict policy envelopes and runtime controls.
- Cannot:
  Change policy scope, self-grant authority, or run outside defined guardrails.

### 3.6 Level 6 — Full Autonomous Operation
- Key authority boundary:
  End-to-end autonomous planning and execution under formal governance.
- Can:
  Orchestrate complex, multi-step operations with minimal human intervention while maintaining compliance evidence.
- Cannot:
  Operate without accountability, observability, and externally enforced control boundaries.

## 4. Key Principles of the Maturity Ladder
- Incremental authority:
  Authority increases one stage at a time; no stage-skipping.
- Preservation of human control:
  Human approval remains the primary authority handoff for power transitions.
- Auditable transitions:
  Every authority increase and execution event must be traceable and reviewable.
- Gate enforcement:
  Missing or failed gates must hard-stop progression and action.
- Integrity before power:
  Immutable artifacts and hash validation are prerequisites for higher-authority actions.

## 5. Current Placement and Crosswalk
Billy currently fits **Conceptual Level 4 — Structured Workflow**.

Implementation crosswalk:
- Current implementation maturity (`MATURITY.md`): **Level 27 — Conversational Front-End & Interpreter Gate (draft/in progress)**
- Mapping rule: implementation Levels `9` through `27` map to conceptual Level `4`
- Conceptual Levels `5` and `6` remain future-state targets

Justification:
- Governed reasoning, drafting, approval, application, tool definition, tool approval, registration, and confirmation-gated execution are in place.
- Conversational front-end secretary routing is in place while governed policy/approval/execution authority remains unchanged.
- Authority transitions are explicit and auditable.
- Registration and visibility are separated from executability.
- Autonomous operation is not enabled.

## 6. Practical Next Steps
### 6.1 Level 4 -> Level 5 (Structured Workflow to Safe Autonomy)
- Must be true:
  Policy-scoped autonomous envelopes are formally defined, testable, and externally reviewable.
- Checkpoints:
  - Zero unauthorized execution events over sustained runs.
  - Deterministic policy evaluation outcomes across repeated test scenarios.
  - Complete audit coverage for every autonomous decision boundary.
  - Proven rollback/containment behavior for policy breaches.

### 6.2 Level 5 -> Level 6 (Safe Autonomy to Full Autonomous Operation)
- Must be true:
  Autonomous planning and execution are reliable across broad operational contexts with enforceable governance.
- Checkpoints:
  - Stable success/failure classification with low ambiguity in high-stakes workflows.
  - End-to-end explainability for autonomous decisions and outcomes.
  - Independent governance controls that can pause, constrain, or revoke autonomy immediately.
  - Continuous compliance evidence demonstrating control durability at scale.
