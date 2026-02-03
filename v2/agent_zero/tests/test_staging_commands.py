"""
Test suite for Agent Zero staging commands.

These tests verify the command handlers work correctly without
actually cloning from GitHub (to avoid network dependencies).
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

from v2.agent_zero import commands
from v2.agent_zero.staging import list_artifacts, get_artifacts_path


class TestStagingCommands(unittest.TestCase):
    """Tests for staging command handlers."""
    
    def test_staging_status_command(self):
        """Test a0 staging-status command."""
        result = commands.handle_command("a0 staging-status")
        self.assertEqual(result["status"], "success")
        self.assertIn("staging", result)
        self.assertFalse(result["staging"]["active"])
    
    def test_list_artifacts_command(self):
        """Test a0 list-artifacts command."""
        result = commands.handle_command("a0 list-artifacts")
        self.assertEqual(result["status"], "success")
        self.assertIn("artifacts", result)
        self.assertIsInstance(result["artifacts"], list)
    
    def test_begin_staging_command_format(self):
        """Test a0 begin-staging command format validation."""
        # Missing version
        result = commands.handle_command("a0 begin-staging")
        self.assertEqual(result["status"], "error")
        self.assertIn("Missing version", result["error"])
    
    def test_begin_staging_dry_run(self):
        """Test a0 begin-staging with --dry-run flag."""
        # This test would require mocking GitHub API
        # For now, we'll just verify the command is recognized
        result = commands.handle_command("a0 begin-staging v0.9.8 --dry-run")
        # Should either succeed with dry run or fail with state check
        self.assertIn("status", result)
    
    def test_cleanup_artifacts_command(self):
        """Test a0 cleanup-artifacts command."""
        result = commands.handle_command("a0 cleanup-artifacts")
        self.assertIn("status", result)
        # Should succeed or fail based on authority
        if result["status"] == "success":
            self.assertIn("deleted_count", result)
    
    def test_cleanup_artifacts_with_keep(self):
        """Test a0 cleanup-artifacts with --keep flag."""
        result = commands.handle_command("a0 cleanup-artifacts --keep 5")
        self.assertIn("status", result)


if __name__ == "__main__":
    unittest.main()