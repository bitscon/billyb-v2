"""
Audit logging for Agent Zero approval workflow.
"""

import os
import json
from datetime import datetime
from typing import Dict, Any, Optional, List
from pathlib import Path

# Valid event types
EVENT_TYPES = [
    "approval_requested",
    "approval_granted", 
    "approval_denied",
    "approval_replaced",
    "duplicate_request",
    "integrity_violation",
    "atomic_write_failed",
    "duplicate_approval"
]

def get_audit_log_path() -> Path:
    """Returns path to upgrade history log."""
    return Path(__file__).parent / ".billy" / "upgrade_history.log"

def get_current_actor() -> str:
    """
    Get the current actor for audit logging.
    
    For now, this is hard-coded to "billy_frame" as the observer.
    In a real implementation, this would be injected by the caller.
    
    Returns:
        str: Current actor identifier
    """
    return "billy_frame"

def log_event(event_type: str, details: Optional[Dict[str, Any]] = None, actor: Optional[str] = None) -> bool:
    """
    Log an event to the upgrade history log.
    
    Args:
        event_type: Type of event
        details: Additional event details
        actor: Override default actor
    
    Returns:
        bool: True if successful
    """
    if event_type not in EVENT_TYPES:
        raise ValueError(f"Invalid event type: {event_type}")
    
    # Create entry
    entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "event_type": event_type,
        "actor": actor or get_current_actor(),
        "agent_id": "agent_zero",
        "version": details.get("version") if details else None,
        "details": details or {}
    }
    
    # Get log file path
    log_path = get_audit_log_path()
    
    # Create parent directory if it doesn't exist
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    
    # Create empty file if it doesn't exist
    if not os.path.exists(log_path):
        with open(log_path, "w") as f:
            pass
    
    # Append event to log
    with open(log_path, "a") as f:
        f.write(json.dumps(entry) + "\n")
    
    return True

def read_audit_log() -> List[Dict[str, Any]]:
    """
    Read the upgrade history log.
    
    Returns:
        List: Audit log entries
    """
    log_path = get_audit_log_path()
    
    if not os.path.exists(log_path):
        return []
    
    entries = []
    with open(log_path, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    # Skip invalid lines
                    continue
    
    return entries