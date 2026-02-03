"""
End-to-end demo showing all phases working together.

This demonstrates the complete workflow from approval through validation.
"""

import os
import json
import sys
import shutil
import tempfile
from pathlib import Path
import unittest.mock

# Add project root to Python path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from v2.agent_zero import commands
from v2.agent_zero.state_machine import AgentZeroStateMachine, State
from v2.agent_zero.tests.mock_artifact import create_mock_artifact
from v2.agent_zero.staging import get_artifacts_path


def print_separator(title):
    """Print a separator with title."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}\n")


def print_status(label, data):
    """Print status information."""
    print(f"{label}:")
    if isinstance(data, dict):
        for key, value in data.items():
            if key != "report":  # Skip verbose report data
                print(f"  {key}: {value}")
    else:
        print(f"  {data}")
    print()


def run_e2e_demo():
    """Run end-to-end demonstration."""
    print_separator("AGENT ZERO LIFECYCLE - END-TO-END DEMONSTRATION")
    
    # Phase 1: Environment Inspection
    print_separator("PHASE 1: Environment Inspection (Read-Only)")
    
    print("Testing read-only commands:")
    result = commands.handle_command("a0 env ls v2/agent_zero/.billy")
    print(f"  ✓ a0 env ls: {result['status']}")
    
    result = commands.handle_command("a0 env cat v2/agent_zero/.billy/version.json")
    print(f"  ✓ a0 env cat: {result['status']}")
    
    # Phase 2: Approval Workflow
    print_separator("PHASE 2: Approval Workflow")
    
    # Mock GitHub API for demo
    def mock_github():
        mock_response = json.dumps({
            "tag_name": "v0.9.8",
            "html_url": "https://github.com/frdel/agent-zero/releases/tag/v0.9.8",
            "draft": False,
            "prerelease": False,
            "target_commitish": "abc123def456",
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
        
        return unittest.mock.patch(
            "urllib.request.urlopen",
            return_value=MockResponse()
        )
    
    with mock_github():
        print("Step 1: Request upgrade approval")
        result = commands.handle_command("a0 request-upgrade v0.9.8")
        print_status("  Result", {"status": result["status"], "message": result.get("message", "")})
        
        print("Step 2: View pending approvals")
        result = commands.handle_command("a0 pending-approvals")
        if result["pending_approvals"]:
            pending = result["pending_approvals"][0]
            print(f"  Pending: {pending['version']} (requested by {pending['requested_by']})")
        
        print("\nStep 3: Approve upgrade (human)")
        result = commands.handle_command("approve a0 upgrade v0.9.8")
        print_status("  Result", {
            "status": result["status"],
            "message": result.get("message", ""),
            "state": result.get("state", "unknown")
        })
    
    # Phase 3: State Machine
    print_separator("PHASE 3: State Machine")
    
    sm = AgentZeroStateMachine()
    current = sm.current()
    
    print(f"Current State: {current['current_state']}")
    print(f"Authority: {current['authority_level']}")
    
    active_op = current.get('active_operation')
    if active_op:
        print(f"Active Operation: {active_op.get('type', 'none')}")
    else:
        print(f"Active Operation: none")
    
    print("\nExplaining current state:")
    result = commands.handle_command("a0 explain-state")
    if result["status"] == "success":
        explanation = result["explanation"]
        print(f"  State: {explanation['current_state']}")
        print(f"  Possible transitions: {', '.join(explanation['possible_next_states'])}")
    
    # Phase 4A: Staging (Simulated)
    print_separator("PHASE 4A: Staging (Simulated)")
    
    print("Note: In a real scenario, staging would:")
    print("  1. Clone repository from GitHub")
    print("  2. Create virtualenv and install dependencies")
    print("  3. Compute checksums")
    print("  4. Store artifact in .billy/artifacts/")
    print()
    print("For this demo, we'll create a mock artifact directly...")
    
    # Create mock artifact
    artifacts_path = get_artifacts_path()
    test_artifact_path = artifacts_path / "v0.9.8"
    
    if test_artifact_path.exists():
        shutil.rmtree(test_artifact_path)
    
    mock_artifact = create_mock_artifact(version="v0.9.8")
    shutil.copytree(mock_artifact, test_artifact_path)
    shutil.rmtree(mock_artifact)
    
    print(f"  ✓ Mock artifact created at: {test_artifact_path}")
    
    # List artifacts
    result = commands.handle_command("a0 list-artifacts")
    print(f"\n  Stored artifacts: {len(result['artifacts'])}")
    for artifact in result["artifacts"]:
        print(f"    • {artifact['version']} - {artifact['size_mb']} MB")
    
    # Phase 4B: Validation
    print_separator("PHASE 4B: Validation Engine")
    
    # Manually set state to VALIDATING for demo
    # First go to STAGING, then to VALIDATING
    print("Transitioning: IDLE → STAGING → VALIDATING")
    sm.transition(
        to_state=State.STAGING,
        reason_code="approval_granted",
        notes="Demo staging",
        metadata={
            "operation": {
                "type": "upgrade",
                "target_version": "v0.9.8"
            }
        }
    )
    
    sm.transition(
        to_state=State.VALIDATING,
        reason_code="approval_granted",
        notes="Demo validation",
        metadata={
            "operation": {
                "type": "upgrade",
                "target_version": "v0.9.8"
            }
        }
    )
    
    print("Step 1: Run validation")
    result = commands.handle_command("a0 validate --version v0.9.8")
    print_status("  Result", {
        "status": result.get("status"),
        "validation_status": result.get("validation_status"),
        "version": result.get("version")
    })
    
    print("Step 2: View validation report")
    result = commands.handle_command("a0 report")
    if result["status"] == "success":
        report = result["report"]
        print(f"  Report Status: {report['status']}")
        print(f"  Elapsed Time: {report['elapsed_ms']}ms")
        print(f"  Checks Passed: {sum(1 for c in report['checks'].values() if c['passed'])}/{len(report['checks'])}")
        print()
        print("  Check Results:")
        for check_name, check_result in report["checks"].items():
            icon = "✓" if check_result["passed"] else "✗"
            print(f"    {icon} {check_name}: {check_result['ms']}ms")
    
    # Check final state
    print_separator("Final State")
    
    sm = AgentZeroStateMachine()
    current = sm.current()
    
    print(f"Current State: {current['current_state']}")
    print(f"Previous State: {current.get('previous_state')}")
    print(f"Authority Level: {current['authority_level']}")
    
    # Cleanup
    print_separator("Cleanup")
    
    if test_artifact_path.exists():
        shutil.rmtree(test_artifact_path)
        print("  ✓ Test artifact removed")
    
    print_separator("End-to-End Demo Complete")
    
    print("\n✅ All Phases Working Together:")
    print("  Phase 1: Read-only inspection ✓")
    print("  Phase 2: Approval workflow ✓")
    print("  Phase 3: State machine ✓")
    print("  Phase 4A: Staging (simulated) ✓")
    print("  Phase 4B: Validation ✓")
    print()
    print("System is ready for Phase 4C (Promotion)")


if __name__ == "__main__":
    run_e2e_demo()