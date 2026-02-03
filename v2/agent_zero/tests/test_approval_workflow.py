"""
Test suite for Agent Zero approval workflow implementation.
"""

import os
import json
import time
import unittest
import tempfile
import shutil
from datetime import datetime
from pathlib import Path
import sys
from unittest.mock import patch, MagicMock

# Add project root to Python path to allow relative imports
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
    import urllib.request
    import urllib.error
except ImportError:
    # Mock for environments without urllib
    class urllib:
        class request:
            Request = object
            urlopen = lambda *args, **kwargs: None
        class error:
            HTTPError = Exception
            URLError = Exception

from v2.agent_zero.schema import (
    InvalidVersionFormatError,
    DowngradeAttemptError
)
from v2.agent_zero.github import (
    InvalidVersionError,
    RateLimitExceededError,
    GitHubUnavailableError
)
from v2.agent_zero.approval import (
    create_approval_request,
    approve_upgrade,
    deny_upgrade,
    get_pending_approvals,
    PendingApprovalExistsError,
    NoPendingApprovalError,
    VersionMismatchError,
    HumanRequiredError,
    read_current_version
)
from v2.agent_zero.fileops import (
    IntegrityViolationError,
    LockAcquisitionError,
    compute_approval_id
)
from v2.agent_zero.audit import read_audit_log
from v2.agent_zero import commands


class TestApprovalWorkflow(unittest.TestCase):
    """Tests for the approval workflow implementation."""
    
    def setUp(self):
        """Set up test environment with temporary directory for .billy."""
        # Create temporary directory
        self.temp_dir = tempfile.mkdtemp()
        self.temp_billy_dir = os.path.join(self.temp_dir, ".billy")
        os.makedirs(self.temp_billy_dir, exist_ok=True)
        
        # Create sample version.json and state.json
        with open(os.path.join(self.temp_billy_dir, "version.json"), "w") as f:
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
        
        with open(os.path.join(self.temp_billy_dir, "state.json"), "w") as f:
            json.dump(
                {
                    "state": "IDLE",
                    "last_transition": "2026-02-01T00:00:00Z",
                    "authority": "observer",
                    "current_operation": None
                },
                f, indent=2
            )
        
        # Create empty upgrade_history.log
        with open(os.path.join(self.temp_billy_dir, "upgrade_history.log"), "w") as f:
            pass
        
        # Create cache directory
        os.makedirs(os.path.join(self.temp_billy_dir, "cache"), exist_ok=True)
        
        # Patch paths to use temp directory
        self.patcher1 = patch("v2.agent_zero.approval.get_metadata_path", return_value=Path(self.temp_billy_dir))
        self.patcher2 = patch("v2.agent_zero.fileops.get_metadata_path", return_value=Path(self.temp_billy_dir))
        self.patcher3 = patch("v2.agent_zero.audit.get_audit_log_path", return_value=Path(self.temp_billy_dir) / "upgrade_history.log")
        self.patcher4 = patch("v2.agent_zero.github.get_cache_path", return_value=Path(self.temp_billy_dir) / "cache")
        
        self.patcher1.start()
        self.patcher2.start()
        self.patcher3.start()
        self.patcher4.start()
        
        # Mock GitHub API
        self.github_patcher = patch("v2.agent_zero.github.urllib.request.urlopen")
        self.urlopen_mock = self.github_patcher.start()
        
        # Setup mock response
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "tag_name": "v0.9.8",
            "html_url": "https://github.com/frdel/agent-zero/releases/tag/v0.9.8",
            "draft": False,
            "prerelease": False,
            "assets": [{"name": "agent-zero.zip"}]
        }).encode("utf-8")
        self.urlopen_mock.return_value.__enter__.return_value = mock_response
    
    def tearDown(self):
        """Clean up after test."""
        # Stop all patches
        self.patcher1.stop()
        self.patcher2.stop()
        self.patcher3.stop()
        self.patcher4.stop()
        self.github_patcher.stop()
        
        # Remove temp directory
        shutil.rmtree(self.temp_dir)
    
    def test_create_approval_request(self):
        """Test 1: Create Approval Request."""
        # Create approval request
        approval = create_approval_request("v0.9.8", "system:test_user")
        
        # Check that pending_approval.json was created
        pending_path = os.path.join(self.temp_billy_dir, "pending_approval.json")
        self.assertTrue(os.path.exists(pending_path))
        
        # Check that content is valid
        with open(pending_path, "r") as f:
            pending = json.load(f)
        
        self.assertEqual(pending["version"], "v0.9.8")
        self.assertEqual(pending["agent_id"], "agent_zero")
        self.assertEqual(pending["requested_by"], "system:test_user")
        self.assertTrue(isinstance(pending["requested_at"], str))
        self.assertTrue(pending["approval_id"])
        
        # Check that approval_id is computed correctly
        expected_id = compute_approval_id(
            pending["version"],
            pending["requested_at"],
            pending["requested_by"]
        )
        self.assertEqual(pending["approval_id"], expected_id)
        
        # Check audit log
        logs = read_audit_log()
        self.assertTrue(logs)
        self.assertEqual(logs[-1]["event_type"], "approval_requested")
        self.assertEqual(logs[-1]["version"], "v0.9.8")
    
    def test_duplicate_request_blocked(self):
        """Test 2: Duplicate Request Blocked."""
        # Create first approval
        create_approval_request("v0.9.8", "system:test_user")
        
        # Attempt duplicate request - should raise exception
        with self.assertRaises(PendingApprovalExistsError):
            create_approval_request("v0.9.8", "system:test_user")
        
        # Check audit log for duplicate request
        logs = read_audit_log()
        self.assertTrue(any(log["event_type"] == "duplicate_request" for log in logs))
    
    def test_force_replacement(self):
        """Test 3: Force Replacement."""
        # Create first approval
        create_approval_request("v0.9.8", "system:test_user")
        
        # Mock different version response
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "tag_name": "v0.9.9",
            "html_url": "https://github.com/frdel/agent-zero/releases/tag/v0.9.9",
            "draft": False,
            "prerelease": False,
            "assets": [{"name": "agent-zero.zip"}]
        }).encode("utf-8")
        self.urlopen_mock.return_value.__enter__.return_value = mock_response
        
        # Replace with force_check
        create_approval_request("v0.9.9", "system:test_user2", force_check=True)
        
        # Check that pending approval was replaced
        pending_path = os.path.join(self.temp_billy_dir, "pending_approval.json")
        with open(pending_path, "r") as f:
            pending = json.load(f)
        
        self.assertEqual(pending["version"], "v0.9.9")
        
        # Check audit log
        logs = read_audit_log()
        self.assertTrue(any(log["event_type"] == "approval_replaced" for log in logs))
    
    def test_approval_clears_pending(self):
        """Test 4: Approval Clears Pending."""
        # Create approval request
        create_approval_request("v0.9.8", "system:test_user")
        
        # Grant approval
        approve_upgrade("v0.9.8", "human:admin", is_human=True)
        
        # Check that pending file was deleted
        pending_path = os.path.join(self.temp_billy_dir, "pending_approval.json")
        self.assertFalse(os.path.exists(pending_path))
        
        # Check that version.json was NOT changed
        with open(os.path.join(self.temp_billy_dir, "version.json"), "r") as f:
            version = json.load(f)
        
        self.assertEqual(version["version"], "v0.9.7")  # Original version
        
        # Check that state.json state is still IDLE
        with open(os.path.join(self.temp_billy_dir, "state.json"), "r") as f:
            state = json.load(f)
        
        self.assertEqual(state["state"], "IDLE")
        
        # Check audit log
        logs = read_audit_log()
        self.assertTrue(any(log["event_type"] == "approval_granted" for log in logs))
    
    def test_denial_clears_pending(self):
        """Test 5: Denial Clears Pending."""
        # Create approval request
        create_approval_request("v0.9.8", "system:test_user")
        
        # Deny approval
        deny_upgrade("v0.9.8", "human:admin", is_human=True, reason="Testing")
        
        # Check that pending file was deleted
        pending_path = os.path.join(self.temp_billy_dir, "pending_approval.json")
        self.assertFalse(os.path.exists(pending_path))
        
        # Check audit log
        logs = read_audit_log()
        approval_denied = False
        for log in logs:
            if log["event_type"] == "approval_denied":
                approval_denied = True
                self.assertEqual(log["details"].get("reason"), "Testing")
                break
        self.assertTrue(approval_denied)
    
    def test_no_execution_side_effects(self):
        """Test 6: No Execution Side Effects."""
        # Create approval request
        create_approval_request("v0.9.8", "system:test_user")
        
        # Get initial file state
        version_path = os.path.join(self.temp_billy_dir, "version.json")
        state_path = os.path.join(self.temp_billy_dir, "state.json")
        
        with open(version_path, "r") as f:
            initial_version = json.load(f)
        
        with open(state_path, "r") as f:
            initial_state = json.load(f)
        
        # Grant approval
        approve_upgrade("v0.9.8", "human:admin", is_human=True)
        
        # Check that files were not modified
        with open(version_path, "r") as f:
            after_version = json.load(f)
        
        with open(state_path, "r") as f:
            after_state = json.load(f)
        
        self.assertEqual(initial_version, after_version)
        self.assertEqual(initial_state, after_state)
    
    def test_integrity_violation_detection(self):
        """Test 7: Integrity Violation Detection."""
        # Create approval request
        create_approval_request("v0.9.8", "system:test_user")
        
        # Tamper with pending_approval.json
        pending_path = os.path.join(self.temp_billy_dir, "pending_approval.json")
        with open(pending_path, "r") as f:
            pending = json.load(f)
        
        # Change version but keep approval_id the same
        pending["version"] = "v0.9.9"
        
        with open(pending_path, "w") as f:
            json.dump(pending, f, indent=2)
        
        # Attempt to approve
        with self.assertRaises(IntegrityViolationError):
            approve_upgrade("v0.9.8", "human:admin", is_human=True)
        
        # Check audit log
        logs = read_audit_log()
        self.assertTrue(any(log["event_type"] == "integrity_violation" for log in logs))
    
    @patch("v2.agent_zero.fileops.fcntl.flock")
    def test_concurrent_write_protection(self, mock_flock):
        """Test 8: Concurrent Write Protection."""
        # Mock flock to simulate lock contention
        mock_flock.side_effect = [BlockingIOError, BlockingIOError, BlockingIOError, None]
        
        # First call should succeed after retries
        create_approval_request("v0.9.8", "system:test_user")
        
        # Reset mock to always fail to simulate timeout
        mock_flock.side_effect = BlockingIOError
        
        # Second call should fail with LockAcquisitionError
        with self.assertRaises(LockAcquisitionError):
            create_approval_request("v0.9.9", "system:test_user2")
    
    def test_invalid_version_rejected(self):
        """Test 9: Invalid Version Rejected."""
        # Test invalid format
        with self.assertRaises(InvalidVersionFormatError):
            create_approval_request("v1.0.0.1", "system:test_user")
        
        # Test downgrade attempt
        with self.assertRaises(DowngradeAttemptError):
            create_approval_request("v0.9.7", "system:test_user")
        
        # Test non-existent version
        self.urlopen_mock.side_effect = urllib.error.HTTPError(
            url="", code=404, msg="Not Found", hdrs={}, fp=None
        )
        with self.assertRaises(InvalidVersionError):
            create_approval_request("v99.99.99", "system:test_user")
    
    def test_github_api_failure_handling(self):
        """Test 10: GitHub API Failure Handling."""
        # Test rate limit exceeded
        self.urlopen_mock.side_effect = urllib.error.HTTPError(
            url="", code=429, msg="Rate Limit Exceeded", hdrs={"Retry-After": "60"}, fp=None
        )
        with self.assertRaises(RateLimitExceededError):
            create_approval_request("v0.9.8", "system:test_user")
        
        # Test GitHub unavailable
        self.urlopen_mock.side_effect = urllib.error.HTTPError(
            url="", code=500, msg="Internal Server Error", hdrs={}, fp=None
        )
        with self.assertRaises(GitHubUnavailableError):
            create_approval_request("v0.9.8", "system:test_user")
    
    def test_command_handle_request_upgrade(self):
        """Test command handler for request-upgrade."""
        # Reset mock for this test
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "tag_name": "v0.9.8",
            "html_url": "https://github.com/frdel/agent-zero/releases/tag/v0.9.8",
            "draft": False,
            "prerelease": False,
            "assets": [{"name": "agent-zero.zip"}]
        }).encode("utf-8")
        self.urlopen_mock.side_effect = None
        self.urlopen_mock.return_value.__enter__.return_value = mock_response
        
        # Test command
        result = commands.handle_command("a0 request-upgrade v0.9.8")
        self.assertEqual(result["status"], "success")
        self.assertTrue("approval_id" in result)
        self.assertEqual(result["version"], "v0.9.8")
    
    def test_command_handle_pending_approvals(self):
        """Test command handler for pending-approvals."""
        # Create approval request
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "tag_name": "v0.9.8",
            "html_url": "https://github.com/frdel/agent-zero/releases/tag/v0.9.8",
            "draft": False,
            "prerelease": False,
            "assets": [{"name": "agent-zero.zip"}]
        }).encode("utf-8")
        self.urlopen_mock.side_effect = None
        self.urlopen_mock.return_value.__enter__.return_value = mock_response
        
        create_approval_request("v0.9.8", "system:test_user")
        
        # Test command
        result = commands.handle_command("a0 pending-approvals")
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["pending_approvals"]), 1)
        self.assertEqual(result["pending_approvals"][0]["version"], "v0.9.8")
        
        # Test JSON output
        result = commands.handle_command("a0 pending-approvals --json")
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["pending_approvals"]), 1)
        self.assertEqual(result["pending_approvals"][0]["version"], "v0.9.8")
    
    def test_command_handle_approve_upgrade(self):
        """Test command handler for approve upgrade."""
        # Create approval request
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "tag_name": "v0.9.8",
            "html_url": "https://github.com/frdel/agent-zero/releases/tag/v0.9.8",
            "draft": False,
            "prerelease": False,
            "assets": [{"name": "agent-zero.zip"}]
        }).encode("utf-8")
        self.urlopen_mock.side_effect = None
        self.urlopen_mock.return_value.__enter__.return_value = mock_response
        
        create_approval_request("v0.9.8", "system:test_user")
        
        # Test approve command
        result = commands.handle_command("approve a0 upgrade v0.9.8")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["version"], "v0.9.8")
    
    def test_command_handle_deny_upgrade(self):
        """Test command handler for deny upgrade."""
        # Create approval request
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "tag_name": "v0.9.8",
            "html_url": "https://github.com/frdel/agent-zero/releases/tag/v0.9.8",
            "draft": False,
            "prerelease": False,
            "assets": [{"name": "agent-zero.zip"}]
        }).encode("utf-8")
        self.urlopen_mock.side_effect = None
        self.urlopen_mock.return_value.__enter__.return_value = mock_response
        
        create_approval_request("v0.9.8", "system:test_user")
        
        # Test deny command
        result = commands.handle_command("deny a0 upgrade v0.9.8 --reason Testing")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["version"], "v0.9.8")


if __name__ == "__main__":
    unittest.main()