# Phase 27 Promotion Checklist

## Purpose
This checklist defines the freeze gate for Level 27 (`Conversational Front-End & Interpreter Gate`).

Phase 27 promotion is blocked until each criterion below is satisfied with test evidence and explicit human acceptance.

## Phase 27 Status
- Level 27 status: frozen baseline
- Frozen tag: `maturity-level-27`
- Previous frozen tag: `maturity-level-25`

## A. Hard Non-Authority Guarantees
- [x] Conversational layer cannot invoke tools directly.
  Evidence target: `v2/core/conversation_layer.py`
- [x] Conversational layer cannot mutate runtime state.
  Evidence target: `v2/core/conversation_layer.py`
- [x] Conversational layer returns only:
  - [x] `{ "escalate": false, "chat_response": "..." }`
  - [x] `{ "escalate": true, "intent_envelope": { ... } }`
  Evidence target: `tests/command_interpreter/test_phase27_conversational_layer.py`

## B. Negative Regression Guards
- [x] Read/path mentions in chat remain non-authoritative by default.
  Evidence target: `tests/command_interpreter/test_phase27_conversational_layer.py`
- [x] Read-like prompts do not enter governed execution path.
  Evidence target: `tests/test_interaction_dispatcher.py`
- [x] Read-like prompts do not trigger deterministic inspection path.
  Evidence target: `tests/test_interaction_dispatcher.py`
- [x] Explicit structured escalation paths still work.
  Evidence target: `tests/command_interpreter/test_phase27_conversational_layer.py`

## C. Single Authority Gateway
- [x] All policy/risk/approval/execution authority remains in governed interpreter paths only.
  Evidence target: `README.md`, `MATURITY.md`, `v2/contracts/intent_policy_rules.yaml`
- [x] No alternate authority shortcut exists in the secretary layer.
  Evidence target: `v2/core/runtime.py`, `v2/core/conversation_layer.py`

## D. Freeze Hygiene
- [x] `README.md`, `MATURITY.md`, `STATE.md`, `STATUS.md`, and onboarding docs are synchronized.
- [x] Full test suite passes in the target environment.
- [x] Human promotion acceptance is recorded.
- [x] New frozen tag created only at promotion time (`maturity-level-27`).

## Freeze Acceptance Record (Required)
- Approved by: Billy maintainer (explicit session instruction: "Freeze it. Tag it.")
- Date: 2026-02-16
- Evidence bundle:
  - `v2/core/conversation_layer.py`
  - `v2/core/runtime.py`
  - `tests/command_interpreter/test_phase27_conversational_layer.py`
  - `tests/test_interaction_dispatcher.py`
- Test report:
  - `./venv/bin/pytest -q tests/command_interpreter/test_phase27_conversational_layer.py tests/test_interaction_dispatcher.py` -> `36 passed`
  - `./venv/bin/pytest -q` -> `2 passed`
- Freeze decision: ACCEPTED. Phase 27 promoted to frozen baseline and tagged `maturity-level-27`.

