# Contract: ToolRunner

**Status:** Authoritative  
**Applies To:** Billy Core  
**Defined By:** BILLY-SYSTEM-SPINE.md §3 (P1, P2)

---

## Purpose

`ToolRunner` is responsible for **executing tools safely and deterministically**.

It enforces:
- time limits
- resource limits
- permission boundaries
- isolation guarantees

Execution happens **only after ToolRegistry validation**.

---

## Responsibilities

The ToolRunner MUST:
- execute a tool invocation using an approved execution backend
- enforce all resource and permission constraints
- capture stdout/stderr, exit codes, and artifacts
- emit structured trace events for the entire lifecycle
- terminate tools that exceed limits

The ToolRunner MUST NOT:
- decide which tool to run
- modify permissions
- infer intent
- store long-term memory
- bypass ToolRegistry validation

---

## Execution Backends

Supported runner types (initial):

- `docker` (default, authoritative)
- `local` (explicitly enabled only)
- `remote` (future)

Runner selection comes from the validated `ToolSpec`.

---

## Execution Lifecycle

1. receive validated invocation
2. prepare isolated workspace
3. apply resource + policy constraints
4. execute tool
5. capture outputs and artifacts
6. emit final trace event
7. return structured result

No step may be skipped.

---

## Interface

```python
run_tool(
  tool_id: str,
  args: dict,
  effective_permissions: dict,
  trace_context: TraceContext
) -> ToolRunResult
````

### ToolRunResult

```python
status: success | error | timeout | killed
exit_code: int | null
stdout: str
stderr: str
artifacts: list[ArtifactRef]
duration_ms: int
error_reason: str | null
```

---

## Isolation & Security (Non-Negotiable)

### Filesystem

* workspace mounted read-write
* no host FS access outside workspace
* artifacts directory write-only

### Network

* disabled by default
* explicit allowlist only (dns/http/https)
* no internal network access unless approved

### Resources

* CPU, memory, and duration strictly enforced
* hard kill on timeout
* no privileged execution

### Secrets

* secrets never written to disk
* injected only per-run if explicitly allowed
* never logged or returned

---

## Failure Semantics

* Any policy violation → immediate termination
* Partial output MAY be returned with status `error`
* No retries unless explicitly requested by AgentLoop

---

## Observability Requirements

The ToolRunner MUST emit:

* `tool_run_start`
* `tool_run_resource_applied`
* `tool_run_output_captured`
* `tool_run_end`

Each event includes:

* tool_id
* runner_type
* container_id (if applicable)
* trace_id
* duration

---

## Determinism Rules

Given:

* same tool image
* same args
* same permissions
* same environment

The result MUST be reproducible.

---

## Non-Goals

* Tool selection logic
* Argument validation
* Scheduling beyond local concurrency limits
* Cross-tool orchestration

---

## Compliance

Any tool execution outside ToolRunner
is considered a **critical architecture violation**.
