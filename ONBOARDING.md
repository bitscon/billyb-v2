## 1. Purpose
This file defines how to start a new session safely in the current Billy state.

## 2. Required Pre-Read (Mandatory)
Before doing work, read these files in order:
1. `AGENTS.md`
2. `README.md`
3. `ARCHITECTURE.md`
4. `CAPABILITIES.md`
5. `STATE.md`
6. `STATUS.md`
7. `MATURITY.md`
8. `MATURITY_MODEL.md`
9. `MATURITY_SYNC_CONTRACT.md`

## 3. Current Operating Model (Level 24)
- Talk to Billy in normal language.
- Billy routes every message through governed interpretation and policy.
- Action requests do not execute immediately; Billy requests explicit approval.
- Approval must use an allowed exact phrase.
- Ambiguous requests route to `CLARIFY`.
- Content must be explicitly captured before later references like `that <label>`.
- Filesystem collaboration is governed, scope-checked, and approval-gated for mutating actions.
- Review-only drafting requests route to `CONTENT_GENERATION` with no execution side effects.
- Composite note persistence requests (`save this idea as a note`) resolve into governed `write_file` with one approval.
- Session working set context resolves `this/that/current/it` and tokens like `current note`, `current page`, `current file`, `current_working_set` for write/append requests when applicable.
- Working set resets on explicit reset commands, task-completion phrases, or session expiry.
- Reads, clarifications, and unrelated chat do not mutate the working set.
- Revision/transformation requests (`revise`, `transform`, `refactor`) resolve through Phase 21 composite intents.
- Revised output is auto-captured to a revision label and updates the working set.
- Any filesystem write-back from revision/refactor still requires explicit approval.
- Project-scoped intents support multi-artifact coordination under an active project context.
- Project-wide refactors use governed multi-step planning and approval before writes.
- Project diagnostics (`what project am I working on`, `show files in this project`) are read-only.
- Project goals/tasks are first-class (`define_project_goal`, `propose_next_tasks`, `list_project_tasks`, `task_status`, `complete_task`).
- Task decomposition is advisory and side-effect free until an explicit approved action is requested.
- Completing side-effecting tasks requires one approval and includes project/goal/task context in the approval prompt.
- Project milestones are first-class (`define_milestone`, `list_milestones`, `describe_milestone`, `achieve_milestone`).
- Project completion checks are advisory (`project_completion_status`) and deterministic over milestones/goals/tasks.
- `finalize_project` and `archive_project` are approval-gated lifecycle actions.
- Finalized/archived projects are read-only for artifact writes unless explicitly reactivated/cloned.

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

### Example E: Content generation + capture
User: `propose a simple HTML template for a homepage`
Billy: returns HTML draft text directly (no approval)
User: `capture this as homepage_template`
Billy: confirms captured content with an ID

### Example F: Composite note persistence
User: `save this idea as a note`
Billy: requests one approval for a governed write to `~/sandbox/notes/<generated-name>.txt`
User: `approve`
Billy: persists note and confirms the resolved file path

### Example G: Working set diagnostics + implicit reference
User: `capture this as homepage_draft`
Billy: confirms captured content and updates current working set
User: `what am i working on`
Billy: reports the current working set label
User: `write text this to file homepage.txt in my workspace`
Billy: requests approval for governed write using working-set text
User: `approve`
Billy: executes once and confirms

### Example H: Revise current artifact
User: `revise the current page to add a footer with copyright notice`
Billy: generates revised content, auto-captures it as a revision label, and requests one approval for write-back
User: `approve`
Billy: writes once through governed `write_file` and confirms path

### Example I: Project context + multi-artifact refactor
User: `create a new project for personal website`
Billy: creates session-scoped project context with normalized root path
User: `refactor all html files in this project to include a common header`
Billy: prepares governed multi-step write plan and requests approval
User: `approve`
Billy: executes steps through governed contracts and updates project artifact metadata

### Example J: Goal + task decomposition
User: `define project goal: launch homepage`
Billy: records a project goal (advisory metadata)
User: `what tasks are needed to finish this site?`
Billy: proposes structured tasks with dependency/status context (no execution)
User: `mark task task-... as completed`
Billy: either marks complete directly (advisory task) or requests explicit approval if side effects are implied

### Example K: Milestone + closure lifecycle
User: `define a milestone: launch readiness with criteria all associated goals completed`
Billy: records milestone metadata tied to project goals
User: `is this project complete?`
Billy: returns completion status breakdown and next steps
User: `finalize the project`
Billy: requests approval, then freezes project to read-only on approval
User: `archive the project`
Billy: requests approval, then relocates project artifacts to governed archive storage

## 7. Freeze and Promotion Rule
Phases approved as frozen infrastructure must not be tuned implicitly.
Any behavioral change to frozen phases requires explicit promotion and acceptance.

## 8. Docs Gate (Always)
For every future phase:
- Update `README.md` and `MATURITY.md`
- Update onboarding docs when user-facing behavior changes
- Provide tests proving behavior and documentation are aligned

A phase is not complete until docs + tests are updated together.
