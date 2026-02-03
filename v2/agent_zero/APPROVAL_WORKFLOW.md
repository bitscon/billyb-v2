# Agent Zero Approval Workflow

This document describes the approval workflow for Agent Zero lifecycle management implemented in Phase 2.

## Overview

The approval workflow allows Billy to request and record approvals for Agent Zero upgrades, but prevents Billy from executing any upgrades without human approval. The workflow is designed to be secure, auditable, and to maintain the principle of least privilege.

## Constraints

- Observer authority level is maintained throughout
- No execution capabilities are provided
- All file modifications are restricted to the `.billy/` directory
- Strict validation and integrity checks are enforced

## Command Reference

### `a0 pending-approvals [--json]`

Displays the current pending approval (if any).

**Example:**
```
a0 pending-approvals
```

**Output:**
```
Pending Approval:
  Version: v0.9.8
  Requested: 2026-02-01T14:30:00Z
  Requested by: system:billy_frame
  GitHub: https://github.com/frdel/agent-zero/releases/tag/v0.9.8
```

Using `--json` will output raw JSON format.

### `a0 request-upgrade <version> [--force-check] [--allow-prerelease]`

Creates an approval request for upgrading to a new version.

**Example:**
```
a0 request-upgrade v0.9.8
```

**Flags:**
- `--force-check`: Replace existing pending approval if one exists
- `--allow-prerelease`: Allow prerelease versions

### `approve a0 upgrade <version>`

Approves a pending upgrade request. Can only be executed by humans.

**Example:**
```
approve a0 upgrade v0.9.8
```

### `deny a0 upgrade <version> [--reason "explanation"]`

Denies a pending upgrade request. Can only be executed by humans.

**Example:**
```
deny a0 upgrade v0.9.8 --reason "Not ready for production"
```

## Security Features

1. **Version Validation**
   - Strict SemVer format validation
   - Prevents downgrade attempts
   - Verifies version exists in GitHub releases

2. **Integrity Protection**
   - Approval IDs computed using cryptographic hash (SHA-256)
   - File modification time validation
   - Schema validation for all data

3. **Audit Logging**
   - Append-only JSONL format
   - All events logged with timestamps
   - Captures both successful and failed operations

4. **Human-Only Operations**
   - Approvals and denials require human authority
   - Cannot be approved by the same actor that requested the upgrade

5. **File Safety**
   - Atomic write operations
   - Creates parent directories when needed
   - Validates data before writing

## Implementation Files

- `schema.py`: JSON schema and version validation
- `fileops.py`: File operations and integrity checks
- `github.py`: GitHub API integration for release verification
- `approval.py`: Core approval workflow implementation
- `audit.py`: Audit logging functionality
- `commands.py`: Command handler integration

## Testing and Demonstration

- `test_approval_workflow.py`: Test suite covering all requirements
- `demo_approval_workflow.py`: End-to-end demonstration of the workflow

## File Structure

```
v2/agent_zero/
  ├─ .billy/
  │   ├─ state.json           [read-only]
  │   ├─ version.json         [read-only]
  │   ├─ pending_approval.json [read/write]
  │   ├─ upgrade_history.log  [append-only]
  │   └─ cache/               [temporary files]
  ├─ schema.py
  ├─ fileops.py
  ├─ github.py
  ├─ approval.py
  ├─ audit.py
  └─ commands.py
```

## Next Steps

Phase 3 will implement the state machine core, modeling transitions without actual execution capabilities.