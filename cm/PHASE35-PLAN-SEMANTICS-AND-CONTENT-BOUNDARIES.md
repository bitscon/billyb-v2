# Phase 35 Plan Semantics and Content Boundaries

## Purpose
This document defines what a Phase 35 inert plan artifact may include and what it MUST NOT include.

## Allowed Plan Semantics
An inert plan artifact MAY include:
1. `plan_title` - descriptive planning label.
2. `plan_objective` - descriptive objective statement.
3. `plan_steps` - ordered descriptive steps.
4. `dependencies` - non-executable step relationships.
5. `assumptions` - explicit assumptions used by planning logic.
6. `constraints` - explicit constraints relevant to planning.
7. `risk_notes` - descriptive risk observations.

All allowed semantics SHALL remain descriptive and non-executable.

## Plan Step Semantics
Each plan step SHALL be descriptive-only and may include:
- step identifier,
- natural-language description,
- step kind classification (`analysis_step`, `decision_step`, `sequencing_step`),
- dependency references.

Plan step semantics MUST NOT contain executable instructions.

## Explicitly Forbidden Content
A Phase 35 plan artifact MUST NOT include:
- shell commands,
- scripts or runnable code blocks,
- API invocation payloads,
- tool names or tool arguments,
- credentials, secrets, keys, or tokens,
- scheduling directives (`cron`, delayed timers, at-time execution),
- runtime execution context targeting.

## Forbidden Semantic Effects
Plan artifacts MUST NOT:
- authorize actions,
- request or imply permission grants,
- request or imply execution readiness,
- encode action application semantics,
- encode autonomous follow-on behavior.

## Routing Compatibility Constraint
A plan artifact MAY be constructed only when:
- routing contract selected category is `planning_candidate`.

If routing category is not `planning_candidate`, plan construction MUST be rejected.

## Safe Representation Requirement
Plan language SHALL remain recommendation-grade and non-operational.

Plan language MUST avoid executable imperative formats and MUST remain auditable as inert content.
