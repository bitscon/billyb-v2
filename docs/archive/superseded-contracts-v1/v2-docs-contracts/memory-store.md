# Contract: MemoryStore

**Status:** Authoritative  
**Applies To:** Billy Core  
**Defined By:** BILLY-SYSTEM-SPINE.md §3 (P1, P5)

---

## Purpose

`MemoryStore` defines **how Billy stores, retrieves, and forgets information**.

Memory exists to:
- improve future decisions
- preserve important facts
- reduce repeated user effort

Memory is **never automatic**.

---

## Responsibilities

The MemoryStore MUST:
- store memory entries with explicit metadata
- support scoped retrieval (user, persona, session)
- apply decay and confidence rules
- enforce write policies
- emit trace events for all operations

The MemoryStore MUST NOT:
- write memory without an explicit request
- mutate memory silently
- infer importance on its own
- act as a raw transcript store
- override user intent

---

## Memory Entry (Canonical)

Each memory entry is stored as:

```yaml
id: string
content: string

scope:
  user_id: string | null
  persona_id: string | null
  session_id: string | null

metadata:
  category: string
  confidence: 0.0–1.0
  importance: low | medium | high
  source: user | system | tool
  created_at: timestamp
  expires_at: timestamp | null

retrieval:
  keywords: []
  embedding_id: string | null
````

---

## Interface

```python
write_memory(entry: MemoryEntry) -> WriteResult

query_memory(
  query: str,
  scope: Scope,
  limit: int
) -> list[MemoryEntry]

expire_memory(now: timestamp) -> ExpireResult
```

---

## Write Policy (Strict)

Memory may be written only if:

* explicitly requested by AgentLoop
* content is non-sensitive OR approved
* scope is clearly defined
* confidence and importance are set

Otherwise, write is rejected.

---

## Retrieval Rules

* Retrieval is scoped by default
* Cross-scope retrieval requires approval
* Results MUST include confidence metadata
* Retrieval does not imply endorsement

---

## Decay & Expiration

* Entries may expire automatically
* Low-confidence memories decay faster
* Expired memories are not returned
* Deletion events are traced

---

## Observability Requirements

The MemoryStore MUST emit:

* `memory_write_attempt`
* `memory_write_success`
* `memory_query`
* `memory_expired`

Each event includes:

* memory_id
* scope
* confidence
* reason (if rejected)

---

## Non-Goals

* Full chat history storage
* Implicit learning
* Self-reflection loops
* Autonomous memory reweighting

---

## Compliance

Any system that:

* writes memory implicitly
* bypasses decay rules
* suppresses memory traces

is considered a **critical architecture violation**.
