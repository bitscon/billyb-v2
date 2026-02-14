## 1. Purpose
This contract prevents maturity drift across system layers in Billy v2. It is a coordination and enforcement document that ensures behavior, dispatch, execution, and documentation remain aligned to the same declared maturity state.

## 2. Scope
This contract applies to all of the following layers:
- Interaction / Dispatch
- Reasoning (ERM)
- Drafting (CDM, TDM)
- Approval / Application (APP, CAM)
- Tool lifecycle (Tool Approval, TRM, TEM)
- Documentation

## 3. Single Source of Truth Rule
`MATURITY.md` defines implementation maturity levels, current release tag, and freeze status.  
`MATURITY_MODEL.md` defines conceptual maturity levels and crosswalk guidance.  
`STATE.md` and `STATUS.md` declare current-state placement and MUST match `MATURITY.md` for implementation level/tag claims.  
This contract enforces synchronization only and MUST NOT redefine levels or progression semantics.

## 4. Layer Maturity Declaration Requirement
Each covered layer MUST explicitly declare:
- The highest maturity level it supports
- The lowest maturity level it requires from upstream layers

Silence, omission, or implicit assumptions are non-compliance.

## 5. Synchronization Invariant
No layer may operate at, expose behavior for, or claim implementation maturity level `N` unless all upstream layers explicitly support level `N`.

Conceptual maturity claims MUST include an explicit mapping to implementation maturity when both are referenced.

A downstream claim without upstream support is invalid, even if partial behavior appears to function.

## 6. Enforcement Rules
Runtime enforcement:
- If a layer does not support the declared maturity, execution MUST fail fast.
- Unsupported maturity paths MUST hard-stop before side effects.

Interaction enforcement:
- Legacy interaction contracts MUST NOT respond when maturity exceeds their declared support.
- Dispatch MUST reject unsupported maturity transitions explicitly.

Documentation enforcement:
- Documentation artifacts MUST declare the maturity context they apply to (`implementation` or `conceptual`) whenever a level is stated.
- Documentation that lacks or conflicts with declared maturity is non-compliant.

## 7. Maturity Promotion Rule
Advancing declared maturity requires all of the following:
- All covered layers explicitly declare support for the target maturity
- Interaction contract compliance is verified at the target maturity
- Documentation is updated to the target maturity state
- Explicit human acceptance is recorded and the resulting state is frozen

No maturity promotion is valid if any requirement is missing.

## 8. Drift Detection
Maturity drift is defined as any of the following:
- Behavior inconsistent with declared maturity
- Legacy constructs responding past their declared support level
- Layer declarations that conflict with runtime or dispatch behavior

Maturity drift is a correctness bug, not a style issue.

## 9. Authority Statement
This contract is mandatory for all maturity-related changes and claims in this repository.  
Any violation invalidates the associated maturity claim until corrected and re-accepted.
