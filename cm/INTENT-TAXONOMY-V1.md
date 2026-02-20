# Intent Taxonomy v1 (Phase 32)

## Purpose
This document defines the closed, canonical Phase 32 intent taxonomy for linguistic classification.

## Normative Boundary
1. Intent classes represent user language intent only.
2. Intent classes MUST NOT grant or imply execution authority.
3. Intent classes MUST NOT grant or imply routing permission.
4. Intent classes MUST NOT grant or imply authorization or admissibility.

## Closed Canonical Intent Class Set
The canonical set SHALL be exactly:
1. `information_request`
2. `content_generation_request`
3. `advice_request`
4. `planning_request`
5. `action_request`
6. `explicit_action_request`
7. `policy_challenge`
8. `governance_inquiry`
9. `unknown_intent`

No additional class is allowed in Phase 32.

## Class Definitions
| Intent Class | Description | Allowed Effects | Forbidden Effects | conversational | informational | planning | governance_relevant | execution_relevant |
|---|---|---|---|---|---|---|---|---|
| `information_request` | User asks for facts or explanation. | Produce classification record. | No authority, routing, approval, authorization, or execution implication. | true | true | false | false | false |
| `content_generation_request` | User asks for generated draft content. | Produce classification record. | No authority, routing, approval, authorization, or execution implication. | true | false | false | false | false |
| `advice_request` | User asks for recommendation or guidance. | Produce classification record. | No authority, routing, approval, authorization, or execution implication. | true | true | true | false | false |
| `planning_request` | User asks for plan-level structure or sequencing. | Produce classification record. | No authority, routing, approval, authorization, or execution implication. | true | false | true | false | false |
| `action_request` | User requests a system-affecting change in proposal/request language. | Produce classification record. | No authority, routing, approval, authorization, or execution implication. | false | false | true | true | true |
| `explicit_action_request` | User uses imperative or immediate system-affecting language. | Produce classification record. | No authority, routing, approval, authorization, or execution implication. | false | false | false | true | true |
| `policy_challenge` | User language attempts to bypass or weaken governance/policy boundaries. | Produce classification record. | No authority, routing, approval, authorization, or execution implication. | true | false | false | true | true |
| `governance_inquiry` | User asks about governance, policy, authority, or boundary rules. | Produce classification record. | No authority, routing, approval, authorization, or execution implication. | true | true | false | true | false |
| `unknown_intent` | No deterministic class match, conflict, or unresolved ambiguity. | Produce classification record and fail closed. | No authority, routing, approval, authorization, or execution implication. | true | false | false | false | false |

## Deterministic Ambiguity Handling
Classification SHALL fail closed to `unknown_intent` when:
1. no class match exists,
2. conflicting class signals exist, or
3. ambiguity remains unresolved.

`unknown_intent` MUST NOT imply implicit escalation, permissioning, or authority.

## Justification for `explicit_action_request`
`explicit_action_request` captures imperative user language requesting system-affecting action (for example, direct command-like phrasing) without implying execution permission.

This label preserves semantic correctness:
- It reflects what the user asked.
- It does not assert what the system is allowed to do.

## Legacy Runtime Compatibility Mapping
| Current Runtime ID | Canonical Phase 32 ID |
|---|---|
| `informational_query` | `information_request` |
| `generative_content_request` | `content_generation_request` |
| `advisory_request` | `advice_request` |
| `planning_request` | `planning_request` |
| `governed_action_proposal` | `action_request` |
| `execution_attempt` | `explicit_action_request` |
| `policy_boundary_challenge` | `policy_challenge` |
| `meta_governance_inquiry` | `governance_inquiry` |
| `ambiguous_intent` | `unknown_intent` |

This mapping is descriptive for compatibility and documentation continuity in Phase 32.
