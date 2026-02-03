"""
State machine core for Agent Zero lifecycle management.

This module implements the core state machine for managing Agent Zero lifecycle,
including state transitions, validation, and enforcement of invariants.
"""

import json
import os
import time
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Dict, Any, Optional, List, Set, Union

from .fileops import (
    acquire_lock, 
    release_lock, 
    atomic_write,
    AtomicWriteError,
    LockAcquisitionError,
    IntegrityViolationError
)
from .audit import log_event, EVENT_TYPES
from .schema import (
    validate_json_schema, 
    SchemaValidationError
)

# Add new event types for state machine
EVENT_TYPES.extend([
    "state_transition", 
    "state_transition_denied",
    "atomic_write_failed",
    "state_corruption_detected",
    "state_initialized"
])

# Reason codes for state transitions
class ReasonCode(str, Enum):
    """Valid reason codes for state transitions."""
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_DENIED = "approval_denied"
    VALIDATION_ERROR = "validation_error" 
    INTEGRITY_VIOLATION = "integrity_violation"
    OPERATOR_RESET = "operator_reset"
    RETRY_REQUESTED = "retry_requested"
    CONFIRMATION_RECEIVED = "confirmation_received"
    HUMAN_CLEARED_FAILURE = "human_cleared_failure"
    INITIALIZATION = "initialization"  # Used only for first boot

# Allow string values for the enum
ReasonCode.__str__ = lambda self: self.value

# Allowed state values
class State(str, Enum):
    """Valid states for the Agent Zero lifecycle."""
    IDLE = "IDLE"
    STAGING = "STAGING"
    VALIDATING = "VALIDATING"
    PROMOTING = "PROMOTING"
    COMPLETE = "COMPLETE"
    ROLLING_BACK = "ROLLING_BACK"
    FAILED = "FAILED"
    FAILED_HARD = "FAILED_HARD"

# Allow string values for the enum
State.__str__ = lambda self: self.value

# Authority levels
class Authority(str, Enum):
    """Authority levels for Agent Zero lifecycle."""
    OBSERVER = "observer"
    EXECUTOR = "executor"

# Allow string values for the enum
Authority.__str__ = lambda self: self.value

# Operation types
class OperationType(str, Enum):
    """Types of operations that can be performed."""
    UPGRADE = "upgrade"
    ROLLBACK = "rollback"

# Allow string values for the enum
OperationType.__str__ = lambda self: self.value

# Schema for state.json
STATE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["current_state", "entered_at", "authority_level"],
    "properties": {
        "current_state": {
            "enum": [str(s) for s in State]
        },
        "entered_at": {
            "type": "string",
            "format": "date-time"
        },
        "previous_state": {
            "type": ["string", "null"]
        },
        "authority_level": {
            "enum": [str(a) for a in Authority]
        },
        "observed_state": {
            "type": "string",
            "enum": ["UNKNOWN", "CONSISTENT", "INCONSISTENT"],
            "default": "UNKNOWN"
        },
        "partial_validation": {
            "type": "boolean"
        },
        "active_operation": {
            "type": ["object", "null"],
            "properties": {
                "type": {
                    "enum": [str(t) for t in OperationType]
                },
                "target_version": {
                    "type": "string"
                },
                "started_at": {
                    "type": "string",
                    "format": "date-time"
                }
            }
        },
        "last_failure": {
            "type": ["object", "null"],
            "properties": {
                "state": {
                    "type": "string"
                },
                "error": {
                    "type": "string"
                },
                "occurred_at": {
                    "type": "string",
                    "format": "date-time"
                },
                "cleared": {
                    "type": "boolean"
                }
            }
        },
        "locks": {
            "type": "object",
            "properties": {
                "upgrade_locked": {
                    "type": "boolean"
                },
                "rollback_locked": {
                    "type": "boolean"
                },
                "lock_reason": {
                    "type": ["string", "null"]
                }
            }
        }
    },
    "additionalProperties": False
}

# Custom exceptions
class StateTransitionError(Exception):
    """Raised when a state transition is invalid."""
    pass

class AuthorityError(Exception):
    """Raised when an actor lacks sufficient authority."""
    pass

class StateCorruptionError(Exception):
    """Raised when the state.json file is corrupt."""
    pass

class LockedOperationError(Exception):
    """Raised when an operation is locked."""
    pass

# Define allowed state transitions
ALLOWED_TRANSITIONS = {
    State.IDLE: {State.STAGING, State.FAILED, State.FAILED_HARD},
    State.STAGING: {State.VALIDATING, State.FAILED},
    State.VALIDATING: {State.PROMOTING, State.FAILED},
    State.PROMOTING: {State.COMPLETE, State.ROLLING_BACK},
    State.COMPLETE: {State.IDLE},  # Only via confirmation
    State.ROLLING_BACK: {State.IDLE, State.FAILED_HARD},
    State.FAILED: {State.IDLE, State.STAGING},  # IDLE via clear-failure, STAGING via retry
    State.FAILED_HARD: set()  # No transitions allowed
}

# States that require active_operation
ACTIVE_OPERATION_STATES = {
    State.STAGING, State.VALIDATING, State.PROMOTING, State.ROLLING_BACK
}

def get_metadata_path() -> Path:
    """Returns the path to Agent Zero metadata directory."""
    return Path(__file__).parent / ".billy"

def get_state_path() -> Path:
    """Returns path to the state file."""
    return get_metadata_path() / "state.json"

class AgentZeroStateMachine:
    """
    State machine for Agent Zero lifecycle management.
    
    This class provides methods for managing the state machine, including
    state transitions, validation, and enforcement of invariants.
    """
    
    def __init__(self):
        """Initialize the state machine."""
        self._state_path = get_state_path()
        self._ensure_state_file()
    
    def _ensure_state_file(self):
        """
        Ensure the state file exists, creating it if necessary.
        
        This method also handles conversion from older state.json formats
        to the new format required by the schema.
        """
        # Initialize with IDLE state
        initial_state = {
            "current_state": str(State.IDLE),
            "entered_at": datetime.utcnow().isoformat() + "Z",
            "previous_state": None,
            "authority_level": str(Authority.OBSERVER),
            "observed_state": "UNKNOWN",
            "active_operation": None,
            "last_failure": None,
            "locks": {
                "upgrade_locked": False,
                "rollback_locked": False,
                "lock_reason": None
            }
        }
        
        try:
            # Create parent directory if needed
            os.makedirs(os.path.dirname(self._state_path), exist_ok=True)
            
            # Check if file exists and try to convert it if needed
            if self._state_path.exists():
                try:
                    with open(self._state_path, 'r') as f:
                        existing_state = json.load(f)
                    
                    # Convert from old format to new if necessary
                    if "state" in existing_state and "current_state" not in existing_state:
                        # This is the old format, convert it
                        existing_state["current_state"] = existing_state.pop("state")
                        
                    if "authority" in existing_state and "authority_level" not in existing_state:
                        # Convert authority field
                        existing_state["authority_level"] = existing_state.pop("authority")
                        
                    if "last_transition" in existing_state and "entered_at" not in existing_state:
                        # Convert timestamp field
                        existing_state["entered_at"] = existing_state.pop("last_transition")
                    
                    if "current_operation" in existing_state and "active_operation" not in existing_state:
                        # Convert operation field
                        existing_state["active_operation"] = existing_state.pop("current_operation")
                    
                    # Ensure all required fields are present
                    for key, value in initial_state.items():
                        if key not in existing_state:
                            existing_state[key] = value
                    
                    # Check if valid after conversion
                    try:
                        validate_json_schema(existing_state, STATE_SCHEMA)
                        # If valid, write the converted state
                        with open(self._state_path, 'w') as f:
                            json.dump(existing_state, f, indent=2)
                        return
                    except SchemaValidationError:
                        # If still invalid, recreate with initial state
                        pass
                    
                except (json.JSONDecodeError, KeyError):
                    # If parsing fails, recreate the file
                    pass
            
            # Write initial state
            with open(self._state_path, 'w') as f:
                json.dump(initial_state, f, indent=2)
            
            # Log initialization
            log_event("state_initialized", {
                "initial_state": initial_state
            })
        except Exception as e:
            # Log error and re-raise
            log_event("atomic_write_failed", {
                "error": str(e),
                "operation": "state_initialization"
            })
            raise
    
    def current(self) -> Dict[str, Any]:
        """
        Get the current state.
        
        Returns:
            Dict: Current state data
        
        Raises:
            StateCorruptionError: If the state file is corrupt
        """
        try:
            with open(self._state_path, 'r') as f:
                state_data = json.load(f)
            
            # Validate against schema
            try:
                validate_json_schema(state_data, STATE_SCHEMA)
                return state_data
            except SchemaValidationError as e:
                # Log corruption and raise
                log_event("state_corruption_detected", {
                    "error": str(e)
                })
                raise StateCorruptionError(f"State file is corrupt: {str(e)}")
        except json.JSONDecodeError as e:
            # Log corruption and raise
            log_event("state_corruption_detected", {
                "error": str(e)
            })
            raise StateCorruptionError(f"State file contains invalid JSON: {str(e)}")
        except FileNotFoundError:
            # This should not happen after _ensure_state_file
            self._ensure_state_file()
            return self.current()
    
    def current_state(self) -> State:
        """
        Get the current state enum value.
        
        Returns:
            State: Current state enum
        """
        state_data = self.current()
        return State(state_data["current_state"])
    
    def current_authority(self) -> Authority:
        """
        Get the current authority level.
        
        Returns:
            Authority: Current authority level
        """
        state_data = self.current()
        return Authority(state_data["authority_level"])
    
    def validate_transition(self, from_state: Union[State, str], to_state: Union[State, str]) -> None:
        """
        Validate a state transition.
        
        Args:
            from_state: Current state
            to_state: Target state
            
        Raises:
            StateTransitionError: If the transition is invalid
        """
        # Convert string values to State enum if needed
        if isinstance(from_state, str):
            from_state = State(from_state)
        
        if isinstance(to_state, str):
            to_state = State(to_state)
        
        # Check if the transition is allowed
        if to_state not in ALLOWED_TRANSITIONS.get(from_state, set()):
            allowed = ", ".join([str(s) for s in ALLOWED_TRANSITIONS.get(from_state, set())])
            raise StateTransitionError(
                f"Invalid transition: {from_state} → {to_state}. Allowed transitions: {allowed}"
            )
    
    def is_terminal(self) -> bool:
        """
        Check if the current state is terminal.
        
        Returns:
            bool: True if the current state is terminal
        """
        current = self.current_state()
        return current == State.FAILED_HARD
    
    def allowed_next_states(self) -> List[str]:
        """
        Get the list of allowed next states from the current state.
        
        Returns:
            List[str]: Allowed next states
        """
        current = self.current_state()
        return [str(s) for s in ALLOWED_TRANSITIONS.get(current, set())]
    
    def transition(self, 
                  to_state: Union[State, str], 
                  reason_code: Union[ReasonCode, str], 
                  actor: str = "billy_frame",
                  is_human: bool = False,
                  notes: Optional[str] = None,
                  metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Perform a state transition.
        
        Args:
            to_state: Target state
            reason_code: Reason for the transition
            actor: Actor performing the transition
            is_human: Whether the actor is human
            notes: Optional notes about the transition
            metadata: Optional additional metadata
            
        Returns:
            Dict: New state data
            
        Raises:
            StateTransitionError: If the transition is invalid
            AuthorityError: If the actor lacks sufficient authority
            LockedOperationError: If the operation is locked
            LockAcquisitionError: If the lock cannot be acquired
            AtomicWriteError: If the write fails
        """
        # Convert string values to enums if needed
        if isinstance(to_state, str):
            to_state = State(to_state)
        
        if isinstance(reason_code, str):
            reason_code = ReasonCode(reason_code)
        
        # Acquire lock
        lock_file = None
        
        try:
            # Get current state
            current_data = self.current()
            from_state = State(current_data["current_state"])
            
            # Validate transition
            self.validate_transition(from_state, to_state)
            
            # Check for COMPLETE → IDLE which requires human confirmation
            if from_state == State.COMPLETE and to_state == State.IDLE:
                if reason_code != ReasonCode.CONFIRMATION_RECEIVED or not is_human:
                    raise AuthorityError(
                        "COMPLETE → IDLE transition requires human confirmation"
                    )
            
            # Check for FAILED → IDLE which requires human intervention
            if from_state == State.FAILED and to_state == State.IDLE:
                if reason_code != ReasonCode.HUMAN_CLEARED_FAILURE or not is_human:
                    raise AuthorityError(
                        "FAILED → IDLE transition requires human intervention"
                    )
            
            # Check for locks
            locks = current_data.get("locks", {})
            if locks.get("upgrade_locked", False) and to_state == State.STAGING:
                raise LockedOperationError(
                    f"Upgrade operations are locked: {locks.get('lock_reason')}"
                )
            
            if locks.get("rollback_locked", False) and to_state == State.ROLLING_BACK:
                raise LockedOperationError(
                    f"Rollback operations are locked: {locks.get('lock_reason')}"
                )
            
            # Acquire lock for file operations
            lock_file = acquire_lock()
            
            # Create new state data
            new_state = current_data.copy()
            new_state["current_state"] = str(to_state)
            new_state["previous_state"] = str(from_state)
            new_state["entered_at"] = datetime.utcnow().isoformat() + "Z"
            
            # Handle active_operation
            if to_state in ACTIVE_OPERATION_STATES:
                # Ensure active_operation is set for appropriate states
                if not new_state.get("active_operation"):
                    # For Phase 3, we use placeholder data since we're not executing
                    new_state["active_operation"] = {
                        "type": str(OperationType.UPGRADE),  # Default for Phase 3
                        "target_version": "unknown",  # Placeholder
                        "started_at": datetime.utcnow().isoformat() + "Z"
                    }
                    
                    # If metadata contains operation details, use them
                    if metadata and "operation" in metadata:
                        op_data = metadata["operation"]
                        if "type" in op_data:
                            new_state["active_operation"]["type"] = op_data["type"]
                        if "target_version" in op_data:
                            new_state["active_operation"]["target_version"] = op_data["target_version"]
            elif to_state not in {State.COMPLETE, State.ROLLING_BACK}:
                # Clear active_operation for non-active states except COMPLETE and ROLLING_BACK
                new_state["active_operation"] = None
            
            # Handle failures
            if to_state == State.FAILED or to_state == State.FAILED_HARD:
                new_state["last_failure"] = {
                    "state": str(from_state),
                    "error": str(notes) if notes else f"Failed during {from_state}",
                    "occurred_at": datetime.utcnow().isoformat() + "Z",
                    "cleared": False
                }
            
            # Handle clearing failures
            if from_state == State.FAILED and to_state == State.IDLE:
                if new_state.get("last_failure"):
                    new_state["last_failure"]["cleared"] = True
            
            # Write new state atomically
            atomic_write(self._state_path, new_state, STATE_SCHEMA)
            
            # Log transition
            log_event("state_transition", {
                "from": str(from_state),
                "to": str(to_state),
                "reason_code": str(reason_code),
                "notes": notes,
                "authority_level": current_data["authority_level"],
                "actor": actor,
                "is_human": is_human
            })
            
            return new_state
            
        except (StateTransitionError, AuthorityError, LockedOperationError) as e:
            # Log denied transition
            log_event("state_transition_denied", {
                "from": str(from_state) if 'from_state' in locals() else "UNKNOWN",
                "to": str(to_state),
                "reason_code": str(reason_code),
                "error": str(e),
                "actor": actor,
                "is_human": is_human
            })
            raise
            
        except Exception as e:
            # Log other errors
            if 'from_state' in locals() and 'to_state' in locals():
                log_event("atomic_write_failed", {
                    "from": str(from_state),
                    "to": str(to_state),
                    "error": str(e)
                })
            raise
            
        finally:
            # Release lock
            release_lock(lock_file)
    
    def explain_state(self) -> Dict[str, Any]:
        """
        Provide a detailed explanation of the current state.
        
        Returns:
            Dict: Explanation of current state, including:
                - Current state and why it was entered
                - Active invariants
                - Possible next states
                - Blocked actions
        """
        current_data = self.current()
        current_state = State(current_data["current_state"])
        authority = Authority(current_data["authority_level"])
        
        # Define base explanation structure
        explanation = {
            "current_state": str(current_state),
            "entered_at": current_data["entered_at"],
            "previous_state": current_data.get("previous_state"),
            "authority_level": str(authority),
            "possible_next_states": self.allowed_next_states(),
            "blocked_actions": [],
            "active_invariants": [],
            "active_operation": current_data.get("active_operation")
        }
        
        # Add invariants
        explanation["active_invariants"].append("no concurrent transitions permitted")
        
        if current_state in ACTIVE_OPERATION_STATES:
            explanation["active_invariants"].append("active_operation must not be null")
        
        if current_state == State.FAILED_HARD:
            explanation["active_invariants"].append("requires human intervention to recover")
        
        # Add blocked actions
        if authority == Authority.OBSERVER:
            explanation["blocked_actions"].append("Execution (observer authority)")
        
        if current_state == State.FAILED_HARD:
            explanation["blocked_actions"].append("All operations (FAILED_HARD state)")
        
        if current_state == State.COMPLETE:
            explanation["blocked_actions"].append("Auto-transition (requires human confirmation)")
        
        # Add state-specific information
        if current_state == State.IDLE:
            explanation["blocked_actions"].append("Promotion (not in upgrade lifecycle)")
        
        elif current_state == State.STAGING:
            explanation["blocked_actions"].append("Promotion (validation required)")
        
        elif current_state == State.VALIDATING:
            explanation["blocked_actions"].append("Promotion (validation incomplete)")
        
        elif current_state == State.PROMOTING:
            # No specific blocks
            pass
        
        elif current_state == State.COMPLETE:
            explanation["blocked_actions"].append("Idle transition (requires confirmation)")
        
        elif current_state == State.ROLLING_BACK:
            # No specific blocks
            pass
        
        elif current_state == State.FAILED:
            explanation["blocked_actions"].append("Operations (failure state)")
        
        elif current_state == State.FAILED_HARD:
            explanation["blocked_actions"].append("All operations (critical failure)")
        
        return explanation