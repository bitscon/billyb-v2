# Phase 36 Action Proposal Promotion Checklist

## Purpose
This checklist defines promotion criteria for Phase 36 (`Action Proposal Artifacts`) as specification-only governance infrastructure.

Phase 36 defines inert, reviewable proposal artifacts that are explicitly unapproved and non-executable.

## Scope
Phase 36 is specification-only.

Phase 36 allows:
- inert proposal artifact construction contracts,
- descriptive proposal semantics,
- deterministic boundary and rejection semantics,
- evidence planning for promotion.

Phase 36 does not allow:
- execution enablement,
- tool invocation,
- scheduling semantics,
- permissioning or approval authority,
- autonomy expansion.

## Phase 36 Status
- Level 36 status: draft (specification-only, not frozen)
- Contract artifact: `action_proposal_artifact.v1`
- Runtime delta: none
- Authority delta: none

## Canonical Preservation Note
- [x] Existing `docs/PHASE36_PROMOTION_CHECKLIST.md` remains unchanged as historical pre-definition material.
- [x] This checklist is the canonical promotion checklist for Phase 36 action proposal artifacts.

## Hard Invariants
- [x] Proposal requires valid `inert_plan_artifact.v1` reference.
- [x] Proposal requires valid `intent_classification_record.v1` reference.
- [x] Proposal requires plan-compatible routing context (`planning_candidate`).
- [x] Proposal MUST be explicitly marked `unapproved`.
- [x] Proposal MUST remain inert, descriptive, and non-authoritative.
- [x] Proposal MUST NOT contain commands, tools, API invocations, credentials, or scheduling directives.
- [x] `execution_enabled` remains `false`.
- [x] `authority_guarantees` remain all `false`.

## Deterministic Validation Order
- [x] Step 1: Validate classification reference exists and is valid.
- [x] Step 2: Validate routing reference exists and is valid.
- [x] Step 3: Validate inert plan reference exists and is valid.
- [x] Step 4: Validate plan and routing compatibility constraints.
- [x] Step 5: Validate explicit unapproved marker.
- [x] Step 6: Reject approval/execution/tool/scheduling/credential content.
- [x] Step 7: Validate authority guarantees and execution-disabled constants.

## Deterministic Rejection Codes (Priority Order)
- [x] `PROPOSAL_SCHEMA_INVALID`
- [x] `PROPOSAL_PRECONDITION_MISSING_CLASSIFICATION_REFERENCE`
- [x] `PROPOSAL_PRECONDITION_INVALID_CLASSIFICATION_REFERENCE`
- [x] `PROPOSAL_PRECONDITION_MISSING_ROUTING_REFERENCE`
- [x] `PROPOSAL_PRECONDITION_INVALID_ROUTING_REFERENCE`
- [x] `PROPOSAL_PRECONDITION_MISSING_PLAN_REFERENCE`
- [x] `PROPOSAL_PRECONDITION_INVALID_PLAN_REFERENCE`
- [x] `PROPOSAL_PLAN_ROUTING_NOT_COMPATIBLE`
- [x] `PROPOSAL_PLAN_ROUTING_CONSTRAINT_BYPASS_FORBIDDEN`
- [x] `PROPOSAL_APPROVAL_STATE_INVALID`
- [x] `PROPOSAL_APPROVAL_IMPLICATION_FORBIDDEN`
- [x] `PROPOSAL_EXECUTION_IMPLICATION_FORBIDDEN`
- [x] `PROPOSAL_EXECUTABLE_CONTENT_FORBIDDEN`
- [x] `PROPOSAL_TOOL_REFERENCE_FORBIDDEN`
- [x] `PROPOSAL_SCHEDULING_CONTENT_FORBIDDEN`
- [x] `PROPOSAL_CREDENTIAL_CONTENT_FORBIDDEN`
- [x] `AUTHORITY_FALSE_GUARANTEE_VIOLATION`
- [x] `EXECUTION_ENABLED_VIOLATION`

## Prohibition Gates (Promotion Blockers)
Promotion MUST be blocked if any condition is true:
- [x] Proposal constructed without required plan/classification references.
- [x] Proposal bypasses routing or plan constraints.
- [x] Proposal implies approval or authorization grant.
- [x] Proposal implies execution readiness or action application.
- [x] Proposal includes executable/tool/API/scheduling/credential content.
- [x] Proposal artifacts imply autonomy expansion.

## Regression Preservation Requirements
- [x] Phase 32 classification-only semantics remain unchanged.
- [x] Phase 33 classification-first ordering remains unchanged.
- [x] Phase 34 routing-category constraints remain unchanged.
- [x] Phase 35 inert plan constraints remain unchanged.

## Test Planning Requirements (No Test Implementation in Phase 36)
Required future validation scenarios:
- [x] Preconditions tests: block proposal construction without valid plan/classification/routing references.
- [x] Unapproved-state tests: reject proposal artifacts without explicit unapproved state.
- [x] Content-safety tests: reject approval/execution/tool/scheduling/credential semantics.
- [x] Constraint-coherence tests: reject plan/routing bypass.
- [x] Inertness tests: verify valid proposals remain non-executable and non-authoritative.
- [x] Determinism tests: rejection-code priority and fail-closed behavior.
- [x] Regression tests preserving Phase 32-35 guarantees.

## Promotion Evidence Requirements
Promotion to frozen Phase 36 requires:
1. Canonical Phase 36 spec artifact approved.
2. Canonical proposal-semantics and content-boundary artifact approved.
3. Canonical boundary and violation rules artifact approved.
4. Normative `action_proposal_artifact.v1` schema approved.
5. Deterministic validation/rejection evidence plan mapped to test scenarios.
6. Explicit sign-off that Phase 36 introduces no execution, tooling, scheduling, permissioning, approval authority, or autonomy expansion.
