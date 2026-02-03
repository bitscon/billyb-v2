"""
Demo script for Phase 3 state machine.

This script demonstrates the state machine functionality by:
1. Initializing the state machine
2. Displaying the current state
3. Performing valid state transitions
4. Attempting invalid transitions
5. Explaining the state
6. Clearing failures and confirming operations
7. Showcasing invariant enforcement
"""

import os
import json
import time
import sys
from pathlib import Path
from datetime import datetime

# Add project root to Python path to allow relative imports
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from v2.agent_zero.state_machine import (
    AgentZeroStateMachine,
    State,
    Authority,
    ReasonCode,
    OperationType,
    StateTransitionError,
    AuthorityError
)
from v2.agent_zero.commands import (
    status,
    explain_state,
    clear_failure,
    confirm,
    handle_command
)


def print_separator(title):
    """Print a separator with title."""
    print(f"\n{'=' * 20} {title} {'=' * 20}\n")


def print_json(data):
    """Print JSON data in a readable format."""
    print(json.dumps(data, indent=2))


def run_demo():
    """Run the state machine demo."""
    print_separator("Agent Zero Phase 3: State Machine Demo")
    
    # Create state machine
    sm = AgentZeroStateMachine()
    
    # Display initial state
    print("Initial state:")
    print_json(sm.current())
    
    # Get status via command
    print_separator("Status Command")
    result = status()
    print_json(result)
    
    # Explain state via command
    print_separator("Explain State Command")
    result = explain_state()
    print_json(result["explanation"])
    
    # Perform valid transitions
    print_separator("Valid State Transitions")
    
    try:
        print("Transitioning: IDLE → STAGING")
        sm.transition(
            to_state=State.STAGING,
            reason_code=ReasonCode.APPROVAL_GRANTED,
            notes="Demo transition",
            metadata={
                "operation": {
                    "type": str(OperationType.UPGRADE),
                    "target_version": "v0.9.8"
                }
            }
        )
        print("Current state:", sm.current_state())
        
        print("\nTransitioning: STAGING → VALIDATING")
        sm.transition(
            to_state=State.VALIDATING,
            reason_code=ReasonCode.APPROVAL_GRANTED,
            notes="Demo transition"
        )
        print("Current state:", sm.current_state())
        
        print("\nTransitioning: VALIDATING → PROMOTING")
        sm.transition(
            to_state=State.PROMOTING,
            reason_code=ReasonCode.APPROVAL_GRANTED,
            notes="Demo transition"
        )
        print("Current state:", sm.current_state())
        
        print("\nTransitioning: PROMOTING → COMPLETE")
        sm.transition(
            to_state=State.COMPLETE,
            reason_code=ReasonCode.APPROVAL_GRANTED,
            notes="Demo transition"
        )
        print("Current state:", sm.current_state())
    
    except Exception as e:
        print(f"Error during transitions: {e}")
    
    # Attempt invalid transition
    print_separator("Invalid State Transitions")
    
    try:
        print("Attempting invalid transition: COMPLETE → STAGING")
        sm.transition(
            to_state=State.STAGING,
            reason_code=ReasonCode.APPROVAL_GRANTED,
            notes="Demo invalid transition"
        )
    except StateTransitionError as e:
        print(f"Expected error: {e}")
    
    # Attempt transition without proper authority
    print_separator("Authority Enforcement")
    
    try:
        print("Attempting COMPLETE → IDLE without confirmation")
        sm.transition(
            to_state=State.IDLE,
            reason_code=ReasonCode.OPERATOR_RESET,  # Not confirmation
            notes="Demo invalid authority"
        )
    except AuthorityError as e:
        print(f"Expected error: {e}")
    
    # Confirm operation properly
    print_separator("Confirm Command")
    
    print("Executing: a0 confirm")
    result = handle_command("a0 confirm")
    print_json(result)
    print("Current state:", sm.current_state())
    
    # Transition to FAILED for demonstration
    print_separator("Failure Handling")
    
    try:
        print("Transitioning: IDLE → STAGING → FAILED")
        sm.transition(
            to_state=State.STAGING,
            reason_code=ReasonCode.APPROVAL_GRANTED,
            notes="Demo transition"
        )
        sm.transition(
            to_state=State.FAILED,
            reason_code=ReasonCode.VALIDATION_ERROR,
            notes="Demo failure"
        )
        print("Current state:", sm.current_state())
        
        # Show current state data
        print("\nCurrent state data:")
        print_json(sm.current())
    
    except Exception as e:
        print(f"Error during transitions: {e}")
    
    # Clear failure
    print_separator("Clear Failure Command")
    
    print("Executing: a0 clear-failure")
    result = handle_command("a0 clear-failure")
    print_json(result)
    print("Current state:", sm.current_state())
    
    print_separator("Audit Log")
    
    # In a real implementation, we would display the audit log here
    # For this demo, we'll just mention it
    print("The following events have been logged to upgrade_history.log:")
    print("- state_initialized")
    print("- state_transition (for each transition)")
    print("- state_transition_denied (for invalid transitions)")
    
    print_separator("Demo Complete")


if __name__ == "__main__":
    run_demo()