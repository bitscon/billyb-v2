# Full Ladder Audit Report

Deterministic audit output for maturity protocol promotion checklists.

- Docs directory: `docs`
- Phase range scanned: `27` to `67`
- Phase files scanned: `41`
- Input digest (sha256): `cb890740af228ee5916c8de0a8450cc152a04a883f0499c8597bc14e7964919e`
- PASS phases: `4`
- FAIL phases: `37`

## Phase Index

| Phase | Level Name | Contract(s) | Status |
|---:|---|---|---|
| 27 | Conversational Front-End & Interpreter Gate | NOT_FOUND | **FAIL** |
| 28 | Explicit Read-Only Inspection Capabilities | NOT_FOUND | **FAIL** |
| 29 | Inspection Dispatch Boundary | inspection_result_binding.v1 | **FAIL** |
| 30 | Delegation Envelope | delegation_envelope.v1 | **FAIL** |
| 31 | Orchestrator Synthesis Loop | synthesis_output.v1 | **FAIL** |
| 32 | Approval-Gated Action Planning | action_plan_envelope.v1 | **FAIL** |
| 33 | Explicit Human Approval Contract | human_approval.v1 | **FAIL** |
| 34 | Approval Verification & Audit Ledger | approval_audit_record.v1 | **FAIL** |
| 35 | Revocation & Supersession Governance | revocation_record.v1 | **FAIL** |
| 36 | Version Lineage & Dependency Integrity | lineage_record.v1 | **FAIL** |
| 37 | Execution Eligibility Gate | execution_eligibility_record.v1 | **FAIL** |
| 38 | Execution Readiness Envelope | execution_readiness_envelope.v1 | **FAIL** |
| 39 | Execution Authorization Boundary | execution_authorization_record.v1 | **FAIL** |
| 40 | Execution Commitment Envelope | execution_commitment_envelope.v1 | **FAIL** |
| 41 | Execution Invocation Boundary | execution_invocation_envelope.v1 | **FAIL** |
| 42 | Execution Runtime Interface Contract | execution_runtime_interface.v1 | **FAIL** |
| 43 | Execution Enablement Switch | execution_enablement_switch.v1 | **FAIL** |
| 44 | Execution Capability Contract | execution_capability.v1 | **FAIL** |
| 45 | Execution Decision Gate | execution_decision.v1 | **FAIL** |
| 46 | Execution Intent Seal | execution_intent_seal.v1 | **PASS** |
| 47 | Pre-Execution Validation Gate | pre_execution_validation.v1 | **FAIL** |
| 48 | Execution Arming Boundary | execution_arming.v1 | **FAIL** |
| 49 | Execution Attempt Boundary | execution_attempt.v1 | **FAIL** |
| 50 | External Executor Interface Contract | executor_interface.v1 | **FAIL** |
| 51 | External Executor Trust Contract | external_executor_trust.v1 | **FAIL** |
| 52 | Executor Result Reporting Contract | executor_result.v1 | **FAIL** |
| 53 | Human Review & Post-Execution Interpretation Gate | human_execution_review.v1 | **FAIL** |
| 54 | Human-Initiated Re-Planning Gate | human_replanning_intent.v1 | **FAIL** |
| 55 | Governed Planning Context Assembly | planning_context.v1 | **FAIL** |
| 56 | Planning Output Envelope | planning_output.v1 | **FAIL** |
| 57 | Planning Session Boundary & Closure | planning_session.v1 | **FAIL** |
| 58 | Human Plan Acceptance Gate | plan_acceptance.v1 | **FAIL** |
| 59 | Human Plan Approval Gate | plan_approval.v1 | **FAIL** |
| 60 | Plan Authorization Gate | plan_authorization.v1 | **FAIL** |
| 61 | Execution Scope Binding Gate | execution_scope_binding.v1 | **FAIL** |
| 62 | Execution Preconditions Declaration Gate | execution_preconditions.v1 | **FAIL** |
| 63 | Readiness Evaluation Gate | execution_readiness.v1 | **PASS** |
| 64 | Readiness Attestation Gate | readiness_attestation.v1 | **PASS** |
| 65 | Execution Arming Authorization Gate | execution_arming_authorization.v1 | **FAIL** |
| 66 | Execution Arming State Machine | execution_arming_state.v1 | **FAIL** |
| 67 | Execution Eligibility Gate | execution_eligibility.v1 | **PASS** |

## Per-Phase Results

### Phase 27 — Conversational Front-End & Interpreter Gate (FAIL)

- File: `docs/PHASE27_PROMOTION_CHECKLIST.md`
- Contracts: `NOT_FOUND`
- Upstream phase refs (declared): 27
- Linked IDs detected: NOT_FOUND
- Uniqueness signals: NOT_FOUND
- Rejection codes in section: NOT_FOUND
- Priority ordering required: no
- Findings:
  - [FAIL] `authority_guarantees_all_false`: NOT_FOUND: contract yaml block missing [docs/PHASE27_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [FAIL] `contract_found`: NOT_FOUND: contract name not found [docs/PHASE27_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [FAIL] `execution_enabled_false`: NOT_FOUND: contract yaml block missing [docs/PHASE27_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [FAIL] `hard_invariants_present`: NOT_FOUND: hard invariants checklist signals missing [docs/PHASE27_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [FAIL] `immutability_flags`: NOT_FOUND: contract yaml block missing [docs/PHASE27_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [PASS] `level_name_found`: PASS [docs/PHASE27_PROMOTION_CHECKLIST.md:8 ("## Phase 27 Status")]
  - [FAIL] `negative_guarantees_present`: NOT_FOUND: deterministic negative guarantees missing [docs/PHASE27_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [FAIL] `rejection_codes_present`: NOT_FOUND: rejection code list section missing or empty [docs/PHASE27_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [PASS] `runtime_delta_none`: PASS [docs/PHASE27_PROMOTION_CHECKLIST.md:8 ("## Phase 27 Status")]

### Phase 28 — Explicit Read-Only Inspection Capabilities (FAIL)

- File: `docs/PHASE28_PROMOTION_CHECKLIST.md`
- Contracts: `NOT_FOUND`
- Upstream phase refs (declared): 27, 28
- Linked IDs detected: NOT_FOUND
- Uniqueness signals: NOT_FOUND
- Rejection codes in section: NOT_FOUND
- Priority ordering required: no
- Findings:
  - [FAIL] `authority_guarantees_all_false`: NOT_FOUND: contract yaml block missing [docs/PHASE28_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [FAIL] `contract_found`: NOT_FOUND: contract name not found [docs/PHASE28_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [FAIL] `execution_enabled_false`: NOT_FOUND: contract yaml block missing [docs/PHASE28_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [FAIL] `hard_invariants_present`: NOT_FOUND: hard invariants checklist signals missing [docs/PHASE28_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [FAIL] `immutability_flags`: NOT_FOUND: contract yaml block missing [docs/PHASE28_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [PASS] `level_name_found`: PASS [docs/PHASE28_PROMOTION_CHECKLIST.md:15 ("## Phase 28 Status")]
  - [FAIL] `negative_guarantees_present`: NOT_FOUND: deterministic negative guarantees missing [docs/PHASE28_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [FAIL] `rejection_codes_present`: NOT_FOUND: rejection code list section missing or empty [docs/PHASE28_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [PASS] `runtime_delta_none`: PASS [docs/PHASE28_PROMOTION_CHECKLIST.md:15 ("## Phase 28 Status")]

### Phase 29 — Inspection Dispatch Boundary (FAIL)

- File: `docs/PHASE29_PROMOTION_CHECKLIST.md`
- Contracts: `inspection_result_binding.v1`
- Upstream phase refs (declared): 27, 28, 29
- Linked IDs detected: NOT_FOUND
- Uniqueness signals: NOT_FOUND
- Rejection codes in section: NOT_FOUND
- Priority ordering required: no
- Findings:
  - [FAIL] `authority_guarantees_all_false`: NOT_FOUND: authority_guarantees block missing [docs/PHASE29_PROMOTION_CHECKLIST.md:46 ("## Inspection Result Binding Contract v1")]
  - [PASS] `contract_found`: PASS [docs/PHASE29_PROMOTION_CHECKLIST.md:46 ("## Inspection Result Binding Contract v1")]
  - [FAIL] `execution_enabled_false`: NOT_FOUND/INVALID: execution_enabled const false not found (value=None) [docs/PHASE29_PROMOTION_CHECKLIST.md:46 ("## Inspection Result Binding Contract v1")]
  - [FAIL] `expiry_semantics`: NOT_FOUND: expiry/time-window checks incomplete [docs/PHASE29_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [FAIL] `hard_invariants_present`: NOT_FOUND: hard invariants checklist signals missing [docs/PHASE29_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [FAIL] `immutability_flags`: NOT_FOUND: immutability_guarantees block missing [docs/PHASE29_PROMOTION_CHECKLIST.md:46 ("## Inspection Result Binding Contract v1")]
  - [PASS] `level_name_found`: PASS [docs/PHASE29_PROMOTION_CHECKLIST.md:13 ("## Phase 29 Status")]
  - [FAIL] `negative_guarantees_present`: NOT_FOUND: deterministic negative guarantees missing [docs/PHASE29_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [FAIL] `rejection_codes_present`: NOT_FOUND: rejection code list section missing or empty [docs/PHASE29_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [PASS] `runtime_delta_none`: PASS [docs/PHASE29_PROMOTION_CHECKLIST.md:13 ("## Phase 29 Status")]

### Phase 30 — Delegation Envelope (FAIL)

- File: `docs/PHASE30_PROMOTION_CHECKLIST.md`
- Contracts: `delegation_envelope.v1`
- Upstream phase refs (declared): 27, 28, 29, 30
- Linked IDs detected: NOT_FOUND
- Uniqueness signals: NOT_FOUND
- Rejection codes in section: NOT_FOUND
- Priority ordering required: no
- Findings:
  - [FAIL] `authority_guarantees_all_false`: NOT_FOUND: authority_guarantees block missing [docs/PHASE30_PROMOTION_CHECKLIST.md:73 ("## Delegation Envelope Contract v1 (Revised)")]
  - [PASS] `contract_found`: PASS [docs/PHASE30_PROMOTION_CHECKLIST.md:73 ("## Delegation Envelope Contract v1 (Revised)")]
  - [FAIL] `execution_enabled_false`: NOT_FOUND/INVALID: execution_enabled const false not found (value=None) [docs/PHASE30_PROMOTION_CHECKLIST.md:73 ("## Delegation Envelope Contract v1 (Revised)")]
  - [FAIL] `hard_invariants_present`: NOT_FOUND: hard invariants checklist signals missing [docs/PHASE30_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [FAIL] `immutability_flags`: NOT_FOUND: immutability_guarantees block missing [docs/PHASE30_PROMOTION_CHECKLIST.md:73 ("## Delegation Envelope Contract v1 (Revised)")]
  - [PASS] `level_name_found`: PASS [docs/PHASE30_PROMOTION_CHECKLIST.md:13 ("## Phase 30 Status")]
  - [FAIL] `negative_guarantees_present`: NOT_FOUND: deterministic negative guarantees missing [docs/PHASE30_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [FAIL] `rejection_codes_present`: NOT_FOUND: rejection code list section missing or empty [docs/PHASE30_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [FAIL] `runtime_delta_none`: INVALID: runtime delta is not none (none (specification-only)) [docs/PHASE30_PROMOTION_CHECKLIST.md:13 ("## Phase 30 Status")]

### Phase 31 — Orchestrator Synthesis Loop (FAIL)

- File: `docs/PHASE31_PROMOTION_CHECKLIST.md`
- Contracts: `synthesis_output.v1`
- Upstream phase refs (declared): 27, 28, 29, 30, 31
- Linked IDs detected: NOT_FOUND
- Uniqueness signals: NOT_FOUND
- Rejection codes in section: NOT_FOUND
- Priority ordering required: no
- Findings:
  - [PASS] `authority_guarantees_all_false`: PASS [docs/PHASE31_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [PASS] `contract_found`: PASS [docs/PHASE31_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [FAIL] `execution_enabled_false`: NOT_FOUND/INVALID: execution_enabled const false not found (value=None) [docs/PHASE31_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [FAIL] `hard_invariants_present`: NOT_FOUND: hard invariants checklist signals missing [docs/PHASE31_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [FAIL] `immutability_flags`: NOT_FOUND: immutability_guarantees block missing [docs/PHASE31_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [PASS] `level_name_found`: PASS [docs/PHASE31_PROMOTION_CHECKLIST.md:13 ("## Phase 31 Status")]
  - [PASS] `negative_guarantees_present`: PASS [docs/PHASE31_PROMOTION_CHECKLIST.md:264 ("## Deterministic Negative Guarantees")]
  - [FAIL] `rejection_codes_present`: NOT_FOUND: rejection code list section missing or empty [docs/PHASE31_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [FAIL] `runtime_delta_none`: INVALID: runtime delta is not none (none (specification-only)) [docs/PHASE31_PROMOTION_CHECKLIST.md:13 ("## Phase 31 Status")]

### Phase 32 — Approval-Gated Action Planning (FAIL)

- File: `docs/PHASE32_PROMOTION_CHECKLIST.md`
- Contracts: `action_plan_envelope.v1`
- Upstream phase refs (declared): 27, 28, 29, 30, 31, 32
- Linked IDs detected: NOT_FOUND
- Uniqueness signals: NOT_FOUND
- Rejection codes in section: NOT_FOUND
- Priority ordering required: no
- Findings:
  - [PASS] `authority_guarantees_all_false`: PASS [docs/PHASE32_PROMOTION_CHECKLIST.md:71 ("## Action Plan Envelope Contract v1")]
  - [PASS] `contract_found`: PASS [docs/PHASE32_PROMOTION_CHECKLIST.md:71 ("## Action Plan Envelope Contract v1")]
  - [FAIL] `execution_enabled_false`: NOT_FOUND/INVALID: execution_enabled const false not found (value=None) [docs/PHASE32_PROMOTION_CHECKLIST.md:71 ("## Action Plan Envelope Contract v1")]
  - [PASS] `hard_invariants_present`: PASS [docs/PHASE32_PROMOTION_CHECKLIST.md:33 ("## A. Hard Invariants")]
  - [FAIL] `immutability_flags`: NOT_FOUND: immutability_guarantees block missing [docs/PHASE32_PROMOTION_CHECKLIST.md:71 ("## Action Plan Envelope Contract v1")]
  - [PASS] `level_name_found`: PASS [docs/PHASE32_PROMOTION_CHECKLIST.md:27 ("## Phase 32 Status")]
  - [PASS] `negative_guarantees_present`: PASS [docs/PHASE32_PROMOTION_CHECKLIST.md:275 ("## Deterministic Negative Guarantees")]
  - [FAIL] `rejection_codes_present`: NOT_FOUND: rejection code list section missing or empty [docs/PHASE32_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [PASS] `runtime_delta_none`: PASS [docs/PHASE32_PROMOTION_CHECKLIST.md:27 ("## Phase 32 Status")]

### Phase 33 — Explicit Human Approval Contract (FAIL)

- File: `docs/PHASE33_PROMOTION_CHECKLIST.md`
- Contracts: `human_approval.v1`
- Upstream phase refs (declared): 27, 28, 29, 30, 31, 32, 33
- Linked IDs detected: `linked_plan_id`
- Uniqueness signals: NOT_FOUND
- Rejection codes in section: NOT_FOUND
- Priority ordering required: no
- Findings:
  - [PASS] `authority_guarantees_all_false`: PASS [docs/PHASE33_PROMOTION_CHECKLIST.md:93 ("## Human Approval Contract v1")]
  - [PASS] `contract_found`: PASS [docs/PHASE33_PROMOTION_CHECKLIST.md:93 ("## Human Approval Contract v1")]
  - [FAIL] `execution_enabled_false`: NOT_FOUND/INVALID: execution_enabled const false not found (value=None) [docs/PHASE33_PROMOTION_CHECKLIST.md:93 ("## Human Approval Contract v1")]
  - [FAIL] `expiry_semantics`: NOT_FOUND: expiry/time-window checks incomplete [docs/PHASE33_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [PASS] `future_linkage_drift`: PASS [docs/PHASE33_PROMOTION_CHECKLIST.md:93 ("## Human Approval Contract v1")]
  - [FAIL] `hard_invariants_present`: NOT_FOUND: hard invariants checklist signals missing [docs/PHASE33_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [FAIL] `immutability_flags`: NOT_FOUND: immutability_guarantees block missing [docs/PHASE33_PROMOTION_CHECKLIST.md:93 ("## Human Approval Contract v1")]
  - [PASS] `level_name_found`: PASS [docs/PHASE33_PROMOTION_CHECKLIST.md:28 ("## Phase 33 Status")]
  - [PASS] `negative_guarantees_present`: PASS [docs/PHASE33_PROMOTION_CHECKLIST.md:234 ("## Deterministic Negative Guarantees")]
  - [FAIL] `rejection_codes_present`: NOT_FOUND: rejection code list section missing or empty [docs/PHASE33_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [PASS] `runtime_delta_none`: PASS [docs/PHASE33_PROMOTION_CHECKLIST.md:28 ("## Phase 33 Status")]

### Phase 34 — Approval Verification & Audit Ledger (FAIL)

- File: `docs/PHASE34_PROMOTION_CHECKLIST.md`
- Contracts: `approval_audit_record.v1`
- Upstream phase refs (declared): 27, 28, 29, 30, 31, 32, 33, 34
- Linked IDs detected: `linked_plan_id`
- Uniqueness signals: NOT_FOUND
- Rejection codes in section: NOT_FOUND
- Priority ordering required: no
- Findings:
  - [PASS] `authority_guarantees_all_false`: PASS [docs/PHASE34_PROMOTION_CHECKLIST.md:91 ("## Approval Audit Record Contract v1")]
  - [PASS] `contract_found`: PASS [docs/PHASE34_PROMOTION_CHECKLIST.md:91 ("## Approval Audit Record Contract v1")]
  - [FAIL] `execution_enabled_false`: NOT_FOUND/INVALID: execution_enabled const false not found (value=None) [docs/PHASE34_PROMOTION_CHECKLIST.md:91 ("## Approval Audit Record Contract v1")]
  - [PASS] `future_linkage_drift`: PASS [docs/PHASE34_PROMOTION_CHECKLIST.md:91 ("## Approval Audit Record Contract v1")]
  - [FAIL] `hard_invariants_present`: NOT_FOUND: hard invariants checklist signals missing [docs/PHASE34_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [PASS] `immutability_flags`: PASS [docs/PHASE34_PROMOTION_CHECKLIST.md:91 ("## Approval Audit Record Contract v1")]
  - [PASS] `level_name_found`: PASS [docs/PHASE34_PROMOTION_CHECKLIST.md:28 ("## Phase 34 Status")]
  - [PASS] `negative_guarantees_present`: PASS [docs/PHASE34_PROMOTION_CHECKLIST.md:243 ("## Deterministic Negative Guarantees")]
  - [FAIL] `rejection_codes_present`: NOT_FOUND: rejection code list section missing or empty [docs/PHASE34_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [PASS] `runtime_delta_none`: PASS [docs/PHASE34_PROMOTION_CHECKLIST.md:28 ("## Phase 34 Status")]

### Phase 35 — Revocation & Supersession Governance (FAIL)

- File: `docs/PHASE35_PROMOTION_CHECKLIST.md`
- Contracts: `revocation_record.v1`
- Upstream phase refs (declared): 27, 28, 29, 30, 31, 32, 33, 34, 35
- Linked IDs detected: NOT_FOUND
- Uniqueness signals: NOT_FOUND
- Rejection codes in section: NOT_FOUND
- Priority ordering required: no
- Findings:
  - [PASS] `authority_guarantees_all_false`: PASS [docs/PHASE35_PROMOTION_CHECKLIST.md:112 ("## Revocation Record Contract v1")]
  - [PASS] `contract_found`: PASS [docs/PHASE35_PROMOTION_CHECKLIST.md:112 ("## Revocation Record Contract v1")]
  - [FAIL] `execution_enabled_false`: NOT_FOUND/INVALID: execution_enabled const false not found (value=None) [docs/PHASE35_PROMOTION_CHECKLIST.md:112 ("## Revocation Record Contract v1")]
  - [FAIL] `hard_invariants_present`: NOT_FOUND: hard invariants checklist signals missing [docs/PHASE35_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [PASS] `immutability_flags`: PASS [docs/PHASE35_PROMOTION_CHECKLIST.md:112 ("## Revocation Record Contract v1")]
  - [PASS] `level_name_found`: PASS [docs/PHASE35_PROMOTION_CHECKLIST.md:28 ("## Phase 35 Status")]
  - [PASS] `negative_guarantees_present`: PASS [docs/PHASE35_PROMOTION_CHECKLIST.md:274 ("## Deterministic Negative Guarantees")]
  - [FAIL] `rejection_codes_present`: NOT_FOUND: rejection code list section missing or empty [docs/PHASE35_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [PASS] `runtime_delta_none`: PASS [docs/PHASE35_PROMOTION_CHECKLIST.md:28 ("## Phase 35 Status")]

### Phase 36 — Version Lineage & Dependency Integrity (FAIL)

- File: `docs/PHASE36_PROMOTION_CHECKLIST.md`
- Contracts: `lineage_record.v1`
- Upstream phase refs (declared): 27, 28, 29, 30, 31, 32, 33, 34, 35, 36
- Linked IDs detected: NOT_FOUND
- Uniqueness signals: NOT_FOUND
- Rejection codes in section: NOT_FOUND
- Priority ordering required: no
- Findings:
  - [PASS] `authority_guarantees_all_false`: PASS [docs/PHASE36_PROMOTION_CHECKLIST.md:111 ("## Lineage Record Contract v1")]
  - [PASS] `contract_found`: PASS [docs/PHASE36_PROMOTION_CHECKLIST.md:111 ("## Lineage Record Contract v1")]
  - [FAIL] `execution_enabled_false`: NOT_FOUND/INVALID: execution_enabled const false not found (value=None) [docs/PHASE36_PROMOTION_CHECKLIST.md:111 ("## Lineage Record Contract v1")]
  - [FAIL] `hard_invariants_present`: NOT_FOUND: hard invariants checklist signals missing [docs/PHASE36_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [PASS] `immutability_flags`: PASS [docs/PHASE36_PROMOTION_CHECKLIST.md:111 ("## Lineage Record Contract v1")]
  - [PASS] `level_name_found`: PASS [docs/PHASE36_PROMOTION_CHECKLIST.md:29 ("## Phase 36 Status")]
  - [PASS] `negative_guarantees_present`: PASS [docs/PHASE36_PROMOTION_CHECKLIST.md:260 ("## Deterministic Negative Guarantees")]
  - [FAIL] `rejection_codes_present`: NOT_FOUND: rejection code list section missing or empty [docs/PHASE36_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [PASS] `runtime_delta_none`: PASS [docs/PHASE36_PROMOTION_CHECKLIST.md:29 ("## Phase 36 Status")]

### Phase 37 — Execution Eligibility Gate (FAIL)

- File: `docs/PHASE37_PROMOTION_CHECKLIST.md`
- Contracts: `execution_eligibility_record.v1`
- Upstream phase refs (declared): 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37
- Linked IDs detected: NOT_FOUND
- Uniqueness signals: NOT_FOUND
- Rejection codes in section: NOT_FOUND
- Priority ordering required: no
- Findings:
  - [PASS] `authority_guarantees_all_false`: PASS [docs/PHASE37_PROMOTION_CHECKLIST.md:122 ("## Execution Eligibility Record Contract v1")]
  - [PASS] `contract_found`: PASS [docs/PHASE37_PROMOTION_CHECKLIST.md:122 ("## Execution Eligibility Record Contract v1")]
  - [FAIL] `execution_enabled_false`: NOT_FOUND/INVALID: execution_enabled const false not found (value=None) [docs/PHASE37_PROMOTION_CHECKLIST.md:122 ("## Execution Eligibility Record Contract v1")]
  - [FAIL] `hard_invariants_present`: NOT_FOUND: hard invariants checklist signals missing [docs/PHASE37_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [FAIL] `immutability_flags`: NOT_FOUND: immutability_guarantees block missing [docs/PHASE37_PROMOTION_CHECKLIST.md:122 ("## Execution Eligibility Record Contract v1")]
  - [PASS] `level_name_found`: PASS [docs/PHASE37_PROMOTION_CHECKLIST.md:29 ("## Phase 37 Status")]
  - [PASS] `negative_guarantees_present`: PASS [docs/PHASE37_PROMOTION_CHECKLIST.md:313 ("## Deterministic Negative Guarantees")]
  - [FAIL] `rejection_codes_present`: NOT_FOUND: rejection code list section missing or empty [docs/PHASE37_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [PASS] `runtime_delta_none`: PASS [docs/PHASE37_PROMOTION_CHECKLIST.md:29 ("## Phase 37 Status")]

### Phase 38 — Execution Readiness Envelope (FAIL)

- File: `docs/PHASE38_PROMOTION_CHECKLIST.md`
- Contracts: `execution_readiness_envelope.v1`
- Upstream phase refs (declared): 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38
- Linked IDs detected: NOT_FOUND
- Uniqueness signals: NOT_FOUND
- Rejection codes in section: NOT_FOUND
- Priority ordering required: no
- Findings:
  - [PASS] `authority_guarantees_all_false`: PASS [docs/PHASE38_PROMOTION_CHECKLIST.md:136 ("## Execution Readiness Envelope Contract v1")]
  - [PASS] `contract_found`: PASS [docs/PHASE38_PROMOTION_CHECKLIST.md:136 ("## Execution Readiness Envelope Contract v1")]
  - [PASS] `execution_enabled_false`: PASS [docs/PHASE38_PROMOTION_CHECKLIST.md:136 ("## Execution Readiness Envelope Contract v1")]
  - [FAIL] `hard_invariants_present`: NOT_FOUND: hard invariants checklist signals missing [docs/PHASE38_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [FAIL] `immutability_flags`: NOT_FOUND: append_only [docs/PHASE38_PROMOTION_CHECKLIST.md:136 ("## Execution Readiness Envelope Contract v1")]
  - [PASS] `level_name_found`: PASS [docs/PHASE38_PROMOTION_CHECKLIST.md:29 ("## Phase 38 Status")]
  - [PASS] `negative_guarantees_present`: PASS [docs/PHASE38_PROMOTION_CHECKLIST.md:381 ("## Deterministic Negative Guarantees")]
  - [FAIL] `rejection_codes_present`: NOT_FOUND: rejection code list section missing or empty [docs/PHASE38_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [PASS] `runtime_delta_none`: PASS [docs/PHASE38_PROMOTION_CHECKLIST.md:29 ("## Phase 38 Status")]

### Phase 39 — Execution Authorization Boundary (FAIL)

- File: `docs/PHASE39_PROMOTION_CHECKLIST.md`
- Contracts: `execution_authorization_record.v1`
- Upstream phase refs (declared): 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39
- Linked IDs detected: NOT_FOUND
- Uniqueness signals: NOT_FOUND
- Rejection codes in section: NOT_FOUND
- Priority ordering required: no
- Findings:
  - [PASS] `authority_guarantees_all_false`: PASS [docs/PHASE39_PROMOTION_CHECKLIST.md:134 ("## Execution Authorization Record Contract v1")]
  - [PASS] `contract_found`: PASS [docs/PHASE39_PROMOTION_CHECKLIST.md:134 ("## Execution Authorization Record Contract v1")]
  - [PASS] `execution_enabled_false`: PASS [docs/PHASE39_PROMOTION_CHECKLIST.md:134 ("## Execution Authorization Record Contract v1")]
  - [FAIL] `expiry_semantics`: NOT_FOUND: expiry/time-window checks incomplete [docs/PHASE39_PROMOTION_CHECKLIST.md:60 ("## D. Deterministic Authorization Validation Order")]
  - [FAIL] `hard_invariants_present`: NOT_FOUND: hard invariants checklist signals missing [docs/PHASE39_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [FAIL] `immutability_flags`: NOT_FOUND: append_only [docs/PHASE39_PROMOTION_CHECKLIST.md:134 ("## Execution Authorization Record Contract v1")]
  - [PASS] `level_name_found`: PASS [docs/PHASE39_PROMOTION_CHECKLIST.md:29 ("## Phase 39 Status")]
  - [PASS] `negative_guarantees_present`: PASS [docs/PHASE39_PROMOTION_CHECKLIST.md:315 ("## Deterministic Negative Guarantees")]
  - [FAIL] `rejection_codes_present`: NOT_FOUND: rejection code list section missing or empty [docs/PHASE39_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [PASS] `runtime_delta_none`: PASS [docs/PHASE39_PROMOTION_CHECKLIST.md:29 ("## Phase 39 Status")]

### Phase 40 — Execution Commitment Envelope (FAIL)

- File: `docs/PHASE40_PROMOTION_CHECKLIST.md`
- Contracts: `execution_commitment_envelope.v1`
- Upstream phase refs (declared): 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40
- Linked IDs detected: NOT_FOUND
- Uniqueness signals: 2
- Rejection codes in section: NOT_FOUND
- Priority ordering required: no
- Findings:
  - [PASS] `authority_guarantees_all_false`: PASS [docs/PHASE40_PROMOTION_CHECKLIST.md:134 ("## Execution Commitment Envelope Contract v1")]
  - [PASS] `contract_found`: PASS [docs/PHASE40_PROMOTION_CHECKLIST.md:134 ("## Execution Commitment Envelope Contract v1")]
  - [PASS] `execution_enabled_false`: PASS [docs/PHASE40_PROMOTION_CHECKLIST.md:134 ("## Execution Commitment Envelope Contract v1")]
  - [FAIL] `expiry_semantics`: NOT_FOUND: expiry/time-window checks incomplete [docs/PHASE40_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [FAIL] `hard_invariants_present`: NOT_FOUND: hard invariants checklist signals missing [docs/PHASE40_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [FAIL] `immutability_flags`: NOT_FOUND: append_only [docs/PHASE40_PROMOTION_CHECKLIST.md:134 ("## Execution Commitment Envelope Contract v1")]
  - [PASS] `level_name_found`: PASS [docs/PHASE40_PROMOTION_CHECKLIST.md:29 ("## Phase 40 Status")]
  - [PASS] `negative_guarantees_present`: PASS [docs/PHASE40_PROMOTION_CHECKLIST.md:334 ("## Deterministic Negative Guarantees")]
  - [FAIL] `rejection_codes_present`: NOT_FOUND: rejection code list section missing or empty [docs/PHASE40_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [PASS] `runtime_delta_none`: PASS [docs/PHASE40_PROMOTION_CHECKLIST.md:29 ("## Phase 40 Status")]

### Phase 41 — Execution Invocation Boundary (FAIL)

- File: `docs/PHASE41_PROMOTION_CHECKLIST.md`
- Contracts: `execution_invocation_envelope.v1`
- Upstream phase refs (declared): 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41
- Linked IDs detected: NOT_FOUND
- Uniqueness signals: 3
- Rejection codes in section: NOT_FOUND
- Priority ordering required: no
- Findings:
  - [PASS] `authority_guarantees_all_false`: PASS [docs/PHASE41_PROMOTION_CHECKLIST.md:134 ("## Execution Invocation Envelope Contract v1")]
  - [PASS] `contract_found`: PASS [docs/PHASE41_PROMOTION_CHECKLIST.md:134 ("## Execution Invocation Envelope Contract v1")]
  - [PASS] `execution_enabled_false`: PASS [docs/PHASE41_PROMOTION_CHECKLIST.md:134 ("## Execution Invocation Envelope Contract v1")]
  - [FAIL] `expiry_semantics`: NOT_FOUND: expiry/time-window checks incomplete [docs/PHASE41_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [FAIL] `hard_invariants_present`: NOT_FOUND: hard invariants checklist signals missing [docs/PHASE41_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [FAIL] `immutability_flags`: NOT_FOUND: append_only [docs/PHASE41_PROMOTION_CHECKLIST.md:134 ("## Execution Invocation Envelope Contract v1")]
  - [PASS] `level_name_found`: PASS [docs/PHASE41_PROMOTION_CHECKLIST.md:29 ("## Phase 41 Status")]
  - [PASS] `negative_guarantees_present`: PASS [docs/PHASE41_PROMOTION_CHECKLIST.md:344 ("## Deterministic Negative Guarantees")]
  - [FAIL] `rejection_codes_present`: NOT_FOUND: rejection code list section missing or empty [docs/PHASE41_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [PASS] `runtime_delta_none`: PASS [docs/PHASE41_PROMOTION_CHECKLIST.md:29 ("## Phase 41 Status")]

### Phase 42 — Execution Runtime Interface Contract (FAIL)

- File: `docs/PHASE42_PROMOTION_CHECKLIST.md`
- Contracts: `execution_runtime_interface.v1`
- Upstream phase refs (declared): NOT_FOUND
- Linked IDs detected: NOT_FOUND
- Uniqueness signals: 2
- Rejection codes in section: NOT_FOUND
- Priority ordering required: no
- Findings:
  - [PASS] `authority_guarantees_all_false`: PASS [docs/PHASE42_PROMOTION_CHECKLIST.md:154 ("## Execution Runtime Interface Contract v1")]
  - [PASS] `contract_found`: PASS [docs/PHASE42_PROMOTION_CHECKLIST.md:154 ("## Execution Runtime Interface Contract v1")]
  - [PASS] `execution_enabled_false`: PASS [docs/PHASE42_PROMOTION_CHECKLIST.md:154 ("## Execution Runtime Interface Contract v1")]
  - [FAIL] `expiry_semantics`: NOT_FOUND: expiry/time-window checks incomplete [docs/PHASE42_PROMOTION_CHECKLIST.md:66 ("## E. Deterministic Payload Validation Order")]
  - [FAIL] `hard_invariants_present`: NOT_FOUND: hard invariants checklist signals missing [docs/PHASE42_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [FAIL] `immutability_flags`: NOT_FOUND: append_only [docs/PHASE42_PROMOTION_CHECKLIST.md:154 ("## Execution Runtime Interface Contract v1")]
  - [PASS] `level_name_found`: PASS [docs/PHASE42_PROMOTION_CHECKLIST.md:28 ("## Phase 42 Status")]
  - [PASS] `negative_guarantees_present`: PASS [docs/PHASE42_PROMOTION_CHECKLIST.md:362 ("## Deterministic Negative Guarantees")]
  - [FAIL] `rejection_codes_present`: NOT_FOUND: rejection code list section missing or empty [docs/PHASE42_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [PASS] `runtime_delta_none`: PASS [docs/PHASE42_PROMOTION_CHECKLIST.md:28 ("## Phase 42 Status")]

### Phase 43 — Execution Enablement Switch (FAIL)

- File: `docs/PHASE43_PROMOTION_CHECKLIST.md`
- Contracts: `execution_enablement_switch.v1`
- Upstream phase refs (declared): 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43
- Linked IDs detected: NOT_FOUND
- Uniqueness signals: 3
- Rejection codes in section: NOT_FOUND
- Priority ordering required: no
- Findings:
  - [PASS] `authority_guarantees_all_false`: PASS [docs/PHASE43_PROMOTION_CHECKLIST.md:119 ("## Execution Enablement Switch Contract v1")]
  - [PASS] `contract_found`: PASS [docs/PHASE43_PROMOTION_CHECKLIST.md:119 ("## Execution Enablement Switch Contract v1")]
  - [PASS] `execution_enabled_false`: PASS [docs/PHASE43_PROMOTION_CHECKLIST.md:119 ("## Execution Enablement Switch Contract v1")]
  - [FAIL] `expiry_semantics`: NOT_FOUND: expiry/time-window checks incomplete [docs/PHASE43_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [PASS] `hard_invariants_present`: PASS [docs/PHASE43_PROMOTION_CHECKLIST.md:34 ("## A. Hard Invariants")]
  - [PASS] `immutability_flags`: PASS [docs/PHASE43_PROMOTION_CHECKLIST.md:119 ("## Execution Enablement Switch Contract v1")]
  - [PASS] `level_name_found`: PASS [docs/PHASE43_PROMOTION_CHECKLIST.md:28 ("## Phase 43 Status")]
  - [PASS] `negative_guarantees_present`: PASS [docs/PHASE43_PROMOTION_CHECKLIST.md:275 ("## Deterministic Negative Guarantees")]
  - [FAIL] `rejection_codes_present`: NOT_FOUND: rejection code list section missing or empty [docs/PHASE43_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [PASS] `runtime_delta_none`: PASS [docs/PHASE43_PROMOTION_CHECKLIST.md:28 ("## Phase 43 Status")]

### Phase 44 — Execution Capability Contract (FAIL)

- File: `docs/PHASE44_PROMOTION_CHECKLIST.md`
- Contracts: `execution_capability.v1`
- Upstream phase refs (declared): 39, 40, 41, 42, 43
- Linked IDs detected: `linked_enablement_id`, `linked_execution_authorization_id`, `linked_execution_commitment_id`, `linked_execution_invocation_id`, `linked_runtime_interface_id`
- Uniqueness signals: 1
- Rejection codes in section: 13
- Priority ordering required: no
- Findings:
  - [PASS] `authority_guarantees_all_false`: PASS [docs/PHASE44_PROMOTION_CHECKLIST.md:119 ("## Execution Capability Contract v1")]
  - [PASS] `contract_found`: PASS [docs/PHASE44_PROMOTION_CHECKLIST.md:119 ("## Execution Capability Contract v1")]
  - [PASS] `execution_enabled_false`: PASS [docs/PHASE44_PROMOTION_CHECKLIST.md:119 ("## Execution Capability Contract v1")]
  - [FAIL] `expiry_semantics`: NOT_FOUND: expiry/time-window checks incomplete [docs/PHASE44_PROMOTION_CHECKLIST.md:52 ("## C. Deterministic Validation Order")]
  - [PASS] `future_linkage_drift`: PASS [docs/PHASE44_PROMOTION_CHECKLIST.md:119 ("## Execution Capability Contract v1")]
  - [PASS] `hard_invariants_present`: PASS [docs/PHASE44_PROMOTION_CHECKLIST.md:34 ("## A. Hard Invariants")]
  - [PASS] `immutability_flags`: PASS [docs/PHASE44_PROMOTION_CHECKLIST.md:119 ("## Execution Capability Contract v1")]
  - [PASS] `level_name_found`: PASS [docs/PHASE44_PROMOTION_CHECKLIST.md:28 ("## Phase 44 Status")]
  - [PASS] `negative_guarantees_present`: PASS [docs/PHASE44_PROMOTION_CHECKLIST.md:254 ("## Deterministic Negative Guarantees")]
  - [PASS] `rejection_codes_present`: PASS [docs/PHASE44_PROMOTION_CHECKLIST.md:77 ("## F. Deterministic Rejection Codes")]
  - [PASS] `runtime_delta_none`: PASS [docs/PHASE44_PROMOTION_CHECKLIST.md:28 ("## Phase 44 Status")]

### Phase 45 — Execution Decision Gate (FAIL)

- File: `docs/PHASE45_PROMOTION_CHECKLIST.md`
- Contracts: `execution_decision.v1`
- Upstream phase refs (declared): 39, 40, 41, 42, 43, 44
- Linked IDs detected: `linked_execution_capability_id`
- Uniqueness signals: 2
- Rejection codes in section: NOT_FOUND
- Priority ordering required: no
- Findings:
  - [PASS] `authority_guarantees_all_false`: PASS [docs/PHASE45_PROMOTION_CHECKLIST.md:121 ("## Execution Decision Contract v1")]
  - [PASS] `contract_found`: PASS [docs/PHASE45_PROMOTION_CHECKLIST.md:121 ("## Execution Decision Contract v1")]
  - [PASS] `execution_enabled_false`: PASS [docs/PHASE45_PROMOTION_CHECKLIST.md:121 ("## Execution Decision Contract v1")]
  - [FAIL] `expiry_semantics`: NOT_FOUND: expiry/time-window checks incomplete [docs/PHASE45_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [PASS] `future_linkage_drift`: PASS [docs/PHASE45_PROMOTION_CHECKLIST.md:121 ("## Execution Decision Contract v1")]
  - [PASS] `hard_invariants_present`: PASS [docs/PHASE45_PROMOTION_CHECKLIST.md:34 ("## A. Hard Invariants")]
  - [PASS] `immutability_flags`: PASS [docs/PHASE45_PROMOTION_CHECKLIST.md:121 ("## Execution Decision Contract v1")]
  - [PASS] `level_name_found`: PASS [docs/PHASE45_PROMOTION_CHECKLIST.md:28 ("## Phase 45 Status")]
  - [PASS] `negative_guarantees_present`: PASS [docs/PHASE45_PROMOTION_CHECKLIST.md:259 ("## Deterministic Negative Guarantees")]
  - [FAIL] `rejection_codes_present`: NOT_FOUND: rejection code list section missing or empty [docs/PHASE45_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [PASS] `runtime_delta_none`: PASS [docs/PHASE45_PROMOTION_CHECKLIST.md:28 ("## Phase 45 Status")]

### Phase 46 — Execution Intent Seal (PASS)

- File: `docs/PHASE46_PROMOTION_CHECKLIST.md`
- Contracts: `execution_intent_seal.v1`
- Upstream phase refs (declared): 39, 40, 41, 42, 43, 44, 45
- Linked IDs detected: `linked_execution_decision_id`
- Uniqueness signals: 3
- Rejection codes in section: 15
- Priority ordering required: no
- Findings:
  - [PASS] `authority_guarantees_all_false`: PASS [docs/PHASE46_PROMOTION_CHECKLIST.md:146 ("## Execution Intent Seal Contract v1")]
  - [PASS] `contract_found`: PASS [docs/PHASE46_PROMOTION_CHECKLIST.md:146 ("## Execution Intent Seal Contract v1")]
  - [PASS] `execution_enabled_false`: PASS [docs/PHASE46_PROMOTION_CHECKLIST.md:146 ("## Execution Intent Seal Contract v1")]
  - [PASS] `expiry_semantics`: PASS [docs/PHASE46_PROMOTION_CHECKLIST.md:67 ("## D. Deterministic Validation Order")]
  - [PASS] `future_linkage_drift`: PASS [docs/PHASE46_PROMOTION_CHECKLIST.md:146 ("## Execution Intent Seal Contract v1")]
  - [PASS] `hard_invariants_present`: PASS [docs/PHASE46_PROMOTION_CHECKLIST.md:34 ("## A. Hard Invariants")]
  - [PASS] `immutability_flags`: PASS [docs/PHASE46_PROMOTION_CHECKLIST.md:146 ("## Execution Intent Seal Contract v1")]
  - [PASS] `level_name_found`: PASS [docs/PHASE46_PROMOTION_CHECKLIST.md:28 ("## Phase 46 Status")]
  - [PASS] `negative_guarantees_present`: PASS [docs/PHASE46_PROMOTION_CHECKLIST.md:296 ("## Deterministic Negative Guarantees")]
  - [PASS] `rejection_codes_present`: PASS [docs/PHASE46_PROMOTION_CHECKLIST.md:98 ("## G. Deterministic Rejection Codes")]
  - [PASS] `runtime_delta_none`: PASS [docs/PHASE46_PROMOTION_CHECKLIST.md:28 ("## Phase 46 Status")]

### Phase 47 — Pre-Execution Validation Gate (FAIL)

- File: `docs/PHASE47_PROMOTION_CHECKLIST.md`
- Contracts: `pre_execution_validation.v1`
- Upstream phase refs (declared): 39, 40, 41, 42, 43, 44, 45, 46
- Linked IDs detected: `linked_execution_intent_seal_id`
- Uniqueness signals: 3
- Rejection codes in section: NOT_FOUND
- Priority ordering required: no
- Findings:
  - [PASS] `authority_guarantees_all_false`: PASS [docs/PHASE47_PROMOTION_CHECKLIST.md:148 ("## Pre-Execution Validation Contract v1")]
  - [PASS] `contract_found`: PASS [docs/PHASE47_PROMOTION_CHECKLIST.md:148 ("## Pre-Execution Validation Contract v1")]
  - [PASS] `execution_enabled_false`: PASS [docs/PHASE47_PROMOTION_CHECKLIST.md:148 ("## Pre-Execution Validation Contract v1")]
  - [FAIL] `expiry_semantics`: NOT_FOUND: expiry/time-window checks incomplete [docs/PHASE47_PROMOTION_CHECKLIST.md:68 ("## C. Deterministic Validation Order")]
  - [PASS] `future_linkage_drift`: PASS [docs/PHASE47_PROMOTION_CHECKLIST.md:148 ("## Pre-Execution Validation Contract v1")]
  - [PASS] `hard_invariants_present`: PASS [docs/PHASE47_PROMOTION_CHECKLIST.md:47 ("## A. Hard Invariants")]
  - [PASS] `immutability_flags`: PASS [docs/PHASE47_PROMOTION_CHECKLIST.md:148 ("## Pre-Execution Validation Contract v1")]
  - [PASS] `level_name_found`: PASS [docs/PHASE47_PROMOTION_CHECKLIST.md:41 ("## Phase 47 Status")]
  - [PASS] `negative_guarantees_present`: PASS [docs/PHASE47_PROMOTION_CHECKLIST.md:291 ("## Deterministic Negative Guarantees")]
  - [FAIL] `rejection_codes_present`: NOT_FOUND: rejection code list section missing or empty [docs/PHASE47_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [PASS] `runtime_delta_none`: PASS [docs/PHASE47_PROMOTION_CHECKLIST.md:41 ("## Phase 47 Status")]

### Phase 48 — Execution Arming Boundary (FAIL)

- File: `docs/PHASE48_PROMOTION_CHECKLIST.md`
- Contracts: `execution_arming.v1`
- Upstream phase refs (declared): 43, 46, 47
- Linked IDs detected: `linked_pre_execution_validation_id`
- Uniqueness signals: 3
- Rejection codes in section: NOT_FOUND
- Priority ordering required: no
- Findings:
  - [PASS] `authority_guarantees_all_false`: PASS [docs/PHASE48_PROMOTION_CHECKLIST.md:134 ("## Execution Arming Contract v1")]
  - [PASS] `contract_found`: PASS [docs/PHASE48_PROMOTION_CHECKLIST.md:134 ("## Execution Arming Contract v1")]
  - [PASS] `execution_enabled_false`: PASS [docs/PHASE48_PROMOTION_CHECKLIST.md:134 ("## Execution Arming Contract v1")]
  - [PASS] `expiry_semantics`: PASS [docs/PHASE48_PROMOTION_CHECKLIST.md:64 ("## C. Deterministic Validation Order")]
  - [PASS] `future_linkage_drift`: PASS [docs/PHASE48_PROMOTION_CHECKLIST.md:134 ("## Execution Arming Contract v1")]
  - [PASS] `hard_invariants_present`: PASS [docs/PHASE48_PROMOTION_CHECKLIST.md:46 ("## A. Hard Invariants")]
  - [PASS] `immutability_flags`: PASS [docs/PHASE48_PROMOTION_CHECKLIST.md:134 ("## Execution Arming Contract v1")]
  - [PASS] `level_name_found`: PASS [docs/PHASE48_PROMOTION_CHECKLIST.md:40 ("## Phase 48 Status")]
  - [PASS] `negative_guarantees_present`: PASS [docs/PHASE48_PROMOTION_CHECKLIST.md:253 ("## Deterministic Negative Guarantees")]
  - [FAIL] `rejection_codes_present`: NOT_FOUND: rejection code list section missing or empty [docs/PHASE48_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [PASS] `runtime_delta_none`: PASS [docs/PHASE48_PROMOTION_CHECKLIST.md:40 ("## Phase 48 Status")]

### Phase 49 — Execution Attempt Boundary (FAIL)

- File: `docs/PHASE49_PROMOTION_CHECKLIST.md`
- Contracts: `execution_attempt.v1`
- Upstream phase refs (declared): 43, 46, 47, 48
- Linked IDs detected: `linked_execution_arming_id`
- Uniqueness signals: 7
- Rejection codes in section: NOT_FOUND
- Priority ordering required: no
- Findings:
  - [PASS] `authority_guarantees_all_false`: PASS [docs/PHASE49_PROMOTION_CHECKLIST.md:137 ("## Execution Attempt Contract v1")]
  - [PASS] `contract_found`: PASS [docs/PHASE49_PROMOTION_CHECKLIST.md:137 ("## Execution Attempt Contract v1")]
  - [PASS] `execution_enabled_false`: PASS [docs/PHASE49_PROMOTION_CHECKLIST.md:137 ("## Execution Attempt Contract v1")]
  - [PASS] `expiry_semantics`: PASS [docs/PHASE49_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [PASS] `future_linkage_drift`: PASS [docs/PHASE49_PROMOTION_CHECKLIST.md:137 ("## Execution Attempt Contract v1")]
  - [PASS] `hard_invariants_present`: PASS [docs/PHASE49_PROMOTION_CHECKLIST.md:46 ("## A. Hard Invariants")]
  - [PASS] `immutability_flags`: PASS [docs/PHASE49_PROMOTION_CHECKLIST.md:137 ("## Execution Attempt Contract v1")]
  - [PASS] `level_name_found`: PASS [docs/PHASE49_PROMOTION_CHECKLIST.md:40 ("## Phase 49 Status")]
  - [PASS] `negative_guarantees_present`: PASS [docs/PHASE49_PROMOTION_CHECKLIST.md:278 ("## Deterministic Negative Guarantees")]
  - [FAIL] `rejection_codes_present`: NOT_FOUND: rejection code list section missing or empty [docs/PHASE49_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [PASS] `runtime_delta_none`: PASS [docs/PHASE49_PROMOTION_CHECKLIST.md:40 ("## Phase 49 Status")]

### Phase 50 — External Executor Interface Contract (FAIL)

- File: `docs/PHASE50_PROMOTION_CHECKLIST.md`
- Contracts: `executor_interface.v1`
- Upstream phase refs (declared): 43, 46, 47, 48, 49
- Linked IDs detected: `linked_execution_attempt_id`
- Uniqueness signals: 4
- Rejection codes in section: NOT_FOUND
- Priority ordering required: no
- Findings:
  - [PASS] `authority_guarantees_all_false`: PASS [docs/PHASE50_PROMOTION_CHECKLIST.md:128 ("## Executor Interface Contract v1")]
  - [PASS] `contract_found`: PASS [docs/PHASE50_PROMOTION_CHECKLIST.md:128 ("## Executor Interface Contract v1")]
  - [PASS] `execution_enabled_false`: PASS [docs/PHASE50_PROMOTION_CHECKLIST.md:128 ("## Executor Interface Contract v1")]
  - [PASS] `expiry_semantics`: PASS [docs/PHASE50_PROMOTION_CHECKLIST.md:67 ("## D. Deterministic Validation Order")]
  - [PASS] `future_linkage_drift`: PASS [docs/PHASE50_PROMOTION_CHECKLIST.md:128 ("## Executor Interface Contract v1")]
  - [PASS] `hard_invariants_present`: PASS [docs/PHASE50_PROMOTION_CHECKLIST.md:41 ("## A. Hard Invariants")]
  - [PASS] `immutability_flags`: PASS [docs/PHASE50_PROMOTION_CHECKLIST.md:128 ("## Executor Interface Contract v1")]
  - [PASS] `level_name_found`: PASS [docs/PHASE50_PROMOTION_CHECKLIST.md:35 ("## Phase 50 Status")]
  - [PASS] `negative_guarantees_present`: PASS [docs/PHASE50_PROMOTION_CHECKLIST.md:270 ("## Deterministic Negative Guarantees")]
  - [FAIL] `rejection_codes_present`: NOT_FOUND: rejection code list section missing or empty [docs/PHASE50_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [PASS] `runtime_delta_none`: PASS [docs/PHASE50_PROMOTION_CHECKLIST.md:35 ("## Phase 50 Status")]

### Phase 51 — External Executor Trust Contract (FAIL)

- File: `docs/PHASE51_PROMOTION_CHECKLIST.md`
- Contracts: `external_executor_trust.v1`
- Upstream phase refs (declared): 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51
- Linked IDs detected: `linked_executor_request_id`
- Uniqueness signals: 4
- Rejection codes in section: NOT_FOUND
- Priority ordering required: no
- Findings:
  - [PASS] `authority_guarantees_all_false`: PASS [docs/PHASE51_PROMOTION_CHECKLIST.md:146 ("## External Executor Trust Contract v1")]
  - [PASS] `contract_found`: PASS [docs/PHASE51_PROMOTION_CHECKLIST.md:146 ("## External Executor Trust Contract v1")]
  - [PASS] `execution_enabled_false`: PASS [docs/PHASE51_PROMOTION_CHECKLIST.md:146 ("## External Executor Trust Contract v1")]
  - [FAIL] `expiry_semantics`: NOT_FOUND: expiry/time-window checks incomplete [docs/PHASE51_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [PASS] `future_linkage_drift`: PASS [docs/PHASE51_PROMOTION_CHECKLIST.md:146 ("## External Executor Trust Contract v1")]
  - [FAIL] `hard_invariants_present`: NOT_FOUND: hard invariants checklist signals missing [docs/PHASE51_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [PASS] `immutability_flags`: PASS [docs/PHASE51_PROMOTION_CHECKLIST.md:146 ("## External Executor Trust Contract v1")]
  - [PASS] `level_name_found`: PASS [docs/PHASE51_PROMOTION_CHECKLIST.md:32 ("## Phase 51 Status")]
  - [PASS] `negative_guarantees_present`: PASS [docs/PHASE51_PROMOTION_CHECKLIST.md:343 ("## Deterministic Negative Guarantees")]
  - [FAIL] `rejection_codes_present`: NOT_FOUND: rejection code list section missing or empty [docs/PHASE51_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [PASS] `runtime_delta_none`: PASS [docs/PHASE51_PROMOTION_CHECKLIST.md:32 ("## Phase 51 Status")]

### Phase 52 — Executor Result Reporting Contract (FAIL)

- File: `docs/PHASE52_PROMOTION_CHECKLIST.md`
- Contracts: `executor_result.v1`
- Upstream phase refs (declared): 50, 51
- Linked IDs detected: `linked_executor_request_id`, `linked_executor_trust_record_id`
- Uniqueness signals: 3
- Rejection codes in section: NOT_FOUND
- Priority ordering required: no
- Findings:
  - [PASS] `authority_guarantees_all_false`: PASS [docs/PHASE52_PROMOTION_CHECKLIST.md:143 ("## Executor Result Contract v1")]
  - [PASS] `contract_found`: PASS [docs/PHASE52_PROMOTION_CHECKLIST.md:143 ("## Executor Result Contract v1")]
  - [PASS] `execution_enabled_false`: PASS [docs/PHASE52_PROMOTION_CHECKLIST.md:143 ("## Executor Result Contract v1")]
  - [PASS] `expiry_semantics`: PASS [docs/PHASE52_PROMOTION_CHECKLIST.md:64 ("## D. Deterministic Validation Order")]
  - [PASS] `future_linkage_drift`: PASS [docs/PHASE52_PROMOTION_CHECKLIST.md:143 ("## Executor Result Contract v1")]
  - [PASS] `hard_invariants_present`: PASS [docs/PHASE52_PROMOTION_CHECKLIST.md:41 ("## A. Hard Invariants")]
  - [PASS] `immutability_flags`: PASS [docs/PHASE52_PROMOTION_CHECKLIST.md:143 ("## Executor Result Contract v1")]
  - [PASS] `level_name_found`: PASS [docs/PHASE52_PROMOTION_CHECKLIST.md:35 ("## Phase 52 Status")]
  - [PASS] `negative_guarantees_present`: PASS [docs/PHASE52_PROMOTION_CHECKLIST.md:330 ("## Deterministic Negative Guarantees")]
  - [FAIL] `rejection_codes_present`: NOT_FOUND: rejection code list section missing or empty [docs/PHASE52_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [PASS] `runtime_delta_none`: PASS [docs/PHASE52_PROMOTION_CHECKLIST.md:35 ("## Phase 52 Status")]

### Phase 53 — Human Review & Post-Execution Interpretation Gate (FAIL)

- File: `docs/PHASE53_PROMOTION_CHECKLIST.md`
- Contracts: `human_execution_review.v1`
- Upstream phase refs (declared): 52
- Linked IDs detected: `linked_execution_attempt_id`, `linked_execution_intent_seal_id`, `linked_executor_request_id`, `linked_executor_result_id`
- Uniqueness signals: 2
- Rejection codes in section: NOT_FOUND
- Priority ordering required: no
- Findings:
  - [PASS] `authority_guarantees_all_false`: PASS [docs/PHASE53_PROMOTION_CHECKLIST.md:143 ("## Human Execution Review Contract v1")]
  - [PASS] `contract_found`: PASS [docs/PHASE53_PROMOTION_CHECKLIST.md:143 ("## Human Execution Review Contract v1")]
  - [PASS] `execution_enabled_false`: PASS [docs/PHASE53_PROMOTION_CHECKLIST.md:143 ("## Human Execution Review Contract v1")]
  - [PASS] `expiry_semantics`: PASS [docs/PHASE53_PROMOTION_CHECKLIST.md:63 ("## D. Deterministic Validation Order")]
  - [PASS] `future_linkage_drift`: PASS [docs/PHASE53_PROMOTION_CHECKLIST.md:143 ("## Human Execution Review Contract v1")]
  - [PASS] `hard_invariants_present`: PASS [docs/PHASE53_PROMOTION_CHECKLIST.md:40 ("## A. Hard Invariants")]
  - [PASS] `immutability_flags`: PASS [docs/PHASE53_PROMOTION_CHECKLIST.md:143 ("## Human Execution Review Contract v1")]
  - [PASS] `level_name_found`: PASS [docs/PHASE53_PROMOTION_CHECKLIST.md:34 ("## Phase 53 Status")]
  - [PASS] `negative_guarantees_present`: PASS [docs/PHASE53_PROMOTION_CHECKLIST.md:345 ("## Deterministic Negative Guarantees")]
  - [FAIL] `rejection_codes_present`: NOT_FOUND: rejection code list section missing or empty [docs/PHASE53_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [PASS] `runtime_delta_none`: PASS [docs/PHASE53_PROMOTION_CHECKLIST.md:34 ("## Phase 53 Status")]

### Phase 54 — Human-Initiated Re-Planning Gate (FAIL)

- File: `docs/PHASE54_PROMOTION_CHECKLIST.md`
- Contracts: `human_replanning_intent.v1`
- Upstream phase refs (declared): 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54
- Linked IDs detected: NOT_FOUND
- Uniqueness signals: NOT_FOUND
- Rejection codes in section: NOT_FOUND
- Priority ordering required: no
- Findings:
  - [PASS] `authority_guarantees_all_false`: PASS [docs/PHASE54_PROMOTION_CHECKLIST.md:155 ("## Human Re-Planning Intent Contract v1")]
  - [PASS] `contract_found`: PASS [docs/PHASE54_PROMOTION_CHECKLIST.md:155 ("## Human Re-Planning Intent Contract v1")]
  - [PASS] `execution_enabled_false`: PASS [docs/PHASE54_PROMOTION_CHECKLIST.md:155 ("## Human Re-Planning Intent Contract v1")]
  - [PASS] `expiry_semantics`: PASS [docs/PHASE54_PROMOTION_CHECKLIST.md:78 ("## E. Deterministic Validation Order")]
  - [PASS] `hard_invariants_present`: PASS [docs/PHASE54_PROMOTION_CHECKLIST.md:42 ("## A. Hard Invariants")]
  - [PASS] `immutability_flags`: PASS [docs/PHASE54_PROMOTION_CHECKLIST.md:155 ("## Human Re-Planning Intent Contract v1")]
  - [PASS] `level_name_found`: PASS [docs/PHASE54_PROMOTION_CHECKLIST.md:36 ("## Phase 54 Status")]
  - [PASS] `negative_guarantees_present`: PASS [docs/PHASE54_PROMOTION_CHECKLIST.md:347 ("## Deterministic Negative Guarantees")]
  - [PASS] `preservation_clause_present`: PASS [docs/PHASE54_PROMOTION_CHECKLIST.md:126 ("## J. Explicit Preservation of Phases 27-53")]
  - [FAIL] `rejection_codes_present`: NOT_FOUND: rejection code list section missing or empty [docs/PHASE54_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [PASS] `runtime_delta_none`: PASS [docs/PHASE54_PROMOTION_CHECKLIST.md:36 ("## Phase 54 Status")]
  - [FAIL] `uniqueness_signal_present`: NOT_FOUND: one-per-* uniqueness statement not detected [docs/PHASE54_PROMOTION_CHECKLIST.md:42 ("## A. Hard Invariants")]

### Phase 55 — Governed Planning Context Assembly (FAIL)

- File: `docs/PHASE55_PROMOTION_CHECKLIST.md`
- Contracts: `planning_context.v1`
- Upstream phase refs (declared): 54
- Linked IDs detected: `linked_human_replanning_intent_id`
- Uniqueness signals: NOT_FOUND
- Rejection codes in section: NOT_FOUND
- Priority ordering required: no
- Findings:
  - [PASS] `authority_guarantees_all_false`: PASS [docs/PHASE55_PROMOTION_CHECKLIST.md:163 ("## Planning Context Contract v1")]
  - [PASS] `contract_found`: PASS [docs/PHASE55_PROMOTION_CHECKLIST.md:163 ("## Planning Context Contract v1")]
  - [PASS] `execution_enabled_false`: PASS [docs/PHASE55_PROMOTION_CHECKLIST.md:163 ("## Planning Context Contract v1")]
  - [PASS] `expiry_semantics`: PASS [docs/PHASE55_PROMOTION_CHECKLIST.md:82 ("## E. Deterministic Validation Order")]
  - [PASS] `future_linkage_drift`: PASS [docs/PHASE55_PROMOTION_CHECKLIST.md:163 ("## Planning Context Contract v1")]
  - [PASS] `hard_invariants_present`: PASS [docs/PHASE55_PROMOTION_CHECKLIST.md:44 ("## A. Hard Invariants")]
  - [PASS] `immutability_flags`: PASS [docs/PHASE55_PROMOTION_CHECKLIST.md:163 ("## Planning Context Contract v1")]
  - [PASS] `level_name_found`: PASS [docs/PHASE55_PROMOTION_CHECKLIST.md:38 ("## Phase 55 Status")]
  - [PASS] `negative_guarantees_present`: PASS [docs/PHASE55_PROMOTION_CHECKLIST.md:384 ("## Deterministic Negative Guarantees")]
  - [PASS] `preservation_clause_present`: PASS [docs/PHASE55_PROMOTION_CHECKLIST.md:133 ("## I. Explicit Preservation of Phases 27-54")]
  - [FAIL] `rejection_codes_present`: NOT_FOUND: rejection code list section missing or empty [docs/PHASE55_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [PASS] `runtime_delta_none`: PASS [docs/PHASE55_PROMOTION_CHECKLIST.md:38 ("## Phase 55 Status")]
  - [FAIL] `uniqueness_signal_present`: NOT_FOUND: one-per-* uniqueness statement not detected [docs/PHASE55_PROMOTION_CHECKLIST.md:44 ("## A. Hard Invariants")]

### Phase 56 — Planning Output Envelope (FAIL)

- File: `docs/PHASE56_PROMOTION_CHECKLIST.md`
- Contracts: `planning_output.v1`
- Upstream phase refs (declared): 54, 55, 56
- Linked IDs detected: `linked_human_replanning_intent_id`, `linked_planning_context_id`
- Uniqueness signals: NOT_FOUND
- Rejection codes in section: NOT_FOUND
- Priority ordering required: no
- Findings:
  - [PASS] `authority_guarantees_all_false`: PASS [docs/PHASE56_PROMOTION_CHECKLIST.md:177 ("## Planning Output Contract v1")]
  - [PASS] `contract_found`: PASS [docs/PHASE56_PROMOTION_CHECKLIST.md:177 ("## Planning Output Contract v1")]
  - [PASS] `execution_enabled_false`: PASS [docs/PHASE56_PROMOTION_CHECKLIST.md:177 ("## Planning Output Contract v1")]
  - [PASS] `expiry_semantics`: PASS [docs/PHASE56_PROMOTION_CHECKLIST.md:84 ("## E. Deterministic Validation Order")]
  - [PASS] `future_linkage_drift`: PASS [docs/PHASE56_PROMOTION_CHECKLIST.md:177 ("## Planning Output Contract v1")]
  - [PASS] `hard_invariants_present`: PASS [docs/PHASE56_PROMOTION_CHECKLIST.md:42 ("## A. Hard Invariants")]
  - [PASS] `immutability_flags`: PASS [docs/PHASE56_PROMOTION_CHECKLIST.md:177 ("## Planning Output Contract v1")]
  - [PASS] `level_name_found`: PASS [docs/PHASE56_PROMOTION_CHECKLIST.md:36 ("## Phase 56 Status")]
  - [PASS] `negative_guarantees_present`: PASS [docs/PHASE56_PROMOTION_CHECKLIST.md:452 ("## Deterministic Negative Guarantees")]
  - [PASS] `preservation_clause_present`: PASS [docs/PHASE56_PROMOTION_CHECKLIST.md:146 ("## I. Explicit Preservation of Phases 27-55")]
  - [FAIL] `rejection_codes_present`: NOT_FOUND: rejection code list section missing or empty [docs/PHASE56_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [PASS] `runtime_delta_none`: PASS [docs/PHASE56_PROMOTION_CHECKLIST.md:36 ("## Phase 56 Status")]
  - [FAIL] `uniqueness_signal_present`: NOT_FOUND: one-per-* uniqueness statement not detected [docs/PHASE56_PROMOTION_CHECKLIST.md:42 ("## A. Hard Invariants")]

### Phase 57 — Planning Session Boundary & Closure (FAIL)

- File: `docs/PHASE57_PROMOTION_CHECKLIST.md`
- Contracts: `planning_session.v1`
- Upstream phase refs (declared): 54, 55, 56
- Linked IDs detected: `linked_human_replanning_intent_id`, `linked_planning_context_id`
- Uniqueness signals: 1
- Rejection codes in section: NOT_FOUND
- Priority ordering required: no
- Findings:
  - [PASS] `authority_guarantees_all_false`: PASS [docs/PHASE57_PROMOTION_CHECKLIST.md:197 ("## Planning Session Contract v1")]
  - [PASS] `contract_found`: PASS [docs/PHASE57_PROMOTION_CHECKLIST.md:197 ("## Planning Session Contract v1")]
  - [PASS] `execution_enabled_false`: PASS [docs/PHASE57_PROMOTION_CHECKLIST.md:197 ("## Planning Session Contract v1")]
  - [PASS] `expiry_semantics`: PASS [docs/PHASE57_PROMOTION_CHECKLIST.md:87 ("## E. Deterministic Validation Order")]
  - [PASS] `future_linkage_drift`: PASS [docs/PHASE57_PROMOTION_CHECKLIST.md:197 ("## Planning Session Contract v1")]
  - [PASS] `hard_invariants_present`: PASS [docs/PHASE57_PROMOTION_CHECKLIST.md:44 ("## A. Hard Invariants")]
  - [PASS] `immutability_flags`: PASS [docs/PHASE57_PROMOTION_CHECKLIST.md:197 ("## Planning Session Contract v1")]
  - [PASS] `level_name_found`: PASS [docs/PHASE57_PROMOTION_CHECKLIST.md:38 ("## Phase 57 Status")]
  - [PASS] `negative_guarantees_present`: PASS [docs/PHASE57_PROMOTION_CHECKLIST.md:476 ("## Deterministic Negative Guarantees")]
  - [PASS] `preservation_clause_present`: PASS [docs/PHASE57_PROMOTION_CHECKLIST.md:165 ("## I. Explicit Preservation of Phases 27-56")]
  - [FAIL] `rejection_codes_present`: NOT_FOUND: rejection code list section missing or empty [docs/PHASE57_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [PASS] `runtime_delta_none`: PASS [docs/PHASE57_PROMOTION_CHECKLIST.md:38 ("## Phase 57 Status")]
  - [PASS] `uniqueness_signal_present`: PASS [docs/PHASE57_PROMOTION_CHECKLIST.md:44 ("## A. Hard Invariants")]

### Phase 58 — Human Plan Acceptance Gate (FAIL)

- File: `docs/PHASE58_PROMOTION_CHECKLIST.md`
- Contracts: `plan_acceptance.v1`
- Upstream phase refs (declared): 54, 55, 56, 57
- Linked IDs detected: `linked_human_replanning_intent_id`, `linked_planning_context_id`, `linked_planning_output_id`, `linked_planning_session_id`
- Uniqueness signals: 9
- Rejection codes in section: NOT_FOUND
- Priority ordering required: no
- Findings:
  - [PASS] `authority_guarantees_all_false`: PASS [docs/PHASE58_PROMOTION_CHECKLIST.md:199 ("## Plan Acceptance Contract v1")]
  - [PASS] `contract_found`: PASS [docs/PHASE58_PROMOTION_CHECKLIST.md:199 ("## Plan Acceptance Contract v1")]
  - [PASS] `execution_enabled_false`: PASS [docs/PHASE58_PROMOTION_CHECKLIST.md:199 ("## Plan Acceptance Contract v1")]
  - [PASS] `expected_linkage_present_once`: PASS [docs/PHASE58_PROMOTION_CHECKLIST.md:199 ("## Plan Acceptance Contract v1")]
  - [PASS] `expiry_semantics`: PASS [docs/PHASE58_PROMOTION_CHECKLIST.md:91 ("## E. Deterministic Validation Order")]
  - [PASS] `future_linkage_drift`: PASS [docs/PHASE58_PROMOTION_CHECKLIST.md:199 ("## Plan Acceptance Contract v1")]
  - [PASS] `hard_invariants_present`: PASS [docs/PHASE58_PROMOTION_CHECKLIST.md:45 ("## A. Hard Invariants")]
  - [PASS] `immutability_flags`: PASS [docs/PHASE58_PROMOTION_CHECKLIST.md:199 ("## Plan Acceptance Contract v1")]
  - [PASS] `level_name_found`: PASS [docs/PHASE58_PROMOTION_CHECKLIST.md:39 ("## Phase 58 Status")]
  - [PASS] `negative_guarantees_present`: PASS [docs/PHASE58_PROMOTION_CHECKLIST.md:469 ("## Deterministic Negative Guarantees")]
  - [PASS] `preservation_clause_present`: PASS [docs/PHASE58_PROMOTION_CHECKLIST.md:166 ("## I. Explicit Preservation of Phases 27-57")]
  - [FAIL] `rejection_codes_present`: NOT_FOUND: rejection code list section missing or empty [docs/PHASE58_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [PASS] `runtime_delta_none`: PASS [docs/PHASE58_PROMOTION_CHECKLIST.md:39 ("## Phase 58 Status")]
  - [PASS] `uniqueness_signal_present`: PASS [docs/PHASE58_PROMOTION_CHECKLIST.md:45 ("## A. Hard Invariants")]

### Phase 59 — Human Plan Approval Gate (FAIL)

- File: `docs/PHASE59_PROMOTION_CHECKLIST.md`
- Contracts: `plan_approval.v1`
- Upstream phase refs (declared): 54, 55, 56, 57, 58
- Linked IDs detected: `linked_plan_acceptance_id`
- Uniqueness signals: 5
- Rejection codes in section: NOT_FOUND
- Priority ordering required: no
- Findings:
  - [PASS] `authority_guarantees_all_false`: PASS [docs/PHASE59_PROMOTION_CHECKLIST.md:211 ("## Plan Approval Contract v1")]
  - [PASS] `contract_found`: PASS [docs/PHASE59_PROMOTION_CHECKLIST.md:211 ("## Plan Approval Contract v1")]
  - [PASS] `execution_enabled_false`: PASS [docs/PHASE59_PROMOTION_CHECKLIST.md:211 ("## Plan Approval Contract v1")]
  - [PASS] `expected_linkage_present_once`: PASS [docs/PHASE59_PROMOTION_CHECKLIST.md:211 ("## Plan Approval Contract v1")]
  - [PASS] `expiry_semantics`: PASS [docs/PHASE59_PROMOTION_CHECKLIST.md:100 ("## E. Deterministic Validation Order")]
  - [PASS] `future_linkage_drift`: PASS [docs/PHASE59_PROMOTION_CHECKLIST.md:211 ("## Plan Approval Contract v1")]
  - [PASS] `hard_invariants_present`: PASS [docs/PHASE59_PROMOTION_CHECKLIST.md:47 ("## A. Hard Invariants")]
  - [PASS] `immutability_flags`: PASS [docs/PHASE59_PROMOTION_CHECKLIST.md:211 ("## Plan Approval Contract v1")]
  - [PASS] `level_name_found`: PASS [docs/PHASE59_PROMOTION_CHECKLIST.md:41 ("## Phase 59 Status")]
  - [PASS] `negative_guarantees_present`: PASS [docs/PHASE59_PROMOTION_CHECKLIST.md:466 ("## Deterministic Negative Guarantees")]
  - [PASS] `preservation_clause_present`: PASS [docs/PHASE59_PROMOTION_CHECKLIST.md:177 ("## I. Explicit Preservation of Phases 27-58")]
  - [FAIL] `rejection_codes_present`: NOT_FOUND: rejection code list section missing or empty [docs/PHASE59_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [PASS] `runtime_delta_none`: PASS [docs/PHASE59_PROMOTION_CHECKLIST.md:41 ("## Phase 59 Status")]
  - [PASS] `uniqueness_signal_present`: PASS [docs/PHASE59_PROMOTION_CHECKLIST.md:47 ("## A. Hard Invariants")]

### Phase 60 — Plan Authorization Gate (FAIL)

- File: `docs/PHASE60_PROMOTION_CHECKLIST.md`
- Contracts: `plan_authorization.v1`
- Upstream phase refs (declared): 54, 55, 56, 57, 58, 59
- Linked IDs detected: `linked_plan_approval_id`
- Uniqueness signals: 6
- Rejection codes in section: NOT_FOUND
- Priority ordering required: no
- Findings:
  - [PASS] `authority_guarantees_all_false`: PASS [docs/PHASE60_PROMOTION_CHECKLIST.md:212 ("## Plan Authorization Contract v1")]
  - [PASS] `contract_found`: PASS [docs/PHASE60_PROMOTION_CHECKLIST.md:212 ("## Plan Authorization Contract v1")]
  - [PASS] `execution_enabled_false`: PASS [docs/PHASE60_PROMOTION_CHECKLIST.md:212 ("## Plan Authorization Contract v1")]
  - [PASS] `expected_linkage_present_once`: PASS [docs/PHASE60_PROMOTION_CHECKLIST.md:212 ("## Plan Authorization Contract v1")]
  - [PASS] `expiry_semantics`: PASS [docs/PHASE60_PROMOTION_CHECKLIST.md:95 ("## E. Deterministic Validation Order")]
  - [PASS] `future_linkage_drift`: PASS [docs/PHASE60_PROMOTION_CHECKLIST.md:212 ("## Plan Authorization Contract v1")]
  - [PASS] `hard_invariants_present`: PASS [docs/PHASE60_PROMOTION_CHECKLIST.md:43 ("## A. Hard Invariants")]
  - [PASS] `immutability_flags`: PASS [docs/PHASE60_PROMOTION_CHECKLIST.md:212 ("## Plan Authorization Contract v1")]
  - [PASS] `level_name_found`: PASS [docs/PHASE60_PROMOTION_CHECKLIST.md:37 ("## Phase 60 Status")]
  - [PASS] `negative_guarantees_present`: PASS [docs/PHASE60_PROMOTION_CHECKLIST.md:489 ("## Deterministic Negative Guarantees")]
  - [PASS] `preservation_clause_present`: PASS [docs/PHASE60_PROMOTION_CHECKLIST.md:177 ("## I. Explicit Preservation of Phases 27-59")]
  - [FAIL] `rejection_codes_present`: NOT_FOUND: rejection code list section missing or empty [docs/PHASE60_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [PASS] `runtime_delta_none`: PASS [docs/PHASE60_PROMOTION_CHECKLIST.md:37 ("## Phase 60 Status")]
  - [PASS] `uniqueness_signal_present`: PASS [docs/PHASE60_PROMOTION_CHECKLIST.md:43 ("## A. Hard Invariants")]

### Phase 61 — Execution Scope Binding Gate (FAIL)

- File: `docs/PHASE61_PROMOTION_CHECKLIST.md`
- Contracts: `execution_scope_binding.v1`
- Upstream phase refs (declared): 54, 55, 56, 57, 58, 59, 60
- Linked IDs detected: `linked_plan_authorization_id`
- Uniqueness signals: 6
- Rejection codes in section: NOT_FOUND
- Priority ordering required: no
- Findings:
  - [PASS] `authority_guarantees_all_false`: PASS [docs/PHASE61_PROMOTION_CHECKLIST.md:241 ("## Execution Scope Binding Contract v1")]
  - [PASS] `contract_found`: PASS [docs/PHASE61_PROMOTION_CHECKLIST.md:241 ("## Execution Scope Binding Contract v1")]
  - [PASS] `execution_enabled_false`: PASS [docs/PHASE61_PROMOTION_CHECKLIST.md:241 ("## Execution Scope Binding Contract v1")]
  - [PASS] `expected_linkage_present_once`: PASS [docs/PHASE61_PROMOTION_CHECKLIST.md:241 ("## Execution Scope Binding Contract v1")]
  - [PASS] `expiry_semantics`: PASS [docs/PHASE61_PROMOTION_CHECKLIST.md:103 ("## E. Deterministic Validation Order")]
  - [PASS] `future_linkage_drift`: PASS [docs/PHASE61_PROMOTION_CHECKLIST.md:241 ("## Execution Scope Binding Contract v1")]
  - [PASS] `hard_invariants_present`: PASS [docs/PHASE61_PROMOTION_CHECKLIST.md:42 ("## A. Hard Invariants")]
  - [PASS] `immutability_flags`: PASS [docs/PHASE61_PROMOTION_CHECKLIST.md:241 ("## Execution Scope Binding Contract v1")]
  - [PASS] `level_name_found`: PASS [docs/PHASE61_PROMOTION_CHECKLIST.md:36 ("## Phase 61 Status")]
  - [PASS] `negative_guarantees_present`: PASS [docs/PHASE61_PROMOTION_CHECKLIST.md:535 ("## Deterministic Negative Guarantees")]
  - [PASS] `preservation_clause_present`: PASS [docs/PHASE61_PROMOTION_CHECKLIST.md:205 ("## I. Explicit Preservation of Phases 27-60")]
  - [FAIL] `rejection_codes_present`: NOT_FOUND: rejection code list section missing or empty [docs/PHASE61_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [PASS] `runtime_delta_none`: PASS [docs/PHASE61_PROMOTION_CHECKLIST.md:36 ("## Phase 61 Status")]
  - [PASS] `uniqueness_signal_present`: PASS [docs/PHASE61_PROMOTION_CHECKLIST.md:42 ("## A. Hard Invariants")]

### Phase 62 — Execution Preconditions Declaration Gate (FAIL)

- File: `docs/PHASE62_PROMOTION_CHECKLIST.md`
- Contracts: `execution_preconditions.v1`
- Upstream phase refs (declared): 54, 55, 56, 57, 58, 59, 60, 61
- Linked IDs detected: `linked_execution_scope_binding_id`
- Uniqueness signals: 6
- Rejection codes in section: NOT_FOUND
- Priority ordering required: no
- Findings:
  - [PASS] `authority_guarantees_all_false`: PASS [docs/PHASE62_PROMOTION_CHECKLIST.md:243 ("## Execution Preconditions Contract v1")]
  - [PASS] `contract_found`: PASS [docs/PHASE62_PROMOTION_CHECKLIST.md:243 ("## Execution Preconditions Contract v1")]
  - [PASS] `execution_enabled_false`: PASS [docs/PHASE62_PROMOTION_CHECKLIST.md:243 ("## Execution Preconditions Contract v1")]
  - [PASS] `expected_linkage_present_once`: PASS [docs/PHASE62_PROMOTION_CHECKLIST.md:243 ("## Execution Preconditions Contract v1")]
  - [PASS] `expiry_semantics`: PASS [docs/PHASE62_PROMOTION_CHECKLIST.md:102 ("## E. Deterministic Validation Order")]
  - [PASS] `future_linkage_drift`: PASS [docs/PHASE62_PROMOTION_CHECKLIST.md:243 ("## Execution Preconditions Contract v1")]
  - [PASS] `hard_invariants_present`: PASS [docs/PHASE62_PROMOTION_CHECKLIST.md:41 ("## A. Hard Invariants")]
  - [PASS] `immutability_flags`: PASS [docs/PHASE62_PROMOTION_CHECKLIST.md:243 ("## Execution Preconditions Contract v1")]
  - [PASS] `level_name_found`: PASS [docs/PHASE62_PROMOTION_CHECKLIST.md:35 ("## Phase 62 Status")]
  - [PASS] `negative_guarantees_present`: PASS [docs/PHASE62_PROMOTION_CHECKLIST.md:593 ("## Deterministic Negative Guarantees")]
  - [PASS] `preservation_clause_present`: PASS [docs/PHASE62_PROMOTION_CHECKLIST.md:206 ("## I. Explicit Preservation of Phases 27-61")]
  - [FAIL] `rejection_codes_present`: NOT_FOUND: rejection code list section missing or empty [docs/PHASE62_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)]
  - [PASS] `runtime_delta_none`: PASS [docs/PHASE62_PROMOTION_CHECKLIST.md:35 ("## Phase 62 Status")]
  - [PASS] `uniqueness_signal_present`: PASS [docs/PHASE62_PROMOTION_CHECKLIST.md:41 ("## A. Hard Invariants")]

### Phase 63 — Readiness Evaluation Gate (PASS)

- File: `docs/PHASE63_PROMOTION_CHECKLIST.md`
- Contracts: `execution_readiness.v1`
- Upstream phase refs (declared): 54, 55, 56, 57, 58, 59, 60, 61, 62
- Linked IDs detected: `linked_execution_preconditions_id`
- Uniqueness signals: 4
- Rejection codes in section: 53
- Priority ordering required: yes; present: yes
- Findings:
  - [PASS] `authority_guarantees_all_false`: PASS [docs/PHASE63_PROMOTION_CHECKLIST.md:230 ("## Execution Readiness Contract v1")]
  - [PASS] `contract_found`: PASS [docs/PHASE63_PROMOTION_CHECKLIST.md:230 ("## Execution Readiness Contract v1")]
  - [PASS] `execution_enabled_false`: PASS [docs/PHASE63_PROMOTION_CHECKLIST.md:230 ("## Execution Readiness Contract v1")]
  - [PASS] `expected_linkage_present_once`: PASS [docs/PHASE63_PROMOTION_CHECKLIST.md:230 ("## Execution Readiness Contract v1")]
  - [PASS] `expiry_semantics`: PASS [docs/PHASE63_PROMOTION_CHECKLIST.md:117 ("## E. Invalidations and Expiry Rules")]
  - [PASS] `future_linkage_drift`: PASS [docs/PHASE63_PROMOTION_CHECKLIST.md:230 ("## Execution Readiness Contract v1")]
  - [PASS] `hard_invariants_present`: PASS [docs/PHASE63_PROMOTION_CHECKLIST.md:42 ("## A. Hard Invariants")]
  - [PASS] `immutability_flags`: PASS [docs/PHASE63_PROMOTION_CHECKLIST.md:230 ("## Execution Readiness Contract v1")]
  - [PASS] `level_name_found`: PASS [docs/PHASE63_PROMOTION_CHECKLIST.md:36 ("## Phase 63 Status")]
  - [PASS] `negative_guarantees_present`: PASS [docs/PHASE63_PROMOTION_CHECKLIST.md:612 ("## Deterministic Negative Guarantees")]
  - [PASS] `preservation_clause_present`: PASS [docs/PHASE63_PROMOTION_CHECKLIST.md:192 ("## H. Explicit Preservation of Phases 27-62")]
  - [PASS] `priority_ordering_present`: PASS [docs/PHASE63_PROMOTION_CHECKLIST.md:230 ("## Execution Readiness Contract v1")]
  - [PASS] `rejection_codes_present`: PASS [docs/PHASE63_PROMOTION_CHECKLIST.md:125 ("## F. Deterministic Rejection Codes (with priority)")]
  - [PASS] `runtime_delta_none`: PASS [docs/PHASE63_PROMOTION_CHECKLIST.md:36 ("## Phase 63 Status")]
  - [PASS] `uniqueness_signal_present`: PASS [docs/PHASE63_PROMOTION_CHECKLIST.md:42 ("## A. Hard Invariants")]

### Phase 64 — Readiness Attestation Gate (PASS)

- File: `docs/PHASE64_PROMOTION_CHECKLIST.md`
- Contracts: `readiness_attestation.v1`
- Upstream phase refs (declared): 54, 55, 56, 57, 58, 59, 60, 61, 62, 63
- Linked IDs detected: `linked_execution_readiness_id`
- Uniqueness signals: 5
- Rejection codes in section: 50
- Priority ordering required: yes; present: yes
- Findings:
  - [PASS] `authority_guarantees_all_false`: PASS [docs/PHASE64_PROMOTION_CHECKLIST.md:217 ("## Readiness Attestation Contract v1")]
  - [PASS] `contract_found`: PASS [docs/PHASE64_PROMOTION_CHECKLIST.md:217 ("## Readiness Attestation Contract v1")]
  - [PASS] `execution_enabled_false`: PASS [docs/PHASE64_PROMOTION_CHECKLIST.md:217 ("## Readiness Attestation Contract v1")]
  - [PASS] `expected_linkage_present_once`: PASS [docs/PHASE64_PROMOTION_CHECKLIST.md:217 ("## Readiness Attestation Contract v1")]
  - [PASS] `expiry_semantics`: PASS [docs/PHASE64_PROMOTION_CHECKLIST.md:77 ("## C. Deterministic Validation Order")]
  - [PASS] `future_linkage_drift`: PASS [docs/PHASE64_PROMOTION_CHECKLIST.md:217 ("## Readiness Attestation Contract v1")]
  - [PASS] `hard_invariants_present`: PASS [docs/PHASE64_PROMOTION_CHECKLIST.md:42 ("## A. Hard Invariants")]
  - [PASS] `immutability_flags`: PASS [docs/PHASE64_PROMOTION_CHECKLIST.md:217 ("## Readiness Attestation Contract v1")]
  - [PASS] `level_name_found`: PASS [docs/PHASE64_PROMOTION_CHECKLIST.md:36 ("## Phase 64 Status")]
  - [PASS] `negative_guarantees_present`: PASS [docs/PHASE64_PROMOTION_CHECKLIST.md:501 ("## Deterministic Negative Guarantees")]
  - [PASS] `preservation_clause_present`: PASS [docs/PHASE64_PROMOTION_CHECKLIST.md:178 ("## H. Explicit Preservation of Phases 27-63")]
  - [PASS] `priority_ordering_present`: PASS [docs/PHASE64_PROMOTION_CHECKLIST.md:217 ("## Readiness Attestation Contract v1")]
  - [PASS] `rejection_codes_present`: PASS [docs/PHASE64_PROMOTION_CHECKLIST.md:114 ("## F. Deterministic Rejection Codes (with priority)")]
  - [PASS] `runtime_delta_none`: PASS [docs/PHASE64_PROMOTION_CHECKLIST.md:36 ("## Phase 64 Status")]
  - [PASS] `uniqueness_signal_present`: PASS [docs/PHASE64_PROMOTION_CHECKLIST.md:42 ("## A. Hard Invariants")]

### Phase 65 — Execution Arming Authorization Gate (FAIL)

- File: `docs/PHASE65_PROMOTION_CHECKLIST.md`
- Contracts: `execution_arming_authorization.v1`
- Upstream phase refs (declared): 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64
- Linked IDs detected: `linked_readiness_attestation_id`
- Uniqueness signals: 5
- Rejection codes in section: 61
- Priority ordering required: yes; present: yes
- Findings:
  - [FAIL] `authority_guarantees_all_false`: INVALID: non-constant boolean found in authority_guarantees [docs/PHASE65_PROMOTION_CHECKLIST.md:241 ("## Execution Arming Authorization Contract v1")]
  - [PASS] `contract_found`: PASS [docs/PHASE65_PROMOTION_CHECKLIST.md:241 ("## Execution Arming Authorization Contract v1")]
  - [PASS] `execution_enabled_false`: PASS [docs/PHASE65_PROMOTION_CHECKLIST.md:241 ("## Execution Arming Authorization Contract v1")]
  - [PASS] `expected_linkage_present_once`: PASS [docs/PHASE65_PROMOTION_CHECKLIST.md:241 ("## Execution Arming Authorization Contract v1")]
  - [PASS] `expiry_semantics`: PASS [docs/PHASE65_PROMOTION_CHECKLIST.md:82 ("## C. Deterministic Validation Order")]
  - [PASS] `future_linkage_drift`: PASS [docs/PHASE65_PROMOTION_CHECKLIST.md:241 ("## Execution Arming Authorization Contract v1")]
  - [PASS] `hard_invariants_present`: PASS [docs/PHASE65_PROMOTION_CHECKLIST.md:42 ("## A. Hard Invariants")]
  - [PASS] `immutability_flags`: PASS [docs/PHASE65_PROMOTION_CHECKLIST.md:241 ("## Execution Arming Authorization Contract v1")]
  - [PASS] `level_name_found`: PASS [docs/PHASE65_PROMOTION_CHECKLIST.md:36 ("## Phase 65 Status")]
  - [PASS] `negative_guarantees_present`: PASS [docs/PHASE65_PROMOTION_CHECKLIST.md:593 ("## Deterministic Negative Guarantees")]
  - [PASS] `preservation_clause_present`: PASS [docs/PHASE65_PROMOTION_CHECKLIST.md:201 ("## H. Explicit Preservation of Phases 27-64")]
  - [PASS] `priority_ordering_present`: PASS [docs/PHASE65_PROMOTION_CHECKLIST.md:241 ("## Execution Arming Authorization Contract v1")]
  - [PASS] `rejection_codes_present`: PASS [docs/PHASE65_PROMOTION_CHECKLIST.md:126 ("## F. Deterministic Rejection Codes (with priority)")]
  - [PASS] `runtime_delta_none`: PASS [docs/PHASE65_PROMOTION_CHECKLIST.md:36 ("## Phase 65 Status")]
  - [PASS] `uniqueness_signal_present`: PASS [docs/PHASE65_PROMOTION_CHECKLIST.md:42 ("## A. Hard Invariants")]

### Phase 66 — Execution Arming State Machine (FAIL)

- File: `docs/PHASE66_PROMOTION_CHECKLIST.md`
- Contracts: `execution_arming_state.v1`
- Upstream phase refs (declared): 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65
- Linked IDs detected: `linked_execution_arming_authorization_id`
- Uniqueness signals: 8
- Rejection codes in section: 59
- Priority ordering required: yes; present: yes
- Findings:
  - [FAIL] `authority_guarantees_all_false`: INVALID: non-constant boolean found in authority_guarantees [docs/PHASE66_PROMOTION_CHECKLIST.md:232 ("## Execution Arming State Contract v1")]
  - [PASS] `contract_found`: PASS [docs/PHASE66_PROMOTION_CHECKLIST.md:232 ("## Execution Arming State Contract v1")]
  - [PASS] `execution_enabled_false`: PASS [docs/PHASE66_PROMOTION_CHECKLIST.md:232 ("## Execution Arming State Contract v1")]
  - [PASS] `expected_linkage_present_once`: PASS [docs/PHASE66_PROMOTION_CHECKLIST.md:232 ("## Execution Arming State Contract v1")]
  - [PASS] `expiry_semantics`: PASS [docs/PHASE66_PROMOTION_CHECKLIST.md:80 ("## C. Deterministic Validation Order")]
  - [PASS] `future_linkage_drift`: PASS [docs/PHASE66_PROMOTION_CHECKLIST.md:232 ("## Execution Arming State Contract v1")]
  - [PASS] `hard_invariants_present`: PASS [docs/PHASE66_PROMOTION_CHECKLIST.md:42 ("## A. Hard Invariants")]
  - [PASS] `immutability_flags`: PASS [docs/PHASE66_PROMOTION_CHECKLIST.md:232 ("## Execution Arming State Contract v1")]
  - [PASS] `level_name_found`: PASS [docs/PHASE66_PROMOTION_CHECKLIST.md:36 ("## Phase 66 Status")]
  - [PASS] `negative_guarantees_present`: PASS [docs/PHASE66_PROMOTION_CHECKLIST.md:540 ("## Deterministic Negative Guarantees")]
  - [PASS] `preservation_clause_present`: PASS [docs/PHASE66_PROMOTION_CHECKLIST.md:191 ("## H. Explicit Preservation of Phases 27-65")]
  - [PASS] `priority_ordering_present`: PASS [docs/PHASE66_PROMOTION_CHECKLIST.md:232 ("## Execution Arming State Contract v1")]
  - [PASS] `rejection_codes_present`: PASS [docs/PHASE66_PROMOTION_CHECKLIST.md:118 ("## F. Deterministic Rejection Codes (with priority)")]
  - [PASS] `runtime_delta_none`: PASS [docs/PHASE66_PROMOTION_CHECKLIST.md:36 ("## Phase 66 Status")]
  - [PASS] `uniqueness_signal_present`: PASS [docs/PHASE66_PROMOTION_CHECKLIST.md:42 ("## A. Hard Invariants")]

### Phase 67 — Execution Eligibility Gate (PASS)

- File: `docs/PHASE67_PROMOTION_CHECKLIST.md`
- Contracts: `execution_eligibility.v1`
- Upstream phase refs (declared): 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66
- Linked IDs detected: `linked_execution_arming_state_id`
- Uniqueness signals: 5
- Rejection codes in section: 61
- Priority ordering required: yes; present: yes
- Findings:
  - [PASS] `authority_guarantees_all_false`: PASS [docs/PHASE67_PROMOTION_CHECKLIST.md:244 ("## Execution Eligibility Contract v1")]
  - [PASS] `contract_found`: PASS [docs/PHASE67_PROMOTION_CHECKLIST.md:244 ("## Execution Eligibility Contract v1")]
  - [PASS] `execution_enabled_false`: PASS [docs/PHASE67_PROMOTION_CHECKLIST.md:244 ("## Execution Eligibility Contract v1")]
  - [PASS] `expected_linkage_present_once`: PASS [docs/PHASE67_PROMOTION_CHECKLIST.md:244 ("## Execution Eligibility Contract v1")]
  - [PASS] `expiry_semantics`: PASS [docs/PHASE67_PROMOTION_CHECKLIST.md:81 ("## C. Deterministic Validation Order")]
  - [PASS] `future_linkage_drift`: PASS [docs/PHASE67_PROMOTION_CHECKLIST.md:244 ("## Execution Eligibility Contract v1")]
  - [PASS] `hard_invariants_present`: PASS [docs/PHASE67_PROMOTION_CHECKLIST.md:42 ("## A. Hard Invariants")]
  - [PASS] `immutability_flags`: PASS [docs/PHASE67_PROMOTION_CHECKLIST.md:244 ("## Execution Eligibility Contract v1")]
  - [PASS] `level_name_found`: PASS [docs/PHASE67_PROMOTION_CHECKLIST.md:36 ("## Phase 67 Status")]
  - [PASS] `negative_guarantees_present`: PASS [docs/PHASE67_PROMOTION_CHECKLIST.md:544 ("## Deterministic Negative Guarantees")]
  - [PASS] `preservation_clause_present`: PASS [docs/PHASE67_PROMOTION_CHECKLIST.md:202 ("## H. Explicit Preservation of Phases 27-66")]
  - [PASS] `priority_ordering_present`: PASS [docs/PHASE67_PROMOTION_CHECKLIST.md:244 ("## Execution Eligibility Contract v1")]
  - [PASS] `rejection_codes_present`: PASS [docs/PHASE67_PROMOTION_CHECKLIST.md:127 ("## F. Deterministic Rejection Codes (with priority)")]
  - [PASS] `runtime_delta_none`: PASS [docs/PHASE67_PROMOTION_CHECKLIST.md:36 ("## Phase 67 Status")]
  - [PASS] `uniqueness_signal_present`: PASS [docs/PHASE67_PROMOTION_CHECKLIST.md:42 ("## A. Hard Invariants")]

## Cross-Phase Inconsistencies and Naming Drift

- None detected by enum-name drift heuristic.

## Missing Priority Ordering Where Expected

- None.

## Missing Preservation Clauses

- None detected for phases requiring preservation checks.

## Authority False Guarantee Failures

- Phase 27: authority false guarantee failed (docs/PHASE27_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)) -> NOT_FOUND: contract yaml block missing
- Phase 28: authority false guarantee failed (docs/PHASE28_PROMOTION_CHECKLIST.md:1 (NOT_FOUND)) -> NOT_FOUND: contract yaml block missing
- Phase 29: authority false guarantee failed (docs/PHASE29_PROMOTION_CHECKLIST.md:46 ("## Inspection Result Binding Contract v1")) -> NOT_FOUND: authority_guarantees block missing
- Phase 30: authority false guarantee failed (docs/PHASE30_PROMOTION_CHECKLIST.md:73 ("## Delegation Envelope Contract v1 (Revised)")) -> NOT_FOUND: authority_guarantees block missing
- Phase 65: authority false guarantee failed (docs/PHASE65_PROMOTION_CHECKLIST.md:241 ("## Execution Arming Authorization Contract v1")) -> INVALID: non-constant boolean found in authority_guarantees
- Phase 66: authority false guarantee failed (docs/PHASE66_PROMOTION_CHECKLIST.md:232 ("## Execution Arming State Contract v1")) -> INVALID: non-constant boolean found in authority_guarantees

## Runtime Change Mentions

- Phase 30: INVALID: runtime delta is not none (none (specification-only)) [docs/PHASE30_PROMOTION_CHECKLIST.md:13 ("## Phase 30 Status")]
- Phase 31: INVALID: runtime delta is not none (none (specification-only)) [docs/PHASE31_PROMOTION_CHECKLIST.md:13 ("## Phase 31 Status")]

## Summary

- PASS: `4`
- FAIL: `37`

_Deterministic ordering rules: phases sorted numerically; findings sorted by check key;
cross-phase lists sorted lexicographically._
