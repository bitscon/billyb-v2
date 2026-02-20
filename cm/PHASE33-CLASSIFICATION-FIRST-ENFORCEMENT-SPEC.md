# Phase 33 - Classification-First Enforcement (Specification-Only)

## Status
- Phase: 33
- Maturity state: draft specification (not frozen)
- Runtime delta: none
- Authority delta: none
- Execution delta: none

## Purpose
Phase 33 defines mandatory classification-first enforcement for every utterance.

No system response of any kind SHALL be emitted unless a valid `intent_classification_record.v1` exists for the current utterance.

## Governing Question
Did a valid intent classification record exist before any response path was allowed for this utterance?

## Scope
Phase 33 covers:
- Ordering invariants for response release.
- Enforcement contract and deterministic fail-closed behavior.
- Clarification boundary rules after classification.
- User-output boundary rules that prevent leakage of internal metadata.
- Promotion criteria and test planning requirements.

## Explicit Non-Goals
Phase 33 MUST NOT:
- enable execution,
- add tools,
- add autonomy,
- add permissioning or authorization logic,
- add new authority or admissibility decisions.

## Normative Ordering Invariant
For every utterance, the system SHALL apply this order:
1. Receive and normalize utterance.
2. Issue `intent_classification_record.v1` for the current utterance.
3. Validate the classification record.
4. Evaluate response candidate type.
5. Apply user-output leakage guard.
6. Release exactly one response type, or block fail-closed.

The system MUST NOT emit chat, clarification, refusal, or governed-routing output before steps 2 and 3 succeed.

## Response Types Under Enforcement
Phase 33 applies equally to:
- chat responses,
- clarification responses,
- refusal responses,
- governed routing responses.

No response type is exempt from classification-first enforcement.

## Missing or Invalid Classification Handling
If classification record is missing or invalid, the system SHALL:
- block response release,
- produce deterministic rejection semantics,
- fail closed without authority expansion.

## Ambiguity Handling After Classification
Ambiguity SHALL be handled only after classification.

Ambiguous input MUST be represented as classification outcome (`unknown_intent`) and MUST NOT bypass classification by directly generating clarification.

## Clarification Boundary
Clarification is allowed only after successful classification validation.

Clarification MUST:
- be user-centric,
- request disambiguating user intent in plain language,
- avoid internal implementation disclosure.

Clarification MUST NOT expose:
- phase numbers,
- protocol names,
- governance state metadata.

## User Output Leakage Boundary
Before response release, user-visible output MUST pass metadata leakage checks.

User-visible output MUST NOT expose internal:
- phase identifiers,
- protocol artifact names,
- deterministic reason-code internals,
- governance state internals.

## Fail-Closed Guarantee
When ordering or leakage requirements are violated, system behavior SHALL fail closed and block user response release until compliant state is restored.

## Contract Artifact
Normative Phase 33 enforcement contract:
- `classification_first_enforcement.v1`

This contract records enforcement outcomes and does not grant authority.

## Promotion Criteria
Phase 33 promotion readiness requires:
1. Classification-first ordering invariants are explicit and complete.
2. Deterministic fail-closed semantics are explicit for missing or invalid classification.
3. Clarification boundary is explicit and post-classification only.
4. User-output leakage prevention requirements are explicit and testable.
5. Deterministic rejection semantics are complete and prioritized.
6. Preservation of Phases 27-32 guarantees is explicit.

## Preservation Requirements
Phase 33 SHALL preserve:
- Phase 27 conversational non-authority,
- Phase 28 read-only inspection boundaries,
- Phase 29 explicit inspection binding boundaries,
- Phase 30 delegation non-authority envelope,
- Phase 31 synthesis inertness and non-execution guarantees,
- Phase 32 classification-only semantics and closed taxonomy guarantees.
