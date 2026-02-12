# Authority Model

## Levels

### observer
May:
- Read status
- Check updates
- Request approvals

May NOT:
- Upgrade
- Rollback
- Confirm
- Self-escalate

### executor
May:
- Upgrade
- Rollback
- Execute lifecycle operations

Still may NOT:
- Approve upgrades
- Grant authority

## Escalation Preconditions (ALL required)
1. ≥1 successful manual upgrade
2. ≥1 successful rollback
3. Governance files valid
4. Audit trail intact

## Automatic Revocation
- Integrity violation
- Unauthorized mutation
- FAILED_HARD