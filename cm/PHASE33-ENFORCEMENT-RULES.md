# Phase 33 Enforcement Rules (Classification-First)

## Purpose
This document defines deterministic enforcement rules for Phase 33 ordering and boundary behavior.

## Enforcement Position in Runtime Flow
Phase 33 enforcement sits at the response-release boundary:
- after utterance intake,
- before any user-visible response release.

## Mandatory Preconditions
Before any response release, the following MUST be true:
1. `intent_classification_record.v1` exists for the current utterance.
2. The classification record validates successfully.
3. Output leakage checks pass for the selected response text.

If any precondition fails, response release MUST be blocked.

## Deterministic Enforcement Rules
1. `R1_CLASSIFICATION_REQUIRED`
   - Rule: Response release MUST NOT proceed without classification record presence.
   - Failure result: block and fail closed.
2. `R2_CLASSIFICATION_VALID_REQUIRED`
   - Rule: Response release MUST NOT proceed with invalid classification record.
   - Failure result: block and fail closed.
3. `R3_CLARIFICATION_POST_CLASSIFICATION_ONLY`
   - Rule: Clarification MUST NOT be emitted before classification validation.
   - Failure result: block and fail closed.
4. `R4_NO_INTERNAL_METADATA_LEAKAGE`
   - Rule: User-visible output MUST NOT expose internal phase/protocol/governance metadata.
   - Failure result: block and fail closed.
5. `R5_SINGLE_RESPONSE_RELEASE`
   - Rule: Exactly one response type may be released per utterance after gate pass.
   - Failure result: block and fail closed.

## Clarification Boundary Rules
Clarification MAY be emitted only when:
- classification exists,
- classification is valid,
- intent outcome requires disambiguation.

Clarification MUST:
- ask for user intent refinement in plain language,
- remain independent from internal protocol wording.

Clarification MUST NOT:
- reference phase numbers,
- reference contract/protocol names,
- expose governance state internals.

## Violation Semantics
Deterministic violation outcomes SHALL be represented using the following reason codes:
- `PRE_CLASSIFICATION_RESPONSE_FORBIDDEN`
- `CLASSIFICATION_RECORD_MISSING`
- `CLASSIFICATION_RECORD_INVALID`
- `CLARIFICATION_PRECLASSIFICATION_FORBIDDEN`
- `INTERNAL_METADATA_EXPOSURE_FORBIDDEN`
- `RESPONSE_RELEASE_BLOCKED_FAIL_CLOSED`

## Rejection Priority Ordering
When multiple violations occur, priority SHALL be:
1. `CLASSIFICATION_RECORD_MISSING`
2. `CLASSIFICATION_RECORD_INVALID`
3. `PRE_CLASSIFICATION_RESPONSE_FORBIDDEN`
4. `CLARIFICATION_PRECLASSIFICATION_FORBIDDEN`
5. `INTERNAL_METADATA_EXPOSURE_FORBIDDEN`
6. `RESPONSE_RELEASE_BLOCKED_FAIL_CLOSED`

## Fail-Closed Behavior
If enforcement cannot prove all preconditions, the system SHALL:
- block release,
- avoid authority inference,
- remain non-executing and non-authoritative,
- request safe user clarification only after valid classification exists.
