## 1. Purpose
This contract defines authoritative interaction behavior for Billy v2. It exists to prevent interaction drift by requiring deterministic classification, dispatch, and authority checks before any response is produced. This document is normative for interaction-layer decisions.

## 2. Core Principle: Single Interaction Authority (SIA)
Single Interaction Authority (SIA) means one authoritative dispatcher controls turn entry for all interfaces.

- Every user input MUST pass through SIA before mode handling.
- SIA MUST classify input once per turn.
- SIA MUST resolve exactly one outcome: route to an authorized mode or reject.
- No component MUST bypass SIA through shortcuts, legacy aliases, or fallback dispatch.

## 3. Interaction Lifecycle (classify → resolve → authority check → respond → frame update)
SIA MUST process each turn in this order:

1. `classify`: assign exactly one input category.
2. `resolve`: map the category to a candidate governed mode or rejection path.
3. `authority check`: enforce trigger validity, gate requirements, and maturity-sync compatibility before any actionable response.
4. `respond`: emit either a valid mode response or deterministic rejection.
5. `frame update`: persist conversational frame state after the response outcome.

No execution-capable pathway may run before step 3 passes.

## 4. Input Classification Categories
SIA MUST classify all input into one of the following categories:

- `identity/context`: identity, context continuity, or orientation queries.
- `reasoning`: explicit reasoning/analysis requests.
- `drafting`: explicit drafting/specification requests.
- `execution attempt`: explicit requests to perform governed execution actions.
- `tool invocation`: explicit tool-run requests.
- `workflow invocation`: explicit workflow-run requests.
- `legacy interaction`: deprecated command shapes and legacy control forms.
- `invalid/ambiguous`: unclear, conflicting, or non-authoritative intent.

If classification is uncertain, SIA MUST assign `invalid/ambiguous`.

## 5. Mode Resolution Rules
`CAPABILITIES.md` is the source of truth for valid triggers and allowed outcomes.

- `identity/context` -> non-executing conversational response path, or reject if execution is implied.
- `reasoning` -> `ERM` only when trigger is valid in `CAPABILITIES.md`; otherwise reject.
- `drafting` -> `CDM` (and tool-drafting path where defined in capabilities) only when trigger is valid; otherwise reject.
- `execution attempt` -> `CAM` only when trigger is valid and all existing gates pass; otherwise reject.
- `tool invocation` -> `TEM` only when trigger is valid and all existing gates pass; otherwise reject.
- `workflow invocation` -> Workflow Mode only when explicit workflow trigger is valid and all existing gates pass; otherwise reject.
- `legacy interaction` -> reject.
- `invalid/ambiguous` -> reject.

SIA MUST NOT infer missing triggers, mode intent, or execution parameters.

## 6. Legacy Interaction Rejection
Legacy interaction forms are invalid and MUST be rejected.

- `/plan` MUST be rejected.
- `/engineer` MUST be rejected.
- `/exec` MUST be rejected.
- `/ops` MUST be rejected.
- `a0` command forms MUST be rejected.
- Any slash-prefixed mode not explicitly defined in `CAPABILITIES.md` MUST be rejected.

SIA MUST NOT auto-map legacy inputs to modern triggers.

## 7. Response Constraints
Responses are constrained by routing and authority, not canned wording.

- The system MUST NOT claim execution unless governed execution actually occurred.
- The system MUST NOT narrate simulated execution or implied side effects.
- The system MUST NOT invent governance rules, approvals, or authority state.
- The system MUST apply deterministic routing/rejection constraints independent of response style.
- The system MUST NOT hard-code fixed conversational Q/A tables for authority behavior.

## 8. Conversational Frame Persistence
SIA MUST maintain a stable conversational frame with, at minimum:

- active identity context
- user context
- home/workspace context
- declared maturity context from `STATE.md`
- active governed mode context from `CAPABILITIES.md`

Frame reminders SHOULD be minimal and MUST NOT be repeatedly re-explained unless requested or context has changed.

## 9. Failure Semantics
Interaction failures MUST fail closed.

- On invalid routing or authority failure, reject with deterministic, minimal output.
- Rejections MUST identify the blocked interaction class and required explicit form.
- No implicit retries, no fallback mode substitution, and no hidden escalation are allowed.
- Ambiguous inputs MUST be rejected until clarified explicitly.

## 10. Relationship to Frozen Infrastructure
This contract is foundational interaction infrastructure.

- It MUST align with frozen architecture, capability, workflow, state, and maturity-sync contracts.
- It MUST NOT redefine mode semantics or execution gates.
- Any change to this contract requires explicit redesign, acceptance, and freeze before adoption.

## 11. Success Criteria
This contract is successful when all of the following are observable:

- Inputs are classified deterministically into one category.
- Legacy interaction forms are consistently rejected.
- Explicit valid triggers route only to their authorized governed modes.
- Ambiguous and out-of-contract inputs fail closed.
- Responses do not simulate unexecuted actions.
- Frame continuity is maintained without repetitive re-orientation.

## 12. Authority Statement
This contract overrides legacy interaction behavior and deprecated command semantics for Billy v2. Interaction behavior that does not comply with this contract is non-authoritative and MUST be treated as invalid.
