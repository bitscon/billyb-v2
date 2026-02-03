"""
Staging executor for Agent Zero lifecycle management.

This module implements the staging execution layer, which acquires, clones,
and prepares a new Agent Zero version in complete isolation from production.
"""

import os
import json
import shutil
import subprocess
import hashlib
import uuid
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

from .schema import validate_json_schema, SchemaValidationError
from .github import get_github_release
from .audit import log_event, EVENT_TYPES
from .state_machine import (
    AgentZeroStateMachine,
    State,
    ReasonCode,
    OperationType,
    StateTransitionError
)
from .fileops import acquire_lock, release_lock, LockAcquisitionError

# Add new event types for staging
EVENT_TYPES.extend([
    "staging_started",
    "clone_completed",
    "clone_failed",
    "dependencies_installed",
    "dependencies_failed",
    "checksums_computed",
    "artifact_stored",
    "staging_completed",
    "staging_failed",
    "temp_cleanup_completed",
    "artifact_deleted"
])

# Repository URL for Agent Zero
AGENT_ZERO_REPO = "https://github.com/frdel/agent-zero.git"

# Manifest schema for artifacts
MANIFEST_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": [
        "version",
        "built_at",
        "source_url",
        "commit_sha",
        "checksums",
        "build_id"
    ],
    "properties": {
        "version": {
            "type": "string",
            "pattern": "^v\\d+\\.\\d+\\.\\d+"
        },
        "built_at": {
            "type": "string",
            "format": "date-time"
        },
        "source_url": {
            "type": "string",
            "format": "uri"
        },
        "commit_sha": {
            "type": "string",
            "pattern": "^[a-f0-9]{40}$"
        },
        "checksums": {
            "type": "object",
            "properties": {
                "algorithm": {"const": "sha256"},
                "files": {
                    "type": "object",
                    "additionalProperties": {
                        "type": "string",
                        "pattern": "^[a-f0-9]{64}$"
                    }
                },
                "tree_hash": {
                    "type": "string",
                    "pattern": "^[a-f0-9]{64}$"
                }
            },
            "required": ["algorithm", "files", "tree_hash"]
        },
        "build_id": {
            "type": "string",
            "pattern": "^[a-f0-9\\-]{36}$"
        },
        "build_log_path": {
            "type": ["string", "null"]
        },
        "virtualenv_hash": {
            "type": ["string", "null"]
        }
    },
    "additionalProperties": False
}

# Custom exceptions
class StagingError(Exception):
    """Base class for staging errors."""
    pass

class CloneError(StagingError):
    """Raised when git clone fails."""
    pass

class DependencyError(StagingError):
    """Raised when dependency installation fails."""
    pass

class ChecksumError(StagingError):
    """Raised when checksum computation fails."""
    pass

class ArtifactError(StagingError):
    """Raised when artifact creation fails."""
    pass


def get_metadata_path() -> Path:
    """Returns the path to Agent Zero metadata directory."""
    return Path(__file__).parent / ".billy"


def get_artifacts_path() -> Path:
    """Returns the path to artifacts directory."""
    artifacts_path = get_metadata_path() / "artifacts"
    os.makedirs(artifacts_path, exist_ok=True)
    return artifacts_path


def get_artifact_path(version: str) -> Path:
    """Returns the path to a specific artifact version."""
    return get_artifacts_path() / version


def generate_build_id() -> str:
    """Generate a unique build ID."""
    return str(uuid.uuid4())


def get_temp_path(build_id: str) -> Path:
    """Returns the temporary build path for a build ID."""
    return Path(f"/tmp/agent_zero_build_{build_id}")


def cleanup_temp_directory(temp_path: Path) -> None:
    """
    Clean up a temporary build directory.
    
    Args:
        temp_path: Path to temporary directory
    """
    if temp_path and str(temp_path).startswith("/tmp/agent_zero_build_"):
        try:
            if temp_path.exists():
                shutil.rmtree(temp_path, ignore_errors=True)
                log_event("temp_cleanup_completed", {"path": str(temp_path)})
        except Exception as e:
            # Log but don't raise - cleanup is best effort
            log_event("temp_cleanup_failed", {
                "path": str(temp_path),
                "error": str(e)
            })


def clone_repository(version: str, temp_path: Path, commit_sha: str) -> None:
    """
    Clone the Agent Zero repository at a specific version.
    
    Args:
        version: Version tag to clone
        temp_path: Temporary path for cloning
        commit_sha: Expected commit SHA for verification
        
    Raises:
        CloneError: If clone fails
    """
    try:
        # Ensure temp directory exists
        os.makedirs(temp_path, exist_ok=True)
        
        # Clone with depth 1 and specific branch/tag
        cmd = [
            "git", "clone",
            "--depth", "1",
            "--branch", version,
            AGENT_ZERO_REPO,
            str(temp_path)
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            check=False,
            timeout=300  # 5 minute timeout
        )
        
        if result.returncode != 0:
            error_msg = result.stderr.decode("utf-8", errors="replace")
            raise CloneError(f"Git clone failed: {error_msg}")
        
        # Verify commit SHA
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(temp_path),
            capture_output=True,
            check=False
        )
        
        if result.returncode == 0:
            actual_sha = result.stdout.decode("utf-8").strip()
            if actual_sha != commit_sha:
                raise CloneError(
                    f"Commit SHA mismatch: expected {commit_sha}, got {actual_sha}"
                )
        
        log_event("clone_completed", {
            "version": version,
            "commit_sha": commit_sha,
            "path": str(temp_path)
        })
        
    except subprocess.TimeoutExpired:
        raise CloneError("Git clone timed out after 5 minutes")
    except Exception as e:
        log_event("clone_failed", {
            "version": version,
            "error": str(e)
        })
        raise CloneError(f"Clone failed: {str(e)}")


def create_virtualenv(temp_path: Path) -> None:
    """
    Create a virtual environment and install dependencies.
    
    Args:
        temp_path: Path to cloned repository
        
    Raises:
        DependencyError: If virtualenv creation or pip install fails
    """
    try:
        venv_path = temp_path / ".venv"
        
        # Create virtualenv
        result = subprocess.run(
            ["python3", "-m", "venv", str(venv_path)],
            capture_output=True,
            check=False,
            timeout=60
        )
        
        if result.returncode != 0:
            error_msg = result.stderr.decode("utf-8", errors="replace")
            raise DependencyError(f"Virtualenv creation failed: {error_msg}")
        
        # Install dependencies
        pip_path = venv_path / "bin" / "pip"
        requirements_path = temp_path / "requirements.txt"
        
        if requirements_path.exists():
            result = subprocess.run(
                [str(pip_path), "install", "-r", str(requirements_path)],
                capture_output=True,
                check=False,
                timeout=600  # 10 minute timeout for pip install
            )
            
            if result.returncode != 0:
                error_msg = result.stderr.decode("utf-8", errors="replace")
                raise DependencyError(f"Pip install failed: {error_msg}")
        
        log_event("dependencies_installed", {
            "path": str(temp_path),
            "venv_path": str(venv_path)
        })
        
    except subprocess.TimeoutExpired:
        raise DependencyError("Dependency installation timed out")
    except Exception as e:
        log_event("dependencies_failed", {
            "path": str(temp_path),
            "error": str(e)
        })
        raise DependencyError(f"Dependency installation failed: {str(e)}")


def compute_checksums(temp_path: Path) -> Tuple[Dict[str, str], str]:
    """
    Compute SHA256 checksums for all files in the directory.
    
    Args:
        temp_path: Path to directory
        
    Returns:
        Tuple of (file_checksums dict, tree_hash)
        
    Raises:
        ChecksumError: If checksum computation fails
    """
    try:
        file_checksums = {}
        
        # Walk all files and compute checksums
        for root, dirs, files in os.walk(temp_path):
            # Skip .git directory
            if '.git' in dirs:
                dirs.remove('.git')
            
            for file in files:
                file_path = Path(root) / file
                relative_path = file_path.relative_to(temp_path)
                
                # Compute SHA256
                hasher = hashlib.sha256()
                try:
                    with open(file_path, 'rb') as f:
                        for chunk in iter(lambda: f.read(4096), b''):
                            hasher.update(chunk)
                    
                    file_checksums[str(relative_path)] = hasher.hexdigest()
                except Exception as e:
                    # Skip files that can't be read
                    continue
        
        # Compute tree hash (SHA256 of sorted file hashes)
        sorted_hashes = sorted(file_checksums.items())
        tree_data = json.dumps(sorted_hashes, sort_keys=True)
        tree_hash = hashlib.sha256(tree_data.encode()).hexdigest()
        
        log_event("checksums_computed", {
            "file_count": len(file_checksums),
            "tree_hash": tree_hash
        })
        
        return file_checksums, tree_hash
        
    except Exception as e:
        raise ChecksumError(f"Checksum computation failed: {str(e)}")


def finalize_artifact(
    version: str,
    temp_path: Path,
    build_id: str,
    commit_sha: str,
    file_checksums: Dict[str, str],
    tree_hash: str
) -> Path:
    """
    Finalize the artifact by moving it to the artifacts directory.
    
    Args:
        version: Version string
        temp_path: Temporary build path
        build_id: Build ID
        commit_sha: Commit SHA
        file_checksums: File checksums dictionary
        tree_hash: Tree hash
        
    Returns:
        Path to finalized artifact
        
    Raises:
        ArtifactError: If artifact finalization fails
    """
    try:
        # Create artifact directory
        artifact_path = get_artifact_path(version)
        os.makedirs(artifact_path, exist_ok=True)
        
        # Create manifest
        manifest = {
            "version": version,
            "built_at": datetime.utcnow().isoformat() + "Z",
            "source_url": AGENT_ZERO_REPO,
            "commit_sha": commit_sha,
            "checksums": {
                "algorithm": "sha256",
                "files": file_checksums,
                "tree_hash": tree_hash
            },
            "build_id": build_id,
            "build_log_path": None,
            "virtualenv_hash": None
        }
        
        # Validate manifest against schema
        validate_json_schema(manifest, MANIFEST_SCHEMA)
        
        # Move files from temp to artifact directory
        for item in temp_path.iterdir():
            # Skip .git directory
            if item.name == '.git':
                continue
            
            dest = artifact_path / item.name
            if dest.exists():
                if dest.is_dir():
                    shutil.rmtree(dest)
                else:
                    dest.unlink()
            
            if item.is_dir():
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)
        
        # Write manifest
        manifest_path = artifact_path / "manifest.json"
        with open(manifest_path, 'w') as f:
            json.dump(manifest, f, indent=2)
        
        log_event("artifact_stored", {
            "version": version,
            "build_id": build_id,
            "path": str(artifact_path),
            "tree_hash": tree_hash
        })
        
        return artifact_path
        
    except Exception as e:
        raise ArtifactError(f"Artifact finalization failed: {str(e)}")


def handle_staging_failure(
    error: Exception,
    build_id: str,
    temp_path: Optional[Path],
    current_stage: str
) -> None:
    """
    Handle a staging failure by cleaning up and transitioning to FAILED state.
    
    Args:
        error: The exception that caused the failure
        build_id: Build ID
        temp_path: Temporary build path
        current_stage: Current stage of staging process
    """
    # Log the failure
    log_event("staging_failed", {
        "build_id": build_id,
        "error": str(error),
        "stage": current_stage
    })
    
    # Cleanup temp directory
    if temp_path:
        cleanup_temp_directory(temp_path)
    
    # Transition to FAILED
    try:
        sm = AgentZeroStateMachine()
        sm.transition(
            to_state=State.FAILED,
            reason_code=ReasonCode.VALIDATION_ERROR,
            notes=f"Staging failed at {current_stage}: {str(error)}",
            metadata={"build_id": build_id, "stage": current_stage}
        )
    except Exception as transition_error:
        # Log transition error but don't raise
        log_event("state_transition_failed", {
            "error": str(transition_error)
        })


def execute_staging(version: str, rebuild: bool = False) -> Dict[str, Any]:
    """
    Execute the full staging workflow.
    
    Args:
        version: Version to stage
        rebuild: Whether to rebuild if artifact already exists
        
    Returns:
        Dict with status and details
        
    Raises:
        StagingError: If staging fails
    """
    build_id = generate_build_id()
    temp_path = None
    current_stage = "initialization"
    lock_file = None
    
    try:
        # Check if artifact already exists
        artifact_path = get_artifact_path(version)
        if artifact_path.exists() and not rebuild:
            return {
                "status": "skipped",
                "message": f"Artifact for {version} already exists. Use --rebuild to force.",
                "artifact_path": str(artifact_path)
            }
        
        # STEP 1: INITIALIZE
        temp_path = get_temp_path(build_id)
        
        # Acquire lock
        lock_file = acquire_lock()
        
        # Get release information from GitHub
        release = get_github_release(version)
        commit_sha = release.get("target_commitish", "")
        
        if not commit_sha:
            # Try to get commit SHA from tag_name
            commit_sha = release.get("tag_name", version)
        
        # Transition to STAGING
        sm = AgentZeroStateMachine()
        sm.transition(
            to_state=State.STAGING,
            reason_code=ReasonCode.APPROVAL_GRANTED,
            notes=f"Beginning staging for {version}",
            metadata={
                "operation": {
                    "type": str(OperationType.UPGRADE),
                    "target_version": version
                },
                "staging": {
                    "build_id": build_id,
                    "temp_path": str(temp_path),
                    "stage": "initializing",
                    "progress_pct": 0
                }
            }
        )
        
        log_event("staging_started", {
            "version": version,
            "build_id": build_id,
            "temp_path": str(temp_path)
        })
        
        # STEP 2: CLONE
        current_stage = "cloning"
        clone_repository(version, temp_path, commit_sha)
        
        # STEP 3: CREATE VIRTUALENV
        current_stage = "installing"
        create_virtualenv(temp_path)
        
        # STEP 4: CHECKSUM
        current_stage = "checksumming"
        file_checksums, tree_hash = compute_checksums(temp_path)
        
        # STEP 5: FINALIZE ARTIFACT
        current_stage = "finalizing"
        final_artifact_path = finalize_artifact(
            version, temp_path, build_id, commit_sha,
            file_checksums, tree_hash
        )
        
        # STEP 6: TRANSITION TO VALIDATING
        sm.transition(
            to_state=State.VALIDATING,
            reason_code=ReasonCode.APPROVAL_GRANTED,
            notes=f"Staging completed for {version}",
            metadata={
                "artifact_path": str(final_artifact_path),
                "tree_hash": tree_hash
            }
        )
        
        log_event("staging_completed", {
            "version": version,
            "build_id": build_id,
            "artifact_path": str(final_artifact_path)
        })
        
        # Cleanup temp directory
        cleanup_temp_directory(temp_path)
        
        return {
            "status": "success",
            "version": version,
            "build_id": build_id,
            "artifact_path": str(final_artifact_path),
            "tree_hash": tree_hash
        }
        
    except Exception as e:
        handle_staging_failure(e, build_id, temp_path, current_stage)
        raise StagingError(f"Staging failed at {current_stage}: {str(e)}")
        
    finally:
        # Release lock
        release_lock(lock_file)


def get_staging_status() -> Dict[str, Any]:
    """
    Get the current staging status.
    
    Returns:
        Dict with staging status
    """
    try:
        sm = AgentZeroStateMachine()
        current_state = sm.current()
        
        if current_state["current_state"] != "STAGING":
            return {
                "active": False,
                "message": "No staging in progress"
            }
        
        active_op = current_state.get("active_operation", {})
        staging_info = active_op.get("staging", {})
        
        # Calculate elapsed time
        started_at = active_op.get("started_at")
        if started_at:
            start_time = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
            elapsed = (datetime.utcnow() - start_time.replace(tzinfo=None)).total_seconds()
        else:
            elapsed = 0
        
        return {
            "active": True,
            "target_version": active_op.get("target_version"),
            "build_id": staging_info.get("build_id"),
            "stage": staging_info.get("stage"),
            "progress_pct": staging_info.get("progress_pct", 0),
            "temp_path": staging_info.get("temp_path"),
            "elapsed_seconds": int(elapsed)
        }
        
    except Exception as e:
        return {
            "error": str(e)
        }


def list_artifacts() -> List[Dict[str, Any]]:
    """
    List all stored artifacts.
    
    Returns:
        List of artifact information
    """
    artifacts = []
    artifacts_path = get_artifacts_path()
    
    if not artifacts_path.exists():
        return artifacts
    
    for version_dir in artifacts_path.iterdir():
        if not version_dir.is_dir():
            continue
        
        manifest_path = version_dir / "manifest.json"
        if not manifest_path.exists():
            continue
        
        try:
            with open(manifest_path, 'r') as f:
                manifest = json.load(f)
            
            # Calculate directory size
            total_size = sum(
                f.stat().st_size
                for f in version_dir.rglob('*')
                if f.is_file()
            )
            
            artifacts.append({
                "version": manifest["version"],
                "built_at": manifest["built_at"],
                "tree_hash": manifest["checksums"]["tree_hash"],
                "size_bytes": total_size,
                "path": str(version_dir)
            })
        except Exception:
            # Skip invalid artifacts
            continue
    
    # Sort by version
    artifacts.sort(key=lambda x: x["version"], reverse=True)
    
    return artifacts


def cleanup_artifacts(keep: int = 2) -> List[str]:
    """
    Clean up old artifacts, keeping the most recent N.
    
    Args:
        keep: Number of artifacts to keep
        
    Returns:
        List of deleted artifact paths
    """
    artifacts = list_artifacts()
    
    # Always keep current version and known_good version
    # For now, we'll just keep the most recent N
    if len(artifacts) <= keep:
        return []
    
    deleted = []
    for artifact in artifacts[keep:]:
        version_dir = Path(artifact["path"])
        try:
            shutil.rmtree(version_dir)
            log_event("artifact_deleted", {
                "version": artifact["version"],
                "path": str(version_dir)
            })
            deleted.append(str(version_dir))
        except Exception as e:
            # Log but continue
            log_event("artifact_delete_failed", {
                "version": artifact["version"],
                "error": str(e)
            })
    
    return deleted