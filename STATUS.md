# Billy Status Snapshot

## Current Maturity
- Level: 29 (`Inspection Dispatch Boundary`)
- Current frozen release tag: `maturity-level-29`
- Phase 29 freeze state: frozen (specification-only)
- Conceptual ladder placement (`MATURITY_MODEL.md`): Level 4 (`Structured Workflow`)

## Frozen Phases
- Phases 1-29 are frozen infrastructure.
- Any behavioral change requires explicit maturity promotion and acceptance.

## Current Governance Posture
- All user input routes through governed interpretation and deterministic policy.
- Mutating actions remain approval-gated with exact approval phrases.
- Content capture is explicit; generation is review-only unless routed to governed execution.
- Project lifecycle now includes goals, tasks, milestones, completion checks, finalization, and archival.
- Delegation is governed via static capability contracts and approval-gated orchestration.
- Workflow orchestration is project-scoped, previewable, approval-gated, and step-audited.
- Conversational front-end routing now separates chat (`escalate: false`) from governed escalation (`escalate: true`) before interpreter execution.
- Explicit inspection capabilities are read-only, bounded, symlink-safe, and authority-sealed (`inspect_file`, `inspect_directory`).
- Inspection dispatch boundary is explicit and binding-driven: inspection outputs are inert unless explicitly bound, with no ambient context carryover, silent persistence, or authority escalation.
- Phase 27 promotion evidence is recorded in `PHASE27_PROMOTION_CHECKLIST.md`.
- Phase 28 promotion evidence is recorded in `docs/PHASE28_PROMOTION_CHECKLIST.md`.
- Phase 29 promotion evidence is recorded in `docs/PHASE29_PROMOTION_CHECKLIST.md`.

## Approval Contract
Allowed approval phrases (case-insensitive exact match):
- `yes, proceed`
- `approve`
- `approved`
- `go ahead`
- `do it`

## Deprecated Inputs
Informational only (non-blocking):
- `/engineer`
- `engineer mode`

## Required Handoff Discipline
Before code changes, execute the onboarding pre-read in `ONBOARDING.md` (which now starts with `AGENTS.md`) and verify:
1. `README.md` current maturity and behavior contract
2. `STATUS.md` current release target and freeze state
3. `MATURITY.md` frozen behavior boundaries

## Contracts Index
- `v2/contracts/intent_policy_rules.yaml`
- `v2/contracts/intent_tool_contracts.yaml`
- `v2/contracts/delegation_capabilities.yaml`
