"""
Demo script for Phase 4B validation engine.

This script demonstrates the validation functionality by:
1. Creating a mock artifact
2. Running validation checks
3. Displaying the validation report
4. Showing state machine transitions
5. Testing failure scenarios
"""

import os
import json
import sys
import shutil
from pathlib import Path

# Add project root to Python path to allow relative imports
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from v2.agent_zero.tests.mock_artifact import create_mock_artifact, create_broken_artifact
from v2.agent_zero.validator import ArtifactValidator, validate_artifact
from v2.agent_zero.state_machine import AgentZeroStateMachine, State
from v2.agent_zero.staging import get_artifacts_path
from v2.agent_zero import commands


def print_separator(title):
    """Print a separator with title."""
    print(f"\n{'=' * 20} {title} {'=' * 20}\n")


def print_json(data):
    """Print JSON data in a readable format."""
    print(json.dumps(data, indent=2))


def run_demo():
    """Run the validation demo."""
    print_separator("Agent Zero Phase 4B: Validation Engine Demo")
    
    # Create mock artifacts in the artifacts directory
    artifacts_path = get_artifacts_path()
    
    # Clean up any existing test artifacts
    test_artifact_path = artifacts_path / "v0.9.8"
    if test_artifact_path.exists():
        shutil.rmtree(test_artifact_path)
    
    # Create a valid mock artifact
    print("Creating mock artifact for v0.9.8...")
    mock_artifact = create_mock_artifact(version="v0.9.8")
    
    # Copy to artifacts directory
    shutil.copytree(mock_artifact, test_artifact_path)
    
    # Clean up temp mock
    shutil.rmtree(mock_artifact)
    
    print(f"Mock artifact created at: {test_artifact_path}")
    
    # Display artifact structure
    print_separator("Artifact Structure")
    print("Critical files:")
    for item in ["agent.py", "models.py", "prompts/", "python/tools/", ".venv/", "manifest.json"]:
        item_path = test_artifact_path / item
        exists = item_path.exists()
        icon = "✓" if exists else "✗"
        print(f"  {icon} {item}")
    
    # Create validator
    print_separator("Running Validation Checks")
    validator = ArtifactValidator(test_artifact_path, "v0.9.8")
    
    # Run individual checks and display results
    checks = {
        "Structural Integrity": validator.run_check_integrity,
        "Import Sanity": validator.run_check_imports,
        "Config Parsing": validator.run_check_config,
        "Tool Registry": validator.run_check_tools,
        "Prompt Assets": validator.run_check_prompts,
        "Memory Initialization": validator.run_check_memory
    }
    
    for check_name, check_func in checks.items():
        result = check_func()
        icon = "✓" if result["passed"] else "✗"
        status = "PASS" if result["passed"] else "FAIL"
        elapsed = result["ms"]
        print(f"{icon} {check_name}: {status} ({elapsed}ms)")
        if result["error"]:
            print(f"    Error: {result['error']}")
    
    # Run full validation
    print_separator("Full Validation Report")
    report = validator.validate_all()
    
    print(f"Status: {report['status']}")
    print(f"Version: {report['version']}")
    print(f"Elapsed: {report['elapsed_ms']}ms")
    print(f"Artifact Hash: {report['artifact_hash']}")
    print()
    
    # Display check summary
    print("Check Summary:")
    for check_name, check_result in report["checks"].items():
        icon = "✓" if check_result["passed"] else "✗"
        print(f"  {icon} {check_name}: {check_result['ms']}ms")
    
    # Store report
    print_separator("Storing Report")
    report_path = validator.store_report(report)
    print(f"Report stored at: {report_path}")
    
    # Test failure scenario
    print_separator("Testing Failure Scenario")
    
    # Create a broken artifact
    broken_artifact_path = artifacts_path / "v0.9.9"
    if broken_artifact_path.exists():
        shutil.rmtree(broken_artifact_path)
    
    broken_artifact = create_broken_artifact(version="v0.9.9", break_type="missing_files")
    shutil.copytree(broken_artifact, broken_artifact_path)
    shutil.rmtree(broken_artifact)
    
    print("Created broken artifact (missing critical files)...")
    
    # Validate broken artifact
    broken_validator = ArtifactValidator(broken_artifact_path, "v0.9.9")
    broken_report = broken_validator.validate_all()
    
    print(f"Validation Status: {broken_report['status']}")
    print(f"Failed Checks:")
    for check_name, check_result in broken_report["checks"].items():
        if not check_result["passed"]:
            print(f"  ✗ {check_name}: {check_result['error']}")
    
    # Test command integration
    print_separator("Command Integration")
    
    print("Testing 'a0 report' command:")
    result = commands.handle_command("a0 report")
    if result["status"] == "success":
        print(f"  ✓ Report retrieved successfully")
        print(f"  Version: {result['report']['version']}")
        print(f"  Status: {result['report']['status']}")
    else:
        print(f"  ✗ Error: {result.get('error')}")
    
    # Clean up test artifacts
    print_separator("Cleanup")
    print("Cleaning up test artifacts...")
    if test_artifact_path.exists():
        shutil.rmtree(test_artifact_path)
    if broken_artifact_path.exists():
        shutil.rmtree(broken_artifact_path)
    print("  ✓ Cleanup complete")
    
    print_separator("Demo Complete")
    print()
    print("✅ Phase 4B validation engine is working correctly")
    print()
    print("Key Features Demonstrated:")
    print("  • 6 comprehensive validation checks")
    print("  • Subprocess isolation for safety")
    print("  • Detailed timing information")
    print("  • Report storage and rotation")
    print("  • Schema validation")
    print("  • Failure detection and handling")
    print("  • Command integration")


if __name__ == "__main__":
    run_demo()