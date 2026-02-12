"""
Direct test for Agent Zero commands without using BillyRuntime.
This avoids dependencies like OpenAI that might not be installed.
"""

import json
import os
import sys

# Add project root to Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from v2.agent_zero.commands import handle_command

def test_a0_commands():
    """Test Agent Zero commands directly."""
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
    test_a0_commands()