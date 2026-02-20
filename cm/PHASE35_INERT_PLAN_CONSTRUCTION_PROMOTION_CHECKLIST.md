# Phase 35 Inert Plan Construction Promotion Checklist

## Purpose
This checklist defines promotion criteria for Phase 35 (`Inert Plan Construction`) as specification-only governance infrastructure.

Phase 35 defines when inert plan artifacts may be constructed without execution, tooling, scheduling, permissioning, or authority expansion.

## Scope
Phase 35 is specification-only.

Phase 35 allows:
- inert plan artifact construction contracts,
- descriptive planning semantics,
- deterministic boundary and rejection semantics,
- evidence planning for promotion.

Phase 35 does not allow:
- execution enablement,
- tool invocation,
- scheduling or delayed execution semantics,
- permissioning or authorization logic,
- side effects.

## Phase 35 Status
- Level 35 status: draft (specification-only, not frozen)
- Contract artifact: `inert_plan_artifact.v1`
- Runtime delta: none
- Authority delta: none

## Canonical Preservation Note
- [x] Existing `docs/PHASE35_PROMOTION_CHECKLIST.md` remains unchanged as historical pre-definition material.
- [x] This checklist is the canonical promotion checklist for Phase 35 inert plan construction.

## Hard Invariants
- [x] Plan construction requires valid `intent_classification_record.v1` reference.
- [x] Plan construction requires valid `post_classification_routing_contract.v1` reference.
- [x] Plan construction requires `selected_routing_category = planning_candidate`.
- [x] Plan artifact is descriptive, inert, and non-authoritative.
- [x] Plan artifact MUST NOT contain commands, tool references, API invocations, credentials, or scheduling directives.
- [x] `execution_enabled` remains `false`.
- [x] `authority_guarantees` remain all `false`.

## Deterministic Validation Order
- [x] Step 1: Validate classification reference exists and is valid.
- [x] Step 2: Validate routing reference exists and is valid.
- [x] Step 3: Validate routing category is plan-compatible (`planning_candidate`).
- [x] Step 4: Validate plan structure and descriptive-only step semantics.
- [x] Step 5: Reject executable/tool/scheduling/credential content.
- [x] Step 6: Validate authority guarantees and execution-disabled constants.

## Deterministic Rejection Codes (Priority Order)
- [x] `PLAN_SCHEMA_INVALID`
- [x] `PLAN_PRECONDITION_MISSING_CLASSIFICATION_REFERENCE`
- [x] `PLAN_PRECONDITION_INVALID_CLASSIFICATION_REFERENCE`
- [x] `PLAN_PRECONDITION_MISSING_ROUTING_REFERENCE`
- [x] `PLAN_PRECONDITION_INVALID_ROUTING_REFERENCE`
- [x] `PLAN_ROUTING_CATEGORY_NOT_PLAN_COMPATIBLE`
- [x] `PLAN_ROUTING_CONSTRAINT_BYPASS_FORBIDDEN`
- [x] `PLAN_EXECUTABLE_CONTENT_FORBIDDEN`
- [x] `PLAN_TOOL_REFERENCE_FORBIDDEN`
- [x] `PLAN_SCHEDULING_CONTENT_FORBIDDEN`
- [x] `PLAN_CREDENTIAL_CONTENT_FORBIDDEN`
- [x] `AUTHORITY_FALSE_GUARANTEE_VIOLATION`
- [x] `EXECUTION_ENABLED_VIOLATION`

## Prohibition Gates (Promotion Blockers)
Promotion MUST be blocked if any condition is true:
- [x] Plan is constructed without required classification/routing references.
- [x] Plan construction bypasses routing-category compatibility.
- [x] Plan includes executable instructions or runnable content.
- [x] Plan includes tool/API invocation semantics.
- [x] Plan includes credential/secret/token content.
- [x] Plan includes scheduling or delayed execution semantics.
- [x] Plan artifacts imply authority, permissioning, or authorization state.

## Regression Preservation Requirements
- [x] Phase 32 classification-only semantics remain unchanged.
- [x] Phase 33 classification-first ordering remains unchanged.
- [x] Phase 34 routing-category non-execution semantics remain unchanged.

## Test Planning Requirements (No Test Implementation in Phase 35)
Required future validation scenarios:
- [x] Preconditions tests: block plan construction without valid classification/routing references.
- [x] Routing-compatibility tests: only `planning_candidate` allows plan construction.
- [x] Content-safety tests: reject commands/tool/API/scheduling/credential content.
- [x] Inertness tests: verify no execution or authority fields can appear in valid artifacts.
- [x] Determinism tests: rejection code priority and fail-closed behavior.
- [x] Regression tests preserving Phase 32-34 guarantees.

## Promotion Evidence Requirements
Promotion to frozen Phase 35 requires:
1. Canonical Phase 35 spec artifact approved.
2. Canonical plan-semantics and content-boundary artifact approved.
3. Canonical boundary and violation rules artifact approved.
4. Normative `inert_plan_artifact.v1` schema approved.
5. Deterministic validation/rejection evidence plan mapped to test scenarios.
6. Explicit sign-off that Phase 35 introduces no execution, tooling, scheduling, or authority expansion.
