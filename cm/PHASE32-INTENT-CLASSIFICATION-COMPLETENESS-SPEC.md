# Phase 32 - Intent Classification Completeness (Specification-Only)

## Status
- Phase: 32
- Maturity state: draft specification (not frozen)
- Runtime delta: none
- Authority delta: none
- Execution delta: none

## Purpose
Phase 32 defines the normative requirement that every user utterance SHALL be classified into exactly one explicit intent class before the utterance can influence any governed path.

## Governing Question
Has each utterance been explicitly and uniquely classified into a closed intent taxonomy before any governed influence is possible?

## Scope
Phase 32 covers:
- Closed intent taxonomy definition.
- Classification-only contract definition.
- Deterministic fail-closed behavior for unknown or ambiguous input.
- Invariants that prohibit classification bypass.
- Promotion criteria and evidence expectations for this phase.

## Explicit Non-Goals
Phase 32 MUST NOT:
- Change runtime execution behavior.
- Add tools, autonomy, or orchestration authority.
- Grant execution authority or permissioning outcomes.
- Add routing, approval, authorization, or admissibility decisions.
- Add side effects, mutation pathways, or background execution.

## Normative Principles
1. Intent classes describe linguistic user intent only.
2. Intent classes MUST NOT imply authority, admissibility, permission, authorization, or execution rights.
3. Classification output SHALL be classification-only.
4. Phase 32 artifacts MUST NOT encode routing, execution, or permissioning decisions.
5. Unknown or unresolved ambiguity MUST fail closed as `unknown_intent`.

## Core Invariants
1. No utterance bypasses classification.
2. Each utterance has exactly one class from the closed taxonomy.
3. Multiple conflicting classes are forbidden.
4. Ambiguous input never escalates implicitly.
5. Governed influence MUST require a valid classification record artifact.

## Boundary Position
Phase 32 is positioned between conversational intake and any governed interpreter, approval, or authorization boundary.

Phase 32 remains pre-permission and pre-authorization:
- It classifies language.
- It does not decide authority.

## Contract Artifact
Normative Phase 32 contract:
- `intent_classification_record.v1`

This artifact SHALL represent classification facts only and SHALL NOT be consumed as an authority grant.

## Deterministic Ambiguity Handling
When classification is uncertain, conflicting, or unresolved, the outcome SHALL be:
- `intent_class = unknown_intent`
- classification record remains valid and immutable
- no implicit governed influence is permitted

## Promotion Criteria
Phase 32 promotion readiness requires:
1. Closed taxonomy is documented with explicit semantics and forbidden effects.
2. Classification contract is complete, deterministic, and auditable.
3. Unknown/ambiguous behavior is fail-closed by specification.
4. Bypass prevention invariants are explicit and testable.
5. Preservation of Phase 27-31 guarantees is explicit.
6. Promotion checklist evidence requirements are complete.

## Preservation Requirements
Phase 32 SHALL preserve prior frozen guarantees:
- Phase 27 conversational non-authority.
- Phase 28 read-only inspection boundaries.
- Phase 29 explicit inspection binding boundaries.
- Phase 30 delegation non-authority envelope.
- Phase 31 synthesis inertness and non-execution guarantees.

## Supersession Note
Earlier Phase 32 drafts that scoped Phase 32 differently are historical pre-definition material for this objective.

For intent classification completeness, this document is the canonical Phase 32 specification.
