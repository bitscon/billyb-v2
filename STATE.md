## Purpose
This file is the current-state handoff for Billy v2. It is the authoritative snapshot of where work stands now, what is frozen, what is deferred, and how to resume safely after context loss.

## Current System Status
- Declared maturity: Level 27 (`Conversational Front-End & Interpreter Gate`), intended tag `maturity-level-27`.
- All core governed modes are implemented and active in the runtime boundary model.
- Execution power is explicitly gated; no implicit execution paths are allowed by design.
- Code and tool actions are approval-driven, hash-validated, and confirmation-gated where required.
- Registration and visibility are separated from executability.
- Conversational front-end routing now separates chat (`escalate: false`) from governed escalation (`escalate: true`) before interpreter execution.
- Latest baseline validation in this environment: targeted Phase 27 suites pass and default `pytest -q` suite passes.

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
The most recent implemented working edge is Level 27 (`Conversational Front-End & Interpreter Gate`, draft/in-progress). This adds a secretary-style conversational layer that classifies chat vs escalation while preserving governed enforcement boundaries.

## Recommended Next Directions
- Formalize Phase 27 promotion criteria and freeze acceptance evidence.
- Expand conversational escalation patterns with contract-backed fixtures while preserving no-authority guarantees.
- Keep policy, approval, and execution authority exclusively in governed interpreter paths.
- Continue maturity-sync hygiene (`MATURITY.md`, `STATUS.md`, `STATE.md`, `ONBOARDING.md`) in each phase increment.

## How to Resume Work
- Read `ONBOARDING.md` first.
- Read `ONBOARDING_AGENTS.md` for escalation strategy guidance.
- Read `README.md`.
- Read `ARCHITECTURE.md`.
- Read `CAPABILITIES.md`.
- Then use this file as the current truth for session handoff, frozen boundaries, and active deferrals.
