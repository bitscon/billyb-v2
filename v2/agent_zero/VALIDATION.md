# Agent Zero Artifact Validation (Phase 4B)

This document describes the validation engine for Agent Zero lifecycle management implemented in Phase 4B.

## Overview

Phase 4B implements the "Safety Gate" that sits between STAGING (Phase 4A) and PROMOTION. It performs comprehensive checks on staged artifacts to ensure they are safe to promote to production.

## The Validation Engine

### Core Objective

The `ArtifactValidator` engine accepts a staged artifact path and returns:
- A boolean Pass/Fail status
- A detailed JSON report
- A state machine transition (VALIDATING → PROMOTING or VALIDATING → FAILED)

### Success Criteria

- ✅ Valid artifacts transition state to `PROMOTING`
- ✅ Invalid artifacts transition state to `FAILED`  
- ✅ **Zero side effects** on the live `agent_zero` installation

## Validation Checks (The "Smoke Suite")

The validator performs 6 comprehensive checks:

### 1. Structural Integrity
**Target:** Filesystem  
**Logic:** Verify critical files and directories exist

**Critical items checked:**
- `agent.py`
- `models.py`
- `prompts/`
- `python/`
- `requirements.txt`

### 2. Import Sanity
**Target:** Runtime  
**Logic:** Run `python -c "import agent"` using the artifact's virtualenv

**Implementation:** Subprocess isolation (never imports into Billy's process)

**Safety:** 10-second timeout per check

### 3. Config Parsing
**Target:** Schema  
**Logic:** Load `.env.example` and `conf/`. Verify parsability.

**Checks:**
- Config files exist
- Files are readable

### 4. Tool Registry
**Target:** Registry  
**Logic:** Verify tools directory exists and contains tool files

**Checks:**
- `python/tools/` directory exists
- Tool files are present

### 5. Prompt Assets
**Target:** Assets  
**Logic:** Check that mandatory Markdown templates exist and are non-empty

**Mandatory prompts:**
- `agent.system.main.md`

### 6. Memory Initialization
**Target:** Vector DB  
**Logic:** Verify memory subsystem can initialize cleanly

**Note:** Phase 4B implements a placeholder check. Full implementation would initialize FAISS/Chroma in a temporary directory.

## Technical Constraints

1. **Timeouts:** 
   - Individual check: 10 seconds
   - Total suite: 30 seconds

2. **Fail-Closed:** Any unhandled exception → `FAILED` state

3. **Idempotency:** Running validation twice yields same result

4. **Subprocess Isolation:**
   - ✅ Good: `subprocess.run([artifact_venv_python, "-c", "import agent"])`
   - ❌ Bad: `import artifacts.v1.agent_zero` (pollutes memory)

## File Structure

```
v2/agent_zero/.billy/
├── state.json                   # READ/WRITE (Transitions)
├── artifacts/
│   └── vX.Y.Z/                  # READ ONLY (Target)
│       ├── agent.py             # Source code
│       ├── .venv/               # Virtual environment
│       └── manifest.json        # Build metadata
└── validation/                  # WRITE ONLY (Outputs)
    ├── latest_report.json       # Most recent report
    ├── history/                 # Rotated reports (last 10 per version)
    └── logs/                    # Detailed subprocess outputs
```

## Validation Report Schema

```json
{
  "version": "v0.9.8",
  "timestamp": "2026-02-02T15:45:00Z",
  "status": "PASSED",
  "checks": {
    "structural_integrity": {
      "passed": true,
      "ms": 12,
      "error": null,
      "details": {"checked": ["agent.py", "models.py", ...]}
    },
    "import_sanity": {
      "passed": true,
      "ms": 245,
      "error": null,
      "details": {"import": "success"}
    },
    ...
  },
  "artifact_hash": "sha256:abc123...",
  "elapsed_ms": 1234
}
```

## State Machine Integration

### Entry Condition
Current state MUST be `VALIDATING` or `STAGING`

### Exit (Pass)
`current_state` → `PROMOTING`

### Exit (Fail)
```json
{
  "current_state": "FAILED",
  "last_failure": {
    "state": "VALIDATING",
    "error": "Validation failed: structural_integrity, import_sanity",
    "occurred_at": "2026-02-02T15:45:00Z",
    "cleared": false
  }
}
```

## Commands

### `a0 validate [--version X.Y.Z]`

Run validation checks on a staged artifact.

**Authority:** executor

**Arguments:**
- `--version X.Y.Z` - Specify version to validate (optional, uses active operation if not provided)

**Example:**
```bash
a0 validate
a0 validate --version v0.9.8
```

**Output (success):**
```json
{
  "status": "success",
  "validation_status": "PASSED",
  "version": "v0.9.8",
  "report": { ... }
}
```

**Output (failure):**
```json
{
  "status": "failed",
  "validation_status": "FAILED",
  "version": "v0.9.8",
  "report": {
    "checks": {
      "structural_integrity": {
        "passed": false,
        "error": "Missing critical items: models.py"
      }
    }
  }
}
```

### `a0 report`

Display the latest validation report.

**Authority:** observer

**Example:**
```bash
a0 report
```

**Output:**
```json
{
  "status": "success",
  "report": {
    "version": "v0.9.8",
    "timestamp": "2026-02-02T15:45:00Z",
    "status": "PASSED",
    "checks": { ... },
    "artifact_hash": "sha256:...",
    "elapsed_ms": 1234
  }
}
```

## Audit Log Events

Phase 4B adds these event types to `upgrade_history.log`:

| Event | When |
|-------|------|
| `validation_started` | Validation begins |
| `validation_completed` | All checks passed |
| `validation_failed` | One or more checks failed |
| `check_passed` | Individual check succeeded |
| `check_failed` | Individual check failed |
| `report_stored` | Report written to disk |

## Testing

### Mock Artifact Generator

For testing without actual staging:

```python
from v2.agent_zero.tests.mock_artifact import create_mock_artifact

# Create valid artifact
artifact = create_mock_artifact(version="v0.9.8")

# Create broken artifact
broken = create_broken_artifact(
    version="v0.9.9",
    break_type="missing_files"  # or "no_venv", "empty_prompts", "no_tools"
)
```

### Test Cases

1. ✅ Valid artifact passes all checks
2. ✅ Missing files fail integrity check
3. ✅ No virtualenv fails import check
4. ✅ Empty prompts fail prompt check
5. ✅ No tools fails tool check
6. ✅ Reports are stored correctly
7. ✅ Reports validate against schema
8. ✅ Validation is idempotent
9. ✅ Non-existent artifacts raise error
10. ✅ All checks report timing

## Security Features

1. **Process Isolation**
   - Import checks run in subprocess
   - Never pollute Billy's runtime
   - Timeout protection (10s per check)

2. **No Side Effects**
   - Validation is read-only
   - No modifications to artifact
   - No modifications to production

3. **Fail-Closed**
   - Any error → FAILED state
   - Comprehensive error logging
   - Clear failure messages

## Implementation Files

- `validator.py` - Core validation engine
- `tests/mock_artifact.py` - Mock artifact generator
- `tests/test_validator.py` - Validation test suite
- `demo_validation.py` - Interactive demo

## Report Rotation

Validation reports are automatically rotated:
- Latest report: `validation/latest_report.json`
- History: `validation/history/<version>_<timestamp>.json`
- Retention: Last 10 reports per version

## State Transitions

Phase 4B implements:

```
VALIDATING → PROMOTING (on validation success)
VALIDATING → FAILED (on validation failure)
```

Phase 4B does NOT implement:
- `PROMOTING → COMPLETE` (Phase 4C)
- Automatic promotion after validation
- Execution of validated code

## Next Phase

**Phase 4C: PROMOTING EXECUTION**
- Atomic swap of production directory
- Backup of current version
- Service restart coordination
- Rollback capability
- Transition: PROMOTING → COMPLETE