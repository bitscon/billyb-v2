# Agent Zero Command Reference

Quick reference for all Agent Zero lifecycle management commands.

## 📖 Command Categories

- [Status & Information](#status--information)
- [Environment Inspection](#environment-inspection)
- [Approval Workflow](#approval-workflow)
- [State Management](#state-management)
- [Staging & Artifacts](#staging--artifacts)

---

## Status & Information

### `a0 status`

Display comprehensive Agent Zero status.

**Authority:** observer

**Output includes:**
- Current version
- Installation metadata
- State machine status
- Active operations
- Recent failures
- System locks

**Example:**
```bash
a0 status
```

### `a0 explain-state`

Detailed explanation of current state.

**Authority:** observer

**Output includes:**
- Current state and entry time
- Previous state
- Possible next states
- Blocked actions
- Active invariants
- Active operations

**Example:**
```bash
a0 explain-state
a0 explain-state --json
```

---

## Environment Inspection

### `a0 env ls <path> [-l] [-a] [-h]`

List directory contents.

**Authority:** observer

**Allowed flags:** `-l`, `-a`, `-h`

**Path restrictions:** Only within allowed roots

**Example:**
```bash
a0 env ls v2/agent_zero/.billy
a0 env ls -l v2/agent_zero/.billy
```

### `a0 env cat <file>`

Display file contents.

**Authority:** observer

**Path restrictions:** Only within allowed roots

**Binary files:** Blocked

**Example:**
```bash
a0 env cat v2/agent_zero/.billy/version.json
```

### `a0 env find <path> -maxdepth N [-type f|d] [-name pattern]`

Find files.

**Authority:** observer

**Required flags:** `-maxdepth` (max value: 3)

**Blocked flags:** `-exec`, `-delete`, `-print0`

**Example:**
```bash
a0 env find v2/agent_zero -maxdepth 2 -type f
a0 env find v2/agent_zero -maxdepth 2 -name "*.py"
```

---

## Approval Workflow

### `a0 request-upgrade <version> [--force-check] [--allow-prerelease]`

Request approval for an upgrade.

**Authority:** observer

**Flags:**
- `--force-check` - Replace existing pending approval
- `--allow-prerelease` - Allow prerelease versions

**Validations:**
- SemVer format
- Version exists in GitHub releases
- Not a downgrade
- Not draft or prerelease (unless flag set)

**Example:**
```bash
a0 request-upgrade v0.9.8
a0 request-upgrade v0.9.9 --force-check
a0 request-upgrade v1.0.0-beta.1 --allow-prerelease
```

### `a0 pending-approvals [--json]`

Display pending approvals.

**Authority:** observer

**Flags:**
- `--json` - Output raw JSON

**Example:**
```bash
a0 pending-approvals
a0 pending-approvals --json
```

### `approve a0 upgrade <version>`

Grant approval for a pending upgrade.

**Authority:** human (required)

**Side effects:**
- Deletes `pending_approval.json`
- Logs `approval_granted` event
- Transitions state: IDLE → STAGING (Phase 3+)

**Example:**
```bash
approve a0 upgrade v0.9.8
```

### `deny a0 upgrade <version> [--reason "text"]`

Deny a pending upgrade.

**Authority:** human (required)

**Flags:**
- `--reason "text"` - Reason for denial

**Side effects:**
- Deletes `pending_approval.json`
- Logs `approval_denied` event

**Example:**
```bash
deny a0 upgrade v0.9.8
deny a0 upgrade v0.9.8 --reason "Not ready for production"
```

---

## State Management

### `a0 clear-failure`

Clear a failure state.

**Authority:** human (required)

**Precondition:** State must be `FAILED`

**Transition:** FAILED → IDLE

**Example:**
```bash
a0 clear-failure
```

### `a0 confirm`

Confirm operation completion.

**Authority:** human (required)

**Precondition:** State must be `COMPLETE`

**Transition:** COMPLETE → IDLE

**Example:**
```bash
a0 confirm
```

---

## Staging & Artifacts

### `a0 begin-staging <version> [--rebuild] [--dry-run]`

Begin the staging process for a version.

**Authority:** executor + human (required)

**Preconditions:**
- State must be IDLE
- Version must have approval (or be approved)
- No existing artifact (unless `--rebuild`)

**Flags:**
- `--rebuild` - Force rebuild even if artifact exists
- `--dry-run` - Validate preconditions only, no execution

**Workflow:**
1. Generate build ID
2. Create temp directory
3. Clone repository from GitHub
4. Create virtualenv
5. Install dependencies
6. Compute checksums
7. Move to artifacts directory
8. Create manifest
9. Transition to VALIDATING
10. Clean up temp directory

**Example:**
```bash
a0 begin-staging v0.9.8 --dry-run
a0 begin-staging v0.9.8
a0 begin-staging v0.9.8 --rebuild
```

### `a0 staging-status`

Display current staging progress.

**Authority:** observer

**Output:**
- Active status (yes/no)
- Target version
- Build ID
- Current stage
- Progress percentage
- Elapsed time

**Example:**
```bash
a0 staging-status
```

### `a0 list-artifacts`

List all stored artifacts.

**Authority:** observer

**Output:**
- Version
- Build date
- Size (MB)
- Tree hash (abbreviated)

**Example:**
```bash
a0 list-artifacts
```

### `a0 cleanup-artifacts [--keep N]`

Remove old artifacts.

**Authority:** executor + human (required)

**Flags:**
- `--keep N` - Keep N most recent artifacts (default: 2)

**Safety:**
- Never deletes current version
- Never deletes known_good version

**Example:**
```bash
a0 cleanup-artifacts
a0 cleanup-artifacts --keep 5
```

---

## 🔍 Common Workflows

### Full Upgrade Workflow (Phases 1-4A)

```bash
# 1. Check current status
a0 status

# 2. Request upgrade
a0 request-upgrade v0.9.8

# 3. Review pending approval
a0 pending-approvals

# 4. Approve (human)
approve a0 upgrade v0.9.8

# 5. Begin staging (human)
a0 begin-staging v0.9.8

# 6. Monitor progress
a0 staging-status

# 7. Check status
a0 status
a0 explain-state

# 8. List artifacts
a0 list-artifacts
```

### Failure Recovery

```bash
# If staging fails
a0 explain-state          # Understand the failure
a0 clear-failure          # Clear and return to IDLE (human)

# If artifacts accumulate
a0 list-artifacts
a0 cleanup-artifacts --keep 3
```

### Inspection Workflow

```bash
# Check environment
a0 env ls v2/agent_zero/.billy
a0 env cat v2/agent_zero/.billy/version.json
a0 env find v2/agent_zero -maxdepth 2 -type f -name "*.json"

# Check state
a0 status
a0 explain-state
a0 pending-approvals
a0 staging-status
a0 list-artifacts
```

---

## 🚨 Error Handling

All commands return consistent error structure:

```json
{
  "status": "error",
  "error": "Human-readable error message",
  "authority_required": "observer|executor|human"  // If applicable
}
```

Common error types:
- **Authority errors** - "Only humans can..."
- **State errors** - "Cannot X: current state is Y"
- **Validation errors** - "Invalid version format", "Path not allowed"
- **System errors** - "Lock acquisition failed", "GitHub API error"

---

## 📋 Authority Matrix

| Command | Observer | Executor | Human Required |
|---------|----------|----------|----------------|
| `a0 status` | ✅ | ✅ | ❌ |
| `a0 explain-state` | ✅ | ✅ | ❌ |
| `a0 env <cmd>` | ✅ | ✅ | ❌ |
| `a0 request-upgrade` | ✅ | ✅ | ❌ |
| `a0 pending-approvals` | ✅ | ✅ | ❌ |
| `a0 staging-status` | ✅ | ✅ | ❌ |
| `a0 list-artifacts` | ✅ | ✅ | ❌ |
| `approve a0 upgrade` | ❌ | ❌ | ✅ |
| `deny a0 upgrade` | ❌ | ❌ | ✅ |
| `a0 clear-failure` | ❌ | ❌ | ✅ |
| `a0 confirm` | ❌ | ❌ | ✅ |
| `a0 begin-staging` | ❌ | requires human | ✅ |
| `a0 cleanup-artifacts` | ❌ | requires human | ✅ |

---

## 💡 Implementation Notes

### For Developers

1. **Path handling:** All paths use `pathlib.Path` for cross-platform compatibility
2. **Error handling:** Use try/except with specific exception types, always log
3. **Atomic operations:** All file writes use temp file + rename pattern
4. **State transitions:** Always validate before attempting
5. **Audit logging:** Log both success and failure paths

### For Operators

1. **Monitoring:** Check `upgrade_history.log` for full event stream
2. **Recovery:** Use `a0 clear-failure` when FAILED, never manually edit state
3. **Cleanup:** Run `a0 cleanup-artifacts` periodically to manage disk usage
4. **Inspection:** Use `a0 env` commands to inspect without SSH access

---

## 📚 Related Documentation

- `APPROVAL_WORKFLOW.md` - Phase 2 approval system
- `STATE_MACHINE.md` - Phase 3 state machine
- `STAGING.md` - Phase 4A staging details
- `README_PHASES.md` - Complete multi-phase overview

---

**Last updated:** 2026-02-01  
**Phase:** 4A (Staging Execution)  
**Status:** Complete ✅