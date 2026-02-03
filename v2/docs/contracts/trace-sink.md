# Contract: TraceSink

**Status:** Authoritative  
**Applies To:** Billy Core  
**Defined By:** BILLY-SYSTEM-SPINE.md §3 (P3)

---

## Purpose

`TraceSink` defines **how Billy records, stores, and exposes execution traces**.

Traces exist to provide:
- auditability
- debuggability
- determinism verification
- postmortem analysis

If it didn’t emit a trace, it didn’t happen.

---

## Responsibilities

The TraceSink MUST:
- accept structured trace events from all core primitives
- enforce a stable event schema
- correlate events by trace_id
- persist traces for later inspection
- support streaming and batch ingestion

The TraceSink MUST NOT:
- alter event semantics
- drop events silently
- infer missing events
- act as a logging replacement
- execute business logic

---

## Trace Event (Canonical)

Each trace event MUST include:

```yaml
trace_id: string
event_id: string
event_type: string
timestamp: timestamp

actor:
  component: agent_loop | tool_registry | tool_runner | memory_store | system
  instance_id: string | null

payload:
  data: object

metadata:
  duration_ms: int | null
  outcome: success | error | denied | timeout | null
````

---

## Interface

```python
emit(event: TraceEvent) -> None

flush(trace_id: str) -> None

get_trace(trace_id: str) -> list[TraceEvent]
```

---

## Event Requirements

* Events MUST be emitted in-order per component
* Events MAY arrive out-of-order across components
* All events MUST reference a valid `trace_id`
* Missing critical events is a hard error

---

## Persistence Rules

* Traces are append-only
* Traces are immutable once written
* Retention policy is configurable
* Deletion (if any) is itself traced

---

## Observability Guarantees

At minimum, a trace MUST allow reconstruction of:

* agent decision phases
* tool validation vs execution
* memory reads/writes
* failures and policy denials
* total request duration

---

## Determinism & Auditing

Given a trace, an engineer MUST be able to answer:

* what happened
* in what order
* why a decision was made
* what data was used
* what failed (if anything)

---

## Non-Goals

* Human-readable logging format
* Metrics aggregation
* Alerting
* UI rendering

---

## Compliance

Any component that:

* performs an action without emitting a trace
* emits malformed or partial events
* suppresses trace failures

is considered a **critical architecture violation**.
