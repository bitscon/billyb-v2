# Billy v2 — Governed Conversational Assistant

Billy is a protocol-driven assistant with explicit authority boundaries.
All user input is processed through a governed conversational pipeline.

## Current Status
- Maturity Level: 18 (`Content Generation Intent Class`)
- Infrastructure freeze: Phases 1-18 are frozen unless explicitly promoted
- Conversational behavior: natural language is first-class; legacy engineer mode is deprecated

## How to Use
Use normal language. Billy routes requests through interpretation, policy, approval, and contract-bound execution.

Examples:
- `save that joke in a text file in your home directory`
- `create an empty text file in your home directory`
- `propose a simple HTML template for a homepage`
- `draft an email to welcome new users`
- `remember the last response as rome_fact`
- `save that rome_fact in a text file in your home directory`

Execution flow:
1. Billy interprets your message into an intent envelope.
2. Billy evaluates deterministic policy (`allowed`, `risk_level`, `requires_approval`).
3. If action is requested, Billy asks for explicit approval.
4. On valid approval, Billy executes exactly once via a registered tool contract.

Approval phrases (exact match, case-insensitive):
- `yes, proceed`
- `approve`
- `approved`
- `go ahead`
- `do it`

Ambiguous input behavior:
- Ambiguous input routes to `CLARIFY` with a follow-up question.
- Normal language is not rejected as a legacy interaction.

Content capture behavior:
- Capture is explicit and user-initiated only (`capture this`, `store this content with label X`, `remember the last response as X`).
- Captured content is stored with `content_id`, source, timestamp, and turn correlation metadata.
- References can use `content_id` (for example `cc-...`) or label (`that <label>`).
- Ambiguous labels are rejected; Billy does not guess.

Content generation behavior:
- Requests to generate/draft/propose review content route to `CONTENT_GENERATION`.
- `CONTENT_GENERATION` produces text only (no tools, no execution, no approval).
- Generated output is eligible for explicit capture via Phase 16.

## Deprecated Inputs
The following are informational only and do not gate behavior:
- `/engineer`
- `engineer mode`

Billy responds with a deprecation note and continues governed routing normally.

## What Billy Will NOT Do
- Execute without explicit approval
- Infer approval from ambiguous language (`ok`, `sure`, etc.)
- Act autonomously or run background tasks
- Bypass policy or approval gates
- Dynamically replan frozen planning behavior
- Change behavior based on memory without explicit promotion

## Contract Index
- `v2/contracts/intent_policy_rules.yaml`
  Deterministic policy map by `lane::intent` used for allow/deny, risk, and approval requirements.
- `v2/contracts/intent_tool_contracts.yaml`
  Static intent-to-tool contract registry used for contract-bound (stubbed) execution.

## Maturity Snapshot
Implemented and frozen progression:
- Phase 1: deterministic interpretation
- Phase 2: semantic lane routing with fallback
- Phase 3: schema-validated structured extraction
- Phase 4: deterministic policy evaluation
- Phase 5: explicit conversational approval gating
- Phase 6: contract-bound tool registry + stub invoker
- Phase 7: append-only execution memory + recall
- Phase 8: approval-gated multi-step planning
- Phase 9: conversational entrypoint unification
- Phase 10: LLM boundary and control-loop integrity
- Phase 11: internal maturity promotion and freeze hardening
- Phase 12: memory-driven advisory insights (non-authoritative)
- Phase 13: observability + replay debugging
- Phase 14: policy/contract evolution workflows (human-governed)
- Phase 15: bounded autonomy (opt-in, scoped, revocable)
- Phase 16: explicit content capture and reference resolution
- Phase 17: governed filesystem collaboration with scope enforcement
- Phase 18: content generation intent class (review-only draft output)

See `MATURITY.md` for freeze policy, docs gate, and promotion state.
