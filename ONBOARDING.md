## 1. Purpose
This file defines how to start a new session safely in the current Billy state.

## 2. Re-Entry Instructions for Coding Assistants
- Read `ONBOARDING.md` first.
- Read `MATURITY.md` second.
- Identify the highest frozen maturity level before any edits.
- Respect all freeze boundaries for approved frozen levels.
- Locate the latest implemented phase and treat it as the current working edge.
- Run tests before making changes.
- Extend maturity forward only; do not retroactively alter frozen phase behavior.

## 3. Required Pre-Read (Mandatory)
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
10. `v2/contracts/delegation_capabilities.yaml`
11. `ONBOARDING_AGENTS.md`

## 4. Current Operating Model (Level 31)
- Level 31 is frozen baseline behavior; changes require explicit forward promotion.
- A conversational front-end (secretary layer) runs before governed interpretation.
- Casual conversation returns direct dialog and does not invoke execution governance.
- Action-oriented and ambiguous action language escalates with a structured intent envelope.
- The conversational layer has no execution authority and cannot mutate state.
- Read/show/view/inspect phrasing in chat does not grant filesystem or tool authority unless escalation is explicit and structured.
- Explicit inspection capabilities are now frozen: `inspect_file` and `inspect_directory`.
- Inspection is read-only and bounded by contract (allowlist paths, traversal rejection, no symlink traversal, deterministic error model).
- Inspection output is caller-only and cannot auto-trigger routing, escalation, tool chaining, or conversational context mutation.
- Phase 29 inspection dispatch boundary is frozen as specification-only: inspection outputs are inert unless explicitly bound to downstream reasoning.
- Inspection-to-reasoning handoff requires structured binding (`inspection_result_id`, immutable payload reference, scope/lifetime/owner) and cannot occur through ambient context or implicit memory.
- Inspection dispatch preserves Phase 27 conversational non-authority and Phase 28 read-only/non-escalation guarantees.
- Phase 30 delegation envelope is frozen as specification-only: delegation is advisory-only and does not grant delegate authority.
- Delegates have zero execution/tool/mutation authority and cannot escalate authority, persist memory, or recursively delegate.
- Delegate outputs are inert and returned only to Billy orchestration; follow-on action still requires explicit governed routing and approval.
- Phase 31 orchestrator synthesis loop is frozen as specification-only: Billy assembles inert structured inputs into review outputs (`proposal`, `plan`, `draft`, `analysis`).
- Synthesis remains non-executing and non-mutating: no tool invocation, no delegation trigger, no background processing, no implicit persistence, and no authority escalation.
- Synthesized output is inert and cannot be auto-applied; any follow-on action requires explicit governed routing and approval.
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
- Delegation intents are first-class (`delegate_to_agent`, `list_delegation_capabilities`, `describe_delegation_result`).
- Delegation scope is constrained by `v2/contracts/delegation_capabilities.yaml`.
- Approved delegation captures generated output and updates the session working set.
- Delegation never grants new execution authority and does not bypass governed approval.
- Workflow intents are first-class (`define_workflow`, `list_workflows`, `describe_workflow`, `preview_workflow`, `run_workflow`, `workflow_status`, `workflow_cancel`).
- Workflows are project-scoped metadata; preview is dry-run only and execution is approval-gated.
- Workflow runs advance one governed step per explicit approval and preserve full audit trail.
- Workflow cancellation is approval-gated and records partial-progress state.

## 5. How to Talk to Billy
- Casual prompts (`tell me a joke`, `thanks`, `explain X`) stay in chat mode and do not escalate.
- Execution prompts (`save`, `write`, `create`, `run`, `delete`, `refactor`, `delegate`, `workflow`, `project`) escalate to governed interpretation.
- Read-only phrasing without explicit structured escalation (`read`, `show`, `view`, `inspect`) stays non-authoritative chat.
- Mixed prompts (`that looks good; now save it`) escalate.
- Ambiguous action prompts (`I want something done`) escalate and are handled as governed `CLARIFY`.
- The governed interpreter remains the only place where policy and approval are enforced.

## 6. Approval Rules (Exact)
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

## 7. Deprecated Inputs
The following inputs are deprecated and informational only:
- `/engineer`
- `engineer mode`

They must not block routing or execution governance.

## 8. Example Conversations
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

### Example L: Delegation with approval
User: `list delegation capabilities for this project`
Billy: returns available specialist agent types and their allowed tools
User: `delegate creating the stylesheet to a coding agent`
Billy: requests approval with delegation contract summary
User: `approve`
Billy: executes governed delegation once, captures delegated output, and updates working set

### Example M: Workflow orchestration
User: `define workflow named site_build schema {"title":{"required":true}} steps [...]`
Billy: validates and stores workflow metadata in project context (no execution)
User: `preview workflow site_build with title=Home`
Billy: returns ordered dry-run preview with resolved parameters and side-effect summary
User: `run workflow site_build with title=Home`
Billy: requests approval for workflow start
User: `approve`
Billy: starts workflow run
User: `approve`
Billy: executes next governed step and reports progress
User: `workflow status`
Billy: reports completed/pending steps and current state

## 9. Freeze and Promotion Rule
Phases approved as frozen infrastructure must not be tuned implicitly.
Any behavioral change to frozen phases requires explicit promotion and acceptance.

## 10. Docs Gate (Always)
For every future phase:
- Update `README.md` and `MATURITY.md`
- Update onboarding docs when user-facing behavior changes
- Provide tests proving behavior and documentation are aligned

A phase is not complete until docs + tests are updated together.
