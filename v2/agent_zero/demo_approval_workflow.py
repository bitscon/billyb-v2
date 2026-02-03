"""
Demo script for Phase 2 approval workflow.

This script demonstrates the approval workflow by:
1. Requesting an upgrade
2. Viewing pending approvals
3. Approving the upgrade
4. Verifying no execution side effects
"""

import os
import json
import sys
from pathlib import Path
import unittest.mock
import urllib.request

# Add project root to Python path to allow relative imports
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from v2.agent_zero import commands
from v2.agent_zero.fileops import get_metadata_path
from v2.agent_zero.github import get_github_release


def mock_github_api():
    """Mock GitHub API for the demo."""
    mock_response = json.dumps({
        "tag_name": "v0.9.8",
        "html_url": "https://github.com/frdel/agent-zero/releases/tag/v0.9.8",
        "draft": False,
        "prerelease": False,
        "assets": [{"name": "agent-zero.zip"}]
    }).encode("utf-8")
    
    class MockResponse:
        def __init__(self):
            self.data = mock_response
        def read(self):
            return self.data
        def __enter__(self):
            return self
        def __exit__(self, type, value, traceback):
            pass
    
    # Apply patch to urllib.request.urlopen
    return unittest.mock.patch(
        "urllib.request.urlopen", 
        return_value=MockResponse()
    )


def run_demo():
    """Run approval workflow demo."""
    metadata_path = get_metadata_path()
    
    # Ensure .billy directory exists
    os.makedirs(metadata_path, exist_ok=True)
    
    # Ensure version.json exists
    version_path = metadata_path / "version.json"
    if not version_path.exists():
        with open(version_path, "w") as f:
            json.dump(
                {
                    "version": "v0.9.7",
                    "installed_at": "2026-02-01T00:00:00Z",
                    "installed_by": "billy_frame",
                    "source": "https://github.com/frdel/agent-zero/releases/tag/v0.9.7",
                    "checksum": "0000000000000000000000000000000000000000000000000000000000000000"
                },
                f, indent=2
            )
    
    # Ensure state.json exists
    state_path = metadata_path / "state.json"
    if not state_path.exists():
        with open(state_path, "w") as f:
            json.dump(
                {
                    "state": "IDLE",
                    "last_transition": "2026-02-01T00:00:00Z",
                    "authority": "observer",
                    "current_operation": None
                },
                f, indent=2
            )
    
    # Ensure upgrade_history.log exists
    log_path = metadata_path / "upgrade_history.log"
    if not log_path.exists():
        with open(log_path, "w") as f:
            pass
    
    # Delete existing pending_approval.json if it exists
    pending_path = metadata_path / "pending_approval.json"
    if pending_path.exists():
        os.unlink(pending_path)
    
    print("===== Agent Zero Phase 2: Approval Workflow Demo =====\n")
    
    # Check version
    print("Current version:")
    with open(version_path, "r") as f:
        version_data = json.load(f)
    
    print(f"  {version_data['version']}")
    print()
    
    # Mock GitHub API for the demo
    with mock_github_api():
        # Request upgrade
        print("1. Requesting upgrade to v0.9.8:")
        result = commands.handle_command("a0 request-upgrade v0.9.8")
        print(f"  {result['status']}: {result.get('message', result.get('error', 'Unknown'))}")
        print()
        
        # View pending approvals
        print("2. Pending approvals:")
        result = commands.handle_command("a0 pending-approvals")
        if result["status"] == "success" and result.get("pending_approvals"):
            for approval in result["pending_approvals"]:
                print(f"  Version: {approval['version']}")
                print(f"  Requested by: {approval['requested_by']}")
                print(f"  GitHub: {approval['github_release_url']}")
        else:
            print(f"  {result['status']}: {result.get('message', result.get('error', 'No pending approvals'))}")
        print()
        
        # Approve upgrade
        print("3. Approving upgrade (human authority required):")
        result = commands.handle_command("approve a0 upgrade v0.9.8")
        print(f"  {result['status']}: {result.get('message', result.get('error', 'Unknown'))}")
        print()
        
        # Verify no execution side effects
        print("4. Verifying no execution side effects:")
        with open(version_path, "r") as f:
            after_version = json.load(f)
        
        with open(state_path, "r") as f:
            after_state = json.load(f)
        
        print(f"  Version after approval: {after_version['version']}")
        print(f"  Expected: {version_data['version']}")
        print(f"  State after approval: {after_state['state']}")
        print(f"  Result: {'✓ No execution side effects (correct)' if version_data['version'] == after_version['version'] and after_state['state'] == 'IDLE' else '✗ Unexpected changes (incorrect)'}")
        print()
        
        # Check if pending approval was cleared
        print("5. Checking if pending approval was cleared:")
        result = commands.handle_command("a0 pending-approvals")
        print(f"  {result.get('message', 'No pending approvals')}")
        print()
        
        # Check audit log
        print("6. Audit log entries:")
        if log_path.exists():
            with open(log_path, "r") as f:
                events = []
                for i, line in enumerate(f):
                    if line.strip():
                        try:
                            entry = json.loads(line.strip())
                            events.append(f"   {i+1}. {entry['event_type']} - {entry['timestamp'][:19]} - Version: {entry['version']}")
                        except (json.JSONDecodeError, KeyError):
                            pass
                
                if events:
                    for event in events:
                        print(event)
                else:
                    print("   No events recorded")
        else:
            print("   Audit log not found!")
    
    print("\n===== Demo Complete =====")


if __name__ == "__main__":
    run_demo()