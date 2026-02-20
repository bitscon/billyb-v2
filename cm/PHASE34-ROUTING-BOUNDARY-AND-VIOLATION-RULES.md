# Phase 34 Routing Boundary and Violation Rules

## Purpose
This document defines deterministic boundary rules and violation handling for post-classification routing.

## Mandatory Preconditions
Before routing decision release, all conditions MUST hold:
1. Current utterance has a valid `intent_classification_record.v1`.
2. Classification-first enforcement precondition is satisfied.
3. Classified intent exists in Phase 32 closed intent enum.
4. Selected routing category is in the permitted category set for that intent.

If any precondition fails, routing MUST be rejected fail-closed.

## Deterministic Boundary Rules
1. `RB1_CLASSIFICATION_REFERENCE_REQUIRED`
   - Routing MUST NOT proceed without classification reference.
2. `RB2_CLASSIFICATION_VALID_REQUIRED`
   - Routing MUST NOT proceed when classification is invalid.
3. `RB3_COMPATIBILITY_REQUIRED`
   - Routing category MUST be compatible with classified intent per matrix.
4. `RB4_ROUTING_NON_EXECUTING_REQUIRED`
   - Routing artifacts MUST NOT encode execution, tooling, permissioning, or authority semantics.
5. `RB5_SINGLE_CATEGORY_SELECTION_REQUIRED`
   - Exactly one routing category SHALL be selected per utterance.

## Deterministic Rejection Codes
Violation outcomes SHALL use these codes:
- `ROUTING_PRECONDITION_MISSING_CLASSIFICATION`
- `ROUTING_PRECONDITION_INVALID_CLASSIFICATION`
- `ROUTING_CLASS_NOT_IN_CLOSED_SET`
- `ROUTING_CATEGORY_NOT_ALLOWED_FOR_INTENT`
- `ROUTING_CATEGORY_UNKNOWN`
- `ROUTING_EXECUTION_SEMANTICS_FORBIDDEN`
- `ROUTING_TOOL_SELECTION_FORBIDDEN`
- `ROUTING_PERMISSIONING_SEMANTICS_FORBIDDEN`
- `ROUTING_RESPONSE_BLOCKED_FAIL_CLOSED`

## Rejection Priority Order
When multiple violations occur, priority SHALL be:
1. `ROUTING_PRECONDITION_MISSING_CLASSIFICATION`
2. `ROUTING_PRECONDITION_INVALID_CLASSIFICATION`
3. `ROUTING_CLASS_NOT_IN_CLOSED_SET`
4. `ROUTING_CATEGORY_NOT_ALLOWED_FOR_INTENT`
5. `ROUTING_CATEGORY_UNKNOWN`
6. `ROUTING_EXECUTION_SEMANTICS_FORBIDDEN`
7. `ROUTING_TOOL_SELECTION_FORBIDDEN`
8. `ROUTING_PERMISSIONING_SEMANTICS_FORBIDDEN`
9. `ROUTING_RESPONSE_BLOCKED_FAIL_CLOSED`

## Fail-Closed Behavior
On routing violation, the system SHALL:
- block routing release,
- avoid execution and tool semantics,
- avoid authority inference,
- remain within non-authoritative handling bounds.
