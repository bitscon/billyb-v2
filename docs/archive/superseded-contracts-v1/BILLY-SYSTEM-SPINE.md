# BILLY SYSTEM SPINE (Authoritative)

**Status:** Authoritative Source of Truth  
**Scope:** Identity, boundaries, contracts, operating modes, and the build plan.  
**Rule:** If a doc, prompt, or code behavior conflicts with this file — this file wins.

---

## 0) North Star

Billy is a long-lived, self-hosted assistant platform built for:
- reliable reasoning
- safe tool execution
- durable memory and traceability
- incremental capability growth without rewrites

Billy is not a “project.” Billy is infrastructure.

---

## 1) Authority Model (Who Decides What)

### 1.1 Billy is the orchestrator
Billy is the authority for:
- interpreting user intent into an internal plan
- selecting tools
- enforcing policy (permissions, secrets, network, filesystem)
- executing tools (via approved runners)
- recording traces + artifacts
- deciding what is stored in memory (via explicit policies)

### 1.2 LLMs are advisors, not authorities
LLMs may propose:
- plans
- tool calls
- summaries
- text output

LLMs may never:
- execute tools directly
- bypass policies
- write secrets
- self-modify code without explicit approval steps
- claim actions happened unless confirmed by traces

### 1.3 Humans are the final authority
Sensitive actions require approval gates (see §6).

---

## 2) System Boundaries (What Billy Is / Is Not)

### 2.1 Billy is
- a runtime + contracts + execution substrate
- a set of stable interfaces (tools/memory/trace/agent loop)
- a repo with a disciplined change process
- an API/CLI/WebUI *surface* (UI is not the core)

### 2.2 Billy is not
- a general “autonomous internet agent”
- a replacement for OS admin judgement
- a black box that can’t be audited
- a chatbot that improvises system state

---

## 3) Core Primitives (Non-negotiable)

These primitives must exist and be stable.

### P1 — Contracts (Interfaces)
- `AgentLoop` (plan/decide)
- `ToolRegistry` (what tools exist)
- `ToolRunner` (how tools run)
- `MemoryStore` (store/retrieve policies)
- `TraceSink` (structured events)

### P2 — Deterministic Execution Substrate
- Tools run through **Billy-managed execution** (default: Docker runner)
- Policies are enforced in the runner (timeouts, resources, network, mounts)

### P3 — Traceability
Every request produces a trace:
- request_start / request_end
- llm_call_start/stop
- tool_call_start/stop
- memory_read/write
- errors (typed, structured)

### P4 — Artifacts
Tool outputs and generated files are saved as artifacts:
- versioned
- size-limited
- referenced by trace IDs

### P5 — Memory Policy
Memory is explicit:
- what is stored
- why it is stored
- confidence / decay
- namespaces per persona/user

---

## 4) Operating Modes (How We Work)

### 4.1 Build Mode (default)
- implement small, testable increments
- ship one primitive at a time
- no big-bang rewrites

### 4.2 Read-Only Planning Mode (`/plan`)
- no file writes
- no tool execution
- architecture/decision work only

### 4.3 Safe Execution Mode (`/exec-safe`)
- tool execution allowed
- strict allowlists
- approval gating for sensitive actions

---

## 5) Source of Truth Rules (Stop the Drift)

### 5.1 Documentation hierarchy
1. **THIS FILE** (`docs/BILLY-SYSTEM-SPINE.md`)
2. Boundary contracts (to be created): `docs/contracts/*.md`
3. Architecture maps and rationale docs: `docs/architecture/*.md`
4. Phase plans and checklists: `docs/plans/*.md`
5. Everything else is non-authoritative

### 5.2 When starting any coding session
The coder MUST:
1. Read this spine
2. State current milestone (see §7)
3. List intended file changes (max 3)
4. Implement and prove with tests/logs

If they can’t do that, they are not allowed to change code.

---

## 6) Safety + Approval Gates

### 6.1 Always requires explicit approval
- network egress for tools (unless tool allowlisted)
- filesystem writes outside workspace/artifacts
- secrets injection into tool containers
- codebase modifications beyond the agreed change list
- any “self-update” behavior

### 6.2 Default deny posture
- tools: deny by default, allow by explicit registry entry
- network: none by default
- mounts: workspace only
- secrets: Billy holds secrets; tools receive none unless approved

---

## 7) Milestones (Authoritative)
- [x] M9.2 — Plan Validation & LLM Guardrails
- [x] M9.3 — Plan Diffing & Promotion Locks
- [x] M9.4 — Plan History & Rollback Guarantees
- [x] M10 — Tool Contracts & Capability Registry
- [x] M11 — Execution Journaling & Forensics
- [ ] M12 — Human Approval Gates (DEFERRED)

---

## 8) Definitions (Short)

- **Tool**: a named capability with args schema and permissions, executed by a runner.
- **Runner**: executes tools (default Docker) and enforces policy.
- **Artifact**: file output produced by a tool or build step.
- **Trace**: structured timeline of one request’s operations.
- **Contract**: stable interface boundary that prevents rewrites.

---

## 9) Non-Goals (For Now)

Not in scope until milestones M0–M3 are stable:
- multi-agent orchestration
- distributed execution (Swarm/K8s)
- autonomous self-improvement loops
- complex UI “step inspector”
- deep Agent Zero coupling

---

## 10) Current Session Rule

All work must state:
- current milestone (from §7)
- one primitive being advanced
- exact files to change (max 3)
- how we verify success (test/log/trace)

If any of these are missing, the change is rejected.
