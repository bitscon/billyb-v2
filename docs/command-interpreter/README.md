# Command Interpreter (Phase 0 Contract)

## Purpose
The Command Interpreter converts a raw user utterance into a deterministic, auditable Intent Envelope.

Phase 0 defines the contract only. It does not implement runtime interpretation behavior.

## Non-Goals
- No command execution
- No tool invocation
- No lane routing or dispatch wiring
- No LLM inference
- No autonomy or background task behavior
- No changes to existing execution contracts

Interpretation and execution remain strictly separated.

## Core Definitions
### Lane
A lane is the high-level handling class assigned to an utterance.

Allowed lane values:
- `CHAT`
- `PLAN`
- `ENGINEER`
- `HELP`
- `CLARIFY`
- `REJECT`

### Intent
Intent is a stable symbolic label describing what the user is asking for, independent of execution.

Example intent names:
- `chat.recommend_drink`
- `plan.create_empty_file`
- `engineer.enter_mode`
- `clarify.request_context`

### Policy
Policy is the explicit safety decision attached to interpretation. It must include:
- `risk_level`
- `allowed`
- `reason`

Policy is advisory at interpretation time and does not grant execution authority.

### Clarification
Clarification is a contract outcome (`lane=CLARIFY`) when the utterance is incomplete or ambiguous. The interpreter must provide a concrete `next_prompt` question.

## Canonical Artifact
The canonical format is defined in:
- `schemas/intent_envelope.schema.json`

Each envelope must include:
- `utterance`
- `lane`
- `intent`
- `entities`
- `confidence`
- `requires_approval`
- `policy` (`risk_level`, `allowed`, `reason`)
- `next_prompt`

## Relationship to Billy Maturity Model
Phase 0 aligns with interpretation-only infrastructure:
- Preserves separation between reasoning/interpretation and execution authority
- Introduces no new authority paths
- Keeps approvals and side effects outside the interpreter boundary

This contract enables Phase 1 implementation without changing execution gates.

## Phase 0 Test Expectations
Phase 0 tests are split into:
- Contract validity tests (schema and fixtures) that pass now
- Interpreter behavior tests that fail until implementation exists

Golden fixtures are in:
- `tests/command_interpreter/fixtures/`

These fixtures are the source of truth for initial behavior targets, including known problematic transcript inputs.
