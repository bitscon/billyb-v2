## Purpose
This file is the fast capability reference for Billy v2. It defines, by mode, what is currently allowed and what is explicitly forbidden.

## Capability Table
| Mode | Trigger | Allowed | Forbidden |
|---|---|---|---|
| ERM | `engineer:`, `analyze:`, `review:` | Read-only engineering reasoning and structured analysis | File writes, command execution, tool calls, state mutation |
| CDM | `draft:`, `code:`, `propose:`, `suggest:`, `fix:` | Create immutable code draft artifacts with proposed file operations | Applying drafts, executing drafts, implicit scope expansion |
| APP | `approve: <draft_id>` | Validate and approve immutable code drafts; append approval records | Approving unknown/non-CDM/drifted drafts; applying code |
| CAM | `apply: <draft_id>` | Apply approved code drafts within validated scope; append apply records | Applying unapproved drafts, bypassing hash/scope checks, retries/self-healing |
| TDM | `tool:`, `define tool:`, `design tool:`, `propose tool:` | Create immutable tool definition drafts and canonical tool hashes | Tool registration, tool execution, runtime wiring changes |
| Tool Approval | `approve tool: <tool_draft_id>` | Validate and approve immutable tool drafts; append tool approval records | Approving unknown/non-TDM/drifted drafts; registration/execution |
| TRM | `register tool: <tool_draft_id>` | Register approved tools as visible metadata; append registration records | Tool execution, implicit permission grants, registration without approval/hash match |
| TEM | `run tool: <tool_name> <json_payload>` then `confirm run tool: <tool_name>` | Validate pending tool runs, execute only after confirmation, append execution records | Execution without confirmation, tool chaining, parameter inference, retries/fallback execution |

## Execution Notes
- Visibility is not executability: registered tools can be visible while still non-executable.
- Approval is not execution: approvals freeze artifacts; they do not run code or tools.
- TEM requires two explicit steps: `run tool:` (validation + pending) and `confirm run tool:` (execution).
- Executability defaults to disabled unless enabled in approved tool definition and preserved in registration metadata.
- Missing any required gate results in hard-stop rejection.

## Frozen Ground Notice
The capabilities listed here are stable, frozen, and authoritative for the current repository state.
