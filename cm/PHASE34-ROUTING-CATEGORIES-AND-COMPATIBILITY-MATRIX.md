# Phase 34 Routing Categories and Compatibility Matrix

## Purpose
This document defines the closed routing-category set and deterministic compatibility mapping from Phase 32 intent classes.

## Closed Routing Category Set
The Phase 34 routing category set SHALL be exactly:
1. `conversational_response`
2. `clarification_response`
3. `planning_candidate`
4. `governance_review`
5. `refusal_required`

No additional routing category is allowed in Phase 34.

## Category Definitions
| Routing Category | Description | Allowed Effects | Explicitly Forbidden Effects |
|---|---|---|---|
| `conversational_response` | Internal lane for direct non-executing user-facing response handling. | Produce non-executing conversational output candidate. | No tool invocation, no execution, no permissioning, no authorization, no authority grant. |
| `clarification_response` | Internal lane for disambiguation prompts after classification. | Produce user-centric clarification candidate. | No bypass of classification, no tool invocation, no execution, no authority inference. |
| `planning_candidate` | Internal lane for advisory/planning shaping only. | Produce non-executing planning candidate output. | No execution payload generation, no tool selection, no permissioning/authorization semantics. |
| `governance_review` | Internal lane for governed review framing where intent is system-affecting but still non-executing. | Prepare governed review candidate metadata and non-executing response framing. | No execution, no tool calls, no approval issuance, no permission grant. |
| `refusal_required` | Internal lane for mandatory safe refusal response. | Produce deterministic refusal candidate. | No fallback into execution/tooling, no implicit authority escalation, no policy bypass. |

## Compatibility Rule
For each utterance:
1. Determine `intent_class` from valid `intent_classification_record.v1`.
2. Load permitted category set from this matrix.
3. Select exactly one routing category from that permitted set.
4. Reject deterministically if selected category is outside the permitted set.

## Intent-to-Routing Compatibility Matrix
| Phase 32 Intent Class | Permitted Routing Categories |
|---|---|
| `information_request` | `conversational_response`, `clarification_response`, `refusal_required` |
| `content_generation_request` | `conversational_response`, `clarification_response`, `refusal_required` |
| `advice_request` | `conversational_response`, `planning_candidate`, `clarification_response`, `refusal_required` |
| `planning_request` | `planning_candidate`, `clarification_response`, `refusal_required` |
| `action_request` | `governance_review`, `clarification_response`, `refusal_required` |
| `explicit_action_request` | `governance_review`, `clarification_response`, `refusal_required` |
| `policy_challenge` | `refusal_required`, `clarification_response` |
| `governance_inquiry` | `conversational_response`, `clarification_response`, `refusal_required` |
| `unknown_intent` | `clarification_response`, `refusal_required` |

## Safe-Subset Rule for `unknown_intent`
`unknown_intent` SHALL map only to:
- `clarification_response`
- `refusal_required`

`unknown_intent` MUST NOT map to:
- `planning_candidate`
- `governance_review`
- `conversational_response`

## Routing Boundary Guarantees
1. No routing category in Phase 34 has execution semantics.
2. No routing category in Phase 34 has tool-selection semantics.
3. No routing category in Phase 34 has permissioning or authorization semantics.
4. Routing category selection is internal handling metadata only.
