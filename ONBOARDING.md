## 1. Purpose
This file defines how to start a new session safely in the current Billy state.

## 2. Required Pre-Read (Mandatory)
Before doing work, read these files in order:
1. `README.md`
2. `ARCHITECTURE.md`
3. `CAPABILITIES.md`
4. `STATE.md`
5. `MATURITY.md`

## 3. Current Operating Model (Level 16)
- Talk to Billy in normal language.
- Billy routes every message through governed interpretation and policy.
- Action requests do not execute immediately; Billy requests explicit approval.
- Approval must use an allowed exact phrase.
- Ambiguous requests route to `CLARIFY`.
- Content must be explicitly captured before later references like `that <label>`.

## 4. Approval Rules (Exact)
Allowed approval phrases (case-insensitive exact match):
- `yes, proceed`
- `approve`
- `approved`
- `go ahead`
- `do it`

Disallowed as approval:
- `ok`
- `sure`
- `sounds good`

## 5. Deprecated Inputs
The following inputs are deprecated and informational only:
- `/engineer`
- `engineer mode`

They must not block routing or execution governance.

## 6. Example Conversations
### Example A: Natural-language action
User: `save that joke in a text file in your home directory`
Billy: approval request describing intent, risk, and exact approval phrase
User: `approve`
Billy: executes once via governed contract path and records audit/memory

### Example B: Ambiguous request
User: `qzv blorp`
Billy: returns `CLARIFY` with a follow-up question

### Example C: Deprecated mode input
User: `/engineer`
Billy: informational deprecation message; governed routing remains active

### Example D: Explicit content capture + reuse
User: `tell me a fun fact about Rome`
Billy: returns fact text
User: `remember the last response as rome_fact`
Billy: confirms captured content with an ID
User: `save that rome_fact in a text file in your home directory`
Billy: approval request through governed execution path

## 7. Freeze and Promotion Rule
Phases approved as frozen infrastructure must not be tuned implicitly.
Any behavioral change to frozen phases requires explicit promotion and acceptance.

## 8. Docs Gate (Always)
For every future phase:
- Update `README.md` and `MATURITY.md`
- Update onboarding docs when user-facing behavior changes
- Provide tests proving behavior and documentation are aligned

A phase is not complete until docs + tests are updated together.
