# Phase 29 Promotion Checklist

## Purpose
This checklist defines the freeze gate for Level 29 (`Inspection Dispatch Boundary`).

Phase 29 promotion is blocked until each criterion below is satisfied with specification evidence and explicit human acceptance.

## Scope
Phase 29 is specification-only infrastructure that formalizes how inspection results can be consumed by downstream reasoning.

No runtime behavior, tools, policy authority, execution authority, or delegation authority is expanded in this phase.

## Phase 29 Status
- Level 29 status: frozen baseline (specification-only by design)
- Frozen tag: `maturity-level-29`
- Previous frozen tag: `maturity-level-28`
- Runtime delta: none


## ACI Minimum Compliance Profile Normalization
This addendum normalizes this phase document to the ACI minimum compliance profile without changing phase intent or runtime behavior.

## Hard Invariants
- [x] This phase remains specification-only and non-executing.
- [x] All authority guarantees are fixed to `false`.
- [x] `execution_enabled` remains `false`.
- [x] Contract records are append-only and immutable after issuance.

## Deterministic Validation Order
- [x] Step 1: Validate normalized schema completeness.
- [x] Step 2: Validate `authority_guarantees` are constant `false`.
- [x] Step 3: Validate immutability guarantees (`append_only=true`, mutation flags `false`).
- [x] Step 4: Validate explicit preservation clause coverage.
- [x] Step 5: Validate time window (`issued_at < expires_at`); otherwise reject `TIME_WINDOW_INVALID`.
- [x] Step 6: Apply deterministic rejection-code priority ordering.

## Deterministic Rejection Codes (with priority ordering)
- [x] `NOT_FOUND`
- [x] `SCHEMA_INVALID`
- [x] `AUTHORITY_FALSE_GUARANTEE_VIOLATION`
- [x] `EXECUTION_ENABLED_VIOLATION`
- [x] `IMMUTABILITY_GUARANTEE_VIOLATION`
- [x] `TIME_WINDOW_INVALID`
- [x] `PRESERVATION_CLAUSE_MISSING`

## Explicit Preservation of Prior Phases
- [x] Phases 27-28 are explicitly preserved with no authority escalation.

## Worked Valid and Invalid Examples
- [x] Valid: normalized artifact contains explicit all-false authority guarantees, `execution_enabled=false`, immutable append-only settings, and valid time window.
- [x] Invalid: artifact omits `authority_guarantees` or sets any authority flag to non-false value; reject deterministically.

## Normalized Contract v1
```yaml
contract: inspection_result_binding.v1
type: object
additionalProperties: false
required:
  - phase
  - record_id
  - issued_at
  - expires_at
  - execution_enabled
  - authority_guarantees
  - immutability_guarantees
  - rejection_priority_order_schema
properties:
  phase:
    const: 29
  record_id:
    type: string
    minLength: 1
  issued_at:
    type: string
    format: date-time
  expires_at:
    type: string
    format: date-time
  execution_enabled:
    const: false
  authority_guarantees:
    type: object
    additionalProperties: false
    properties:
      can_execute:
        const: false
      can_authorize:
        const: false
      can_arm:
        const: false
      can_attempt_execution:
        const: false
      can_mutate_runtime:
        const: false
      can_escalate_authority:
        const: false
  immutability_guarantees:
    type: object
    additionalProperties: false
    properties:
      append_only:
        const: true
      mutable_after_write:
        const: false
      overwrite_allowed:
        const: false
      delete_allowed:
        const: false
  rejection_priority_order_schema:
    type: array
    minItems: 1
    items:
      type: string
      minLength: 1
validation_rules:
  - issued_at < expires_at
rejection_code_priority_order:
  - NOT_FOUND
  - SCHEMA_INVALID
  - AUTHORITY_FALSE_GUARANTEE_VIOLATION
  - EXECUTION_ENABLED_VIOLATION
  - IMMUTABILITY_GUARANTEE_VIOLATION
  - TIME_WINDOW_INVALID
  - PRESERVATION_CLAUSE_MISSING
```

## Deterministic Negative Guarantees
- [x] No execution is performed in this phase.
- [x] No arming, scheduling, callbacks, retries, or autonomous branching are enabled.
- [x] No implicit authority is created from context, status, or prior artifacts.
- [x] No runtime behavior change is introduced by this document.

## A. Hard Inspection Dispatch Invariants
- [x] Inspection outputs are inert data unless explicitly bound through a structured inspection-result binding.
  Evidence target: `docs/PHASE29_PROMOTION_CHECKLIST.md` (Inspection Result Binding Contract v1)
- [x] Inspection-to-reasoning handoff requires explicit structured references and cannot occur implicitly.
  Evidence target: `docs/PHASE29_PROMOTION_CHECKLIST.md` (Routing Boundary Rules)
- [x] Binding is caller-bound with explicit ownership, scope, and lifetime constraints.
  Evidence target: `docs/PHASE29_PROMOTION_CHECKLIST.md` (Inspection Result Binding Contract v1)
- [x] Unbound, expired, mismatched-owner, and out-of-scope bindings are rejected deterministically.
  Evidence target: `docs/PHASE29_PROMOTION_CHECKLIST.md` (Worked Examples, Boundary Failure Modes)

## B. Routing Boundary Rules
- [x] Conversation -> Inspection remains Phase 28 structured-intent-only behavior.
  Evidence target: `README.md`, `MATURITY.md`, `ONBOARDING.md`
- [x] Inspection -> Reasoning requires explicit binding (`inspection_result_id` + immutable payload reference).
  Evidence target: `docs/PHASE29_PROMOTION_CHECKLIST.md` (Inspection Result Binding Contract v1)
- [x] No inspection data is auto-injected into prompts, memory, or interpreter state.
  Evidence target: `README.md`, `MATURITY.md`, `STATE.md`, `STATUS.md`, `ONBOARDING.md`
- [x] Inspection results cannot auto-trigger summarization, planning, transformation, delegation, or execution.
  Evidence target: `README.md`, `MATURITY.md`, `docs/PHASE29_PROMOTION_CHECKLIST.md` (Negative Guarantees)

## C. Negative Guarantees
- [x] Inspection results cannot escalate authority.
- [x] Inspection results cannot trigger execution or additional tool invocation.
- [x] Inspection results cannot be auto-summarized.
- [x] Inspection results cannot be silently persisted.
- [x] Inspection results cannot be reused across turns without explicit rebinding.

## Inspection Result Binding Contract v1
```yaml
contract: inspection_result_binding.v1
type: object
additionalProperties: false
required:
  - inspection_result_id
  - source_tool
  - payload_ref
  - owner
  - scope
  - lifetime
  - consumer
properties:
  inspection_result_id:
    type: string
    minLength: 1
    description: Stable caller-visible identifier of a previously returned inspection result.
  source_tool:
    type: string
    enum: [inspect_file, inspect_directory]
    description: Source inspection capability that produced the result payload.
  payload_ref:
    type: object
    additionalProperties: false
    required: [payload_hash_sha256, bytes, created_at]
    properties:
      payload_hash_sha256:
        type: string
        pattern: "^[a-f0-9]{64}$"
      bytes:
        type: integer
        minimum: 0
      created_at:
        type: string
        format: date-time
    description: Immutable payload identity and provenance; hash mismatch invalidates binding.
  owner:
    type: object
    additionalProperties: false
    required: [caller_id, session_id]
    properties:
      caller_id:
        type: string
        minLength: 1
      session_id:
        type: string
        minLength: 1
    description: Binding owner; mismatches are rejected.
  scope:
    type: string
    enum: [single_turn, session_scoped]
    description: Allowed consumption boundary for this binding.
  lifetime:
    type: object
    additionalProperties: false
    required: [expires_at, reusable]
    properties:
      expires_at:
        type: string
        format: date-time
      reusable:
        type: boolean
    description: Explicit expiry and reuse policy; no implicit persistence.
  consumer:
    type: object
    additionalProperties: false
    required: [consumer_type, operation]
    properties:
      consumer_type:
        type: string
        enum: [reasoning]
      operation:
        type: string
        enum: [analysis_only]
    description: Only analysis-only reasoning consumption is permitted in Phase 29.
inertness_rule:
  description: Unbound inspection outputs MUST be treated as inert data and MUST NOT influence downstream reasoning.
```

## Worked Examples
- [x] Example A (valid): A caller provides a matching `inspection_result_id`, immutable `payload_ref`, owner/session match, unexpired `session_scoped` binding, and `consumer.operation=analysis_only`; reasoning consumption is permitted.
- [x] Example B (rejection): A caller references inspection text in natural language without structured binding; reject with `BINDING_REQUIRED`.
- [x] Example C (rejection): Binding exists but `lifetime.expires_at` is past current time; reject with `BINDING_EXPIRED`.
- [x] Example D (rejection): `owner.caller_id` or `owner.session_id` mismatches current caller/session; reject with `OWNER_SCOPE_MISMATCH`.
- [x] Example E (rejection): Prior-turn inspection result is reused without explicit rebinding; reject with `REBIND_REQUIRED`.

## Boundary Failure Modes
- [x] Unknown `inspection_result_id` -> reject with `UNKNOWN_INSPECTION_RESULT`.
- [x] `payload_ref.payload_hash_sha256` mismatch -> reject with `PAYLOAD_HASH_MISMATCH`.
- [x] Binding scope exceeded (single-turn consumed outside allowed turn) -> reject with `SCOPE_EXCEEDED`.
- [x] `consumer.consumer_type` not allowed -> reject with `CONSUMER_NOT_ALLOWED`.
- [x] `consumer.operation` not `analysis_only` -> reject with `OPERATION_NOT_ALLOWED`.

## Phase Interaction Guarantees
- [x] Phase 27 preserved: conversational input remains non-authoritative and cannot implicitly route inspection data into authority paths.
- [x] Phase 28 preserved: inspection remains read-only, non-mutating, bounded, and non-escalating.
- [x] Phase 29 does not enable execution, delegation, automatic summarization, automatic planning, automatic transformation, or automatic persistence.

## Freeze Hygiene
- [x] `MATURITY.md`, `README.md`, `STATE.md`, `STATUS.md`, and `ONBOARDING.md` are synchronized for Level 29 freeze.
- [x] Phase 29 promotion artifact is present at `docs/PHASE29_PROMOTION_CHECKLIST.md`.
- [x] Phase 29 is documented as specification-only and frozen by design.
- [x] No production code changes were introduced as part of this freeze.
- [x] No tests were added or modified as part of this freeze.
- [x] Human freeze acceptance placeholders are present for operator completion.

## Evidence Checklist
- Specification artifact:
  - `docs/PHASE29_PROMOTION_CHECKLIST.md`
- Maturity/status sync:
  - `MATURITY.md`
  - `README.md`
  - `STATE.md`
  - `STATUS.md`
  - `ONBOARDING.md`
- Review commands:
  - `git diff -- docs/PHASE29_PROMOTION_CHECKLIST.md MATURITY.md README.md STATE.md STATUS.md ONBOARDING.md`
  - `git status --short`

## Freeze Acceptance Record (Required)
- Approved by: `<maintainer_name>`
- Date: `<YYYY-MM-DD>`
- Evidence bundle: `<paths_or_commit_ids>`
- Review notes: `<summary_of_checks>`
- Freeze decision: `<ACCEPTED|REJECTED>`
