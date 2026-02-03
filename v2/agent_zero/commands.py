"""
Agent Zero lifecycle command implementations.

This module handles Agent Zero commands, with the read-only
implementation providing secure environment inspection capabilities,
approval workflow for lifecycle management, and state machine core.
"""

import shutil
import json
import os
import re
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime

from . import read_only
from .schema import (
    InvalidVersionFormatError,
    DowngradeAttemptError
)
from .github import (
    InvalidVersionError,
    RateLimitExceededError,
    GitHubUnavailableError,
    GitHubAPIError
)
from .approval import (
    create_approval_request,
    approve_upgrade,
    deny_upgrade,
    get_pending_approvals,
    PendingApprovalExistsError,
    NoPendingApprovalError,
    VersionMismatchError,
    HumanRequiredError
)
import shutil
from .fileops import (
    IntegrityViolationError,
    LockAcquisitionError,
    acquire_lock,
    release_lock
)
from .audit import log_event
from .state_machine import (
    AgentZeroStateMachine,
    State,
    Authority,
    ReasonCode,
    OperationType,
    StateTransitionError,
    AuthorityError,
    StateCorruptionError,
    LockedOperationError
)
from .staging import (
    execute_staging,
    get_staging_status,
    list_artifacts,
    cleanup_artifacts,
    StagingError
)
from .validator import (
    validate_artifact,
    ArtifactValidator,
    ValidationError,
    get_validation_path
)


def get_metadata_path() -> Path:
    """Returns the path to the Agent Zero metadata directory."""
    return Path(__file__).parent / ".billy"


def read_json_file(file_path: Path) -> Dict[str, Any]:
    """Read a JSON file and return its contents."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"error": f"Failed to read file: {e}"}


def status() -> Dict[str, Any]:
    """
    Implementation of 'a0 status' command.
    Returns the current status of Agent Zero.
    
    Enhanced to include state machine information.
    """
    # Get basic status from read_only module
    basic_status = read_only.read_status_metadata()
    
    # Add state machine information
    try:
        sm = AgentZeroStateMachine()
        current_state = sm.current()
        
        # Add state machine info to status
        state_machine_info = {
            "state_machine": {
                "current_state": current_state["current_state"],
                "previous_state": current_state.get("previous_state"),
                "entered_at": current_state["entered_at"],
                "observed_state": current_state.get("observed_state", "UNKNOWN"),
                "authority_level": current_state["authority_level"]
            }
        }
        
        # Add active operation if present
        if current_state.get("active_operation"):
            state_machine_info["active_operation"] = current_state["active_operation"]
        
        # Add locks information
        if current_state.get("locks"):
            state_machine_info["locks"] = current_state["locks"]
        
        # Add last failure information if present
        if current_state.get("last_failure"):
            state_machine_info["last_failure"] = current_state["last_failure"]
        
        # Merge with basic status
        basic_status.update(state_machine_info)
        
        return basic_status
    
    except Exception as e:
        # If state machine info cannot be retrieved, still return basic status
        # but include error
        basic_status["state_machine_error"] = str(e)
        return basic_status


def check_updates() -> Dict[str, Any]:
    """
    Implementation of 'a0 check-updates' command.
    Checks for available updates for Agent Zero.
    """
    metadata_path = get_metadata_path()
    version_path = metadata_path / "version.json"
    version_data = read_json_file(version_path)
    current_version = version_data.get("version", "UNKNOWN")
    
    try:
        # Make a call to GitHub API to check for newer versions
        # For this implementation, we'll simulate no updates available
        from .github import get_github_release
        
        # In a real implementation, this would query all available releases
        # and filter for versions newer than current_version
        return {
            "status": "success",
            "current_version": current_version,
            "available_updates": [],
            "latest_version": current_version,
            "update_available": False
        }
    except GitHubAPIError as e:
        return {
            "status": "error",
            "error": f"Failed to check for updates: {str(e)}"
        }
    except Exception as e:
        return {
            "status": "error",
            "error": f"Unexpected error checking for updates: {str(e)}"
        }


def pending_approvals(json_output: bool = False) -> Dict[str, Any]:
    """
    Implementation of 'a0 pending-approvals' command.
    Returns a list of pending approval requests.
    
    Args:
        json_output: Whether to return raw JSON
    """
    try:
        # Get pending approvals
        approvals = get_pending_approvals()
        
        if json_output:
            # Return raw JSON for --json flag
            return {
                "status": "success",
                "pending_approvals": approvals
            }
        
        # Format for human readability
        if not approvals:
            return {
                "status": "success",
                "message": "No pending approvals",
                "pending_approvals": []
            }
        
        # There should be only one pending approval in Phase 2
        pending = approvals[0]
        
        return {
            "status": "success",
            "pending_approvals": [
                {
                    "agent_id": pending["agent_id"],
                    "version": pending["version"],
                    "requested_at": pending["requested_at"],
                    "requested_by": pending["requested_by"],
                    "github_release_url": pending["github_release_url"],
                    "notes": pending["notes"]
                }
            ]
        }
    
    except IntegrityViolationError as e:
        return {
            "status": "error",
            "error": f"Integrity violation: {str(e)}",
            "pending_approvals": []
        }
    
    except Exception as e:
        return {
            "status": "error",
            "error": f"Error retrieving pending approvals: {str(e)}",
            "pending_approvals": []
        }


def request_upgrade(version: str, force_check: bool = False, allow_prerelease: bool = False) -> Dict[str, Any]:
    """
    Implementation of 'a0 request-upgrade' command.
    Creates a new upgrade approval request.
    
    Args:
        version: Requested version
        force_check: Whether to replace existing pending approval
        allow_prerelease: Whether to allow prerelease versions
    """
    try:
        # Currently, only billy_frame can request upgrades
        # In a real implementation, the requester would be determined dynamically
        requester = "system:billy_frame"
        
        # Create approval request
        approval = create_approval_request(version, requester, None, force_check, allow_prerelease)
        
        return {
            "status": "success",
            "message": f"Approval request created for version {version}",
            "approval_id": approval["approval_id"],
            "version": version,
            "requested_at": approval["requested_at"]
        }
    
    except PendingApprovalExistsError as e:
        return {
            "status": "error",
            "error": str(e)
        }
    
    except InvalidVersionFormatError as e:
        return {
            "status": "error",
            "error": f"Invalid version format: {str(e)}"
        }
    
    except DowngradeAttemptError as e:
        return {
            "status": "error",
            "error": f"Downgrade not allowed: {str(e)}"
        }
    
    except InvalidVersionError as e:
        return {
            "status": "error",
            "error": f"Invalid version: {str(e)}"
        }
    
    except (RateLimitExceededError, GitHubUnavailableError) as e:
        return {
            "status": "error",
            "error": f"GitHub API error: {str(e)}"
        }
    
    except IntegrityViolationError as e:
        return {
            "status": "error",
            "error": f"Integrity violation: {str(e)}"
        }
    
    except LockAcquisitionError as e:
        return {
            "status": "error",
            "error": f"Lock acquisition failed: {str(e)}"
        }
    
    except Exception as e:
        return {
            "status": "error",
            "error": f"Unexpected error: {str(e)}"
        }


def approve_upgrade_command(version: str, is_human: bool = False) -> Dict[str, Any]:
    """
    Implementation of 'approve a0 upgrade' command.
    Grants approval for a pending upgrade.
    
    Args:
        version: Version to approve
        is_human: Whether the actor is human
    """
    try:
        # In a real implementation, the approver would be determined dynamically
        approver = "human:admin" if is_human else "system:billy_frame"
        
        # Approve upgrade
        approve_upgrade(version, approver, is_human)
        
        # After approval, transition state machine to STAGING
        # Note: In Phase 3, this only records the intent, no actual execution occurs
        try:
            # Get state machine
            sm = AgentZeroStateMachine()
            
            # Only transition if in IDLE state
            if sm.current_state() == State.IDLE:
                # Transition to STAGING
                sm.transition(
                    to_state=State.STAGING,
                    reason_code=ReasonCode.APPROVAL_GRANTED,
                    actor=approver,
                    is_human=is_human,
                    notes=f"Approval granted for upgrade to {version}",
                    metadata={
                        "operation": {
                            "type": str(OperationType.UPGRADE),
                            "target_version": version
                        }
                    }
                )
        except Exception as state_error:
            # Log state transition error but don't fail the approval
            # The approval itself succeeded
            return {
                "status": "partial_success",
                "message": f"Approval granted for version {version}, but state transition failed",
                "version": version,
                "approved_at": datetime.utcnow().isoformat() + "Z",
                "state_error": str(state_error)
            }
        
        return {
            "status": "success",
            "message": f"Approval granted for version {version}",
            "version": version,
            "approved_at": datetime.utcnow().isoformat() + "Z",
            "state": "STAGING"  # In Phase 3, we're now recording the intent to stage
        }
    
    except HumanRequiredError:
        return {
            "status": "error",
            "error": "Only humans can approve upgrades",
            "authority_required": "human"
        }
    
    except NoPendingApprovalError as e:
        return {
            "status": "error",
            "error": str(e)
        }
    
    except VersionMismatchError as e:
        return {
            "status": "error",
            "error": str(e)
        }
    
    except IntegrityViolationError as e:
        return {
            "status": "error",
            "error": f"Integrity violation: {str(e)}"
        }
    
    except LockAcquisitionError as e:
        return {
            "status": "error",
            "error": f"Lock acquisition failed: {str(e)}"
        }
    
    except Exception as e:
        return {
            "status": "error",
            "error": f"Unexpected error: {str(e)}"
        }


def deny_upgrade_command(version: str, is_human: bool = False, reason: Optional[str] = None) -> Dict[str, Any]:
    """
    Implementation of 'deny a0 upgrade' command.
    Denies a pending upgrade.
    
    Args:
        version: Version to deny
        is_human: Whether the actor is human
        reason: Optional reason for denial
    """
    try:
        # In a real implementation, the denier would be determined dynamically
        denier = "human:admin" if is_human else "system:billy_frame"
        
        # Deny upgrade
        deny_upgrade(version, denier, is_human, reason)
        
        return {
            "status": "success",
            "message": f"Approval denied for version {version}",
            "version": version,
            "denied_at": datetime.utcnow().isoformat() + "Z"
        }
    
    except HumanRequiredError:
        return {
            "status": "error",
            "error": "Only humans can deny upgrades",
            "authority_required": "human"
        }
    
    except NoPendingApprovalError as e:
        return {
            "status": "error",
            "error": str(e)
        }
    
    except VersionMismatchError as e:
        return {
            "status": "error",
            "error": str(e)
        }
    
    except LockAcquisitionError as e:
        return {
            "status": "error",
            "error": f"Lock acquisition failed: {str(e)}"
        }
    
    except Exception as e:
        return {
            "status": "error",
            "error": f"Unexpected error: {str(e)}"
        }


def explain_state(json_output: bool = False) -> Dict[str, Any]:
    """
    Implementation of 'a0 explain-state' command.
    Provides a detailed explanation of the current state.
    
    Args:
        json_output: Whether to return raw JSON
        
    Returns:
        Dict: Explanation of current state
    """
    try:
        # Get state machine
        sm = AgentZeroStateMachine()
        
        # Get explanation
        explanation = sm.explain_state()
        
        return {
            "status": "success",
            "explanation": explanation
        }
    
    except StateCorruptionError as e:
        return {
            "status": "error",
            "error": f"State corruption: {str(e)}"
        }
    
    except Exception as e:
        return {
            "status": "error",
            "error": f"Unexpected error: {str(e)}"
        }


def clear_failure(is_human: bool = False) -> Dict[str, Any]:
    """
    Implementation of 'a0 clear-failure' command.
    Clears a failure state, transitioning from FAILED to IDLE.
    
    Args:
        is_human: Whether the actor is human
        
    Returns:
        Dict: Result of the operation
    """
    # Only humans can clear failures
    if not is_human:
        return {
            "status": "error",
            "error": "Only humans can clear failures",
            "authority_required": "human"
        }
    
    try:
        # Get state machine
        sm = AgentZeroStateMachine()
        
        # Verify current state is FAILED
        if sm.current_state() != State.FAILED:
            return {
                "status": "error",
                "error": f"Cannot clear failure: current state is {sm.current_state()}, not FAILED"
            }
        
        # Transition to IDLE
        sm.transition(
            to_state=State.IDLE,
            reason_code=ReasonCode.HUMAN_CLEARED_FAILURE,
            actor="human:admin", # In a real implementation, this would be the actual human
            is_human=True,
            notes="Failure manually cleared by human"
        )
        
        return {
            "status": "success",
            "message": "Failure cleared. System is now IDLE."
        }
    
    except StateTransitionError as e:
        return {
            "status": "error",
            "error": f"Invalid state transition: {str(e)}"
        }
    
    except AuthorityError as e:
        return {
            "status": "error",
            "error": f"Authority error: {str(e)}",
            "authority_required": "human"
        }
        
    except StateCorruptionError as e:
        return {
            "status": "error",
            "error": f"State corruption: {str(e)}"
        }
    
    except Exception as e:
        return {
            "status": "error",
            "error": f"Unexpected error: {str(e)}"
        }


def begin_staging(version: str, rebuild: bool = False, dry_run: bool = False, is_human: bool = False) -> Dict[str, Any]:
    """
    Implementation of 'a0 begin-staging' command.
    Begins the staging process for a new version.
    
    Args:
        version: Version to stage
        rebuild: Whether to rebuild if artifact already exists
        dry_run: Whether to perform a dry run (validation only)
        is_human: Whether the actor is human
        
    Returns:
        Dict: Result of the operation
    """
    # Only humans with executor authority can begin staging
    if not is_human:
        return {
            "status": "error",
            "error": "Only humans can initiate staging",
            "authority_required": "executor+human"
        }
    
    try:
        # Get state machine
        sm = AgentZeroStateMachine()
        
        # Verify current state is IDLE
        if sm.current_state() != State.IDLE:
            return {
                "status": "error",
                "error": f"Cannot begin staging: current state is {sm.current_state()}, not IDLE"
            }
        
        # If dry run, just validate preconditions
        if dry_run:
            return {
                "status": "success",
                "message": "Dry run: all preconditions met",
                "version": version
            }
        
        # Execute staging
        result = execute_staging(version, rebuild)
        
        return {
            "status": result["status"],
            "message": f"Staging completed for {version}" if result["status"] == "success" else result.get("message", ""),
            "version": version,
            "build_id": result.get("build_id"),
            "artifact_path": result.get("artifact_path"),
            "tree_hash": result.get("tree_hash")
        }
    
    except StagingError as e:
        return {
            "status": "error",
            "error": f"Staging failed: {str(e)}"
        }
    
    except StateTransitionError as e:
        return {
            "status": "error",
            "error": f"State transition failed: {str(e)}"
        }
    
    except Exception as e:
        return {
            "status": "error",
            "error": f"Unexpected error: {str(e)}"
        }


def staging_status_command() -> Dict[str, Any]:
    """
    Implementation of 'a0 staging-status' command.
    Displays the current staging status.
    
    Returns:
        Dict: Staging status
    """
    try:
        status = get_staging_status()
        
        if status.get("active"):
            elapsed = status.get("elapsed_seconds", 0)
            minutes = elapsed // 60
            seconds = elapsed % 60
            
            return {
                "status": "success",
                "staging": {
                    "active": True,
                    "target_version": status.get("target_version"),
                    "build_id": status.get("build_id"),
                    "stage": status.get("stage"),
                    "progress_pct": status.get("progress_pct"),
                    "temp_path": status.get("temp_path"),
                    "elapsed": f"{minutes}m {seconds}s"
                }
            }
        else:
            return {
                "status": "success",
                "staging": {
                    "active": False,
                    "message": status.get("message", "No staging in progress")
                }
            }
    
    except Exception as e:
        return {
            "status": "error",
            "error": f"Failed to get staging status: {str(e)}"
        }


def list_artifacts_command() -> Dict[str, Any]:
    """
    Implementation of 'a0 list-artifacts' command.
    Lists all stored artifacts.
    
    Returns:
        Dict: List of artifacts
    """
    try:
        artifacts = list_artifacts()
        
        # Format artifacts for display
        formatted_artifacts = []
        for artifact in artifacts:
            size_mb = artifact["size_bytes"] / (1024 * 1024)
            formatted_artifacts.append({
                "version": artifact["version"],
                "built_at": artifact["built_at"][:10],  # Just the date
                "size_mb": round(size_mb, 1),
                "tree_hash": artifact["tree_hash"][:8] + "..."
            })
        
        return {
            "status": "success",
            "artifacts": formatted_artifacts
        }
    
    except Exception as e:
        return {
            "status": "error",
            "error": f"Failed to list artifacts: {str(e)}"
        }


def validate_command(version: Optional[str] = None, check: Optional[str] = None) -> Dict[str, Any]:
    """
    Implementation of 'a0 validate' command.
    Validates a staged artifact.
    
    Args:
        version: Version to validate (optional, uses current if not provided)
        
    Returns:
        Dict: Validation result
    """
    try:
        # If no version specified, try to get from state machine
        if not version:
            sm = AgentZeroStateMachine()
            current_state = sm.current()
            
            active_op = current_state.get("active_operation")
            if active_op:
                version = active_op.get("target_version")
            
            if not version:
                return {
                    "status": "error",
                    "error": "No version specified and no active operation"
                }
        
        # Validate artifact
        success, report = validate_artifact(version, check=check)
        
        return {
            "status": "success" if success else "failed",
            "validation_status": report["status"],
            "version": version,
            "report": report
        }
    
    except ValidationError as e:
        return {
            "status": "error",
            "error": f"Validation error: {str(e)}"
        }
    
    except Exception as e:
        return {
            "status": "error",
            "error": f"Unexpected error: {str(e)}"
        }


def report_command() -> Dict[str, Any]:
    """
    Implementation of 'a0 report' command.
    Displays the latest validation report.
    
    Returns:
        Dict: Latest validation report
    """
    try:
        latest_report_path = get_validation_path() / "latest_report.json"
        
        if not latest_report_path.exists():
            return {
                "status": "error",
                "error": "No validation report found. Run 'a0 validate' first."
            }
        
        with open(latest_report_path, 'r') as f:
            report = json.load(f)
        
        return {
            "status": "success",
            "report": report
        }
    
    except Exception as e:
        return {
            "status": "error",
            "error": f"Failed to read report: {str(e)}"
        }


def cleanup_artifacts_command(keep: int = 2, is_human: bool = False) -> Dict[str, Any]:
    """
    Implementation of 'a0 cleanup-artifacts' command.
    Cleans up old artifacts.
    
    Args:
        keep: Number of artifacts to keep
        is_human: Whether the actor is human
        
    Returns:
        Dict: Result of cleanup
    """
    # Only humans with executor authority can cleanup artifacts
    if not is_human:
        return {
            "status": "error",
            "error": "Only humans can cleanup artifacts",
            "authority_required": "executor+human"
        }
    
    try:
        deleted = cleanup_artifacts(keep)
        
        return {
            "status": "success",
            "message": f"Cleaned up {len(deleted)} old artifact(s)",
            "deleted_count": len(deleted),
            "deleted_paths": deleted
        }
    
    except Exception as e:
        return {
            "status": "error",
            "error": f"Cleanup failed: {str(e)}"
        }


def promote_command(version: str) -> Dict[str, Any]:
    lock_file = None
    try:
        from .state_machine import AgentZeroStateMachine, State, ReasonCode
        
        # Acquire lock
        lock_file = None
        try:
            lock_file = acquire_lock()
        except LockAcquisitionError as e:
            return {
                "status": "error",
                "error": f"Lock acquisition failed: {str(e)}"
            }
        
        # Get paths
        metadata_path = get_metadata_path()
        agent_zero_path = Path(__file__).parent
        artifact_path = metadata_path / "artifacts" / version / "agent_zero"
        promotion_path = metadata_path / "promotion"
        live_path = agent_zero_path
        prev_path = agent_zero_path.parent / "agent_zero.prev"
        
        # Create promotion directory
        promotion_path.mkdir(parents=True, exist_ok=True)
        
        # Verify artifact exists
        if not artifact_path.exists():
            release_lock(lock_file)
            return {
                "status": "error",
                "error": f"Artifact not found: {artifact_path}"
            }
        
        # Get state machine
        sm = AgentZeroStateMachine()
        current_state = sm.current_state()
        
        # Verify we're in PROMOTING state
        if current_state != "PROMOTING":
            release_lock(lock_file)
            return {
                "status": "error",
                "error": f"Cannot promote: current state is {current_state}, not PROMOTING"
            }
        
        # Step 1: Archive current live to .prev
        try:
            if prev_path.exists():
                shutil.rmtree(prev_path)
            shutil.move(str(live_path), str(prev_path))
        except Exception as e:
            release_lock(lock_file)
            return {
                "status": "error",
                "error": f"Failed to archive current live: {str(e)}",
                "exit_code": 2
            }
        
        # Step 2: Copy artifact to live
        try:
            shutil.copytree(str(artifact_path), str(live_path))
        except Exception as e:
            # Rollback: restore .prev
            try:
                if live_path.exists():
                    shutil.rmtree(live_path)
                shutil.move(str(prev_path), str(live_path))
            except:
                pass
            
            release_lock(lock_file)
            return {
                "status": "error",
                "error": f"Failed to promote artifact: {str(e)}",
                "exit_code": 2
            }
        
        # Step 3: Run smoke tests
        try:
            # Simple smoke test - check if critical files exist
            critical_files = ["agent.py", "models.py", "prompts", "python"]
            missing_files = []
            
            for file_name in critical_files:
                file_path = live_path / file_name
                if not file_path.exists():
                    missing_files.append(file_name)
            
            if missing_files:
                # Smoke test failed - keep promotion in place (no auto-rollback)
                report = {
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "status": "FAILED",
                    "from": f"artifacts/{version}/agent_zero/",
                    "to": "v2/agent_zero/",
                    "notes": f"Smoke test failed: missing {', '.join(missing_files)}"
                }
                
                with open(promotion_path / "latest_report.json", 'w') as f:
                    json.dump(report, f, indent=2)
                
                # Update state to FAILED
                sm.transition(
                    to_state=State.FAILED,
                    reason_code=ReasonCode.VALIDATION_ERROR,
                    notes=f"Smoke test failed: {', '.join(missing_files)}"
                )
                
                release_lock(lock_file)
                return {
                    "status": "failed",
                    "error": f"Smoke test failed: missing {', '.join(missing_files)}",
                    "exit_code": 1
                }
            
        except Exception as e:
            release_lock(lock_file)
            return {
                "status": "error",
                "error": f"Smoke test failed: {str(e)}",
                "exit_code": 1
            }
        
        # Step 4: Update state and write report
        try:
            # Update state to COMPLETE
            sm.transition(
                to_state=State.COMPLETE,
                reason_code=ReasonCode.APPROVAL_GRANTED,
                notes=f"Successfully promoted {version} to live"
            )
            
            # Write promotion report
            report = {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "status": "PROMOTED",
                "from": f"artifacts/{version}/agent_zero/",
                "to": "v2/agent_zero/",
                "notes": f"Successfully promoted {version}"
            }
            
            with open(promotion_path / "latest_report.json", 'w') as f:
                json.dump(report, f, indent=2)
            
            release_lock(lock_file)
            return {
                "status": "success",
                "message": f"Successfully promoted {version}",
                "version": version
            }
            
        except Exception as e:
            release_lock(lock_file)
            return {
                "status": "error",
                "error": f"Failed to update state: {str(e)}"
            }
            
    except Exception as e:
        if 'lock_file' in locals() and lock_file:
            release_lock(lock_file)
        return {
            "status": "error",
            "error": f"Unexpected error: {str(e)}"
        }


def rollback_command() -> Dict[str, Any]:
    lock_file = None
    try:
        from .state_machine import AgentZeroStateMachine, State, ReasonCode
        
        # Acquire lock
        lock_file = None
        try:
            lock_file = acquire_lock()
        except LockAcquisitionError as e:
            return {
                "status": "error",
                "error": f"Lock acquisition failed: {str(e)}",
                "exit_code": 1
            }
        
        # Get paths
        agent_zero_path = Path(__file__).parent
        prev_path = agent_zero_path.parent / "agent_zero.prev"
        metadata_path = get_metadata_path()
        state_path = metadata_path / "state.json"
        promotion_path = metadata_path / "promotion"
        
        # Verify .prev exists
        if not prev_path.exists():
            release_lock(lock_file)
            return {
                "status": "error",
                "error": "Previous version not found: agent_zero.prev/ does not exist",
                "exit_code": 1
            }
        
        # Verify state.json exists
        if not state_path.exists():
            release_lock(lock_file)
            return {
                "status": "error",
                "error": "State file not found: .billy/state.json",
                "exit_code": 1
            }
        
        # Get state machine
        sm = AgentZeroStateMachine()
        
        # Step 1: Archive current live to failed with timestamp
        try:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            failed_path = agent_zero_path.parent / f"agent_zero.failed.{timestamp}"
            
            if agent_zero_path.exists():
                shutil.move(str(agent_zero_path), str(failed_path))
        except Exception as e:
            release_lock(lock_file)
            return {
                "status": "error",
                "error": f"Failed to archive current live: {str(e)}",
                "exit_code": 2
            }
        
        # Step 2: Promote previous to live
        try:
            shutil.move(str(prev_path), str(agent_zero_path))
        except Exception as e:
            release_lock(lock_file)
            return {
                "status": "error",
                "error": f"Failed to promote previous version: {str(e)}",
                "exit_code": 2
            }
        
        # Step 3: Update state.json
        try:
            # Update state to IDLE
            sm.transition(
                to_state=State.IDLE,
                reason_code=ReasonCode.OPERATOR_RESET,
                notes="manual rollback executed"
            )
            
        except Exception as e:
            release_lock(lock_file)
            return {
                "status": "error",
                "error": f"Failed to update state: {str(e)}"
            }
        
        # Step 4: Write rollback report
        try:
            promotion_path.mkdir(parents=True, exist_ok=True)
            
            report = {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "status": "ROLLED_BACK",
                "from": "v2/agent_zero.prev/",
                "to": "v2/agent_zero/",
                "notes": "manual rollback invoked"
            }
            
            with open(promotion_path / "rollback_report.json", 'w') as f:
                json.dump(report, f, indent=2)
            
            release_lock(lock_file)
            return {
                "status": "success",
                "message": "Successfully rolled back to previous version"
            }
            
        except Exception as e:
            release_lock(lock_file)
            return {
                "status": "error",
                "error": f"Failed to write rollback report: {str(e)}"
            }
            
    except Exception as e:
        if 'lock_file' in locals() and lock_file:
            release_lock(lock_file)
        return {
            "status": "error",
            "error": f"Unexpected error: {str(e)}"
        }


def confirm(is_human: bool = False) -> Dict[str, Any]:
    """
    Implementation of 'a0 confirm' command.
    Confirms the completion of an operation, transitioning from COMPLETE to IDLE.
    
    Args:
        is_human: Whether the actor is human
        
    Returns:
        Dict: Result of the operation
    """
    # Only humans can confirm
    if not is_human:
        return {
            "status": "error",
            "error": "Only humans can confirm operations",
            "authority_required": "human"
        }
    
    try:
        # Get state machine
        sm = AgentZeroStateMachine()
        
        # Verify current state is COMPLETE
        if sm.current_state() != State.COMPLETE:
            return {
                "status": "error",
                "error": f"Cannot confirm: current state is {sm.current_state()}, not COMPLETE"
            }
        
        # Transition to IDLE
        sm.transition(
            to_state=State.IDLE,
            reason_code=ReasonCode.CONFIRMATION_RECEIVED,
            actor="human:admin", # In a real implementation, this would be the actual human
            is_human=True,
            notes="Operation completion confirmed by human"
        )
        
        return {
            "status": "success",
            "message": "Operation confirmed. System is now IDLE."
        }
    
    except StateTransitionError as e:
        return {
            "status": "error",
            "error": f"Invalid state transition: {str(e)}"
        }
    
    except AuthorityError as e:
        return {
            "status": "error",
            "error": f"Authority error: {str(e)}",
            "authority_required": "human"
        }
        
    except StateCorruptionError as e:
        return {
            "status": "error",
            "error": f"State corruption: {str(e)}"
        }
    
    except Exception as e:
        return {
            "status": "error",
            "error": f"Unexpected error: {str(e)}"
        }


def handle_command(command: str) -> Optional[Dict[str, Any]]:
    """
    Handles Agent Zero commands.
    
    Args:
        command: The command string (starting with 'a0 ')
        
    Returns:
        Command result as dictionary or None if command is not recognized
    """
    if not command.startswith("a0 ") and not command.startswith("approve a0 ") and not command.startswith("deny a0 "):
        return None
    
    # Handle read-only environment commands
    if command.startswith("a0 env "):
        return read_only.execute_command(command)
    
    # Parse command
    parts = command.strip().split()
    
    # Handle approval commands
    if command.startswith("approve a0 "):
        if len(parts) < 4 or parts[2] != "upgrade":
            return {"status": "error", "error": "Invalid command format. Use: approve a0 upgrade <version>"}
        
        version = parts[3]
        # In a real implementation, is_human would be determined dynamically
        # For Phase 3, we'll simulate human approvals
        is_human = True
        
        return approve_upgrade_command(version, is_human)
    
    # Handle denial commands
    if command.startswith("deny a0 "):
        if len(parts) < 4 or parts[2] != "upgrade":
            return {"status": "error", "error": "Invalid command format. Use: deny a0 upgrade <version>"}
        
        version = parts[3]
        # In a real implementation, is_human would be determined dynamically
        # For Phase 3, we'll simulate human denials
        is_human = True
        
        reason = None
        if len(parts) > 4 and parts[4] == "--reason":
            reason = " ".join(parts[5:])
        
        return deny_upgrade_command(version, is_human, reason)
    
    # Handle standard lifecycle commands
    # Remove 'a0 ' prefix
    cmd_parts = parts[1:]
    
    if not cmd_parts:
        return {"status": "error", "error": "Invalid command format"}
    
    command_name = cmd_parts[0]
    
    if command_name == "status":
        return status()
    
    elif command_name == "check-updates":
        return check_updates()
    
    elif command_name == "pending-approvals":
        json_output = "--json" in cmd_parts
        return pending_approvals(json_output)
    
    elif command_name == "request-upgrade":
        if len(cmd_parts) < 2:
            return {"status": "error", "error": "Missing version. Use: a0 request-upgrade <version>"}
        
        version = cmd_parts[1]
        force_check = "--force-check" in cmd_parts
        allow_prerelease = "--allow-prerelease" in cmd_parts
        
        return request_upgrade(version, force_check, allow_prerelease)
    
    elif command_name == "explain-state":
        json_output = "--json" in cmd_parts
        return explain_state(json_output)
    
    elif command_name == "clear-failure":
        # In a real implementation, is_human would be determined dynamically
        is_human = True
        return clear_failure(is_human)
    
    elif command_name == "confirm":
        # In a real implementation, is_human would be determined dynamically
        is_human = True
        return confirm(is_human)
    
    elif command_name == "begin-staging":
        if len(cmd_parts) < 2:
            return {"status": "error", "error": "Missing version. Use: a0 begin-staging <version>"}
        
        version = cmd_parts[1]
        rebuild = "--rebuild" in cmd_parts
        dry_run = "--dry-run" in cmd_parts
        is_human = True  # In a real implementation, this would be determined dynamically
        
        return begin_staging(version, rebuild, dry_run, is_human)
    
    elif command_name == "staging-status":
        return staging_status_command()
    
    elif command_name == "list-artifacts":
        return list_artifacts_command()
    
    elif command_name == "cleanup-artifacts":
        keep = 2  # Default
        if "--keep" in cmd_parts:
            try:
                keep_idx = cmd_parts.index("--keep")
                if keep_idx + 1 < len(cmd_parts):
                    keep = int(cmd_parts[keep_idx + 1])
            except (ValueError, IndexError):
                return {"status": "error", "error": "Invalid --keep value. Use: a0 cleanup-artifacts --keep N"}
        
        is_human = True  # In a real implementation, this would be determined dynamically
        return cleanup_artifacts_command(keep, is_human)
    
    elif command_name == "validate":
        version = None
        if len(cmd_parts) >= 2 and cmd_parts[1].startswith("v"):
            version = cmd_parts[1]
        elif "--version" in cmd_parts:
            try:
                version_idx = cmd_parts.index("--version")
                if version_idx + 1 < len(cmd_parts):
                    version = cmd_parts[version_idx + 1]
            except (ValueError, IndexError):
                return {"status": "error", "error": "Invalid --version value"}
        
        check = None
        if "--check" in cmd_parts:
            try:
                check_idx = cmd_parts.index("--check")
                if check_idx + 1 < len(cmd_parts):
                    check = cmd_parts[check_idx + 1]
            except (ValueError, IndexError):
                return {"status": "error", "error": "Invalid --check value"}

        return validate_command(version, check=check)
    
    elif command_name == "report":
        return report_command()
    
    elif command_name == "promote":
        version = None
        if len(cmd_parts) >= 2 and cmd_parts[1] == "--version":
            version = cmd_parts[2] if len(cmd_parts) > 2 else None
        elif "--version" in cmd_parts:
            try:
                version_idx = cmd_parts.index("--version")
                if version_idx + 1 < len(cmd_parts):
                    version = cmd_parts[version_idx + 1]
            except (ValueError, IndexError):
                return {"status": "error", "error": "Invalid --version value"}
        
        if not version:
            return {"status": "error", "error": "Missing version. Use: a0 promote --version <version>"}
        
        return promote_command(version)
    
    elif command_name == "rollback":
        return rollback_command()
    
    elif command_name == "upgrade":
        # For now, all upgrade commands are blocked by observer mode
        return {
            "status": "error", 
            "error": "Command not available in observer mode", 
            "authority_required": "executor"
        }
    
    else:
        return {"status": "error", "error": f"Unknown command: {command_name}"}