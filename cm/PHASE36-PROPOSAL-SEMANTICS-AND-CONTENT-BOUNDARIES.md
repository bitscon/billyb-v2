# Phase 36 Proposal Semantics and Content Boundaries

## Purpose
This document defines what a Phase 36 action proposal artifact may include and what it MUST NOT include.

## Allowed Proposal Semantics
A proposal artifact MAY include:
1. `proposal_title` - descriptive proposal label.
2. `proposal_intent_summary` - concise summary of intended outcome.
3. `proposal_rationale` - reasoning context from inert planning.
4. `expected_outcome` - descriptive expected result if later approved in governed flow.
5. `assumptions` - explicit assumptions.
6. `constraints` - explicit constraints.
7. `risk_notes` - descriptive risks.
8. `review_questions` - explicit questions for human review.

All allowed semantics SHALL remain inert and non-authoritative.

## Explicit Unapproved Marker
A proposal artifact MUST include explicit unapproved state metadata.

Proposal content SHALL communicate:
- candidate-only status,
- review-required status,
- non-executable status.

## Explicitly Forbidden Content
A Phase 36 proposal artifact MUST NOT include:
- shell commands,
- scripts or runnable code blocks,
- tool names, tool selectors, or tool arguments,
- API invocation payloads,
- credentials, secrets, keys, or tokens,
- scheduling directives or delayed execution semantics,
- runtime execution target/context declarations.

## Forbidden Semantic Effects
Proposal artifacts MUST NOT:
- claim approval has occurred,
- imply authorization has been granted,
- imply execution readiness,
- trigger or encode action application semantics,
- imply autonomous continuation.

## Plan and Routing Constraint Requirement
A proposal artifact MAY be constructed only when:
- referenced inert plan is valid and constructed,
- referenced routing context is plan-compatible (`planning_candidate`),
- proposal remains coherent with the referenced inert plan scope.

If plan or routing constraints are not satisfied, proposal construction MUST be rejected.

## Safe Representation Requirement
Proposal language SHALL remain review-oriented and non-operational.

Proposal language MUST avoid command-like formulations and MUST remain auditable as inert content.
