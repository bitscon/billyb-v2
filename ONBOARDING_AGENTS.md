# Billy Agent Strategy Onboarding

## Introduction
Billy is a governed assistant. Pattern selection is a safety and quality decision, not a convenience choice.  
The default posture is to use the **least autonomous pattern** that can solve the task with clear traceability.

This document defines when to use:
1. Inert LLM content generation
2. Structured workflows
3. Tool-augmented reasoning
4. Guarded agentic loops
5. Authorized execution

The strategy encodes these design principles:
- Prefer workflows over agents.
- Avoid autonomy unless it is required by task uncertainty.
- Keep planning and decision traces visible for audit/debugging.
- Grant only minimal, essential tool scope.
- Keep designs simple and deterministic first.

## Strategy Hierarchy
Use this hierarchy in order. Do not jump to higher autonomy unless lower levels are insufficient.

1. **Inert LLM content generation**
2. **Structured workflows**
3. **Tool-augmented reasoning**
4. **Guarded agentic loops**
5. **Authorized execution**

## Definitions of Each Level
### 1) Inert LLM Content Generation
Use when the task is text-only and has no external side effects.
- Why: lowest risk, fastest iteration, no authority handoff.
- When: drafting, summarizing, rewriting, explaining, brainstorming.
- Output: text only.

### 2) Structured Workflows
Use when the task steps are known and repeatable.
- Why: deterministic control and easy auditing.
- When: prompt chaining, orchestrator->worker fan-out, evaluator loops with fixed boundaries.
- Output: explicit stage outputs and stable checkpoints.

### 3) Tool-Augmented Reasoning
Use when the task needs factual retrieval or system interaction, but not autonomous looping.
- Why: controlled capability expansion with bounded scope.
- When: read-only lookups, bounded tool calls, verification passes.
- Output: tool traces + explicit rationale.

### 4) Guarded Agentic Loops
Use only when tool feedback changes subsequent steps and fixed workflows are inadequate.
- Why: some tasks are inherently adaptive, but still require strict governance.
- When: dynamic environments, uncertain subtask ordering, iterative repair with bounded attempts.
- Output: visible planning trace, loop guards (time, step, tool, scope limits), and stop conditions.

### 5) Authorized Execution
Use when actions mutate state or perform high-impact operations.
- Why: authority transfer must be explicit and auditable.
- When: filesystem writes/deletes, deployments, service restarts, privileged operations.
- Output: approval request, governed execution record, and auditable outcome.

## Design Rules & Anti-Patterns
### Rules
- Start at the lowest level and escalate only with evidence.
- Prefer workflow composition before introducing agent loops.
- Keep tool inventories minimal and task-specific.
- Require explicit reasoning traces for any adaptive loop behavior.
- Separate planning from execution authority.
- Route all mutating actions through approval-gated execution.

### Anti-Patterns
- Using agent loops for deterministic tasks.
- Expanding tool access “just in case”.
- Hiding intermediate plans or tool decisions.
- Treating content generation as implicit permission to execute.
- Combining strategy selection and execution authority in one ungated step.

## Example Scenarios
1. **“Draft a welcome email.”**
- Pattern: Inert LLM content generation.
- Why: text only, no side effects.

2. **“Run the standard incident summary pipeline for logs.”**
- Pattern: Structured workflows.
- Why: known fixed stages and deterministic review steps.

3. **“Compare today’s service status with last week’s report.”**
- Pattern: Tool-augmented reasoning.
- Why: requires bounded retrieval tools, not autonomous looping.

4. **“Diagnose flaky integration tests across changing environments and propose fixes.”**
- Pattern: Guarded agentic loops.
- Why: adaptive iteration is needed; keep strict loop/tool limits and visible traces.

5. **“Delete obsolete files and restart service.”**
- Pattern: Authorized execution.
- Why: mutating/high-impact action requires explicit approval and governed execution.

