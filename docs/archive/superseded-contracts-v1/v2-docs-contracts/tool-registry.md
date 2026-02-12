# Contract: ToolRegistry

**Status:** Authoritative  
**Applies To:** Billy Core  
**Defined By:** BILLY-SYSTEM-SPINE.md §3 (P1 Contracts)

---

## Purpose

`ToolRegistry` is the single source of truth for:
- what tools exist
- what they are allowed to do
- how they are described and validated

It defines **capability**, not execution.

---

## Responsibilities

The ToolRegistry MUST:
- register tools with stable identifiers
- expose tool metadata and schemas
- declare permissions required by each tool
- validate tool invocation requests (args + permissions)
- remain execution-agnostic

The ToolRegistry MUST NOT:
- execute tools
- access secrets
- perform I/O
- make policy exceptions
- infer permissions dynamically

---

## Tool Definition (Canonical)

Each tool is defined by a `ToolSpec`:

```yaml
id: string            # stable, unique (e.g. "fs.list", "web.fetch")
name: string          # human-readable
description: string  # concise capability description

args_schema:          # machine-validated schema (JSON Schema compatible)
  type: object
  properties: {}
  required: []

permissions:
  network:
    outbound: false | ["dns", "http", "https"]
  filesystem:
    read: []
    write: []
  secrets:
    allowed: []       # named secrets only
  execution:
    runner: docker | local | remote
    max_duration_sec: int
    max_memory_mb: int
    max_cpu_cores: int

artifacts:
  produces: []        # declared artifact types (optional)

version: string       # semver; breaking changes require new id
