## Purpose
This file is the current-state handoff for Billy v2. It is the authoritative snapshot of where work stands now, what is frozen, what is deferred, and how to resume safely after context loss.

## Current System Status
- Declared maturity baseline: Level 29 (`Inspection Dispatch Boundary`, frozen; specification-only).
- Current frozen release tag: `maturity-level-29` (Phases 1-29).
- All core governed modes are implemented and active in the runtime boundary model.
- Execution power is explicitly gated; no implicit execution paths are allowed by design.
- Code and tool actions are approval-driven, hash-validated, and confirmation-gated where required.
- Registration and visibility are separated from executability.
- Conversational front-end routing now separates chat (`escalate: false`) from governed escalation (`escalate: true`) before interpreter execution.
- Explicit inspection capabilities (`inspect_file`, `inspect_directory`) are read-only, bounded, symlink-safe, and authority-sealed.
- Phase 29 dispatch boundary is frozen specification behavior: inspection outputs stay inert unless explicitly bound for reasoning consumption.
- Latest runtime baseline validation in this environment remains Phase 28 targeted inspection suites with Phase 27 boundary preservation suites (Phase 29 introduced no runtime changes).

## Frozen Infrastructure
- ERM
- CDM
- APP
- CAM
- TDM
- Tool Approval
- TRM
- TEM
- Supporting safety contracts around explicit invocation, gating, hashing, append-only audit logging, and confirmation flow

Frozen items must not be modified implicitly. Any change to frozen infrastructure requires explicit instruction and a new accepted change cycle.

## Actively Deferred or Not Implemented
- Autonomous execution or self-directed task selection
- Tool chaining or multi-tool orchestration
- Background execution, scheduling, or queued task runners
- Implicit parameter inference for execution-capable actions
- Automatic workflow orchestration across modes
- CMDB-style inventory integration and external observability platform integration

These are conscious deferrals, not accidental omissions.

## Last Major Milestone
Phase 29 (`Inspection Dispatch Boundary`) is now frozen as specification-only infrastructure. Inspection outputs can be consumed downstream only via explicit structured binding, with no ambient context carryover, no silent persistence, and no authority expansion.

## Recommended Next Directions
- Begin Phase 30 planning as a forward-only maturity increment.
- Preserve Phase 27 conversational non-authority guarantees, Phase 28 inspection non-escalation/non-mutation guarantees, and Phase 29 explicit inspection dispatch boundary guarantees during future promotion.
- Keep policy, approval, and execution authority exclusively in governed interpreter paths.
- Continue maturity-sync hygiene (`MATURITY.md`, `STATUS.md`, `STATE.md`, `ONBOARDING.md`) in each phase increment.

## How to Resume Work
- Read `ONBOARDING.md` first.
- Read `ONBOARDING_AGENTS.md` for escalation strategy guidance.
- Read `README.md`.
- Read `ARCHITECTURE.md`.
- Read `CAPABILITIES.md`.
- Then use this file as the current truth for session handoff, frozen boundaries, and active deferrals.
