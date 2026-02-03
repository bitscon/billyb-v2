# Agent Zero Lifecycle Management - Complete Implementation

This document provides an overview of the complete Agent Zero lifecycle management system implemented across Phases 1-4A.

## System Architecture

The Agent Zero lifecycle management system consists of four layers:

1. **Phase 1: Read-Only Tooling** - Environment inspection
2. **Phase 2: Approval Workflow** - Request and record approvals
3. **Phase 3: State Machine Core** - Lifecycle state modeling
4. **Phase 4A: Staging Execution** - Isolated artifact preparation

## Phase 1: Read-Only Tooling

**Purpose:** Provide secure, read-only inspection of Agent Zero environment

**Authority:** observer

**Commands:**
- `a0 status` - Display Agent Zero status
- `a0 env ls <path>` - List directory contents
- `a0 env cat <file>` - Display file contents
- `a0 env find <path> -maxdepth N` - Find files

**Security:**
- Strict command allowlist
- Path validation (only allowed roots)
- Binary file detection and blocking
- Output size limits (64KB)
- Comprehensive logging

**Files:**
- `read_only.py` - Core implementation
- `v2/agent_zero/.billy/read_only_exec.log` - Execution log

## Phase 2: Approval Workflow

**Purpose:** Enable Billy to request and record upgrade approvals without execution

**Authority:** observer

**Commands:**
- `a0 request-upgrade <version>` - Request upgrade approval
- `a0 pending-approvals [--json]` - Display pending approvals
- `approve a0 upgrade <version>` - Grant approval (human-only)
- `deny a0 upgrade <version>` - Deny approval (human-only)

**Security:**
- Human-only approval/denial
- Integrity protection via SHA-256 approval IDs
- Schema validation
- GitHub release verification
- Version validation (SemVer)
- No execution side effects

**Files:**
- `schema.py` - Schema and version validation
- `fileops.py` - Atomic file operations
- `github.py` - GitHub API integration
- `approval.py` - Core approval workflow
- `audit.py` - Audit logging
- `v2/agent_zero/.billy/pending_approval.json` - Current pending approval
- `v2/agent_zero/.billy/upgrade_history.log` - Audit log

## Phase 3: State Machine Core

**Purpose:** Establish authoritative lifecycle state machine with enforced invariants

**Authority:** observer (records intent only)

**Commands:**
- `a0 status` - Enhanced with state machine info
- `a0 explain-state` - Detailed state explanation
- `a0 clear-failure` - Clear failure state (human-only)
- `a0 confirm` - Confirm operation completion (human-only)

**States:**
- IDLE, STAGING, VALIDATING, PROMOTING, COMPLETE
- ROLLING_BACK, FAILED, FAILED_HARD

**Security:**
- Strict transition validation
- Human-only state clearing
- Authority enforcement
- Idempotent transitions
- Corruption detection

**Files:**
- `state_machine.py` - Core state machine
- `v2/agent_zero/.billy/state.json` - Current state

## Phase 4A: Staging Execution

**Purpose:** Acquire, clone, and prepare new Agent Zero version in isolation

**Authority:** executor (staging operations only)

**Commands:**
- `a0 begin-staging <version>` - Begin staging process
- `a0 staging-status` - Display staging progress
- `a0 list-artifacts` - List stored artifacts
- `a0 cleanup-artifacts [--keep N]` - Clean up old artifacts

**Workflow:**
1. Initialize (build ID, temp directory)
2. Clone from GitHub (with SHA verification)
3. Create virtualenv and install dependencies
4. Compute checksums (SHA256 per file + tree hash)
5. Finalize artifact (move to .billy/artifacts/)
6. Transition to VALIDATING state

**Security:**
- Production tree never touched
- Complete isolation in /tmp/ and .billy/artifacts/
- Failure always triggers cleanup
- Human approval required
- Full audit trail

**Files:**
- `staging.py` - Staging executor
- `v2/agent_zero/.billy/artifacts/` - Artifact storage

## Command Summary

### Observer Authority (Read-Only)

```bash
# Environment inspection
a0 env ls <path>
a0 env cat <file>
a0 env find <path> -maxdepth N

# Status and information
a0 status
a0 explain-state
a0 pending-approvals [--json]
a0 staging-status
a0 list-artifacts
```

### Human Authority Required

```bash
# Approval workflow
a0 request-upgrade <version> [--force-check] [--allow-prerelease]
approve a0 upgrade <version>
deny a0 upgrade <version> [--reason "text"]

# State management
a0 clear-failure
a0 confirm

# Staging execution
a0 begin-staging <version> [--rebuild] [--dry-run]
a0 cleanup-artifacts [--keep N]
```

## Security Model

### Authority Levels

| Level | Capabilities |
|-------|-------------|
| **observer** | Read metadata, request approvals, view status |
| **executor** | Stage upgrades in isolation, manage artifacts |
| **human** | Approve/deny upgrades, clear failures, confirm operations |

### Mutation Scope

| Phase | Allowed Mutations |
|-------|------------------|
| Phase 1 | None (read-only) |
| Phase 2 | .billy/pending_approval.json, upgrade_history.log |
| Phase 3 | .billy/state.json, upgrade_history.log |
| Phase 4A | /tmp/agent_zero_build_*, .billy/artifacts/, .billy/state.json |

### Production Protection

The production tree (`v2/agent_zero/`) is **NEVER modified** by any phase.

## Audit Trail

All operations are logged to `v2/agent_zero/.billy/upgrade_history.log` in JSONL format.

Event types include:
- `state_transition` / `state_transition_denied`
- `approval_requested` / `approval_granted` / `approval_denied`
- `staging_started` / `staging_completed` / `staging_failed`
- `clone_completed` / `dependencies_installed` / `checksums_computed`
- `artifact_stored` / `temp_cleanup_completed`
- `integrity_violation` / `atomic_write_failed`

## File Structure

```
v2/agent_zero/
├── .billy/
│   ├── state.json                  # State machine
│   ├── version.json                # Current version
│   ├── pending_approval.json       # Pending approvals
│   ├── upgrade_history.log         # Audit log (JSONL)
│   ├── read_only_exec.log          # Read-only command log
│   ├── .lock                       # File lock
│   ├── artifacts/                  # Staged artifacts
│   │   └── v0.9.X/
│   │       ├── manifest.json       # Build metadata
│   │       └── <agent_zero_files>/ # Cloned repository
│   └── cache/                      # GitHub API cache
│
├── read_only.py                    # Phase 1 implementation
├── schema.py                       # Schema validation
├── fileops.py                      # Atomic file operations
├── github.py                       # GitHub API integration
├── approval.py                     # Approval workflow
├── audit.py                        # Audit logging
├── state_machine.py                # State machine core
├── staging.py                      # Staging executor
└── commands.py                     # Command handler

└── tests/
    ├── test_read_only.py           # Phase 1 tests
    ├── test_approval_workflow.py   # Phase 2 tests
    ├── test_state_machine.py       # Phase 3 tests
    └── test_staging_commands.py    # Phase 4A tests
```

## Next Steps

**Phase 4B: VALIDATING EXECUTION**
- Smoke tests on staged artifacts
- Import validation
- Configuration parsing
- Health check dry-run
- Transition: VALIDATING → PROMOTING

This will complete the execution pipeline before the final promotion step.