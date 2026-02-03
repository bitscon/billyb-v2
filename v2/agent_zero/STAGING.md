# Agent Zero Staging Execution (Phase 4A)

This document describes the staging execution layer for Agent Zero lifecycle management implemented in Phase 4A.

## Overview

Phase 4A introduces the first real execution layer for Billy's upgrade system. This phase enables Billy to **acquire, clone, and prepare** a new Agent Zero version in complete isolation from production.

This is where Billy gains **executor authority** for the first time, but only within a tightly constrained sandbox.

## Key Constraints

| Rule | Enforcement |
|------|-------------|
| **Authority** | `executor` (for staging operations only) |
| **Mutation scope** | `/tmp/agent_zero_build_*` + `.billy/artifacts/` + `.billy/` metadata |
| **Production tree** | ❌ `v2/agent_zero/` is **NEVER touched** |
| **State machine** | All transitions must pass Phase 3 validators |
| **Failure mode** | Fail closed — cleanup and return to IDLE |

If any constraint is violated → **ABORT + CLEANUP + LOG**

## File Structure

```
v2/agent_zero/.billy/
├── state.json                    # state machine (Phase 3)
├── version.json                  # current version (read-only in 4A)
├── known_good.json               # rollback target (read-only in 4A)
├── pending_approval.json         # approval record (consumed)
├── upgrade_history.log           # audit log (append-only)
├── last_health_check.json        # health status
├── .lock                         # file lock
└── artifacts/                    # NEW: validated builds
    └── vX.Y.Z/                   # versioned artifact directory
        ├── manifest.json         # build metadata + checksums
        └── <agent_zero_files>/   # complete cloned tree

/tmp/
└── agent_zero_build_<uuid>/      # ephemeral staging area
```

## Staging Workflow

### Entry Conditions

All of the following must be true:

- `state.json.current_state == IDLE`
- `pending_approval.json` exists and is valid
- Approval version matches requested version
- `authority_level` is escalated to `executor` (human-initiated)
- No existing artifact for target version (or `--rebuild` flag)

### Execution Steps

1. **INITIALIZE**
   - Generate build_id (UUID4)
   - Create temp directory: `/tmp/agent_zero_build_<build_id>`
   - Acquire file lock
   - Transition: IDLE → STAGING
   - Log: staging_started

2. **CLONE**
   - `git clone --depth 1 --branch <version> <repo_url> <temp>`
   - Verify commit SHA matches GitHub API response
   - Update state: staging.stage = "cloning"
   - Log: clone_completed
   - On failure: ABORT → cleanup → FAILED

3. **CREATE VIRTUALENV**
   - `python -m venv <temp>/.venv`
   - Activate and install: `pip install -r requirements.txt`
   - Update state: staging.stage = "installing"
   - Log: dependencies_installed
   - On failure: ABORT → cleanup → FAILED

4. **CHECKSUM**
   - Walk all files, compute SHA256 for each
   - Compute tree_hash = SHA256(sorted file hashes)
   - Update state: staging.stage = "checksumming"
   - Log: checksums_computed

5. **FINALIZE ARTIFACT**
   - Create `.billy/artifacts/vX.Y.Z/`
   - Move temp contents → artifact directory
   - Write manifest.json (validated against schema)
   - Update state: staging.stage = "finalizing"
   - Log: artifact_stored

6. **TRANSITION TO VALIDATING**
   - Validate manifest.json schema
   - Transition: STAGING → VALIDATING
   - Log: staging_completed
   - Release file lock

## Commands

### `a0 begin-staging <version> [--rebuild] [--dry-run]`

Begins the staging process for a new version.

**Authority:** executor + human

**Flags:**
- `--rebuild`: Force re-stage even if artifact exists
- `--dry-run`: Validate preconditions only, no execution

**Example:**
```
a0 begin-staging v0.9.8
```

**Output (success):**
```
✓ Staging v0.9.8 initiated (build_id: abc123...)
✓ Cloning from GitHub...
✓ Installing dependencies...
✓ Computing checksums...
✓ Artifact stored: .billy/artifacts/v0.9.8/
✓ Transitioned to VALIDATING
```

**Output (failure):**
```
✗ Staging failed at stage: installing
  Error: pip install returned exit code 1
✗ Temp directory cleaned up
✗ State: FAILED
  Run 'a0 explain-state' for details
```

### `a0 staging-status`

Displays the current staging status.

**Authority:** observer

**Example:**
```
a0 staging-status
```

**Output:**
```
Staging Status:
  State: STAGING
  Target: v0.9.8
  Build ID: abc123-def456-...
  Stage: installing (45%)
  Temp Path: /tmp/agent_zero_build_abc123/
  Elapsed: 2m 34s
```

### `a0 list-artifacts`

Lists all stored artifacts.

**Authority:** observer

**Example:**
```
a0 list-artifacts
```

**Output:**
```
Stored Artifacts:
  v0.9.1  │ 2026-01-28 │ 145 MB │ tree:a3f8c2...
  v0.9.2  │ 2026-02-02 │ 148 MB │ tree:b7d4e1...
```

### `a0 cleanup-artifacts [--keep N]`

Removes old artifacts beyond retention policy.

**Authority:** executor + human

**Flags:**
- `--keep N`: Keep N most recent artifacts (default: 2)

**Safety:**
- Never deletes current version artifact
- Never deletes known_good version artifact

**Example:**
```
a0 cleanup-artifacts --keep 3
```

## Manifest Schema

Each artifact has a `manifest.json` file with the following structure:

```json
{
  "version": "v0.9.8",
  "built_at": "2026-02-02T15:30:00Z",
  "source_url": "https://github.com/frdel/agent-zero.git",
  "commit_sha": "abc123def456...",
  "checksums": {
    "algorithm": "sha256",
    "files": {
      "file1.py": "hash1...",
      "file2.py": "hash2..."
    },
    "tree_hash": "combined_hash..."
  },
  "build_id": "uuid-here",
  "build_log_path": null,
  "virtualenv_hash": null
}
```

## Failure Handling

On any error during staging:

1. Log the failure with full context
2. Cleanup temp directory (always deleted)
3. Transition to FAILED state
4. Release file lock

### Cleanup Guarantees

- Temp directories are **always** deleted on failure
- Partial artifacts are **never** written to `.billy/artifacts/`
- State always reflects reality
- Audit log captures full failure context

## Audit Log Events

The following events are logged to `upgrade_history.log`:

| Event | When |
|-------|------|
| `staging_started` | Workflow begins |
| `clone_completed` | Git clone succeeds |
| `clone_failed` | Git clone fails |
| `dependencies_installed` | pip install succeeds |
| `dependencies_failed` | pip install fails |
| `checksums_computed` | All hashes calculated |
| `artifact_stored` | Final artifact written |
| `staging_completed` | Transition to VALIDATING |
| `staging_failed` | Any failure during staging |
| `temp_cleanup_completed` | Temp directory removed |
| `artifact_deleted` | Old artifact garbage collected |

## Security Features

1. **Production Isolation**
   - Production tree (`v2/agent_zero/`) is never touched
   - All work happens in isolated directories
   - No symlink manipulation
   - No service restarts

2. **Authority Requirements**
   - Staging requires executor authority
   - Only humans can initiate staging
   - Observer authority can view status and artifacts

3. **Failure Safety**
   - All failures result in cleanup
   - No partial artifacts
   - State machine integrity preserved
   - Full audit trail

## State Transitions

Phase 4A implements the following state transitions:

```
IDLE → STAGING → VALIDATING
STAGING → FAILED (on any error)
FAILED → IDLE (via a0 clear-failure, human only)
```

Phase 4A does NOT implement:
- `VALIDATING → PROMOTING`
- `PROMOTING → COMPLETE`
- Any automatic promotion logic

## Implementation Files

- `staging.py`: Core staging execution module
- `commands.py`: Command handler integration  
- `demo_staging.py`: Demo script

## Next Phase

**Phase 4B: VALIDATING EXECUTION**
- Smoke tests on staged artifact
- Import validation
- Config parsing
- Health check dry-run