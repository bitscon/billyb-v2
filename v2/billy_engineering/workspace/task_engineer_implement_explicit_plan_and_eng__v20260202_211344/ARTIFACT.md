Summary of implemented changes

1) Charters and docs updated to use explicit modes
- Operational modes now define /plan (default, read-only) and /engineer (explicit-only).
- Governance explicitly limits modes to /plan and /engineer and disallows keyword triggering.
- Operational discipline updated to require artifacts in /engineer and to request a switch from /plan when artifacts are needed.
- Tools/Workers clarifies no execution in /plan or /engineer.

2) Repo docs updated
- Root README now includes a short Operational Modes section with /plan and /engineer behavior.
- Engineering README references /engineer explicitly and lists required artifacts.
- Integration artifacts updated to reflect /plan as default and /engineer as explicit.
- last-night.md invocation example updated to /engineer.

3) CLI usage updated
- v2/main.py usage text now includes /plan and /engineer examples and descriptions.

4) Minimal test added
- tests/test_engineering_modes.py ensures only /engineer triggers engineering intent.

Files touched
- v2/docs/charter/02_GOVERNANCE_AND_LAW.md
- v2/docs/charter/03_BILLY_IDENTITY.md
- v2/docs/charter/04_OPERATIONAL_MODES.md
- v2/docs/charter/05_OPERATIONAL_DISCIPLINE.md
- v2/docs/charter/08_TOOLS_WORKERS_EXECUTION.md
- v2/docs/charter/README.md
- v2/billy_engineering/README.md
- README.md
- integration_artifacts/billy-inventory.md
- integration_artifacts/billy-architecture-map.md
- last-night.md
- v2/main.py
- v2/core/runtime.py (optional root_path arg only, no behavior change)
- tests/test_engineering_modes.py
