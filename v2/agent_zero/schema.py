"""
JSON schema validation for Agent Zero approval workflow.
"""

import json
import re
from typing import Dict, Any, Optional
from datetime import datetime

try:
    import jsonschema
    from packaging.version import Version, InvalidVersion
except ImportError:
    # Fallback implementation if dependencies missing
    jsonschema = None
    Version = str
    InvalidVersion = ValueError

# Schema for pending_approval.json
PENDING_APPROVAL_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": [
        "agent_id",
        "version",
        "requested_at",
        "requested_by",
        "approval_id",
        "github_release_url"
    ],
    "properties": {
        "agent_id": {
            "type": "string",
            "default": "agent_zero"
        },
        "version": {
            "type": "string",
            "pattern": "^v(0|[1-9]\\d*)\\.(0|[1-9]\\d*)\\.(0|[1-9]\\d*)(?:-((?:0|[1-9]\\d*|\\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\\.(?:0|[1-9]\\d*|\\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?(?:\\+([0-9a-zA-Z-]+(?:\\.[0-9a-zA-Z-]+)*))?$"
        },
        "requested_at": {
            "type": "string",
            "format": "date-time"
        },
        "requested_by": {
            "type": "string",
            "pattern": "^(human|system):.+$"
        },
        "approval_id": {
            "type": "string",
            "pattern": "^[a-f0-9]{64}$"
        },
        "github_release_url": {
            "type": "string",
            "format": "uri"
        },
        "notes": {
            "type": ["string", "null"]
        },
        "last_modified": {
            "type": "string",
            "format": "date-time"
        }
    },
    "additionalProperties": False
}

# SemVer validation pattern
SEMVER_PATTERN = r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
SEMVER_REGEX = re.compile(SEMVER_PATTERN)

# Custom exceptions
class SchemaValidationError(Exception):
    """Raised when JSON schema validation fails."""
    pass

class InvalidVersionFormatError(Exception):
    """Raised when a version string does not follow SemVer format."""
    pass

class DowngradeAttemptError(Exception):
    """Raised when attempting to upgrade to a version <= current version."""
    pass

def validate_json_schema(data: Dict[str, Any], schema: Dict[str, Any]) -> bool:
    """
    Validate data against a JSON schema.
    
    Args:
        data: The data to validate
        schema: The JSON schema to validate against
        
    Returns:
        bool: True if validation passes
        
    Raises:
        SchemaValidationError: If validation fails
    """
    if jsonschema is None:
        # Basic validation if jsonschema not available
        for field in schema.get("required", []):
            if field not in data:
                raise SchemaValidationError(f"Missing required field: {field}")
        return True
        
    try:
        jsonschema.validate(instance=data, schema=schema)
        return True
    except jsonschema.exceptions.ValidationError as e:
        raise SchemaValidationError(f"Schema validation failed: {str(e)}") from e

def validate_version_format(version: str) -> bool:
    """
    Validate that a version string follows SemVer format.
    
    Args:
        version: Version string to validate
        
    Returns:
        bool: True if valid
        
    Raises:
        InvalidVersionFormatError: If format is invalid
    """
    if not SEMVER_REGEX.match(version):
        raise InvalidVersionFormatError(f"Invalid SemVer format: {version}")
    return True

def compare_versions(v1: str, v2: str) -> int:
    """
    Compare two version strings.
    
    Args:
        v1: First version string
        v2: Second version string
        
    Returns:
        int: -1 if v1 < v2, 0 if v1 == v2, 1 if v1 > v2
        
    Raises:
        InvalidVersionFormatError: If either version has invalid format
    """
    # Validate format
    validate_version_format(v1)
    validate_version_format(v2)
    
    if isinstance(Version, type):
        try:
            # Use packaging.version if available
            v1_parsed = Version(v1.lstrip('v'))
            v2_parsed = Version(v2.lstrip('v'))
            
            if v1_parsed < v2_parsed:
                return -1
            elif v1_parsed > v2_parsed:
                return 1
            else:
                return 0
        except InvalidVersion as e:
            raise InvalidVersionFormatError(f"Invalid version format: {str(e)}") from e
    else:
        # Basic fallback implementation
        v1_parts = v1.lstrip('v').split('.')
        v2_parts = v2.lstrip('v').split('.')
        
        for i in range(max(len(v1_parts), len(v2_parts))):
            p1 = int(v1_parts[i]) if i < len(v1_parts) else 0
            p2 = int(v2_parts[i]) if i < len(v2_parts) else 0
            
            if p1 < p2:
                return -1
            elif p1 > p2:
                return 1
        
        return 0

def validate_version_upgrade(requested: str, current: str) -> bool:
    """
    Validate that requested version is greater than current version.
    
    Args:
        requested: Requested version string
        current: Current version string
        
    Returns:
        bool: True if valid upgrade
        
    Raises:
        DowngradeAttemptError: If requested version <= current version
        InvalidVersionFormatError: If either version has invalid format
    """
    # Compare versions
    comparison = compare_versions(requested, current)
    
    # Reject downgrades and same version
    if comparison <= 0:
        raise DowngradeAttemptError(f"Version {requested} is not newer than {current}. Use rollback for downgrades.")
    
    return True