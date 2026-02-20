# Phase 32 Intent Classification Promotion Checklist

## Purpose
This checklist defines promotion criteria for Phase 32 (`Intent Classification Completeness`) as specification-only governance infrastructure.

Phase 32 establishes a closed, deterministic, classification-only intent layer that MUST classify each utterance before governed influence is possible.

## Scope
Phase 32 is specification-only.

Phase 32 allows:
- Intent taxonomy definition.
- Classification contract definition.
- Deterministic fail-closed ambiguity handling.
- Promotion evidence planning.

Phase 32 does not allow:
- Runtime behavior change.
- Tool additions.
- Authority expansion.
- Routing, permissioning, authorization, or execution decisions in classification artifacts.

## Phase 32 Status
- Level 32 status: draft (specification-only, not frozen)
- Contract artifact: `intent_classification_record.v1`
- Runtime delta: none
- Authority delta: none

## Canonical Preservation Note
- [x] Existing `docs/PHASE32_PROMOTION_CHECKLIST.md` remains unchanged as historical pre-definition material.
- [x] This checklist is the canonical promotion checklist for Phase 32 intent-classification completeness.

## Hard Invariants
- [x] Every utterance MUST be classified before governed influence.
- [x] Exactly one class MUST be assigned from the closed taxonomy.
- [x] Unknown or unresolved ambiguity MUST fail closed as `unknown_intent`.
- [x] Classification records MUST remain classification-only.
- [x] Classification records MUST NOT encode routing or permissioning outcomes.
- [x] `execution_enabled` MUST remain `false`.
- [x] `authority_guarantees` MUST remain all `false`.
- [x] Classification artifacts are immutable and append-only by governance semantics.

## Deterministic Validation Order
- [x] Step 1: Validate schema shape and required fields.
- [x] Step 2: Reject forbidden routing/permissioning metadata fields.
- [x] Step 3: Validate `intent_class` is in the closed canonical enum.
- [x] Step 4: Validate single-label exclusivity.
- [x] Step 5: Validate ambiguity handling consistency (`unknown_intent` fail-closed behavior).
- [x] Step 6: Validate authority guarantees are all `false`.
- [x] Step 7: Validate `execution_enabled=false`.

## Deterministic Rejection Codes (Priority Order)
- [x] `SCHEMA_INVALID`
- [x] `CLASSIFICATION_REQUIRED`
- [x] `INTENT_CLASS_NOT_IN_CLOSED_SET`
- [x] `MULTI_CLASS_CONFLICT`
- [x] `AMBIGUITY_UNRESOLVED`
- [x] `ROUTING_METADATA_FORBIDDEN`
- [x] `PERMISSIONING_METADATA_FORBIDDEN`
- [x] `AUTHORITY_FALSE_GUARANTEE_VIOLATION`
- [x] `EXECUTION_ENABLED_VIOLATION`

## Prohibition Gates (Promotion Blockers)
Promotion MUST be blocked if any check fails:
- [x] Any classification artifact contains `route_disposition`.
- [x] Any classification artifact contains `escalation_eligibility`.
- [x] Any classification artifact includes routing, admissibility, authorization, or permission state.
- [x] Any non-closed-set intent class appears.
- [x] Any utterance can bypass classification.

## Closed Taxonomy Completeness Checks
- [x] Canonical classes are defined as a closed set in `cm/INTENT-TAXONOMY-V1.md`.
- [x] `explicit_action_request` is present and semantically justified.
- [x] `execution_request` is absent from canonical class definitions.
- [x] `unknown_intent` fail-closed semantics are normative.
- [x] Legacy runtime compatibility mapping is complete and unambiguous.

## No-Classification-No-Governed-Influence Rule
- [x] Phase 32 spec explicitly states governed influence requires a valid `intent_classification_record.v1`.
- [x] Phase 32 spec explicitly forbids implicit escalation from unclassified input.
- [x] Phase 32 spec explicitly forbids ambiguous input from gaining governed influence.

## Preservation of Prior Phase Guarantees
- [x] Phase 27 conversational non-authority preserved.
- [x] Phase 28 inspection read-only boundaries preserved.
- [x] Phase 29 inspection binding boundaries preserved.
- [x] Phase 30 delegation non-authority boundaries preserved.
- [x] Phase 31 synthesis inertness and non-execution guarantees preserved.

## Test Planning Requirements (No Test Implementation in Phase 32)
Required future validation scenarios for promotion:
- [x] Completeness tests: each utterance yields one closed-set class.
- [x] Exclusivity tests: no utterance yields multiple classes.
- [x] Fail-closed tests: ambiguous/no-match/conflict inputs classify as `unknown_intent`.
- [x] Boundary tests: artifacts with routing/permissioning fields are rejected.
- [x] Authority tests: all valid records keep `execution_enabled=false` and all authority flags false.
- [x] Compatibility tests: legacy-to-canonical mapping is total and deterministic.
- [x] Regression tests: Phases 27-31 guarantees remain unchanged.

## Promotion Evidence Requirements
Promotion to frozen Phase 32 requires:
1. Canonical Phase 32 spec artifact present and approved.
2. Canonical taxonomy artifact present and approved.
3. Normative schema artifact present and approved.
4. Validation evidence plan mapping each invariant to deterministic checks.
5. Explicit sign-off that Phase 32 remains specification-only with no runtime authority change.
