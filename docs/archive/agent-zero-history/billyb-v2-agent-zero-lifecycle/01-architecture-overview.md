# Architecture Overview

## Core Concept
Agent Zero is treated as a **managed subsystem** with:
- explicit lifecycle
- immutable audit trail
- human-approved upgrades
- rollback guarantees

## Paths
- **Working:** `v2/agent_zero/`
- **Metadata:** `v2/agent_zero/.billy/`
- **Staging:** `/tmp/agent_zero-<version>/`

## Release Source
- GitHub tagged releases only
- No branches
- No prereleases

## Roles
| Actor | Role |
|------|-----|
| Human | Final authority |
| Billy | Observer by default |
| billy_frame | Initial executor |

Billy may **earn** executor authority, never assume it.

## Upgrade Model
- Detect → Request → Approve → Execute → Confirm
- State-machine enforced
- Authority enforced