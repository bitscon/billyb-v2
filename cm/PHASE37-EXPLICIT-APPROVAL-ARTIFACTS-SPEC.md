# Phase 37 - Explicit Approval Artifacts (Specification-Only)

## Status
- Phase: 37
- Maturity state: draft specification (not frozen)
- Runtime delta: none
- Authority delta: none (execution authority remains absent)
- Execution delta: none

## Purpose
Phase 37 defines when a human authority may explicitly approve or reject an action proposal artifact.

Phase 37 introduces explicit approval decision artifacts that remain non-executing and auditable.

## Governing Question
Under which validated conditions may an explicit approve/reject decision be recorded against an action proposal without causing execution?

## Scope
Phase 37 covers:
- explicit approval artifact contract definition,
- approval decision and lifecycle semantics,
- deterministic rejection semantics for implicit/invalid approval behavior,
- promotion criteria and evidence planning.

## Explicit Non-Goals
Phase 37 MUST NOT:
- enable execution,
- invoke tools,
- introduce scheduling semantics,
- expand autonomy,
- allow implicit approval inference,
- cause side effects beyond artifact issuance.

## Approval Is Not Execution
Phase 37 enforces:
1. Approval != execution.
2. Rejection != execution.
3. Approval artifact != executable authority token.

An approval artifact SHALL only record explicit governance decision state.

## Ordering and Dependency Preconditions
Approval artifact construction SHALL require:
1. valid Phase 36 proposal reference (`action_proposal_artifact.v1`),
2. proposal is currently unapproved and non-executing,
3. explicit approving-authority identity (abstract identity fields),
4. explicit decision state (`approved` or `rejected`).

Any missing or invalid precondition MUST trigger deterministic fail-closed rejection.

## Normative Contract Artifact
Phase 37 contract artifact:
- `explicit_approval_artifact.v1`

This artifact SHALL be immutable, auditable, explicit, revocable, expirable, and non-executing.

## Deterministic Fail-Closed Boundary
If approval is implicit, proposal is missing, or approval content implies execution/tooling/scheduling behavior, approval artifact construction SHALL be rejected fail-closed.

## Promotion Criteria
Phase 37 promotion readiness requires:
1. approval artifact schema references valid proposal artifact and authority identity,
2. explicit approve/reject decision semantics are deterministic,
3. approval lifecycle (revocation/expiration) semantics are explicit and non-executing,
4. deterministic rejection semantics are complete and prioritized,
5. approval/authority record remains auditable and immutable,
6. regression protections for Phases 32-36 are explicit.

## Preservation Requirements
Phase 37 SHALL preserve:
- Phase 32 classification-only semantics,
- Phase 33 classification-first enforcement ordering,
- Phase 34 routing non-execution semantics,
- Phase 35 inert plan non-authority semantics,
- Phase 36 inert proposal and explicit-unapproved semantics.
