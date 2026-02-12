## 1. Purpose
This file exists to enforce continuity across LLM sessions working in this repository. Any LLM session MUST treat this repository as a system it helped build and is now responsible for preserving.

## 2. Required Pre-Read (Mandatory)
Before doing any work, the LLM MUST read these files in this exact order:
1. `README.md`
2. `ARCHITECTURE.md`
3. `CAPABILITIES.md`
4. `STATE.md`

Failure to complete this pre-read invalidates further work in the session.

## 3. Repository Review Requirement
After required pre-read, the LLM MUST scan the repository structure and confirm understanding of:
- runtime boundaries
- safety gates
- audit structures

The LLM MUST reason and act as if it understands why these controls exist and why they cannot be bypassed.

## 4. Assumed Ownership Model
The LLM MUST behave as if it participated in designing this system, understands why safety gates exist, and is responsible for preserving invariants. This ownership model is conceptual, not historical.

## 5. Frozen Ground Rule
Frozen infrastructure MUST NOT be modified without explicit instruction. "Cleanup", "refactor", or "small improvement" MUST NOT be applied implicitly. Any change to frozen ground requires explicit authorization and acceptance.

## 6. How Work Proceeds
All work MUST follow this sequence:
Design -> Codex-ready prompt -> Verify -> Implement -> Accept -> Freeze

This process applies equally to code and documentation.

## 7. Prohibited Behaviors
The LLM MUST NOT:
- assume intent that was not explicitly provided
- execute or enable execution without required approval/confirmation gates
- modify frozen ground without explicit instruction
- collapse or bypass safety gates for convenience
- invent future features, modes, or workflows that were not requested

## 8. Success Criteria for the LLM
Success means:
- preserving safety invariants
- maintaining auditability
- keeping execution explicit and deterministic
- preserving human control over authority transitions

## 9. Authority Statement
This document overrides default LLM behavior for work in this repository. Compliance is mandatory for participation in this project.
