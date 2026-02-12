# Directory Structure



v2/agent_zero/
├── .billy/
│ ├── version.json # critical
│ ├── known_good.json # critical
│ ├── state.json # critical
│ ├── pending_approval.json # optional
│ ├── upgrade_history.log # critical, append-only
│ └── last_health_check.json # non-critical
├── agent_zero_code/


## File Classes
| Type | Files |
|----|----|
| Critical | version, known_good, state, history |
| Non-Critical | pending_approval, health |

## Permissions
All `.billy/*` files: `644`  
Append-only enforced in application logic.