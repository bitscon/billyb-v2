"""
Test suite for Agent Zero artifact validator.
"""

import os
import json
import tempfile
import shutil
import unittest
from pathlib import Path
import sys

# Add project root to Python path to allow relative imports
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from v2.agent_zero.validator import (
    ArtifactValidator,
    validate_artifact,
    ValidationError,
    ArtifactNotFoundError,
    REPORT_SCHEMA
)
from v2.agent_zero.tests.mock_artifact import (
    create_mock_artifact,
    create_broken_artifact
)
from v2.agent_zero.schema import validate_json_schema
from v2.agent_zero.state_machine import AgentZeroStateMachine, State


class TestArtifactValidator(unittest.TestCase):
    """Tests for artifact validation."""
    
    def setUp(self):
        """Set up test environment."""
        self.test_artifacts = []
    
    def tearDown(self):
        """Clean up test artifacts."""
        for artifact_path in self.test_artifacts:
            if artifact_path.exists():
                shutil.rmtree(artifact_path, ignore_errors=True)
    
    def test_valid_artifact_passes_all_checks(self):
        """Test 1: Valid artifact passes all checks."""
        # Create mock artifact
        artifact_path = create_mock_artifact()
        self.test_artifacts.append(artifact_path)
        
        # Create validator
        validator = ArtifactValidator(artifact_path, "v0.9.8")
        
        # Run validation
        report = validator.validate_all()
        
        # Check that all checks passed
        self.assertEqual(report["status"], "PASSED")
        self.assertTrue(report["checks"]["structural_integrity"]["passed"])
        self.assertTrue(report["checks"]["prompt_assets"]["passed"])
        self.assertTrue(report["checks"]["tool_registry"]["passed"])
        
        # Verify report schema
        validate_json_schema(report, REPORT_SCHEMA)
    
    def test_missing_files_fail_integrity_check(self):
        """Test 2: Missing critical files fail integrity check."""
        # Create broken artifact
        artifact_path = create_broken_artifact(break_type="missing_files")
        self.test_artifacts.append(artifact_path)
        
        # Create validator
        validator = ArtifactValidator(artifact_path, "v0.9.8")
        
        # Run validation
        report = validator.validate_all()
        
        # Check that validation failed
        self.assertEqual(report["status"], "FAILED")
        self.assertFalse(report["checks"]["structural_integrity"]["passed"])
    
    def test_no_venv_fails_import_check(self):
        """Test 3: Missing virtualenv fails import check."""
        # Create broken artifact
        artifact_path = create_broken_artifact(break_type="no_venv")
        self.test_artifacts.append(artifact_path)
        
        # Create validator
        validator = ArtifactValidator(artifact_path, "v0.9.8")
        
        # Run validation
        report = validator.validate_all()
        
        # Check that import sanity check failed
        self.assertFalse(report["checks"]["import_sanity"]["passed"])
    
    def test_empty_prompts_fail_prompt_check(self):
        """Test 4: Empty prompt files fail prompt check."""
        # Create broken artifact
        artifact_path = create_broken_artifact(break_type="empty_prompts")
        self.test_artifacts.append(artifact_path)
        
        # Create validator
        validator = ArtifactValidator(artifact_path, "v0.9.8")
        
        # Run validation
        report = validator.validate_all()
        
        # Check that prompt assets check failed
        self.assertFalse(report["checks"]["prompt_assets"]["passed"])
    
    def test_no_tools_fails_tool_check(self):
        """Test 5: Missing tools directory fails tool check."""
        # Create broken artifact
        artifact_path = create_broken_artifact(break_type="no_tools")
        self.test_artifacts.append(artifact_path)
        
        # Create validator
        validator = ArtifactValidator(artifact_path, "v0.9.8")
        
        # Run validation
        report = validator.validate_all()
        
        # Check that tool registry check failed
        self.assertFalse(report["checks"]["tool_registry"]["passed"])
    
    def test_report_storage(self):
        """Test 6: Validation report is stored correctly."""
        # Create mock artifact
        artifact_path = create_mock_artifact()
        self.test_artifacts.append(artifact_path)
        
        # Create validator
        validator = ArtifactValidator(artifact_path, "v0.9.8")
        
        # Run validation
        report = validator.validate_all()
        
        # Store report
        report_path = validator.store_report(report)
        
        # Verify report was stored
        self.assertTrue(report_path.exists())
        
        # Verify content
        with open(report_path, 'r') as f:
            stored_report = json.load(f)
        
        self.assertEqual(stored_report["version"], "v0.9.8")
        self.assertEqual(stored_report["status"], report["status"])
    
    def test_report_schema_validation(self):
        """Test 7: Report validates against schema."""
        # Create mock artifact
        artifact_path = create_mock_artifact()
        self.test_artifacts.append(artifact_path)
        
        # Create validator
        validator = ArtifactValidator(artifact_path, "v0.9.8")
        
        # Run validation
        report = validator.validate_all()
        
        # Validate against schema
        validate_json_schema(report, REPORT_SCHEMA)
    
    def test_idempotency(self):
        """Test 8: Running validation twice yields same result."""
        # Create mock artifact
        artifact_path = create_mock_artifact()
        self.test_artifacts.append(artifact_path)
        
        # Create validator
        validator1 = ArtifactValidator(artifact_path, "v0.9.8")
        validator2 = ArtifactValidator(artifact_path, "v0.9.8")
        
        # Run validation twice
        report1 = validator1.validate_all()
        report2 = validator2.validate_all()
        
        # Check that status is the same
        self.assertEqual(report1["status"], report2["status"])
        
        # Check that all check results are the same
        for check_name in report1["checks"]:
            self.assertEqual(
                report1["checks"][check_name]["passed"],
                report2["checks"][check_name]["passed"]
            )
    
    def test_artifact_not_found(self):
        """Test 9: Non-existent artifact raises error."""
        # Try to validate non-existent artifact
        with self.assertRaises(ArtifactNotFoundError):
            ArtifactValidator(Path("/tmp/nonexistent_artifact"), "v0.9.8")
    
    def test_all_checks_have_timing(self):
        """Test 10: All checks report timing information."""
        # Create mock artifact
        artifact_path = create_mock_artifact()
        self.test_artifacts.append(artifact_path)
        
        # Create validator
        validator = ArtifactValidator(artifact_path, "v0.9.8")
        
        # Run validation
        report = validator.validate_all()
        
        # Verify all checks have timing
        for check_name, check_result in report["checks"].items():
            self.assertIn("ms", check_result)
            self.assertIsInstance(check_result["ms"], (int, float))
            self.assertGreaterEqual(check_result["ms"], 0)


if __name__ == "__main__":
    unittest.main()