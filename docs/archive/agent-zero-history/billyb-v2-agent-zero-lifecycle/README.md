# Agent Zero Lifecycle Management (Billy v2)

This document set defines the **authoritative lifecycle, governance, and control system**
for managing the Agent Zero codebase inside Billy v2.

This specification is **complete**, **locked**, and **implementation-ready**.

## Purpose
- Safe upgrade and rollback of Agent Zero
- Human-controlled approval workflow
- Auditable, state-machine-governed execution
- Explicit authority escalation and revocation

## Start Here (Implementers)
1. Read **01-architecture-overview.md**
2. Implement schemas from **schemas/**
3. Follow **09-implementation-checklist.md** strictly in order

## Quick Command Reference

| Command | Purpose |
|------|------|
| `a0 status` | Show lifecycle status |
| `a0 check-updates` | Detect new stable releases |
| `a0 pending-approvals` | Show approval queue |
| `approve a0 upgrade <v>` | Human approval |
| `deny a0 upgrade <v>` | Human denial |
| `a0 upgrade <v>` | Execute upgrade |
| `a0 rollback` | Roll back to known-good |
| `a0 confirm` | Mark version known-good |

## Canonical Constraints
- **Working Path:** `v2/agent_zero/`
- **Metadata Path:** `v2/agent_zero/.billy/`
- **Staging Path:** `/tmp/agent_zero-*`
- **Release Source:** GitHub **tagged releases only**
- **Initial Authority:** `observer`
- **Approval:** Mandatory, human-only
- **Audit Log:** Append-only JSONL