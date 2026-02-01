"""
Test script for Agent Zero integration with BillyRuntime.
"""

import json
import sys
import os

# Add project root to Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from v2.core.runtime import BillyRuntime

def test_a0_commands_integration():
    """Test Agent Zero commands integration with BillyRuntime."""
    runtime = BillyRuntime()
    
    # Test status command
    response = runtime.ask("a0 status")
    print("BillyRuntime - a0 status response:")
    print(response)
    print()
    
    # Test check-updates command
    response = runtime.ask("a0 check-updates")
    print("BillyRuntime - a0 check-updates response:")
    print(response)
    print()
    
    # Test pending-approvals command
    response = runtime.ask("a0 pending-approvals")
    print("BillyRuntime - a0 pending-approvals response:")
    print(response)
    print()
    
    # Test with non-a0 command (should use LLM)
    print("BillyRuntime - non-a0 command:")
    print("(This would normally call the LLM, but we don't test that here)")

if __name__ == "__main__":
    test_a0_commands_integration()