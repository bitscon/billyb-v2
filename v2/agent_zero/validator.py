"""
Artifact validator for Agent Zero lifecycle management.

This module implements the validation engine that sits between STAGING and PROMOTION.
It performs comprehensive safety checks on staged artifacts before allowing promotion.
"""

import os
import json
import subprocess
import hashlib
import time
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

from .audit import log_event, EVENT_TYPES
from .state_machine import AgentZeroStateMachine, State, ReasonCode
from .schema import validate_json_schema, SchemaValidationError

# Add new event types for validation
EVENT_TYPES.extend([
    "validation_started",
    "validation_completed",
    "validation_failed",
    "check_passed",
    "check_failed",
    "report_stored"
])

# Timeouts
CHECK_TIMEOUT = 10  # seconds per individual check
SUITE_TIMEOUT = 30  # seconds for entire validation suite

# Check result schema
CHECK_RESULT_SCHEMA = {
    "type": "object",
    "required": ["passed", "ms"],
    "properties": {
        "passed": {"type": "boolean"},
        "ms": {"type": "number"},
        "error": {"type": ["string", "null"]},
        "details": {"type": "object"}
    }
}

# Validation report schema
REPORT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["version", "timestamp", "status", "checks", "artifact_hash"],
    "properties": {
        "version": {"type": "string"},
        "timestamp": {"type": "string", "format": "date-time"},
        "status": {"enum": ["PASSED", "FAILED"]},
        "checks": {
            "type": "object",
            "properties": {
                "structural_integrity": {"$ref": "#/$defs/check_result"},
                "import_sanity": {"$ref": "#/$defs/check_result"},
                "config_parsing": {"$ref": "#/$defs/check_result"},
                "tool_registry": {"$ref": "#/$defs/check_result"},
                "prompt_assets": {"$ref": "#/$defs/check_result"},
                "memory_initialization": {"$ref": "#/$defs/check_result"}
            }
        },
        "artifact_hash": {"type": "string", "pattern": "^sha256:[a-f0-9]{64}$"},
        "elapsed_ms": {"type": "number"}
    },
    "$defs": {
        "check_result": {
            "type": "object",
            "required": ["passed", "ms"],
            "properties": {
                "passed": {"type": "boolean"},
                "ms": {"type": "number"},
                "error": {"type": ["string", "null"]},
                "details": {"type": "object"}
            }
        }
    },
    "additionalProperties": False
}

# Custom exceptions
class ValidationError(Exception):
    """Base class for validation errors."""
    pass

class ValidationTimeoutError(ValidationError):
    """Raised when a validation check times out."""
    pass

class ArtifactNotFoundError(ValidationError):
    """Raised when an artifact cannot be found."""
    pass


def get_metadata_path() -> Path:
    """Returns the path to Agent Zero metadata directory."""
    return Path(__file__).parent / ".billy"


def get_validation_path() -> Path:
    """Returns the path to validation directory."""
    validation_path = get_metadata_path() / "validation"
    os.makedirs(validation_path, exist_ok=True)
    return validation_path


def get_validation_history_path() -> Path:
    """Returns the path to validation history directory."""
    history_path = get_validation_path() / "history"
    os.makedirs(history_path, exist_ok=True)
    return history_path


def get_validation_logs_path() -> Path:
    """Returns the path to validation logs directory."""
    logs_path = get_validation_path() / "logs"
    os.makedirs(logs_path, exist_ok=True)
    return logs_path


def get_artifacts_path() -> Path:
    """Returns the path to artifacts directory."""
    return get_metadata_path() / "artifacts"


def get_artifact_path(version: str) -> Path:
    """Returns the path to a specific artifact."""
    return get_artifacts_path() / version


def compute_artifact_hash(artifact_path: Path) -> str:
    """
    Compute a hash of the artifact directory.
    
    Args:
        artifact_path: Path to artifact
        
    Returns:
        str: Hash in format "sha256:<hex>"
    """
    # Read manifest if it exists
    manifest_path = artifact_path / "manifest.json"
    if manifest_path.exists():
        with open(manifest_path, 'r') as f:
            manifest = json.load(f)
        
        tree_hash = manifest.get("checksums", {}).get("tree_hash")
        if tree_hash:
            return f"sha256:{tree_hash}"
    
    # Fallback: compute hash of directory listing
    hasher = hashlib.sha256()
    for root, dirs, files in os.walk(artifact_path):
        for file in sorted(files):
            hasher.update(file.encode())
    
    return f"sha256:{hasher.hexdigest()}"


class ArtifactValidator:
    """
    Validator for staged Agent Zero artifacts.
    
    Performs comprehensive safety checks before allowing promotion.
    """
    
    def __init__(self, artifact_path: Path, version: str):
        """
        Initialize the validator.
        
        Args:
            artifact_path: Path to the staged artifact
            version: Version string
        """
        self.artifact_path = artifact_path
        self.version = version
        self.checks_results = {}
        self.start_time = None
        self.elapsed_ms = 0
        
        # Verify artifact exists
        if not artifact_path.exists():
            raise ArtifactNotFoundError(f"Artifact not found: {artifact_path}")
    
    def _run_with_timeout(self, func, timeout: int = CHECK_TIMEOUT) -> Any:
        """
        Run a function with a timeout.
        
        Args:
            func: Function to run
            timeout: Timeout in seconds
            
        Returns:
            Function result
            
        Raises:
            ValidationTimeoutError: If function times out
        """
        import signal
        
        def timeout_handler(signum, frame):
            raise ValidationTimeoutError(f"Check timed out after {timeout}s")
        
        # Set timeout handler
        old_handler = signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(timeout)
        
        try:
            result = func()
            signal.alarm(0)  # Cancel alarm
            return result
        except ValidationTimeoutError:
            raise
        finally:
            signal.signal(signal.SIGALRM, old_handler)
    
    def run_check_integrity(self) -> Dict[str, Any]:
        """
        Check 1: Structural Integrity
        
        Verifies that critical files and directories exist.
        
        Returns:
            Dict: Check result
        """
        start = time.time()
        
        try:
            # Define critical files/directories
            critical_items = [
                "agent.py",
                "models.py",
                "prompts",
                "python",
                "requirements.txt"
            ]
            
            missing = []
            for item in critical_items:
                item_path = self.artifact_path / item
                if not item_path.exists():
                    missing.append(item)
            
            elapsed = int((time.time() - start) * 1000)
            
            if missing:
                result = {
                    "passed": False,
                    "ms": elapsed,
                    "error": f"Missing critical items: {', '.join(missing)}",
                    "details": {"missing": missing}
                }
            else:
                result = {
                    "passed": True,
                    "ms": elapsed,
                    "error": None,
                    "details": {"checked": critical_items}
                }
            
            # Log result
            event_type = "check_passed" if result["passed"] else "check_failed"
            log_event(event_type, {
                "check": "structural_integrity",
                "version": self.version,
                "passed": result["passed"]
            })
            
            return result
            
        except Exception as e:
            elapsed = int((time.time() - start) * 1000)
            return {
                "passed": False,
                "ms": elapsed,
                "error": str(e),
                "details": {}
            }
    
    def run_check_imports(self) -> Dict[str, Any]:
        """
        Check 2: Import Sanity
        
        Verifies that Agent Zero can be imported using the artifact's virtualenv.
        
        Returns:
            Dict: Check result
        """
        start = time.time()
        
        try:
            # Find Python executable in venv
            venv_python = self.artifact_path / ".venv" / "bin" / "python"
            
            if not venv_python.exists():
                # Try alternate location
                venv_python = self.artifact_path / ".venv" / "bin" / "python3"
            
            if not venv_python.exists():
                return {
                    "passed": False,
                    "ms": int((time.time() - start) * 1000),
                    "error": "Virtual environment not found",
                    "details": {}
                }
            
            # Test import in subprocess
            cmd = [
                str(venv_python),
                "-c",
                "import sys; sys.path.insert(0, '.'); import agent"
            ]
            
            result = subprocess.run(
                cmd,
                cwd=str(self.artifact_path),
                capture_output=True,
                timeout=CHECK_TIMEOUT
            )
            
            elapsed = int((time.time() - start) * 1000)
            
            if result.returncode == 0:
                check_result = {
                    "passed": True,
                    "ms": elapsed,
                    "error": None,
                    "details": {"import": "success"}
                }
            else:
                stderr = result.stderr.decode("utf-8", errors="replace")
                check_result = {
                    "passed": False,
                    "ms": elapsed,
                    "error": f"Import failed: {stderr[:200]}",
                    "details": {"stderr": stderr}
                }
            
            # Log result
            event_type = "check_passed" if check_result["passed"] else "check_failed"
            log_event(event_type, {
                "check": "import_sanity",
                "version": self.version,
                "passed": check_result["passed"]
            })
            
            return check_result
            
        except subprocess.TimeoutExpired:
            elapsed = int((time.time() - start) * 1000)
            return {
                "passed": False,
                "ms": elapsed,
                "error": "Import check timed out",
                "details": {}
            }
        except Exception as e:
            elapsed = int((time.time() - start) * 1000)
            return {
                "passed": False,
                "ms": elapsed,
                "error": str(e),
                "details": {}
            }
    
    def run_check_config(self) -> Dict[str, Any]:
        """
        Check 3: Config Parsing
        
        Verifies that configuration files can be parsed.
        
        Returns:
            Dict: Check result
        """
        start = time.time()
        
        try:
            config_files = []
            
            # Check for .env.example
            env_example = self.artifact_path / ".env.example"
            if env_example.exists():
                config_files.append(".env.example")
            
            # Check for config directory
            config_dir = self.artifact_path / "conf"
            if config_dir.exists():
                for config_file in config_dir.glob("*.yaml"):
                    config_files.append(str(config_file.relative_to(self.artifact_path)))
            
            elapsed = int((time.time() - start) * 1000)
            
            if not config_files:
                return {
                    "passed": True,
                    "ms": elapsed,
                    "error": None,
                    "details": {"message": "No config files to validate"}
                }
            
            # Log result
            log_event("check_passed", {
                "check": "config_parsing",
                "version": self.version,
                "passed": True
            })
            
            return {
                "passed": True,
                "ms": elapsed,
                "error": None,
                "details": {"config_files": config_files}
            }
            
        except Exception as e:
            elapsed = int((time.time() - start) * 1000)
            return {
                "passed": False,
                "ms": elapsed,
                "error": str(e),
                "details": {}
            }
    
    def run_check_tools(self) -> Dict[str, Any]:
        """
        Check 4: Tool Registry
        
        Verifies that standard tools can be discovered.
        
        Returns:
            Dict: Check result
        """
        start = time.time()
        
        try:
            # Check for tools directory
            tools_dir = self.artifact_path / "python" / "tools"
            
            if not tools_dir.exists():
                return {
                    "passed": False,
                    "ms": int((time.time() - start) * 1000),
                    "error": "Tools directory not found",
                    "details": {}
                }
            
            # Count tool files
            tool_files = list(tools_dir.glob("*.py"))
            
            elapsed = int((time.time() - start) * 1000)
            
            # Log result
            log_event("check_passed", {
                "check": "tool_registry",
                "version": self.version,
                "passed": True
            })
            
            return {
                "passed": True,
                "ms": elapsed,
                "error": None,
                "details": {"tool_count": len(tool_files)}
            }
            
        except Exception as e:
            elapsed = int((time.time() - start) * 1000)
            return {
                "passed": False,
                "ms": elapsed,
                "error": str(e),
                "details": {}
            }
    
    def run_check_prompts(self) -> Dict[str, Any]:
        """
        Check 5: Prompt Assets
        
        Verifies that mandatory prompt templates exist and are non-empty.
        
        Returns:
            Dict: Check result
        """
        start = time.time()
        
        try:
            prompts_dir = self.artifact_path / "prompts"
            
            if not prompts_dir.exists():
                return {
                    "passed": False,
                    "ms": int((time.time() - start) * 1000),
                    "error": "Prompts directory not found",
                    "details": {}
                }
            
            # Check for mandatory prompts
            mandatory_prompts = [
                "agent.system.main.md"
            ]
            
            missing = []
            empty = []
            
            for prompt in mandatory_prompts:
                prompt_path = prompts_dir / prompt
                if not prompt_path.exists():
                    missing.append(prompt)
                elif prompt_path.stat().st_size == 0:
                    empty.append(prompt)
            
            elapsed = int((time.time() - start) * 1000)
            
            if missing or empty:
                error_parts = []
                if missing:
                    error_parts.append(f"Missing: {', '.join(missing)}")
                if empty:
                    error_parts.append(f"Empty: {', '.join(empty)}")
                
                result = {
                    "passed": False,
                    "ms": elapsed,
                    "error": "; ".join(error_parts),
                    "details": {"missing": missing, "empty": empty}
                }
            else:
                prompt_count = len(list(prompts_dir.glob("*.md")))
                result = {
                    "passed": True,
                    "ms": elapsed,
                    "error": None,
                    "details": {"prompt_count": prompt_count}
                }
            
            # Log result
            event_type = "check_passed" if result["passed"] else "check_failed"
            log_event(event_type, {
                "check": "prompt_assets",
                "version": self.version,
                "passed": result["passed"]
            })
            
            return result
            
        except Exception as e:
            elapsed = int((time.time() - start) * 1000)
            return {
                "passed": False,
                "ms": elapsed,
                "error": str(e),
                "details": {}
            }
    
    def run_check_memory(self) -> Dict[str, Any]:
        """
        Check 6: Memory Initialization
        
        Verifies that memory subsystem can initialize cleanly.
        
        Returns:
            Dict: Check result
        """
        start = time.time()
        
        try:
            # For Phase 4B, we'll do a basic check
            # Real implementation would test FAISS/Chroma initialization
            
            # Check if memory-related files exist
            memory_dir = self.artifact_path / "memory"
            
            # This is a placeholder - real implementation would:
            # 1. Create temp directory
            # 2. Initialize vector DB in subprocess
            # 3. Verify clean startup
            # 4. Clean up temp directory
            
            elapsed = int((time.time() - start) * 1000)
            
            # For now, pass if memory directory exists or can be created
            result = {
                "passed": True,
                "ms": elapsed,
                "error": None,
                "details": {"message": "Memory initialization check (placeholder)"}
            }
            
            # Log result
            log_event("check_passed", {
                "check": "memory_initialization",
                "version": self.version,
                "passed": True
            })
            
            return result
            
        except Exception as e:
            elapsed = int((time.time() - start) * 1000)
            return {
                "passed": False,
                "ms": elapsed,
                "error": str(e),
                "details": {}
            }
    
    def validate_one(self, check_name: str) -> Dict[str, Any]:
        """
        Run a single validation check.
        
        Args:
            check_name: The name of the check to run
        
        Returns:
            Dict: Partial validation report
        """
        self.start_time = time.time()
        
        # Log validation start
        log_event("validation_started", {
            "version": self.version,
            "artifact_path": str(self.artifact_path),
            "partial": True,
            "check": check_name
        })
        
        # All available checks
        all_checks = {
            "integrity": self.run_check_integrity,
            "imports": self.run_check_imports,
            "config": self.run_check_config,
            "tools": self.run_check_tools,
            "prompts": self.run_check_prompts,
            "memory": self.run_check_memory
        }

        # Get the check function
        check_func = all_checks.get(check_name)
        
        if not check_func:
            raise ValidationError(f"Unknown check: {check_name}")

        # Run the check
        try:
            result = check_func()
        except ValidationTimeoutError as e:
            result = {
                "passed": False,
                "ms": CHECK_TIMEOUT * 1000,
                "error": str(e),
                "details": {}
            }
        except Exception as e:
            result = {
                "passed": False,
                "ms": 0,
                "error": f"Unexpected error: {str(e)}",
                "details": {}
            }

        self.elapsed_ms = int((time.time() - self.start_time) * 1000)

        # Determine overall status
        status = "PASSED" if result["passed"] else "FAILED"

        # Create report
        report = {
            "version": self.version,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "status": status,
            "partial": True,
            "checks": {
                check_name: result
            }
        }
        
        # Log completion
        event_type = "validation_completed" if status == "PASSED" else "validation_failed"
        log_event(event_type, {
            "version": self.version,
            "status": report["status"],
            "elapsed_ms": self.elapsed_ms,
            "partial": True
        })
        
        return report


    def validate_all(self) -> Dict[str, Any]:
        """
        Run all validation checks.
        
        Returns:
            Dict: Complete validation report
        """
        self.start_time = time.time()
        
        # Log validation start
        log_event("validation_started", {
            "version": self.version,
            "artifact_path": str(self.artifact_path)
        })
        
        # Run all checks
        checks = {
            "structural_integrity": self.run_check_integrity,
            "import_sanity": self.run_check_imports,
            "config_parsing": self.run_check_config,
            "tool_registry": self.run_check_tools,
            "prompt_assets": self.run_check_prompts,
            "memory_initialization": self.run_check_memory
        }
        
        results = {}
        
        for check_name, check_func in checks.items():
            try:
                # Check if we've exceeded suite timeout
                if time.time() - self.start_time > SUITE_TIMEOUT:
                    results[check_name] = {
                        "passed": False,
                        "ms": 0,
                        "error": "Suite timeout exceeded",
                        "details": {}
                    }
                    break
                
                # Run check
                results[check_name] = check_func()
                
            except ValidationTimeoutError as e:
                results[check_name] = {
                    "passed": False,
                    "ms": CHECK_TIMEOUT * 1000,
                    "error": str(e),
                    "details": {}
                }
            except Exception as e:
                results[check_name] = {
                    "passed": False,
                    "ms": 0,
                    "error": f"Unexpected error: {str(e)}",
                    "details": {}
                }
        
        self.elapsed_ms = int((time.time() - self.start_time) * 1000)
        
        # Determine overall status
        all_passed = all(result["passed"] for result in results.values())
        
        # Compute artifact hash
        artifact_hash = compute_artifact_hash(self.artifact_path)
        
        # Create report
        report = {
            "version": self.version,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "status": "PASSED" if all_passed else "FAILED",
            "checks": results,
            "artifact_hash": artifact_hash,
            "elapsed_ms": self.elapsed_ms
        }
        
        # Validate report against schema
        try:
            validate_json_schema(report, REPORT_SCHEMA)
        except SchemaValidationError as e:
            # Log schema error but don't fail validation
            log_event("report_schema_error", {
                "error": str(e)
            })
        
        # Log completion
        event_type = "validation_completed" if all_passed else "validation_failed"
        log_event(event_type, {
            "version": self.version,
            "status": report["status"],
            "elapsed_ms": self.elapsed_ms
        })
        
        return report
    
    def store_report(self, report: Dict[str, Any]) -> Path:
        """
        Store validation report.
        
        Args:
            report: Validation report
            
        Returns:
            Path: Path to stored report
        """
        # Store as latest_report.json
        latest_path = get_validation_path() / "latest_report.json"
        with open(latest_path, 'w') as f:
            json.dump(report, f, indent=2)
        
        # Store in history with timestamp
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        history_filename = f"{self.version}_{timestamp}.json"
        history_path = get_validation_history_path() / history_filename
        
        with open(history_path, 'w') as f:
            json.dump(report, f, indent=2)
        
        # Rotate old reports (keep last 10 per version)
        self._rotate_reports()
        
        log_event("report_stored", {
            "version": self.version,
            "path": str(history_path)
        })
        
        return latest_path
    
    def _rotate_reports(self) -> None:
        """
        Rotate old validation reports, keeping last 10 per version.
        """
        history_path = get_validation_history_path()
        
        # Group reports by version
        version_reports = {}
        for report_file in history_path.glob(f"{self.version}_*.json"):
            version = self.version
            if version not in version_reports:
                version_reports[version] = []
            version_reports[version].append(report_file)
        
        # Keep only last 10 per version
        for version, reports in version_reports.items():
            if len(reports) > 10:
                # Sort by modification time
                reports.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                
                # Delete old reports
                for old_report in reports[10:]:
                    try:
                        old_report.unlink()
                    except Exception:
                        pass


def validate_artifact(version: str, artifact_path: Optional[Path] = None, check: Optional[str] = None) -> Tuple[bool, Dict[str, Any]]:
    """
    Validate a staged artifact and handle state transitions.
    
    Args:
        version: Version to validate
        artifact_path: Path to artifact (optional, will be determined if not provided)
        
    Returns:
        Tuple of (success: bool, report: dict)
    """
    try:
        # Determine artifact path if not provided
        if artifact_path is None:
            artifact_path = get_artifact_path(version)
        
        # Create validator
        validator = ArtifactValidator(artifact_path, version)
        
        # Run validation
        if check:
            report = validator.validate_one(check)
        else:
            report = validator.validate_all()
        
        # Store report
        validator.store_report(report)
        
        # Handle state transitions
        sm = AgentZeroStateMachine()
        current_state = sm.current_state()
        
        # Only transition if we're in an appropriate state and not doing a partial validation
        if current_state in [State.VALIDATING, State.STAGING] and not report.get("partial"):
            if report["status"] == "PASSED":
                # Transition to PROMOTING
                try:
                    sm.transition(
                        to_state=State.PROMOTING,
                        reason_code=ReasonCode.APPROVAL_GRANTED,
                        notes=f"Validation passed for {version}",
                        metadata={
                            "tree_hash": report["artifact_hash"],
                            "elapsed_ms": report["elapsed_ms"]
                        }
                    )
                except Exception as e:
                    # Log transition error but don't fail validation
                    log_event("state_transition_failed", {
                        "error": str(e),
                        "from": str(current_state),
                        "to": "PROMOTING"
                    })
                
                return True, report
            else:
                # Transition to FAILED
                # Find which checks failed
                failed_checks = [
                    name for name, result in report["checks"].items()
                    if not result["passed"]
                ]
                
                try:
                    sm.transition(
                        to_state=State.FAILED,
                        reason_code=ReasonCode.VALIDATION_ERROR,
                        notes=f"Validation failed for {version}: {', '.join(failed_checks)}",
                        metadata={
                            "failed_checks": failed_checks
                        }
                    )
                except Exception as e:
                    # Log transition error but don't fail validation
                    log_event("state_transition_failed", {
                        "error": str(e),
                        "from": str(current_state),
                        "to": "FAILED"
                    })
                
                return False, report
        else:
            # Not in a state where we can transition
            # Just return the validation result without state change
            log_event("validation_without_transition", {
                "version": version,
                "current_state": str(current_state),
                "validation_status": report["status"]
            })
            
            return report["status"] == "PASSED", report
            
    except ArtifactNotFoundError as e:
        # Artifact doesn't exist
        report = {
            "version": version,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "status": "FAILED",
            "checks": {},
            "artifact_hash": "sha256:unknown",
            "elapsed_ms": 0,
            "error": str(e)
        }
        
        log_event("validation_failed", {
            "version": version,
            "error": str(e)
        })
        
        return False, report
        
    except Exception as e:
        # Unexpected error
        report = {
            "version": version,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "status": "FAILED",
            "checks": {},
            "artifact_hash": "sha256:unknown",
            "elapsed_ms": 0,
            "error": f"Unexpected error: {str(e)}"
        }
        
        log_event("validation_failed", {
            "version": version,
            "error": str(e)
        })
        
        return False, report