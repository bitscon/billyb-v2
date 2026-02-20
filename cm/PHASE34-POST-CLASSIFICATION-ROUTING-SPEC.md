# Phase 34 - Post-Classification Routing Contracts (Specification-Only)

## Status
- Phase: 34
- Maturity state: draft specification (not frozen)
- Runtime delta: none
- Authority delta: none
- Execution delta: none

## Purpose
Phase 34 defines post-classification routing contracts.

Given a valid `intent_classification_record.v1`, Phase 34 specifies which internal handling categories are admissible without performing execution, tool invocation, permissioning, or authority expansion.

## Governing Question
For this classified intent, which routing categories are admissible for internal handling?

## Scope
Phase 34 covers:
- closed routing-category definitions,
- intent-to-routing compatibility rules,
- routing contract requirements,
- deterministic rejection semantics for routing-boundary violations,
- promotion criteria and evidence planning.

## Explicit Non-Goals
Phase 34 MUST NOT:
- enable execution,
- invoke tools,
- add autonomy,
- add permissioning or authorization logic,
- grant authority expansion,
- define executable action plans.

## Routing Is Not Execution
Routing in Phase 34 is descriptive and categorical.

Routing categories SHALL describe permissible internal handling lanes only.

Routing categories MUST NOT:
- trigger execution,
- select tools,
- authorize actions,
- imply permission or admissibility for execution.

## Ordering Dependency
Phase 34 SHALL consume Phase 32 and respect Phase 33 ordering:
1. Valid classification record exists for current utterance (`intent_classification_record.v1`).
2. Classification-first enforcement preconditions are satisfied.
3. Routing category selection is evaluated against the compatibility matrix.
4. Routing contract is issued or deterministically rejected.

Routing MUST NOT occur if steps 1 or 2 fail.

## Normative Contract Artifact
Phase 34 routing contract artifact:
- `post_classification_routing_contract.v1`

This artifact SHALL record routing-category eligibility and selection without embedding execution, tooling, or authority semantics.

## Deterministic Fail-Closed Boundary
If classification reference is missing, invalid, or non-compliant, routing SHALL fail closed.

If selected routing category is not permitted for the classified intent, routing SHALL fail closed.

## Promotion Criteria
Phase 34 promotion readiness requires:
1. Closed routing categories are explicitly defined.
2. Intent-to-routing compatibility matrix is complete for all Phase 32 intent classes.
3. Routing contract schema is deterministic and classification-referenced.
4. Deterministic rejection semantics are complete and prioritized.
5. Routing/authority separation is explicit and testable.
6. Regression protections for Phases 32-33 are explicit.

## Preservation Requirements
Phase 34 SHALL preserve:
- Phase 32 classification-only semantics and closed intent taxonomy.
- Phase 33 classification-first enforcement ordering and leakage boundaries.
