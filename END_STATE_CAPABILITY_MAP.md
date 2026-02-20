# End-State Capability Map

## Purpose
This document defines the current capability boundary for Billy and the required path from governance to execution.

## Current Capability Boundary (Post-Phase 49)
- Observe: Explicit, read-only inspection only (`inspect_file`, `inspect_directory`) with bounded output, path/symlink safety, and no mutation.
- Reason about: Structured analysis over explicitly bound artifacts only (no ambient context carryover).
- Propose: Inert synthesis outputs and action plans only (no execution semantics).
- Approve: Explicit human approval artifacts with deterministic state and scope.
- Authorize: Time-bounded, revocable authorization artifacts tied to lineage and audit integrity.
- Attempt: Deterministic admissibility checks via validation, arming, and attempt boundary.
- Execute: Nothing. Execution is not enabled.

## Capability Tiers
1. Governance completeness: Complete through Phase 49 and treated as baseline constitution.
2. Execution substrate: Next tier; must be external, minimal, and non-reasoning.
3. Autonomy: Deferred until execution substrate is proven safe, reversible, and auditable.

## Execution Introduction Policy
Execution is introduced only after Phase 49, and only via an external executor that cannot reason or escalate.

The external executor must:
- Accept one sealed, validated, armed, admissible attempt payload.
- Perform one bounded operation.
- Return deterministic results and audit references.
- Hold no planning authority, memory, or delegation authority.

## Non-Negotiable Constraints
- No implicit authority inference from prior artifacts.
- No ambient context execution.
- No hidden execution paths.
- No mutation without explicit, governed boundary crossing.
