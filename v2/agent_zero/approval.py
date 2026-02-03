"""
Approval workflow for Agent Zero lifecycle management.
"""

import os
import json
from datetime import datetime
from typing import Dict, Any, Optional, List, Union
from pathlib import Path

from .schema import (
    PENDING_APPROVAL_SCHEMA, 
    validate_version_format,
    validate_version_upgrade,
    SchemaValidationError,
    InvalidVersionFormatError,
    DowngradeAttemptError
)
from .fileops import (
    atomic_write,
    compute_approval_id,
    verify_approval_integrity,
    verify_file_integrity,
    acquire_lock,
    release_lock,
    IntegrityViolationError,
    LockAcquisitionError
)
from .github import (
    get_github_release,
    InvalidVersionError,
    GitHubAPIError
)
from .audit import log_event

# Custom exceptions
class ApprovalError(Exception):
    """Base class for approval workflow errors."""
    pass

class PendingApprovalExistsError(ApprovalError):
    """Raised when a pending approval already exists."""
    pass

class NoPendingApprovalError(ApprovalError):
    """Raised when no pending approval exists."""
    pass

class VersionMismatchError(ApprovalError):
    """Raised when approval version doesn't match pending version."""
    pass

class HumanRequiredError(ApprovalError):
    """Raised when a human-only operation is attempted by non-human."""
    pass

def get_metadata_path() -> Path:
    """Returns the path to Agent Zero metadata directory."""
    return Path(__file__).parent / ".billy"

def get_pending_approval_path() -> Path:
    """Returns path to pending approval file."""
    return get_metadata_path() / "pending_approval.json"

def get_version_path() -> Path:
    """Returns path to the Agent Zero version file."""
    return get_metadata_path() / "version.json"

def get_state_path() -> Path:
    """Returns path to the Agent Zero state file."""
    return get_metadata_path() / "state.json"

def read_current_version() -> Dict[str, Any]:
    """
    Read current Agent Zero version.
    
    Returns:
        Dict: Version data
    """
    version_path = get_version_path()
    
    try:
        with open(version_path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        raise ApprovalError(f"Failed to read current version: {str(e)}")

def read_pending_approval() -> Optional[Dict[str, Any]]:
    """
    Read pending approval, if it exists.
    
    Returns:
        Dict or None: Pending approval data or None if no pending approval
    """
    pending_path = get_pending_approval_path()
    
    if not os.path.exists(pending_path):
        return None
    
    try:
        with open(pending_path, "r") as f:
            return json.load(f)
    except json.JSONDecodeError:
        # Log integrity violation
        log_event("integrity_violation", {"error": "Invalid JSON in pending_approval.json"})
        raise IntegrityViolationError("pending_approval.json contains invalid JSON")

def is_duplicate_request(requested_version: str) -> bool:
    """
    Check if this is a duplicate of an existing pending approval.
    
    Args:
        requested_version: Requested version string
        
    Returns:
        bool: True if duplicate
    """
    pending = read_pending_approval()
    
    if pending and pending.get("version") == requested_version:
        return True
    
    return False

def create_approval_request(
        version: str, 
        requester: str,
        notes: Optional[str] = None,
        force_check: bool = False,
        allow_prerelease: bool = False) -> Dict[str, Any]:
    """
    Create a new approval request.
    
    Args:
        version: Requested version
        requester: Requester identifier (e.g., "human:alice@example.com")
        notes: Optional notes
        force_check: Whether to replace existing pending approval
        allow_prerelease: Whether to allow prerelease versions
        
    Returns:
        Dict: Created approval data
        
    Raises:
        PendingApprovalExistsError: If approval already exists and force_check is False
        InvalidVersionFormatError: If version format is invalid
        DowngradeAttemptError: If version <= current version
        InvalidVersionError: If version doesn't exist in GitHub
        GitHubAPIError: For GitHub-related errors
        IntegrityViolationError: For file integrity issues
    """
    # Check if there's already a pending approval
    pending = read_pending_approval()
    
    if pending and not force_check:
        # Check if this is a duplicate request
        if pending.get("version") == version:
            log_event("duplicate_request", {"version": version})
            raise PendingApprovalExistsError(f"Duplicate approval request for {version}")
        else:
            raise PendingApprovalExistsError(f"Pending approval exists for {pending.get('version')}. Use --force-check to replace.")
    
    # Read current version
    current_version_data = read_current_version()
    current_version = current_version_data.get("version")
    
    # Validate version format and upgrade path
    validate_version_upgrade(version, current_version)
    
    # Check GitHub for release
    release = get_github_release(version, allow_prerelease, force_check)
    
    # Get timestamp
    requested_at = datetime.utcnow().isoformat() + "Z"
    
    # Compute approval ID
    approval_id = compute_approval_id(version, requested_at, requester)
    
    # Create approval data
    approval_data = {
        "agent_id": "agent_zero",
        "version": version,
        "requested_at": requested_at,
        "requested_by": requester,
        "approval_id": approval_id,
        "github_release_url": release["html_url"],
        "notes": notes,
        "last_modified": requested_at
    }
    
    # Write approval file atomically
    pending_path = get_pending_approval_path()
    
    # Write atomically - simplified for testing
    atomic_write(pending_path, approval_data, PENDING_APPROVAL_SCHEMA)
    
    # Log event
    if pending and force_check:
        log_event("approval_replaced", {
            "version": version,
            "previous_version": pending.get("version"),
            "requester": requester
        })
    else:
        log_event("approval_requested", {
            "version": version,
            "requester": requester,
            "github_url": release["html_url"]
        })
    
    return approval_data

def approve_upgrade(version: str, actor: str, is_human: bool = False) -> bool:
    """
    Grant approval for a pending upgrade.
    
    Args:
        version: Version to approve
        actor: Approver identifier
        is_human: Whether the actor is human
        
    Returns:
        bool: True on success
        
    Raises:
        NoPendingApprovalError: If no pending approval exists
        VersionMismatchError: If version doesn't match pending approval
        IntegrityViolationError: If approval integrity check fails
        HumanRequiredError: If is_human is False
    """
    # Only humans can approve upgrades
    if not is_human:
        raise HumanRequiredError("Only humans can approve upgrades")
    
    # Check if there's a pending approval
    pending = read_pending_approval()
    
    if not pending:
        raise NoPendingApprovalError("No pending approval to grant")
    
    # Check if versions match
    if pending.get("version") != version:
        raise VersionMismatchError(f"Requested version {version} doesn't match pending approval for {pending.get('version')}")
    
    # Verify approval integrity
    verify_approval_integrity(pending)
    
    # Verify file integrity
    verify_file_integrity(get_pending_approval_path(), pending)
    
    # Delete pending approval - simplified for testing
    os.unlink(get_pending_approval_path())
    
    # Log event
    log_event("approval_granted", {
        "version": version,
        "approver": actor,
        "requested_by": pending.get("requested_by")
    })
    
    # Note: In Phase 2, we do NOT execute the upgrade
    # or change authority level. This only records the approval.
    
    return True

def deny_upgrade(version: str, actor: str, is_human: bool = False, reason: Optional[str] = None) -> bool:
    """
    Deny a pending upgrade.
    
    Args:
        version: Version to deny
        actor: Denier identifier
        is_human: Whether the actor is human
        reason: Optional reason for denial
        
    Returns:
        bool: True on success
        
    Raises:
        NoPendingApprovalError: If no pending approval exists
        VersionMismatchError: If version doesn't match pending approval
        HumanRequiredError: If is_human is False
    """
    # Only humans can deny upgrades
    if not is_human:
        raise HumanRequiredError("Only humans can deny upgrades")
    
    # Check if there's a pending approval
    pending = read_pending_approval()
    
    if not pending:
        raise NoPendingApprovalError("No pending approval to deny")
    
    # Check if versions match
    if pending.get("version") != version:
        raise VersionMismatchError(f"Requested version {version} doesn't match pending approval for {pending.get('version')}")
    
    # Delete pending approval - simplified for testing
    os.unlink(get_pending_approval_path())
    
    # Log event
    log_event("approval_denied", {
        "version": version,
        "denier": actor,
        "requested_by": pending.get("requested_by"),
        "reason": reason
    })
    
    return True

def get_pending_approvals() -> List[Dict[str, Any]]:
    """
    Get list of pending approvals.
    In Phase 2, there's only one possible pending approval.
    
    Returns:
        List: Pending approvals
    """
    pending = read_pending_approval()
    
    if not pending:
        return []
    
    # Try to verify integrity
    try:
        verify_approval_integrity(pending)
        verify_file_integrity(get_pending_approval_path(), pending)
    except IntegrityViolationError as e:
        # Log integrity violation
        log_event("integrity_violation", {"error": str(e)})
        # Still return the data, but a real implementation would require human intervention
    
    return [pending]