# Contract: AgentLoop

**Status:** Authoritative  
**Applies To:** Billy Core  
**Defined By:** BILLY-SYSTEM-SPINE.md §3 (P1)

---

## Purpose

`AgentLoop` is responsible for **turn-level decision making**.

It converts:
- user input
- system state
- memory context

into:
- zero or more tool invocations
- a final response

It does **not** execute tools directly.

---

## Responsibilities

The AgentLoop MUST:
- assemble context (persona, memory, system state)
- request proposals from an LLM
- select or reject proposed actions
- invoke ToolRegistry validation
- dispatch approved actions to ToolRunner
- aggregate results
- produce a final response
- emit trace events for each step

The AgentLoop MUST NOT:
- bypass ToolRegistry or ToolRunner
- directly execute system commands
- mutate system state without traces
- assume tools succeeded without confirmation
- self-modify code or contracts

---

## Decision Model

The AgentLoop operates in **explicit phases**:

1. **Input Intake**
2. **Context Assembly**
3. **Planning / Proposal**
4. **Validation**
5. **Execution**
6. **Synthesis**
7. **Completion**

Each phase emits trace events.

---

## Interface

```python
run_turn(
  user_input: str,
  session_context: SessionContext
) -> AgentTurnResult
````

### AgentTurnResult

```python
final_output: str
tool_calls: list[ToolRunResult]
status: success | partial | error
trace_id: str
```

---

## Planning Phase Rules

* Planning MAY involve one or more LLM calls
* LLM outputs are treated as **untrusted proposals**
* All proposals must be:

  * validated
  * normalized
  * policy-checked

No proposal is executed automatically.

---

## Tool Invocation Rules

* Tool calls MUST pass:

  1. ToolRegistry validation
  2. Approval gates (if required)
  3. ToolRunner execution

* Failed tools do NOT halt the loop by default

* The AgentLoop decides whether to:

  * retry
  * degrade
  * abort
  * continue

---

## Memory Interaction

The AgentLoop:

* MAY read memory before planning
* MAY write memory after completion
* MUST respect MemoryStore policies
* MUST emit memory read/write trace events

Memory writes are never automatic.

---

## Error Handling

* Errors are classified:

  * planning_error
  * validation_error
  * execution_error
  * synthesis_error

* Errors are returned explicitly

* Partial results may be returned with status `partial`

---

## Observability Requirements

The AgentLoop MUST emit:

* `agent_turn_start`
* `agent_context_assembled`
* `agent_plan_proposed`
* `agent_tool_validated`
* `agent_tool_executed`
* `agent_turn_end`

Each event includes:

* trace_id
* phase
* duration
* outcome

---

## Determinism Rules

Given:

* same user input
* same session state
* same memory snapshot
* same tool results

The AgentLoop MUST produce the same final output.

---

## Non-Goals

* Multi-agent coordination
* Background scheduling
* Long-running workflows
* UI rendering concerns

---

## Compliance

Any system behavior that:

* executes tools outside this loop
* skips validation
* suppresses trace events

is considered a **critical architecture violation**.
