"""
Test script for Agent Zero commands.
"""

import json
from commands import handle_command, status, check_updates, pending_approvals

def test_command_handler():
    """Test command handler functionality."""
    # Test status command
    result = handle_command("a0 status")
    print("a0 status result:")
    print(json.dumps(result, indent=2))
    print()
    
    # Test check-updates command
    result = handle_command("a0 check-updates")
    print("a0 check-updates result:")
    print(json.dumps(result, indent=2))
    print()
    
    # Test pending-approvals command
    result = handle_command("a0 pending-approvals")
    print("a0 pending-approvals result:")
    print(json.dumps(result, indent=2))
    print()
    
    # Test invalid command
    result = handle_command("a0 invalid-command")
    print("a0 invalid-command result:")
    print(json.dumps(result, indent=2))
    print()

if __name__ == "__main__":
    test_command_handler()