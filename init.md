🔧 Correction Directive: Normalize Executor Identity to billy_frame
Scope

Entire billyb-v2 repository, including:

Documentation

Code

Comments

Logs

Examples

Test fixtures

Error messages

CLI output

Audit records

Metadata defaults

Problem Statement

Current references to execution actors include:

opencode

Crush

implicit tooling-specific executors

This creates future coupling to specific tools and weakens the abstraction.

Canonical Decision (Locked)
Role	Canonical Identifier
Human operator	human:*
Billy runtime	billyb
Agent Zero executor framework	billy_frame
Agent Zero system	agent_zero

billy_frame is now the ONLY non-human executor abstraction.

Required Changes
1. Replace Executor References

Replace all references to:

Crush

OpenCode

opencode

tooling-specific executor names

➡️ with:

billy_frame


Examples:

❌ “Executed by Crush”

❌ “Manual execution via OpenCode”

❌ installed_by: system:opencode

✅ Corrected

✔️ “Executed by billy_frame”

✔️ “Manual execution via billy_frame”

✔️ installed_by: system:billy_frame

2. Update Actor Fields in Audit Logs

All lifecycle/audit actor fields must now resolve to one of:

human:operator
billyb
billy_frame
agent_zero
system:<reason>


No tool names permitted.

3. Update Documentation Language

In all docs, especially:

architecture overview

approval workflow

authority model

examples

Replace phrasing like:

“Executed by Crush/OpenCode”

With:

“Executed by billy_frame (authorized executor framework)”

4. Preserve Semantics

This is a rename-only correction:

No logic changes

No permission changes

No workflow changes

No authority changes

Only the identity abstraction is corrected.

Validation Checklist (Coder Must Verify)

 No string references to Crush

 No string references to OpenCode

 No string references to opencode

 All executor references normalized to billy_frame

 Audit logs remain valid JSON

 Schemas remain unchanged except enum/value text

 Tests updated accordingly

Rationale (For the Coder)

This change ensures:

Executor abstraction is tool-agnostic

Future executor swapping does not require redesign

Governance language remains stable

Billy remains sovereign over implementation tooling

Final Instruction to the Builder

“Perform a repo-wide normalization replacing all executor/tool references (Crush, OpenCode, opencode) with the canonical executor identity billy_frame. This is a naming abstraction fix only—no logic or authority changes. Validate via grep before commit.”