# Phase 37 Approval Boundary and Violation Rules

## Purpose
This document defines deterministic boundary enforcement and rejection semantics for explicit approval artifacts.

## Mandatory Preconditions
Before approval artifact release, all conditions MUST hold:
1. valid `action_proposal_artifact.v1` reference exists,
2. proposal referenced is explicitly unapproved,
3. explicit approving-authority identity is present,
4. explicit decision is present (`approved` or `rejected`),
5. approval content passes non-execution checks.

If any precondition fails, approval artifact construction MUST be rejected fail-closed.

## Deterministic Boundary Rules
1. `AB1_PROPOSAL_REFERENCE_REQUIRED`
   - Approval MUST NOT proceed without valid proposal reference.
2. `AB2_EXPLICIT_DECISION_REQUIRED`
   - Approval MUST NOT proceed without explicit decision state.
3. `AB3_IMPLICIT_APPROVAL_FORBIDDEN`
   - Approval inference from context without explicit decision field is forbidden.
4. `AB4_UNAPPROVED_PROPOSAL_REQUIRED`
   - Approval MUST NOT proceed when proposal is already approved or non-coherent.
5. `AB5_NON_EXECUTION_REQUIRED`
   - Approval artifacts MUST NOT imply execution, tooling, or scheduling behavior.

## Deterministic Rejection Codes
Violation outcomes SHALL use:
- `APPROVAL_PRECONDITION_MISSING_PROPOSAL_REFERENCE`
- `APPROVAL_PRECONDITION_INVALID_PROPOSAL_REFERENCE`
- `APPROVAL_IMPLICIT_FORBIDDEN`
- `APPROVAL_DECISION_INVALID`
- `APPROVAL_PROPOSAL_STATE_INVALID`
- `APPROVAL_AUTHORITY_IDENTITY_MISSING`
- `APPROVAL_EXECUTION_IMPLICATION_FORBIDDEN`
- `APPROVAL_TOOL_REFERENCE_FORBIDDEN`
- `APPROVAL_SCHEDULING_CONTENT_FORBIDDEN`
- `APPROVAL_TIME_WINDOW_INVALID`
- `APPROVAL_REVOCATION_STATE_INVALID`
- `APPROVAL_RESPONSE_BLOCKED_FAIL_CLOSED`

## Rejection Priority Order
When multiple violations occur, priority SHALL be:
1. `APPROVAL_PRECONDITION_MISSING_PROPOSAL_REFERENCE`
2. `APPROVAL_PRECONDITION_INVALID_PROPOSAL_REFERENCE`
3. `APPROVAL_IMPLICIT_FORBIDDEN`
4. `APPROVAL_DECISION_INVALID`
5. `APPROVAL_PROPOSAL_STATE_INVALID`
6. `APPROVAL_AUTHORITY_IDENTITY_MISSING`
7. `APPROVAL_EXECUTION_IMPLICATION_FORBIDDEN`
8. `APPROVAL_TOOL_REFERENCE_FORBIDDEN`
9. `APPROVAL_SCHEDULING_CONTENT_FORBIDDEN`
10. `APPROVAL_TIME_WINDOW_INVALID`
11. `APPROVAL_REVOCATION_STATE_INVALID`
12. `APPROVAL_RESPONSE_BLOCKED_FAIL_CLOSED`

## Fail-Closed Behavior
On violation, the system SHALL:
- block approval artifact release,
- remain non-executing and non-authoritative,
- avoid tool and scheduling semantics,
- provide deterministic rejection outcome.
