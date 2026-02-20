# Phase 36 - Action Proposal Artifacts (Specification-Only)

## Status
- Phase: 36
- Maturity state: draft specification (not frozen)
- Runtime delta: none
- Authority delta: none
- Execution delta: none

## Purpose
Phase 36 defines when Billy may construct an action proposal artifact.

An action proposal artifact describes a possible action path for review while remaining explicitly unapproved, non-executable, and non-authoritative.

## Governing Question
Under which validated conditions may an unapproved, inert proposal artifact be constructed from inert planning context?

## Scope
Phase 36 covers:
- proposal artifact contract definition,
- proposal-content semantics and prohibited content boundaries,
- deterministic rejection semantics for approval/execution implication and constraint bypass,
- promotion criteria and evidence planning.

## Explicit Non-Goals
Phase 36 MUST NOT:
- enable execution,
- invoke tools,
- introduce scheduling semantics,
- introduce permissioning or approval authority,
- expand autonomy,
- create side effects.

## Proposal Is Not Approval Is Not Execution
Phase 36 enforces three separations:
1. Proposal != approval.
2. Proposal != execution.
3. Proposal != authority grant.

A proposal artifact SHALL be explicitly marked `unapproved` and SHALL NOT be treated as executable.

## Ordering and Dependency Preconditions
Proposal construction SHALL require:
1. valid Phase 32 classification reference (`intent_classification_record.v1`),
2. valid Phase 34 routing reference (`post_classification_routing_contract.v1`),
3. valid Phase 35 inert plan reference (`inert_plan_artifact.v1`),
4. coherent planning context (`planning_candidate`) across routing and plan artifacts.

Proposal construction MUST be rejected fail-closed when any precondition is missing, invalid, or incoherent.

## Normative Contract Artifact
Phase 36 contract artifact:
- `action_proposal_artifact.v1`

This artifact SHALL remain inert, auditable, immutable, and explicitly unapproved.

## Deterministic Fail-Closed Boundary
If a proposal implies approval, execution, tool invocation, or scheduling behavior, proposal construction SHALL be rejected fail-closed.

If a proposal bypasses plan or routing constraints, proposal construction SHALL be rejected fail-closed.

## Promotion Criteria
Phase 36 promotion readiness requires:
1. proposal schema deterministically references Phase 32 and Phase 35 artifacts,
2. proposal schema and rules enforce explicit `unapproved` marking,
3. proposal semantics clearly separate proposal from approval and execution,
4. plan/routing constraint enforcement is explicit and deterministic,
5. deterministic rejection semantics are complete and prioritized,
6. regression protections for Phases 32-35 are explicit.

## Preservation Requirements
Phase 36 SHALL preserve:
- Phase 32 classification-only semantics,
- Phase 33 classification-first enforcement ordering,
- Phase 34 routing non-execution/non-authority semantics,
- Phase 35 inert planning and non-authority semantics.
