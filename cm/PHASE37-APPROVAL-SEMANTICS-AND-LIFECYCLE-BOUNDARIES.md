# Phase 37 Approval Semantics and Lifecycle Boundaries

## Purpose
This document defines what explicit approval means, what it does not mean, and how revocation and expiration are represented.

## What Approval Means
In Phase 37, approval means:
1. a human authority explicitly selected decision state `approved`,
2. the decision is recorded against a specific proposal artifact,
3. decision record is immutable and auditable.

Approval is a governance-state record only.

## What Rejection Means
In Phase 37, rejection means:
1. a human authority explicitly selected decision state `rejected`,
2. the decision is recorded against a specific proposal artifact,
3. proposal remains non-executable and unperformed.

Rejection is a governance-state record only.

## What Approval Does Not Mean
Approval in Phase 37 MUST NOT mean:
- execution permission has been exercised,
- execution is triggered,
- tool invocation is allowed,
- scheduling is allowed,
- autonomy is expanded.

## Explicitness Requirement
Approval decisions MUST be explicit.

Implicit approval (for example, inferred from context, tone, or missing decision fields) is forbidden and MUST be rejected.

## Approving Authority Identity (Abstract)
Approval artifacts MUST include abstract authority identity fields:
- authority identifier,
- authority kind/classification,
- attestation reference.

Phase 37 does not define identity-provider implementation.

## Revocation Semantics
Approval artifacts are revocable by explicit record semantics.

Revocation SHALL be represented as explicit artifact state:
- `revocation_state = revoked`
- `revocation_reason` present

Revocation MUST NOT mutate prior records in place; revocation state is represented by explicit artifact issuance semantics.

## Expiration Semantics
Approval artifacts SHALL include explicit validity window:
- `issued_at`
- `expires_at`

Expiration means:
- approval record remains auditable,
- execution remains disallowed in this phase,
- expired state is not approval grant for any action.

## Lifecycle States
Approval lifecycle state is represented as one of:
- `active`
- `revoked`
- `expired`
- `inactive_rejected`

Lifecycle representation remains non-executing and non-authoritative for runtime action.

## Safe Representation Requirement
Approval artifact language SHALL remain governance-record oriented and MUST avoid operational instructions.
