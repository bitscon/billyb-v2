# Billy v2 — Governed Conversational Assistant

Billy is a protocol-driven assistant with explicit authority boundaries.
All user input is processed through a governed conversational pipeline.

## Current Status
- Maturity Level: 28 (`Explicit Read-Only Inspection Capabilities`)
- Infrastructure freeze: Phases 1-28 are frozen unless explicitly promoted
- Frozen release tag: `maturity-level-28`
- Conversational behavior: natural language is first-class; a secretary-style front-end separates chat from governed execution escalation
- Inspection behavior: explicit contract-bound read-only inspection is available for file/directory observation without expanding authority

## How to Use
Use normal language. Billy routes requests through interpretation, policy, approval, and contract-bound execution.

## Conversational Layer (Phase 27)
- A front-end conversational interpreter runs first on natural-language turns.
- Casual chat stays in chat mode (`escalate: false`) and returns dialog output.
- Execution-oriented requests return `escalate: true` with a structured Billy-compatible intent envelope.
- Ambiguous action language is escalated to Billy’s governed interpreter for `CLARIFY`.
- The conversational layer does not execute tools, mutate state, or grant authority.
- Path mentions and read/show-style phrasing in chat do not grant filesystem/tool authority by default.
- Explicit structured governed requests continue to escalate through the interpreter.
- Policy, risk, approval, and contract execution remain enforced only in Billy’s governed interpreter.

## Explicit Inspection Layer (Phase 28)
- `inspect_file` and `inspect_directory` are explicit read-only inspection capabilities under contract.
- Inspection access is structured-intent-only and path-trust constrained (workspace allowlist + canonicalization + traversal rejection).
- Symlinks are not followed; directory symlink results are metadata-only.
- Outputs are bounded (excerpt/page/depth/hash limits) with deterministic error contracts.
- Inspection is authority-sealed: no auto-routing, no escalation, no tool chaining, no conversational context injection.
- Phase 27 conversational non-authority guarantees remain unchanged.

Examples:
- `tell me a joke` -> chat response, no escalation
- `thanks for the help` -> chat response, no escalation
- `save this idea to a file` -> escalation with intent envelope
- `that looks good; now save it` -> escalation
- `I want something done` -> escalation for governed `CLARIFY`

Examples:
- `save that joke in a text file in your home directory`
- `create an empty text file in your home directory`
- `save this idea as a note`
- `propose a simple HTML template for a homepage`
- `draft an email to welcome new users`
- `remember the last response as rome_fact`
- `save that rome_fact in a text file in your home directory`
- `what am i working on`
- `write text this to file rome.txt in my workspace`
- `reset current working set`
- `revise this to include a short conclusion`
- `transform this note to uppercase`
- `refactor the current file to add error handling`
- `create a new project for a website`
- `list all files in the project`
- `refactor all html files in this project to include a common header`
- `define project goal: launch homepage`
- `what tasks are needed to finish this site?`
- `mark task task-... as completed`
- `define a milestone: launch readiness with criteria all associated goals completed`
- `is this project complete?`
- `finalize the project`
- `archive the project`
- `list delegation capabilities for this project`
- `delegate creating the stylesheet to a coding agent`
- `describe the result of the last delegation`
- `define workflow named site_build schema {...} steps [...]`
- `preview workflow site_build with title=Home`
- `run workflow site_build with title=Home`
- `workflow status`
- `cancel current workflow`

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

Composite persistence behavior (`persist_note`):
- Requests like `save this idea as a note` route to a governed composite intent.
- Billy resolves content (inline, captured/reference, or generated minimal text) and a safe filename.
- Notes are persisted under `~/sandbox/notes/` with one explicit approval.
- Execution is still contract-bound (`write_file`) with no legacy engineer authority paths.

Working set behavior (session advisory context):
- The working set is updated after explicit capture and governed filesystem writes.
- Implicit references like `this`, `that`, `current`, `it`, `current note`, `current page`, `current file`, or `current_working_set` resolve to working-set text for write/append intents.
- Reads, clarifications, and unrelated conversation do not change the working set.
- Reset commands (`reset current working set`) and task-completion phrasing (`I'm done with this page`) clear it.
- Working set state is session-scoped, expires automatically, and does not persist as long-term memory.
- Diagnostics are available with prompts like `what am i working on`.

Revision and transformation behavior (Phase 21):
- `revise_content`, `transform_content`, and `refactor_file` are first-class governed intents.
- Billy resolves target content from explicit captured references (`that <label>`/`cc-...`) or the current working set.
- Billy generates revised/transformed output with structured generation logic and no filesystem side effects by default.
- Revised output is auto-captured as a new revision label (`<label>_revN`) and becomes the current working set.
- When write-back is requested or implied for file/page targets, Billy routes through governed `write_file` and asks for one explicit approval.

Project context behavior (Phase 22):
- Billy supports project-scoped intents: `create_project`, `update_project`, `list_project_artifacts`, `delete_project`, `open_project_artifact`, `project_wide_refactor`, `project_documentation_generate`.
- Project context is session-scoped (`project_id`, `name`, `root_path`) and resolves natural references like `this project`, `current project`, and `the site`.
- Artifact metadata is tracked under the project root and updated on governed filesystem writes/deletes.
- Project-wide refactors build governed multi-step write plans and require explicit approval before execution.
- Project diagnostics are read-only (`what project am I working on`, `show files in this project`, `show next steps for this project`).

Goal-directed execution behavior (Phase 23):
- Billy supports project goal/task intents: `define_project_goal`, `list_project_goals`, `describe_project_goal`, `list_project_tasks`, `task_status`, `propose_next_tasks`, `complete_task`.
- Goal/task proposals are advisory by default and do not execute changes.
- `propose_next_tasks` decomposes project goals into structured tasks with dependencies and status (`PENDING`/`BLOCKED`/`COMPLETED`).
- Completing a task that implies side effects is approval-gated with project/goal/task context in the approval prompt.
- Approved completion uses the existing governed execution path; no new execution authority is introduced.

Milestones and completion semantics (Phase 24):
- Billy supports milestone intents: `define_milestone`, `list_milestones`, `describe_milestone`, `achieve_milestone`.
- Milestones can associate goals and criteria, and are evaluated deterministically against existing goal/task metadata.
- `project_completion_status` reports whether the project is complete, with milestone/task breakdown and next steps.
- `finalize_project` is approval-gated and freezes project edits (read-only project state).
- `archive_project` is approval-gated and relocates project artifacts under a governed archive namespace.
- After finalization/archival, writes to project artifacts are blocked until explicit reactivation/cloning workflows are introduced.

Delegation behavior (Phase 25):
- Billy supports delegation intents: `delegate_to_agent`, `list_delegation_capabilities`, `describe_delegation_result`.
- Delegation capability scope is contract-defined in `v2/contracts/delegation_capabilities.yaml` (`agent_type` + allowed tools).
- Delegation requests are approval-gated and execute through governed `plan.user_action_request`; no direct authority is granted to sub-agents.
- Approved delegation executes a deterministic delegated generation stub, auto-captures the delegated output, and updates the working set.
- Delegation remains side-effect safe by default (no implicit filesystem writes, no legacy engineer execution).

Execution pipelines behavior (Phase 26):
- Billy supports workflow intents: `define_workflow`, `list_workflows`, `describe_workflow`, `preview_workflow`, `run_workflow`, `workflow_status`, `workflow_cancel`.
- Workflows are project-scoped metadata containing ordered governed intents and parameterized step payloads.
- `preview_workflow` is dry-run only: it resolves parameters, orders by dependencies, and reports estimated side effects with zero execution.
- `run_workflow` requires explicit approval to start and then advances one governed step per explicit `approve`.
- Workflow steps never bypass existing policy, approval, capture, filesystem scope, or delegation safeguards.
- `workflow_cancel` is approval-gated and preserves partial audit history for any completed steps.

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
- `v2/contracts/delegation_capabilities.yaml`
  Static sub-agent capability map (`agent_type`, `allowed_tools`) used to validate governed delegation scope.

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
- Phase 19: composite persistence intent (`persist_note`) with single-approval governed note writes
- Phase 20: session working set context for safe implicit `this/that/current/it` reference resolution
- Phase 21: structured revision/transformation intents with auto-capture and approval-gated write-back
- Phase 22: project-scoped context and governed multi-artifact coordination
- Phase 23: goal-directed project execution with advisory task decomposition and governed task completion
- Phase 24: milestone lifecycle, project completion checks, governed finalization, and governed archival
- Phase 25: governed delegation contracts and approval-gated sub-agent orchestration with captured results
- Phase 26: project-scoped workflow orchestration with dry-run preview, approval-gated runs, status, and cancellation
- Phase 27: conversational front-end secretary gate with explicit escalation envelopes and governed interpreter handoff
- Phase 28: explicit read-only inspection capabilities (`inspect_file`, `inspect_directory`) with authority-sealed observation boundaries

See `MATURITY.md` for freeze policy, docs gate, and promotion state.
