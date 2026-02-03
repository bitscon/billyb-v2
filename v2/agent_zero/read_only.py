"""
Agent Zero Phase 1 read-only tooling for lifecycle inspection.

This module implements a security-focused, read-only command execution
environment for Agent Zero lifecycle inspection. It provides strict
controls on allowed commands, path security, and binary file handling.

Usage:
    from v2.agent_zero.read_only import execute_command
    result = execute_command("a0 env ls -l /home/billyb/workspaces/billyb-v2/v2/agent_zero")

Security features:
- Command allowlist with strict flag validation
- Path security with realpath resolution
- Binary file detection and blocking
- Pre-execution security checks
- Output size limits and processing
- Comprehensive logging
"""

import json
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple, Set, Union


# --- 1. COMMAND ALLOWLIST (STRICT) ---
ALLOWED_COMMANDS = {
    "ls": {
        "allowed_flags": ["-l", "-a", "-h"],
        "max_args": 3
    },
    "cat": {
        "require_absolute_path": True,
        "max_files": 2
    },
    "find": {
        "required_flags": ["-maxdepth"],
        "max_depth": 3,
        "allowed_flags": ["-maxdepth", "-type", "-name"],
        "blocked_flags": ["-exec", "-delete", "-print0"]
    }
}

# --- 2. PATH SECURITY (MANDATORY) ---
ALLOWED_ROOTS = [
    "/home/billyb/workspaces/billyb-v2",
    "/tmp/agent_zero-"
]

# --- 5. OUTPUT PROCESSING ---
MAX_OUTPUT_SIZE = 64 * 1024  # 64KB

# --- 6. COMMAND GRAMMAR ---
COMMAND_MAP = {
    "a0 status": "read_status_metadata",
    "a0 env ls": "shell_runner_ls",
    "a0 env cat": "shell_runner_cat",
    "a0 env find": "shell_runner_find"
}

# Observer mode error message
OBSERVER_MODE_ERROR = "Command not available in observer mode"


# Custom exception classes
class InvalidCommandError(Exception):
    """Raised when a command is not in the allowed list."""
    pass


class WriteAttemptError(Exception):
    """Raised when a write operation is detected."""
    pass


class PathViolationError(Exception):
    """Raised when a path violates security constraints."""
    pass


class BinaryFileError(Exception):
    """Raised when a binary file is detected."""
    pass


class SafetyLimitExceededError(Exception):
    """Raised when a safety limit is exceeded."""
    pass


def get_metadata_path() -> Path:
    """Returns the path to the Agent Zero metadata directory."""
    return Path(__file__).parent / ".billy"


def get_log_path() -> Path:
    """Returns the path to the execution log file."""
    return get_metadata_path() / "read_only_exec.log"


def validate_file_content(content: bytes) -> None:
    """
    Validate that file content is not binary.
    
    Args:
        content: Raw file content to check
        
    Raises:
        BinaryFileError: If the file appears to be binary
    """
    # Check for null bytes in the first 1024 bytes
    if b"\x00" in content[:1024]:
        raise BinaryFileError("Binary files blocked in observer mode")
    
    # Additional validation could be added here if needed


def is_path_allowed(path: str) -> bool:
    """
    Check if a path is within the allowed roots.
    
    Args:
        path: Path to check
        
    Returns:
        bool: True if the path is allowed, False otherwise
    """
    # Handle binary files with special permissions
    if path.startswith("/bin/") or path.startswith("/usr/bin/") or path.startswith("/sbin/"):
        # These are binary system files, handle as special case for testing
        return False
    
    # Resolve the path to handle symlinks and relative paths
    resolved_path = os.path.realpath(path)
    
    # Check if the resolved path starts with any of the allowed roots
    return any(resolved_path.startswith(root) for root in ALLOWED_ROOTS)


def detect_write_semantics(cmd: List[str]) -> bool:
    """
    Detect if a command has write semantics.
    
    Args:
        cmd: Command and arguments as a list
        
    Returns:
        bool: True if write operation detected, False otherwise
    """
    # Check for redirection operators
    command_str = " ".join(cmd)
    if ">" in command_str or ">>" in command_str:
        return True
    
    # Check for common write flags
    write_flags = ["-w", "--write", "-o", "--output"]
    return any(flag in cmd for flag in write_flags)


def parse_maxdepth(args: List[str]) -> Optional[int]:
    """
    Extract maxdepth value from find command arguments.
    
    Args:
        args: Command arguments
        
    Returns:
        Optional[int]: The maxdepth value if found, None otherwise
    """
    for i, arg in enumerate(args):
        if arg == "-maxdepth" and i + 1 < len(args):
            try:
                return int(args[i + 1])
            except ValueError:
                return None
    return None


def validate_command_args(command: str, args: List[str]) -> None:
    """
    Validate command arguments against the allowlist.
    
    Args:
        command: The command name
        args: Command arguments
        
    Raises:
        InvalidCommandError: If the command or arguments are invalid
        SafetyLimitExceededError: If a safety limit is exceeded
        PathViolationError: If a path violates security constraints
        WriteAttemptError: If a write operation is detected
    """
    if command not in ALLOWED_COMMANDS:
        raise InvalidCommandError(f"Command not allowed in observer mode: {command}")
    
    cmd_config = ALLOWED_COMMANDS[command]
    
    # Check for max args limit
    if "max_args" in cmd_config and len(args) > cmd_config["max_args"]:
        raise SafetyLimitExceededError(f"Too many arguments for {command}, max {cmd_config['max_args']}")
    
    # Validate flags
    if "allowed_flags" in cmd_config:
        for arg in args:
            if arg.startswith("-") and arg not in cmd_config["allowed_flags"]:
                raise InvalidCommandError(f"Flag not allowed: {arg}")
    
    # Check for required flags
    if "required_flags" in cmd_config:
        for required_flag in cmd_config["required_flags"]:
            if required_flag not in args:
                raise InvalidCommandError(f"Required flag missing: {required_flag}")
    
    # Check for blocked flags
    if "blocked_flags" in cmd_config:
        for blocked_flag in cmd_config["blocked_flags"]:
            if blocked_flag in args:
                raise InvalidCommandError(f"Blocked flag detected: {blocked_flag}")
    
    # Path validation for file arguments
    if command in ["cat", "ls"]:
        paths = [arg for arg in args if not arg.startswith("-")]
        for path in paths:
            if not is_path_allowed(path):
                raise PathViolationError(f"Path not allowed: {path}")
    
    # Special validation for 'find'
    if command == "find":
        # Check maxdepth
        maxdepth = parse_maxdepth(args)
        if maxdepth is None:
            raise InvalidCommandError("Missing or invalid -maxdepth value")
        
        if maxdepth > cmd_config["max_depth"]:
            raise SafetyLimitExceededError(f"Maxdepth too large: {maxdepth}, max allowed: {cmd_config['max_depth']}")
            
        # Validate path
        paths = [arg for arg in args if not arg.startswith("-") and args.index(arg) == 0]
        if paths and not is_path_allowed(paths[0]):
            raise PathViolationError(f"Path not allowed: {paths[0]}")


def log_execution(command: str, args: List[str], authorized: bool, 
                  output_size_bytes: int, execution_ms: int, 
                  violation_triggered: bool = False, error_type: Optional[str] = None,
                  resolved_path: Optional[str] = None) -> None:
    """
    Log execution details to the execution log file.
    
    Args:
        command: The command name
        args: Command arguments
        authorized: Whether the execution was authorized
        output_size_bytes: Size of the execution output in bytes
        execution_ms: Execution time in milliseconds
        violation_triggered: Whether a security violation was triggered
        error_type: Type of error if any
        resolved_path: Resolved path if applicable
    """
    log_path = get_log_path()
    
    log_entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "actor": "billy_frame",
        "authority": "observer",
        "command": command,
        "arguments": args,
        "resolved_path": resolved_path or "",
        "authorized": authorized,
        "output_size_bytes": output_size_bytes,
        "execution_ms": execution_ms,
        "violation_triggered": violation_triggered,
        "error_type": error_type
    }
    
    try:
        # Read existing logs
        if log_path.exists():
            try:
                with open(log_path, "r") as f:
                    logs = json.load(f)
                if not isinstance(logs, list):
                    logs = []
            except (json.JSONDecodeError, FileNotFoundError):
                logs = []
        else:
            logs = []
        
        # Append new log entry
        logs.append(log_entry)
        
        # Write updated logs back to file
        with open(log_path, "w") as f:
            json.dump(logs, f, indent=2)
    except Exception as e:
        print(f"Error writing to log file: {e}")


def process_output(raw: bytes) -> str:
    """
    Process command output with size limits and validation.
    
    Args:
        raw: Raw command output
        
    Returns:
        str: Processed output
        
    Raises:
        BinaryFileError: If binary content is detected
    """
    # Check for binary content
    try:
        validate_file_content(raw)
    except BinaryFileError:
        raise
    
    # Truncate if exceeds maximum size
    if len(raw) > MAX_OUTPUT_SIZE:
        truncated = raw[:MAX_OUTPUT_SIZE]
        return truncated.decode("utf-8") + "\n[OUTPUT TRUNCATED: exceeded 64KB]"
    
    # Decode to string
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise BinaryFileError("Binary content detected in output")


def shell_runner(command: str, args: List[str]) -> Dict[str, Any]:
    """
    Run a shell command with security validations.
    
    Args:
        command: The command name
        args: Command arguments
        
    Returns:
        Dict: Result dictionary with output or error
    """
    start_time = time.time()
    resolved_path = None
    
    # Run pre-execution security checks
    try:
        # Verify command is allowed
        validate_command_args(command, args)
        
        # Detect write attempts
        if detect_write_semantics(args):
            raise WriteAttemptError("Write operations not allowed in observer mode")
        
        # Path validation for real paths
        path_args = [arg for arg in args if not arg.startswith("-")]
        if path_args:
            resolved_path = os.path.realpath(path_args[0])
            if not is_path_allowed(resolved_path):
                raise PathViolationError(f"Path not allowed: {resolved_path}")
        
        # Execute command
        cmd = [command] + args
        result = subprocess.run(
            cmd,
            capture_output=True,
            check=False,
            timeout=10  # 10-second timeout for safety
        )
        
        # Process output
        if result.returncode == 0:
            output = process_output(result.stdout)
            execution_time = int((time.time() - start_time) * 1000)
            
            # Log successful execution
            log_execution(
                command=f"a0 env {command}",
                args=args,
                authorized=True,
                output_size_bytes=len(result.stdout),
                execution_ms=execution_time,
                resolved_path=resolved_path
            )
            
            return {
                "status": "success",
                "command": command,
                "output": output,
                "execution_ms": execution_time
            }
        else:
            error_output = result.stderr.decode("utf-8", errors="replace")
            execution_time = int((time.time() - start_time) * 1000)
            
            # Log failed execution
            log_execution(
                command=f"a0 env {command}",
                args=args,
                authorized=True,
                output_size_bytes=len(result.stderr),
                execution_ms=execution_time,
                violation_triggered=True,
                error_type="command_error",
                resolved_path=resolved_path
            )
            
            return {
                "status": "error",
                "command": command,
                "error": f"Command returned non-zero exit code: {result.returncode}",
                "details": error_output,
                "execution_ms": execution_time
            }
            
    except (InvalidCommandError, WriteAttemptError, PathViolationError,
            BinaryFileError, SafetyLimitExceededError) as e:
        execution_time = int((time.time() - start_time) * 1000)
        
        # Log security violation
        log_execution(
            command=f"a0 env {command}",
            args=args,
            authorized=False,
            output_size_bytes=0,
            execution_ms=execution_time,
            violation_triggered=True,
            error_type=e.__class__.__name__,
            resolved_path=resolved_path
        )
        
        return {
            "status": "error",
            "command": command,
            "error": str(e),
            "violation": e.__class__.__name__,
            "execution_ms": execution_time
        }
    except Exception as e:
        execution_time = int((time.time() - start_time) * 1000)
        
        # Log unexpected error
        log_execution(
            command=f"a0 env {command}",
            args=args,
            authorized=False,
            output_size_bytes=0,
            execution_ms=execution_time,
            violation_triggered=True,
            error_type="unexpected_error",
            resolved_path=resolved_path
        )
        
        return {
            "status": "error",
            "command": command,
            "error": f"Unexpected error: {str(e)}",
            "execution_ms": execution_time
        }


def shell_runner_ls(args: List[str]) -> Dict[str, Any]:
    """Run 'ls' command with security validations."""
    return shell_runner("ls", args)


def shell_runner_cat(args: List[str]) -> Dict[str, Any]:
    """Run 'cat' command with security validations."""
    return shell_runner("cat", args)


def shell_runner_find(args: List[str]) -> Dict[str, Any]:
    """Run 'find' command with security validations."""
    return shell_runner("find", args)


def read_status_metadata() -> Dict[str, Any]:
    """
    Implementation of 'a0 status' command.
    Returns the current status of Agent Zero with observer-level detail.
    """
    start_time = time.time()
    metadata_path = get_metadata_path()
    state_path = metadata_path / "state.json"
    version_path = metadata_path / "version.json"
    
    try:
        # Read state and version data
        with open(state_path, "r", encoding="utf-8") as f:
            state_data = json.load(f)
        with open(version_path, "r", encoding="utf-8") as f:
            version_data = json.load(f)
        
        execution_time = int((time.time() - start_time) * 1000)
        
        # Log successful execution
        log_execution(
            command="a0 status",
            args=[],
            authorized=True,
            output_size_bytes=sum(len(str(v)) for v in {**state_data, **version_data}.values()),
            execution_ms=execution_time
        )
        
        return {
            "status": "success",
            "state": state_data.get("state", "UNKNOWN"),
            "authority": state_data.get("authority", "observer"),  # Default to observer
            "version": version_data.get("version", "UNKNOWN"),
            "installed_at": version_data.get("installed_at", "UNKNOWN"),
            "installed_by": version_data.get("installed_by", "UNKNOWN"),
            "source": version_data.get("source", "UNKNOWN"),
            "metadata_path": str(metadata_path),
            "execution_ms": execution_time
        }
    except Exception as e:
        execution_time = int((time.time() - start_time) * 1000)
        
        # Log execution error
        log_execution(
            command="a0 status",
            args=[],
            authorized=False,
            output_size_bytes=0,
            execution_ms=execution_time,
            violation_triggered=True,
            error_type="metadata_error"
        )
        
        return {
            "status": "error",
            "error": f"Failed to read metadata: {str(e)}",
            "execution_ms": execution_time
        }


def execute_command(command: str) -> Dict[str, Any]:
    """
    Execute a read-only Agent Zero command.
    
    Args:
        command: Full command string (starting with 'a0 ')
        
    Returns:
        Dict: Command execution result
    """
    if not command.startswith("a0 "):
        return {
            "status": "error",
            "error": "Not an Agent Zero command"
        }
    
    # Split command into parts
    parts = command.strip().split()
    if len(parts) < 2:
        return {
            "status": "error",
            "error": "Invalid command format"
        }
    
    # Extract command name and arguments
    cmd_prefix = f"{parts[0]} {parts[1]}"  # e.g., "a0 env"
    
    if cmd_prefix == "a0 status":
        return read_status_metadata()
    elif cmd_prefix == "a0 env":
        if len(parts) < 3:
            return {
                "status": "error", 
                "error": "Missing shell command"
            }
        
        shell_cmd = parts[2]
        args = parts[3:]
        
        if shell_cmd == "ls":
            return shell_runner_ls(args)
        elif shell_cmd == "cat":
            return shell_runner_cat(args)
        elif shell_cmd == "find":
            return shell_runner_find(args)
        else:
            return {
                "status": "error",
                "error": f"Command not allowed in observer mode: {shell_cmd}",
                "violation": "InvalidCommandError"
            }
    elif cmd_prefix == "a0 upgrade":
        # Always block upgrade commands in observer mode
        log_execution(
            command=cmd_prefix,
            args=parts[2:] if len(parts) > 2 else [],
            authorized=False,
            output_size_bytes=0,
            execution_ms=0,
            violation_triggered=True,
            error_type="AuthorityError"
        )
        return {
            "status": "error",
            "error": OBSERVER_MODE_ERROR,
            "violation": "AuthorityError"
        }
    else:
        # Unrecognized command
        return {
            "status": "error",
            "error": f"Unknown command: {cmd_prefix}"
        }