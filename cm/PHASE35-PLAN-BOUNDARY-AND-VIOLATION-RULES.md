# Phase 35 Plan Boundary and Violation Rules

## Purpose
This document defines deterministic boundary enforcement and rejection semantics for inert plan construction.

## Mandatory Preconditions
Before plan construction release, all conditions MUST hold:
1. valid `intent_classification_record.v1` reference exists,
2. valid `post_classification_routing_contract.v1` reference exists,
3. routing category is plan-compatible (`planning_candidate`),
4. plan content passes inert-content checks.

If any precondition fails, plan construction MUST be rejected fail-closed.

## Deterministic Boundary Rules
1. `PB1_CLASSIFICATION_REFERENCE_REQUIRED`
   - Plan construction MUST NOT proceed without valid classification reference.
2. `PB2_ROUTING_REFERENCE_REQUIRED`
   - Plan construction MUST NOT proceed without valid routing reference.
3. `PB3_ROUTING_COMPATIBILITY_REQUIRED`
   - Plan construction MUST NOT proceed when routing category is not plan-compatible.
4. `PB4_INERT_CONTENT_REQUIRED`
   - Plan construction MUST NOT proceed when candidate includes executable/tool/scheduling/credential content.
5. `PB5_NON_AUTHORITY_REQUIRED`
   - Plan artifacts MUST remain non-authoritative and non-executing.

## Deterministic Rejection Codes
Violation outcomes SHALL use:
- `PLAN_PRECONDITION_MISSING_CLASSIFICATION_REFERENCE`
- `PLAN_PRECONDITION_INVALID_CLASSIFICATION_REFERENCE`
- `PLAN_PRECONDITION_MISSING_ROUTING_REFERENCE`
- `PLAN_PRECONDITION_INVALID_ROUTING_REFERENCE`
- `PLAN_ROUTING_CATEGORY_NOT_PLAN_COMPATIBLE`
- `PLAN_ROUTING_CONSTRAINT_BYPASS_FORBIDDEN`
- `PLAN_EXECUTABLE_CONTENT_FORBIDDEN`
- `PLAN_TOOL_REFERENCE_FORBIDDEN`
- `PLAN_SCHEDULING_CONTENT_FORBIDDEN`
- `PLAN_CREDENTIAL_CONTENT_FORBIDDEN`
- `PLAN_RESPONSE_BLOCKED_FAIL_CLOSED`

## Rejection Priority Order
When multiple violations occur, priority SHALL be:
1. `PLAN_PRECONDITION_MISSING_CLASSIFICATION_REFERENCE`
2. `PLAN_PRECONDITION_INVALID_CLASSIFICATION_REFERENCE`
3. `PLAN_PRECONDITION_MISSING_ROUTING_REFERENCE`
4. `PLAN_PRECONDITION_INVALID_ROUTING_REFERENCE`
5. `PLAN_ROUTING_CATEGORY_NOT_PLAN_COMPATIBLE`
6. `PLAN_ROUTING_CONSTRAINT_BYPASS_FORBIDDEN`
7. `PLAN_EXECUTABLE_CONTENT_FORBIDDEN`
8. `PLAN_TOOL_REFERENCE_FORBIDDEN`
9. `PLAN_SCHEDULING_CONTENT_FORBIDDEN`
10. `PLAN_CREDENTIAL_CONTENT_FORBIDDEN`
11. `PLAN_RESPONSE_BLOCKED_FAIL_CLOSED`

## Fail-Closed Behavior
On violation, the system SHALL:
- block plan release,
- remain non-executing and non-authoritative,
- avoid tool, scheduling, and permission semantics,
- provide deterministic rejection outcome.
