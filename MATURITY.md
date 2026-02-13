# Billy Maturity Snapshot

## Release
- Tag: `maturity-level-10`
- Status: `Level 10 - Unified Conversational Governance` achieved

## Current Maturity
Billy is operating at Level 10 with end-to-end governed conversational routing.

## Phase Summary (1-9)
1. `Phase 1 - Deterministic Interpreter`
   Deterministic intent envelope generation.
2. `Phase 2 - Semantic Lane Routing`
   Lane classification with confidence threshold and mandatory deterministic fallback.
3. `Phase 3 - Structured Intent Extraction`
   Schema-validated JSON extraction (`intent`, `entities`, `confidence`) with bounded retries and fallback.
4. `Phase 4 - Deterministic Policy Evaluation`
   Deterministic policy decisions (`allowed`, `risk_level`, `requires_approval`) with optional explanation-only LLM path.
5. `Phase 5 - Explicit Conversational Approval Gating`
   Pending-action lifecycle, exact approval phrases, TTL, single-use approval, single-shot execution gate.
6. `Phase 6 - Contract-Bound Tool Execution`
   Static intent-to-tool contracts with typed, stubbed execution backend and auditable events.
7. `Phase 7 - Append-Only Memory`
   Append-only memory recording for execution attempts plus deterministic recall APIs.
8. `Phase 8 - Approval-Gated Multi-Step Planning`
   Plan construction as explicit data; step/plan approval modes; ordered execution through existing gates.
9. `Phase 9 - Conversational Entrypoint Unification`
   Unified conversational routing through governed pipeline; deprecated engineer-mode inputs are informational only.

## Maturity Level 9 — Approval-Gated Planning & Execution (Frozen)
Capabilities:
- Multi-step plan construction with contract-mapped steps
- Approval-gated ordered execution
- Per-step auditable execution and memory recording

Status:
Frozen infrastructure. No dynamic replanning, auto-retry, or implicit step skipping.

## Maturity Level 10 — Unified Conversational Governance (Frozen)
Capabilities:
- All conversational input is governed through a single entrypoint
- Natural-language action requests route to policy + approval flow
- Legacy engineer-mode inputs are deprecated and non-blocking
- Ambiguous input routes to `CLARIFY`, not legacy rejection

Status:
Frozen UX/governance infrastructure. No legacy mode revival or shortcut authority paths.

## Freeze Policy
Once a phase is approved and frozen:
- No tuning, heuristic expansion, or semantic drift is allowed in that phase.
- Any change requires explicit maturity promotion and acceptance.
- Freeze applies to behavior, gates, and user-facing governance semantics.

## Docs Gate (Required for Every Future Phase)
A phase/PR is incomplete unless it includes:
- `README.md` update
- `MATURITY.md` update
- Onboarding update when user-facing behavior changes
- Test proof that behavior and docs are aligned

## Contracts Index
- `v2/contracts/intent_policy_rules.yaml`
  Deterministic policy rules keyed by `lane::intent`.
- `v2/contracts/intent_tool_contracts.yaml`
  Static intent-to-tool contract mapping used by governed execution.
