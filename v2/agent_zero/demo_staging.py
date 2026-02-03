"""
Demo script for Phase 4A staging execution.

This script demonstrates the staging functionality by:
1. Checking staging status
2. Listing existing artifacts
3. Simulating the staging workflow (dry run)
4. Showing how staging would work in a real scenario
"""

import os
import json
import sys
from pathlib import Path

# Add project root to Python path to allow relative imports
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from v2.agent_zero import commands
from v2.agent_zero.state_machine import AgentZeroStateMachine


def print_separator(title):
    """Print a separator with title."""
    print(f"\n{'=' * 20} {title} {'=' * 20}\n")


def print_json(data):
    """Print JSON data in a readable format."""
    print(json.dumps(data, indent=2))


def run_demo():
    """Run the staging demo."""
    print_separator("Agent Zero Phase 4A: Staging Execution Demo")
    
    # Check current state
    print("Current state:")
    sm = AgentZeroStateMachine()
    print_json(sm.current())
    
    # Check staging status
    print_separator("Staging Status")
    result = commands.handle_command("a0 staging-status")
    print_json(result)
    
    # List artifacts
    print_separator("Existing Artifacts")
    result = commands.handle_command("a0 list-artifacts")
    print_json(result)
    
    # Show what would happen with begin-staging (dry run)
    print_separator("Dry Run: Begin Staging")
    print("This would execute: a0 begin-staging v0.9.8 --dry-run")
    print("\nNote: In a real scenario, this would:")
    print("  1. Generate a build ID")
    print("  2. Create a temp directory: /tmp/agent_zero_build_<uuid>")
    print("  3. Clone the repository from GitHub")
    print("  4. Install dependencies in a virtualenv")
    print("  5. Compute checksums for all files")
    print("  6. Move the build to .billy/artifacts/v0.9.8/")
    print("  7. Create manifest.json with build metadata")
    print("  8. Transition state machine: IDLE → STAGING → VALIDATING")
    print("  9. Clean up the temp directory")
    
    print("\nBecause this is a demo and we don't want to actually clone")
    print("from GitHub (which requires network access and takes time),")
    print("we're showing what the command structure looks like.")
    
    # Show command format
    print_separator("Command Reference")
    print("Available staging commands:")
    print("  • a0 begin-staging <version> [--rebuild] [--dry-run]")
    print("  • a0 staging-status")
    print("  • a0 list-artifacts")
    print("  • a0 cleanup-artifacts [--keep N]")
    
    print("\nSecurity constraints:")
    print("  • Production tree (v2/agent_zero/) is NEVER touched")
    print("  • All work happens in /tmp/agent_zero_build_* and .billy/artifacts/")
    print("  • Staging requires executor authority + human approval")
    print("  • Failures always clean up temp directories")
    print("  • All operations are fully audited")
    
    print_separator("Demo Complete")


if __name__ == "__main__":
    run_demo()