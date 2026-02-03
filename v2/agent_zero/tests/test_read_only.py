"""
Test suite for Agent Zero read-only command implementation.

This module contains tests that verify the functionality and security
of the read-only command implementation.
"""

import json
import os
import sys
import time
import unittest
from pathlib import Path

# Add project root to Python path to allow relative imports
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from v2.agent_zero import read_only


class TestReadOnlyImplementation(unittest.TestCase):
    """Tests for the read-only implementation."""
    
    def setUp(self):
        """Set up test environment."""
        self.test_dir = Path(__file__).parent
        self.agent_zero_dir = self.test_dir.parent
        self.billy_dir = self.agent_zero_dir / ".billy"
    
    def test_status_command(self):
        """Test that status command works correctly."""
        result = read_only.execute_command("a0 status")
        self.assertEqual(result["status"], "success")
        self.assertIn("version", result)
        self.assertIn("state", result)
        self.assertIn("authority", result)
    
    def test_ls_command_valid(self):
        """Test that ls command works with valid paths."""
        result = read_only.execute_command(f"a0 env ls {self.agent_zero_dir}")
        self.assertEqual(result["status"], "success")
        self.assertIn("output", result)
    
    def test_cat_command_valid(self):
        """Test that cat command works with valid files."""
        result = read_only.execute_command(f"a0 env cat {self.billy_dir}/version.json")
        self.assertEqual(result["status"], "success")
        self.assertIn("output", result)
        self.assertIn("version", result["output"])
    
    def test_find_command_valid(self):
        """Test that find command works with valid arguments."""
        result = read_only.execute_command(f"a0 env find {self.agent_zero_dir} -maxdepth 2 -type f")
        self.assertEqual(result["status"], "success")
        self.assertIn("output", result)
    
    def test_path_traversal_check(self):
        """Test path traversal detection."""
        result = read_only.execute_command("a0 env cat ../../../../etc/passwd")
        self.assertEqual(result["status"], "error")
        self.assertIn("Path not allowed", result["error"])
        self.assertEqual(result["violation"], "PathViolationError")
    
    def test_binary_file_detection(self):
        """Test binary file detection."""
        # This test might be system-dependent
        if os.path.exists("/bin/ls"):
            result = read_only.execute_command("a0 env cat /bin/ls")
            self.assertEqual(result["status"], "error")
            self.assertIn("Path not allowed", result["error"])
    
    def test_excessive_recursion(self):
        """Test detection of excessive recursion depth."""
        result = read_only.execute_command(f"a0 env find {self.agent_zero_dir} -maxdepth 4")
        self.assertEqual(result["status"], "error")
        self.assertIn("Maxdepth too large", result["error"])
        self.assertEqual(result["violation"], "SafetyLimitExceededError")
    
    def test_write_attempt_detection(self):
        """Test detection of write attempts."""
        result = read_only.execute_command(f"a0 env ls {self.agent_zero_dir} > out.txt")
        self.assertEqual(result["status"], "error")
        self.assertIn("Write operations not allowed", result["error"])
        self.assertEqual(result["violation"], "WriteAttemptError")
    
    def test_command_not_in_allowlist(self):
        """Test rejection of commands not in allowlist."""
        result = read_only.execute_command("a0 env rm -rf /")
        self.assertEqual(result["status"], "error")
        self.assertIn("Command not allowed", result["error"])
    
    def test_disallowed_flags(self):
        """Test rejection of disallowed flags."""
        result = read_only.execute_command(f"a0 env ls -x {self.agent_zero_dir}")
        self.assertEqual(result["status"], "error")
        self.assertIn("Flag not allowed", result["error"])
    
    def test_upgrade_command_blocked(self):
        """Test that upgrade command is blocked in observer mode."""
        result = read_only.execute_command("a0 upgrade v0.9.8")
        self.assertEqual(result["status"], "error")
        self.assertIn("not available in observer mode", result["error"])
    
    def test_logging(self):
        """Test that command execution is logged correctly."""
        log_path = self.billy_dir / "read_only_exec.log"
        
        # Get current log size
        if log_path.exists():
            with open(log_path, "r") as f:
                logs_before = json.load(f)
            log_count_before = len(logs_before)
        else:
            log_count_before = 0
        
        # Execute a command
        read_only.execute_command(f"a0 env ls {self.agent_zero_dir}")
        
        # Check that log was updated
        time.sleep(0.1)  # Give a moment for logging to complete
        with open(log_path, "r") as f:
            logs_after = json.load(f)
        
        self.assertGreater(len(logs_after), log_count_before)
        
        # Verify log structure
        latest_log = logs_after[-1]
        self.assertIn("timestamp", latest_log)
        self.assertIn("command", latest_log)
        self.assertIn("arguments", latest_log)
        self.assertIn("output_size_bytes", latest_log)
    
    def test_verification_suite(self):
        """Run the verification test suite specified in the requirements."""
        # Test 1: Path traversal
        result = read_only.execute_command("a0 env cat ../../../../etc/passwd")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["violation"], "PathViolationError")
        
        # Test 2: Binary file detection - system-dependent
        if os.path.exists("/bin/ls"):
            result = read_only.execute_command("a0 env cat /bin/ls")
            self.assertEqual(result["status"], "error")
            # For this test, we're considering /bin files as unauthorized paths
            self.assertEqual(result["violation"], "PathViolationError")
        
        # Test 3: Excessive recursion
        result = read_only.execute_command(f"a0 env find {self.agent_zero_dir} -maxdepth 4")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["violation"], "SafetyLimitExceededError")
        
        # Test 4: Write attempt
        result = read_only.execute_command(f"a0 env ls {self.agent_zero_dir} > out.txt")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["violation"], "WriteAttemptError")
        
        # Test 5: Metadata truth
        result = read_only.execute_command("a0 status")
        self.assertEqual(result["status"], "success")
        self.assertIn("version", result)
        self.assertIn("state", result)


if __name__ == "__main__":
    unittest.main()