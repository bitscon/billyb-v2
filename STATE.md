## Purpose
This file is the current-state handoff for Billy v2. It is the authoritative snapshot of where work stands now, what is frozen, what is deferred, and how to resume safely after context loss.

## Current System Status
- Declared maturity baseline: Level 28 (`Explicit Read-Only Inspection Capabilities`, frozen).
- Current frozen release tag: `maturity-level-28` (Phases 1-28).
- All core governed modes are implemented and active in the runtime boundary model.
- Execution power is explicitly gated; no implicit execution paths are allowed by design.
- Code and tool actions are approval-driven, hash-validated, and confirmation-gated where required.
- Registration and visibility are separated from executability.
- Conversational front-end routing now separates chat (`escalate: false`) from governed escalation (`escalate: true`) before interpreter execution.
- Explicit inspection capabilities (`inspect_file`, `inspect_directory`) are read-only, bounded, symlink-safe, and authority-sealed.
- Latest baseline validation in this environment: targeted Phase 28 inspection suites pass with Phase 27 boundary preservation suites.

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
Phase 28 (`Explicit Read-Only Inspection Capabilities`) is now frozen. Inspection can observe file/directory state under strict read-only contracts without mutating state, escalating authority, or injecting conversational context.

## Recommended Next Directions
- Begin Phase 29 planning as a forward-only maturity increment.
- Preserve Phase 27 conversational non-authority guarantees and Phase 28 inspection non-escalation/non-mutation guarantees during future promotion.
- Keep policy, approval, and execution authority exclusively in governed interpreter paths.
- Continue maturity-sync hygiene (`MATURITY.md`, `STATUS.md`, `STATE.md`, `ONBOARDING.md`) in each phase increment.

## How to Resume Work
- Read `ONBOARDING.md` first.
- Read `ONBOARDING_AGENTS.md` for escalation strategy guidance.
- Read `README.md`.
- Read `ARCHITECTURE.md`.
- Read `CAPABILITIES.md`.
- Then use this file as the current truth for session handoff, frozen boundaries, and active deferrals.
