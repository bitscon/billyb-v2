# Billy v2 — Governed Engineering Assistant

Billy is a **protocol-driven engineering assistant** designed to behave like a safe, auditable, self-hosted alternative to Codex.

Billy separates **thinking from power**.  
Nothing executes implicitly.  
Every dangerous action is explicit, gated, and logged.

This repository is the **canonical source of truth** for Billy’s capabilities and constraints.

---

## What Billy Is

Billy is an engineering agent that can:
- reason about systems and code
- draft concrete changes
- apply approved code
- design, approve, register, and execute tools

All actions follow explicit human approval gates.

Billy is designed to be:
- predictable
- inspectable
- auditable
- extensible without refactoring core behavior

---

## What Billy Is Not

Billy does **not**:
- execute autonomously
- infer intent
- select tools on its own
- chain actions
- run background jobs
- bypass approval or confirmation steps

Power is earned in stages.

---

## Engineering Pipeline (High Level)

Billy operates through a fixed pipeline of modes:

ERM → CDM → APP → CAM
↘
TDM → Tool Approval → TRM → TEM


Each mode has a single responsibility and hard boundaries.

---

## Capabilities by Mode

| Mode | Trigger | Purpose |
|-----|-------|--------|
| ERM (Engineering Reasoning) | `engineer:`, `analyze:` | Explain, analyze, reason |
| CDM (Code Drafting) | `draft:`, `propose:` | Draft code changes |
| APP (Approval) | `approve:` | Freeze approved drafts |
| CAM (Code Application) | `apply:` | Apply approved code only |
| TDM (Tool Definition) | `tool:`, `design tool:` | Design tool specifications |
| Tool Approval | `approve tool:` | Approve tool definitions |
| TRM (Tool Registration) | `register tool:` | Register tools (visible, inert) |
| TEM (Tool Execution) | `run tool:` + `confirm run tool:` | Execute tools with confirmation |

---

## Typical Usage Flow

### 1. Reason about a problem
engineer: analyze how execution journaling works


### 2. Draft a change
draft: refactor execution journal path handling


### 3. Approve the draft
approve: DRAFT-014


### 4. Apply the approved draft
apply: DRAFT-014


### 5. Design a tool
tool: design tool for applying approved drafts


### 6. Approve the tool
approve tool: TOOL-003


### 7. Register the tool
register tool: TOOL-003


### 8. Execute the tool (explicit, gated)
run tool: apply_approved_draft {"draft_id":"DRAFT-014"}
confirm run tool: apply_approved_draft


---

## Safety Guarantees

Billy enforces the following invariant:

designed
→ approved
→ registered
→ explicitly invoked
→ validated
→ confirmed
→ executed


If any gate is missing, execution **hard-stops**.

All approvals, applications, and executions are:
- hash-validated
- append-only
- auditable

---

## Repository Status

- All core modes implemented
- 180+ tests passing
- Core infrastructure frozen
- New capabilities added only as new modes

---

## Key Documentation

For deeper understanding, read these in order:

1. `ARCHITECTURE.md` — system mental model
2. `CAPABILITIES.md` — fast reference
3. `STATE.md` — current project status
4. `ONBOARDING.md` — instructions for new sessions

---

## Design Philosophy (Short)

Billy favors:
- explicit intent over inference
- boring execution over cleverness
- protocol over personality

This makes Billy safe enough to grow.

What to do next (keeping the same workflow)
create the README.md

Commit it

Tell Codex: “README.md accepted. Freeze.”

Then we move on to the next document:
