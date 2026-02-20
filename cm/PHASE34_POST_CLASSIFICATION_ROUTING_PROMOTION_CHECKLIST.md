# Phase 34 Post-Classification Routing Promotion Checklist

## Purpose
This checklist defines promotion criteria for Phase 34 (`Post-Classification Routing Contracts`) as specification-only governance infrastructure.

Phase 34 defines admissible internal routing categories based on classified intent while remaining strictly non-executing and non-authoritative.

## Scope
Phase 34 is specification-only.

Phase 34 allows:
- closed routing-category definitions,
- intent-to-routing compatibility mapping,
- deterministic routing-contract validation and rejection semantics,
- evidence planning for promotion.

Phase 34 does not allow:
- execution enablement,
- tool invocation,
- permissioning or authorization logic,
- authority expansion.

## Phase 34 Status
- Level 34 status: draft (specification-only, not frozen)
- Contract artifact: `post_classification_routing_contract.v1`
- Runtime delta: none
- Authority delta: none

## Canonical Preservation Note
- [x] Existing `docs/PHASE34_PROMOTION_CHECKLIST.md` remains unchanged as historical pre-definition material.
- [x] This checklist is the canonical promotion checklist for Phase 34 post-classification routing contracts.

## Hard Invariants
- [x] Routing requires valid `intent_classification_record.v1` reference.
- [x] Routing requires Phase 33 classification-first enforcement precondition.
- [x] Exactly one routing category is selected per utterance.
- [x] Selected category MUST be permitted for classified intent.
- [x] Unknown intent maps only to safe subset (`clarification_response`, `refusal_required`).
- [x] Routing categories remain descriptive and non-executable.
- [x] `execution_enabled` remains `false`.
- [x] `authority_guarantees` remain all `false`.

## Deterministic Validation Order
- [x] Step 1: Validate classification reference exists and is valid.
- [x] Step 2: Validate classification-first enforcement reference and pass state.
- [x] Step 3: Validate intent class in closed Phase 32 enum.
- [x] Step 4: Validate selected category is in closed Phase 34 category enum.
- [x] Step 5: Validate selected category is allowed for intent per compatibility matrix.
- [x] Step 6: Reject execution/tool/permissioning semantics.
- [x] Step 7: Validate authority guarantees and execution-disabled constants.

## Deterministic Rejection Codes (Priority Order)
- [x] `ROUTING_SCHEMA_INVALID`
- [x] `ROUTING_PRECONDITION_MISSING_CLASSIFICATION`
- [x] `ROUTING_PRECONDITION_INVALID_CLASSIFICATION`
- [x] `ROUTING_CLASS_NOT_IN_CLOSED_SET`
- [x] `ROUTING_CATEGORY_NOT_ALLOWED_FOR_INTENT`
- [x] `ROUTING_CATEGORY_UNKNOWN`
- [x] `ROUTING_EXECUTION_SEMANTICS_FORBIDDEN`
- [x] `ROUTING_TOOL_SELECTION_FORBIDDEN`
- [x] `ROUTING_PERMISSIONING_SEMANTICS_FORBIDDEN`
- [x] `AUTHORITY_FALSE_GUARANTEE_VIOLATION`
- [x] `EXECUTION_ENABLED_VIOLATION`

## Prohibition Gates (Promotion Blockers)
Promotion MUST be blocked if any condition is true:
- [x] Routing occurs without valid classification.
- [x] Routing occurs without Phase 33 ordering precondition.
- [x] Selected category exceeds intent permission in compatibility matrix.
- [x] Routing artifact encodes execution or tool-selection metadata.
- [x] Routing artifact encodes permissioning/authorization metadata.
- [x] Unknown intent maps outside safe subset.

## Regression Preservation Requirements
- [x] Phase 32 classification-only semantics remain unchanged.
- [x] Phase 33 classification-first ordering remains unchanged.
- [x] Phase 33 leakage boundaries remain unchanged.

## Test Planning Requirements (No Test Implementation in Phase 34)
Required future validation scenarios:
- [x] Ordering tests: routing blocked without valid classification.
- [x] Compatibility tests: each intent only allows mapped categories.
- [x] Safe-subset tests for `unknown_intent`.
- [x] Rejection tests for out-of-matrix category selections.
- [x] Rejection tests for execution/tool/permissioning metadata presence.
- [x] Regression tests preserving Phase 32-33 guarantees.

## Promotion Evidence Requirements
Promotion to frozen Phase 34 requires:
1. Canonical Phase 34 spec artifact approved.
2. Canonical routing categories and compatibility matrix approved.
3. Canonical boundary and violation rules approved.
4. Normative `post_classification_routing_contract.v1` schema approved.
5. Deterministic validation/rejection evidence plan mapped to test scenarios.
6. Explicit sign-off that Phase 34 introduces no execution, tooling, or authority expansion.
