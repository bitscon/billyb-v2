Billy v2 runtime entrypoint documentation.

## ACI Intent Router + Phase Gatekeeper
Conversational input is routed through a deterministic ACI ingress path before any
governance-ladder action is considered:

1. `IntentRouter` classifies exactly one `INTENT_CLASS`.
2. `PhaseGatekeeper` checks strict phase admissibility (read-only ladder state).
3. Billy returns one deterministic envelope shape only:
   - `proposal`
   - `refusal`
   - `clarification`

This ingress path is classification + gating only. It does not execute, invoke tools,
mutate state, or auto-advance phases.

## ACI Issuance Ledger
When a human provides explicit confirmation (`confirm issuance`), Billy records one
issued governance artifact in an append-only ACI ledger:

1. Deterministic lineage validation (present, unrevoked, environment-consistent).
2. Single-use/replay guard for the same phase transition and lineage.
3. Read-only `receipt` envelope return with artifact metadata.

This path remains non-executing and non-autonomous. It issues governance records
only, with `execution_enabled` fixed to `false` and all authority guarantees `false`.

The ledger also supports explicit negative-authority artifacts:

1. `revocation_record.v1` via `revoke <artifact_id>` (confirmation-gated).
2. `supersession_record.v1` via `supersede <old_artifact_id> with <new_artifact_id>` (confirmation-gated).

Revoked and superseded artifacts remain readable/auditable but are inadmissible for
downstream lineage validation.
