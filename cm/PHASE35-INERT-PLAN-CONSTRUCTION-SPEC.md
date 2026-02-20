# Phase 35 - Inert Plan Construction (Specification-Only)

## Status
- Phase: 35
- Maturity state: draft specification (not frozen)
- Runtime delta: none
- Authority delta: none
- Execution delta: none

## Purpose
Phase 35 defines when Billy may construct an inert plan artifact.

An inert plan artifact describes possible steps and reasoning structure without performing, authorizing, scheduling, or invoking any action.

## Governing Question
Under which validated conditions may an inert plan artifact be constructed from classified intent and routing context?

## Scope
Phase 35 covers:
- inert plan artifact contract definition,
- plan-content semantics and prohibited content boundaries,
- deterministic rejection semantics for executable or routing-bypass content,
- promotion criteria and evidence planning.

## Explicit Non-Goals
Phase 35 MUST NOT:
- enable execution,
- invoke tools,
- schedule delayed actions,
- introduce permissioning or authorization logic,
- produce side effects,
- grant authority to plan artifacts.

## Plans Are Non-Executable
Plan artifacts in Phase 35 are descriptive-only.

A plan artifact SHALL NOT:
- execute any operation,
- imply executable authority,
- imply approval, authorization, or permission state.

## Ordering and Dependency Preconditions
Plan construction SHALL require:
1. valid Phase 32 classification reference (`intent_classification_record.v1`),
2. valid Phase 34 routing reference (`post_classification_routing_contract.v1`),
3. routing compatibility for plan construction.

Plan construction MUST be rejected fail-closed when any precondition is missing or invalid.

## Plan Construction Admissibility
A plan artifact is admissible only when routing context is plan-compatible.

Phase 35 defines plan-compatible routing as:
- `selected_routing_category = planning_candidate`

Any other routing category MUST deterministically reject plan construction.

## Normative Contract Artifact
Phase 35 contract artifact:
- `inert_plan_artifact.v1`

This artifact SHALL remain inert, auditable, immutable, and non-authoritative.

## Deterministic Fail-Closed Boundary
If a candidate plan includes executable, tooling, credential, or scheduling content, plan construction SHALL be rejected fail-closed.

If routing constraints are bypassed, plan construction SHALL be rejected fail-closed.

## Promotion Criteria
Phase 35 promotion readiness requires:
1. plan artifact schema is deterministic and references Phase 32 and Phase 34 artifacts,
2. plan semantics clearly separate descriptive planning from execution semantics,
3. executable/tool/scheduling/credential content is explicitly forbidden,
4. routing-compatibility enforcement is explicit and deterministic,
5. deterministic rejection semantics are complete and prioritized,
6. regression protections for Phases 32-34 are explicit.

## Preservation Requirements
Phase 35 SHALL preserve:
- Phase 32 classification-only semantics and closed intent taxonomy,
- Phase 33 classification-first enforcement ordering guarantees,
- Phase 34 routing-category non-execution and non-authority guarantees.
