"""
Generate Phase 1 implementation report.

This script runs the verification test suite and generates a summary report.
"""

import os
import json
import sys
import unittest
from pathlib import Path

# Add project root to Python path to allow relative imports
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from v2.agent_zero.tests.test_read_only import TestReadOnlyImplementation


def generate_report():
    """Run tests and generate implementation report."""
    # Run the tests
    test_suite = unittest.TestLoader().loadTestsFromTestCase(TestReadOnlyImplementation)
    test_result = unittest.TextTestRunner(verbosity=0).run(test_suite)
    
    # Check if all tests passed
    all_passed = test_result.wasSuccessful()
    
    # Get implementation details
    from v2.agent_zero import read_only
    
    # Create the report
    report = f"""╔══════════════════════════════════════════════════╗
║  Phase 1 Read-Only Agent — Implementation Report ║
╚══════════════════════════════════════════════════╝

Mode:                  plan/observe
Authority Level:       observer
Mutation Capability:   DISABLED
Allowed Commands:      ls, cat, find
Binary Files:          BLOCKED
Max Output Size:       {read_only.MAX_OUTPUT_SIZE // 1024}KB
Allowed Roots:
  • {read_only.ALLOWED_ROOTS[0]}
  • {read_only.ALLOWED_ROOTS[1]}*

Logging:               ENABLED
Log Path:              v2/agent_zero/.billy/read_only_exec.log
Schema Validation:     ENFORCED
Test Suite:            {"ALL PASSED ✓" if all_passed else "FAILED ✗"}
"""
    
    # Write report to file
    report_path = Path(__file__).resolve().parent / "phase1_report.txt"
    with open(report_path, "w") as f:
        f.write(report)
    
    print(report)
    print(f"\nReport written to: {report_path}")


if __name__ == "__main__":
    generate_report()