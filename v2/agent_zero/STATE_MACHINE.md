# Agent Zero State Machine

This document describes the state machine core for Agent Zero lifecycle management implemented in Phase 3.

## Overview

The state machine establishes an authoritative lifecycle with enforced invariants, atomic transitions, and full auditability. It allows recording of lifecycle intent and bookkeeping but prohibits actual execution of upgrades or rollbacks.

## State Diagram

```
IDLE
 ├─▶ STAGING
 ├─▶ FAILED
 └─▶ FAILED_HARD

STAGING
 ├─▶ VALIDATING
 └─▶ FAILED

VALIDATING
 ├─▶ PROMOTING
 └─▶ FAILED

PROMOTING
 ├─▶ COMPLETE
 └─▶ ROLLING_BACK

COMPLETE
 └─▶ IDLE (via a0 confirm OR explicit reset only)

ROLLING_BACK
 ├─▶ IDLE
 └─▶ FAILED_HARD

FAILED
 ├─▶ IDLE (via a0 clear-failure)
 └─▶ STAGING (re-attempt after approval)

FAILED_HARD
 └─▶ (NO EXIT — human intervention only)
```

## State File Schema

The state machine is defined by the `state.json` file in the `.billy/` directory with the following schema:

```json
{
  "current_state": "IDLE",
  "entered_at": "ISO-8601 timestamp",
  "previous_state": "previous state or null",
  "authority_level": "observer",
  "observed_state": "UNKNOWN",
  "active_operation": {
    "type": "upgrade or rollback",
    "target_version": "version string",
    "started_at": "ISO-8601 timestamp"
  },
  "last_failure": {
    "state": "state where failure occurred",
    "error": "error description",
    "occurred_at": "ISO-8601 timestamp",
    "cleared": false
  },
  "locks": {
    "upgrade_locked": false,
    "rollback_locked": false,
    "lock_reason": null
  }
}
```

## Reason Codes

Every state transition must include a reason code:

- `approval_granted` - Transition occurred because approval was granted
- `approval_denied` - Transition occurred because approval was denied
- `validation_error` - Transition occurred due to a validation error
- `integrity_violation` - Transition occurred due to an integrity violation
- `operator_reset` - Transition was requested by an operator
- `retry_requested` - Transition occurred because a retry was requested
- `confirmation_received` - Transition occurred because confirmation was received
- `human_cleared_failure` - Transition occurred because a human cleared a failure

## Invariants

The following invariants are enforced by the state machine:

1. **Single state only** - No concurrent transitions
2. `active_operation != null` **iff** state ∈ {STAGING, VALIDATING, PROMOTING, ROLLING_BACK}
3. `FAILED_HARD` locks **all operations**
4. `observer` authority may record lifecycle intent but **may not initiate or confirm real-world execution**
5. Every transition → **audit log entry**
6. State writes are schema-validated and atomic
7. Corrupt `state.json` → immediate `FAILED_HARD`
8. State transitions are idempotent

## Command Reference

### `a0 status`

Enhanced to include state machine information:

```
State Machine:
  Current State:        VALIDATING
  Previous State:       STAGING
  Entered At:           2026-02-01T14:22:09Z
  Observed State:       UNKNOWN
  Authority Level:      observer

Active Operation:
  Type:                 upgrade
  Target Version:       v0.9.8
  Started At:           2026-02-01T14:20:15Z

Locks:
  Upgrade Locked:       false
  Rollback Locked:      false
```

### `a0 explain-state`

Provides a detailed explanation of the current state, including invariants and possible next states:

```
Current State: VALIDATING
Entered At: 2026-02-01T14:22:09Z
Reason: approval_granted
Authority Level: observer

Active Operation:
- Upgrade to v0.9.8 (requested)

Blocked Actions:
- Execution (observer authority)
- Promotion (validation incomplete)

Possible Next States:
- PROMOTING (requires executor authority)
- FAILED (on validation error)

Invariants Active:
- active_operation must not be null
- no concurrent transitions permitted
```

### `a0 clear-failure`

Clears a failure state, transitioning from FAILED to IDLE. Requires human authority.

### `a0 confirm`

Confirms the completion of an operation, transitioning from COMPLETE to IDLE. Requires human authority.

## Audit Logging

All state transitions are logged to `upgrade_history.log` with the following structure:

```json
{
  "timestamp": "ISO-8601",
  "event_type": "state_transition",
  "actor": "billy_frame",
  "details": {
    "from": "VALIDATING",
    "to": "FAILED",
    "reason_code": "validation_error",
    "notes": "checksum mismatch detected",
    "authority_level": "observer"
  }
}
```

## Usage Examples

### Transition to STAGING after approval

```python
sm = AgentZeroStateMachine()
sm.transition(
    to_state=State.STAGING,
    reason_code=ReasonCode.APPROVAL_GRANTED,
    notes="Approval granted for v0.9.8",
    metadata={
        "operation": {
            "type": str(OperationType.UPGRADE),
            "target_version": "v0.9.8"
        }
    }
)
```

### Clear a failure

```
a0 clear-failure
```

### Confirm an operation

```
a0 confirm
```

## Security Features

1. **Observer Constraints**
   - No execution of real-world operations
   - No self-escalation of authority
   - No commits, rollbacks, or filesystem changes

2. **Human-Only Operations**
   - Only humans can clear failures
   - Only humans can confirm operations
   - Approval workflow requires human intervention

3. **Integrity Protection**
   - Schema validation for state file
   - Atomic writes with temporary files
   - Detection of corruption

## Implementation Files

- `state_machine.py`: Core state machine implementation
- `commands.py`: Command handler integration
- `test_state_machine.py`: Test suite
- `demo_state_machine.py`: Demo script