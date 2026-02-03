Problem statement
Billy needs explicit, named modes (/plan and /engineer) reflected across docs and runtime-adjacent materials, plus a CLI usage hint and a minimal test to ensure /engineer is the only trigger.

Constraints
- /plan is default read-only; no filesystem writes or artifact enforcement.
- /engineer is explicit-only; no keyword inference.
- No API surface changes.
- Do not alter runtime behavior beyond naming and clarity.

Non-goals
- No new API endpoints.
- No tool execution or deployment logic.
- No changes to LLM provider configuration.

Proposed approach
1. Update charters and docs to reference /plan and /engineer explicitly.
2. Update repo README and engineering README to clarify mode behavior.
3. Add CLI usage text describing modes and examples.
4. Add a minimal unit test asserting /engineer is the only trigger.
