# Billy Engineering Subsystem

This subsystem enforces Billy's `/engineer` contract:

- Engineering tasks must produce inspectable artifacts.
- Artifacts are written to an immutable, versioned workspace.
- Responses without artifacts are invalid for `/engineer` requests.

Workspace layout:

```
workspace/
  task_<slug>__vYYYYMMDD_HHMMSS/
    PLAN.md
    ARTIFACT.<ext>
    VERIFY.md
```

State tracking:

```
state/engineering_state.json
```

This directory is the only location where Billy may write engineering artifacts.

Mode rules:
- `/plan` is the default, read-only mode.
- `/engineer` is explicit-only and requires `PLAN.md`, `ARTIFACT.md`, and `VERIFY.md`.

## Testing (Billy Engineering)

By default, pytest is scoped to Billy’s engineering tests only.

- Test root: `v2/billy_engineering/tests/`
- Isolation is intentional to avoid pulling in Agent Zero or adapter dependencies.
- This is enforced via `pytest.ini` at repo root.

To run tests:
    ./venv/bin/pytest -q
