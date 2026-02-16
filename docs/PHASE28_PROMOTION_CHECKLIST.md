# Phase 28 Promotion Checklist

## Purpose
This checklist defines the freeze gate for Level 28 (`Explicit Read-Only Inspection Capabilities`).

Phase 28 promotion is blocked until each criterion below is satisfied with test evidence and explicit human acceptance.

## Scope
Phase 28 introduces explicit, contract-bound inspection tools:
- `inspect_file`
- `inspect_directory`

Scope is strictly read-only observation. No authority expansion is allowed.

## Phase 28 Status
- Level 28 status: frozen baseline
- Frozen tag: `maturity-level-28`
- Previous frozen tag: `maturity-level-27`

## A. Hard Inspection Invariants
- [x] Inspection remains read-only and cannot mutate files, directories, or runtime execution state.
  Evidence target: `v2/core/tools/inspect_file_runner.py`, `tests/test_inspect_file_runner.py`, `tests/test_phase28_inspection_boundaries.py`
- [x] Inspection cannot escalate authority, trigger routing, or invoke additional tools.
  Evidence target: `tests/test_phase28_inspection_boundaries.py`
- [x] Inspection output is returned only to the caller and is not auto-injected into conversational context.
  Evidence target: `tests/test_phase28_inspection_boundaries.py`
- [x] Path trust model is enforced before access (traversal rejection, canonicalization, allowlist containment).
  Evidence target: `v2/core/tools/inspect_file_runner.py`, `tests/test_inspect_file_runner.py`
- [x] Symlinks are not followed; symlink handling remains metadata-only for directory inspection.
  Evidence target: `v2/core/tools/inspect_file_runner.py`, `tests/test_inspect_file_runner.py`

## B. Bounded Read-Only Capability Guarantees
- [x] `inspect_file` enforces bounded excerpt reads and optional bounded hashing with explicit limits.
  Evidence target: `v2/core/tools/inspect_file_runner.py`, `tests/test_inspect_file_runner.py`
- [x] `inspect_directory` enforces bounded pagination, bounded depth, and hidden-entry policy.
  Evidence target: `v2/core/tools/inspect_file_runner.py`, `tests/test_inspect_file_runner.py`
- [x] Contract error model is explicit and deterministic (typed status/error fields, stable error codes).
  Evidence target: `v2/core/tools/inspect_file_runner.py`, `tests/test_inspect_file_runner.py`

## C. Phase 27 Boundary Preservation
- [x] Conversational front-end remains non-authoritative and cannot trigger inspection from normal chat phrasing.
  Evidence target: `tests/test_interaction_dispatcher.py`, `tests/test_phase28_inspection_boundaries.py`
- [x] Policy/approval/execution authority remains exclusively in governed interpreter paths.
  Evidence target: `README.md`, `MATURITY.md`, `STATUS.md`, `STATE.md`, `ONBOARDING.md`
- [x] No tool chaining or implicit follow-on execution is introduced by inspection results.
  Evidence target: `v2/core/tools/inspect_file_runner.py`, `tests/test_phase28_inspection_boundaries.py`

## D. Freeze Hygiene
- [x] `README.md`, `MATURITY.md`, `STATE.md`, `STATUS.md`, and `ONBOARDING.md` are synchronized for Level 28 freeze.
- [x] Phase 28 promotion artifact is present at `docs/PHASE28_PROMOTION_CHECKLIST.md`.
- [x] Focused inspection suites pass in target environment.
- [x] Human promotion acceptance is recorded.
- [x] New frozen tag is created only at promotion time (`maturity-level-28`).

## Evidence Checklist
- Implementation locations:
  - `v2/core/tools/inspect_file_runner.py`
- Tests:
  - `tests/test_inspect_file_runner.py`
  - `tests/test_phase28_inspection_boundaries.py`
  - `tests/test_interaction_dispatcher.py`
- Commands run:
  - `PYTHONDONTWRITEBYTECODE=1 ./v2/.venv/bin/pytest -q tests/test_inspect_file_runner.py`
  - `PYTHONDONTWRITEBYTECODE=1 ./v2/.venv/bin/pytest -q tests/test_phase28_inspection_boundaries.py`
  - `PYTHONDONTWRITEBYTECODE=1 ./v2/.venv/bin/pytest -q tests/test_inspect_file_runner.py tests/test_runtime_snapshot_safety.py tests/test_m216_inspection_triggers_introspection.py`

## Freeze Acceptance Record (Required)
- Approved by: Billy maintainer (explicit session instruction)
- Date: 2026-02-16
- Evidence bundle:
  - `v2/core/tools/inspect_file_runner.py`
  - `tests/test_inspect_file_runner.py`
  - `tests/test_phase28_inspection_boundaries.py`
  - `tests/test_interaction_dispatcher.py`
- Test report:
  - `PYTHONDONTWRITEBYTECODE=1 ./v2/.venv/bin/pytest -q tests/test_inspect_file_runner.py` -> `9 passed`
  - `PYTHONDONTWRITEBYTECODE=1 ./v2/.venv/bin/pytest -q tests/test_phase28_inspection_boundaries.py` -> `4 passed`
  - `PYTHONDONTWRITEBYTECODE=1 ./v2/.venv/bin/pytest -q tests/test_inspect_file_runner.py tests/test_runtime_snapshot_safety.py tests/test_m216_inspection_triggers_introspection.py` -> `11 passed`
- Freeze decision: ACCEPTED. Phase 28 promoted to frozen baseline and scheduled for tag `maturity-level-28`.
