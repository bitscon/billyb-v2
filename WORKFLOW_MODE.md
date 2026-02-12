## 1. Purpose
Workflow Mode is Level-4 infrastructure for Billy’s maturity ladder. It enables deterministic automation of already-governed actions without introducing autonomy, inference, or new execution authority.

## 2. Definition of Workflow Mode
Workflow Mode is deterministic orchestration of predeclared steps and state transitions. It is not planning, not autonomous decision-making, and not a mechanism for selecting tools or actions dynamically.

Workflow Mode coordinates existing governed actions; it does not create new power paths.

## 3. Core Invariant
A workflow may only perform actions that could already be executed individually under existing gates.

No workflow step may bypass, weaken, or replace the gate logic of the underlying mode.

## 4. Workflow Artifact Model (Conceptual)
A workflow is a declared, immutable artifact with conceptual fields:
- `id`: stable workflow identity
- `steps`: ordered, explicit step definitions
- `status`: lifecycle state of the workflow
- `audit`: append-only execution and validation history

Once declared and accepted, a workflow artifact is treated as immutable. Changes require a new workflow identity.

## 5. Allowed Step Types
Execution-capable workflow steps are limited to actions that map one-to-one to existing execution modes:
- Code-application steps mapped to CAM semantics
- Tool-execution steps mapped to TEM semantics

A workflow may reference prerequisite approvals, but it must not perform implicit approval, implicit registration, or implicit confirmation on behalf of those modes.

## 6. Workflow Gates
Workflow Mode requires explicit workflow approval before execution.

Each step must re-run the full validation gates of its mapped mode at execution time. Prior validation from earlier phases is not sufficient on its own.

Failure behavior is strict:
- first failing step stops the workflow
- downstream steps do not execute
- no implicit retries
- no fallback substitution

## 7. Visibility vs Execution
Defined or approved workflows are not executable by default. Visibility of a workflow does not grant execution permission.

Execution occurs only through explicit invocation under workflow gates and underlying mode gates.

## 8. Audit and Forensics Model
Workflow Mode requires two audit layers:
- Workflow-level audit: identity, declared steps, lifecycle transitions, terminal outcome
- Step-level audit: mapped mode, validation outcomes, execution outcome, side-effect summary

Final outcomes must be classified explicitly (for example: successful completion, validation stop, execution failure, explicit halt) so forensic interpretation is deterministic.

## 9. Relationship to the Maturity Ladder
Workflow Mode defines Level-4 completion as orchestration infrastructure over existing governed actions. It does not increase authority beyond what CAM and TEM already permit.

Safe Autonomy (Level-5) is impossible without this layer because autonomy requires a deterministic, auditable orchestration substrate with enforced gates.

## 10. Frozen Ground Statement
This design is stable infrastructure once accepted. It must not be modified implicitly.

Any change requires explicit redesign, explicit acceptance, and explicit freeze.
