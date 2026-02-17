# Full Ladder Audit Spec

## Purpose

Define a deterministic, fail-closed documentation audit for `docs/PHASE*_PROMOTION_CHECKLIST.md` (Phases 27–67).

The audit is documentation/tooling only and does not modify runtime behavior.

## Inputs and Outputs

- Input files: `docs/PHASE*_PROMOTION_CHECKLIST.md`
- Tool: `tools/audit_ladder.py` (Python stdlib only)
- Output report: `docs/LADDER_AUDIT_REPORT.md`

## Deterministic Rules

- Discover files by filename regex `PHASE(\d+)_PROMOTION_CHECKLIST.md`.
- Sort phases numerically ascending.
- Process one phase at a time in sorted order.
- Sort per-phase findings by stable check key.
- Sort cross-phase aggregate lists lexicographically.
- Render report sections in fixed order.
- Include input SHA-256 digest for reproducibility.

Given identical input files, the report ordering and formatting are identical.

## Fail-Closed Policy

If a required signal cannot be confidently detected, mark the phase check as `FAIL` with reason prefix `NOT_FOUND`.

No heuristic pass is allowed for missing critical fields.

## Audit Checks

The audit extracts and verifies:

1. Phase metadata
- phase number
- level name
- contract name(s)

2. Upstream and linkage declarations
- declared upstream phase references
- `linked_*_id` chain fields
- expected immediate-link key presence where defined
- future-linkage drift detection

3. Invariants and negative guarantees (presence)
- `Hard Invariants` checklist signals
- `Deterministic Negative Guarantees` checklist signals
- preservation clause presence for later phases

4. Authority guarantees
- `execution_enabled` constrained to `const: false`
- `authority_guarantees` contains only false constants (no true, no unconstrained boolean)

5. Immutability guarantees
- `append_only` = true
- `mutable_after_write` = false
- `overwrite_allowed` = false
- `delete_allowed` = false

6. Rejection handling
- rejection code list present
- priority ordering present when phase text requires priority ordering

7. Uniqueness constraints
- one-per-* style uniqueness statements present (for late phases)

8. Expiry semantics
- if expiry fields are present, require explicit time-window invalidation signals

9. Runtime-change prohibition
- detect runtime delta markers that are not `none`

10. Cross-phase drift
- detect enum naming drift for state/outcome-like fields with same key name

## Report Contract

The report contains:

- PASS/FAIL counts
- per-phase PASS/FAIL status
- concrete reasons with file+section anchors
- cross-phase inconsistencies and naming drift
- missing priority ordering where expected
- missing preservation/authority false guarantees
- runtime-change mentions (should be none)

