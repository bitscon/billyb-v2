# Phase 36 Proposal Boundary and Violation Rules

## Purpose
This document defines deterministic boundary enforcement and rejection semantics for action proposal artifact construction.

## Mandatory Preconditions
Before proposal construction release, all conditions MUST hold:
1. valid `intent_classification_record.v1` reference exists,
2. valid `post_classification_routing_contract.v1` reference exists,
3. valid `inert_plan_artifact.v1` reference exists,
4. routing and plan context are coherent and plan-compatible,
5. proposal content passes inert-content checks.

If any precondition fails, proposal construction MUST be rejected fail-closed.

## Deterministic Boundary Rules
1. `QB1_CLASSIFICATION_REFERENCE_REQUIRED`
   - Proposal construction MUST NOT proceed without valid classification reference.
2. `QB2_ROUTING_REFERENCE_REQUIRED`
   - Proposal construction MUST NOT proceed without valid routing reference.
3. `QB3_PLAN_REFERENCE_REQUIRED`
   - Proposal construction MUST NOT proceed without valid inert plan reference.
4. `QB4_PLAN_ROUTING_COMPATIBILITY_REQUIRED`
   - Proposal construction MUST NOT proceed when plan/routing context is not plan-compatible.
5. `QB5_UNAPPROVED_STATE_REQUIRED`
   - Proposal artifact MUST be explicitly marked `unapproved`.
6. `QB6_INERT_CONTENT_REQUIRED`
   - Proposal construction MUST NOT proceed when candidate includes executable/tool/scheduling/credential or approval-implying content.

## Deterministic Rejection Codes
Violation outcomes SHALL use:
- `PROPOSAL_PRECONDITION_MISSING_CLASSIFICATION_REFERENCE`
- `PROPOSAL_PRECONDITION_INVALID_CLASSIFICATION_REFERENCE`
- `PROPOSAL_PRECONDITION_MISSING_ROUTING_REFERENCE`
- `PROPOSAL_PRECONDITION_INVALID_ROUTING_REFERENCE`
- `PROPOSAL_PRECONDITION_MISSING_PLAN_REFERENCE`
- `PROPOSAL_PRECONDITION_INVALID_PLAN_REFERENCE`
- `PROPOSAL_PLAN_ROUTING_NOT_COMPATIBLE`
- `PROPOSAL_PLAN_ROUTING_CONSTRAINT_BYPASS_FORBIDDEN`
- `PROPOSAL_APPROVAL_STATE_INVALID`
- `PROPOSAL_APPROVAL_IMPLICATION_FORBIDDEN`
- `PROPOSAL_EXECUTION_IMPLICATION_FORBIDDEN`
- `PROPOSAL_EXECUTABLE_CONTENT_FORBIDDEN`
- `PROPOSAL_TOOL_REFERENCE_FORBIDDEN`
- `PROPOSAL_SCHEDULING_CONTENT_FORBIDDEN`
- `PROPOSAL_CREDENTIAL_CONTENT_FORBIDDEN`
- `PROPOSAL_RESPONSE_BLOCKED_FAIL_CLOSED`

## Rejection Priority Order
When multiple violations occur, priority SHALL be:
1. `PROPOSAL_PRECONDITION_MISSING_CLASSIFICATION_REFERENCE`
2. `PROPOSAL_PRECONDITION_INVALID_CLASSIFICATION_REFERENCE`
3. `PROPOSAL_PRECONDITION_MISSING_ROUTING_REFERENCE`
4. `PROPOSAL_PRECONDITION_INVALID_ROUTING_REFERENCE`
5. `PROPOSAL_PRECONDITION_MISSING_PLAN_REFERENCE`
6. `PROPOSAL_PRECONDITION_INVALID_PLAN_REFERENCE`
7. `PROPOSAL_PLAN_ROUTING_NOT_COMPATIBLE`
8. `PROPOSAL_PLAN_ROUTING_CONSTRAINT_BYPASS_FORBIDDEN`
9. `PROPOSAL_APPROVAL_STATE_INVALID`
10. `PROPOSAL_APPROVAL_IMPLICATION_FORBIDDEN`
11. `PROPOSAL_EXECUTION_IMPLICATION_FORBIDDEN`
12. `PROPOSAL_EXECUTABLE_CONTENT_FORBIDDEN`
13. `PROPOSAL_TOOL_REFERENCE_FORBIDDEN`
14. `PROPOSAL_SCHEDULING_CONTENT_FORBIDDEN`
15. `PROPOSAL_CREDENTIAL_CONTENT_FORBIDDEN`
16. `PROPOSAL_RESPONSE_BLOCKED_FAIL_CLOSED`

## Fail-Closed Behavior
On violation, the system SHALL:
- block proposal release,
- remain non-executing and non-authoritative,
- avoid tool, scheduling, approval, and permission semantics,
- provide deterministic rejection outcome.
