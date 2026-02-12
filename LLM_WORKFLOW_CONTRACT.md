# LLM Workflow Contract

## 1. Purpose of This Contract
This contract defines the required behavior for any LLM working in this repository. LLM behavior MUST be constrained, explicit, and auditable to prevent drift, overreach, and mismatched expectations. This document is authoritative and MUST be treated as the source of truth for collaboration workflow.

## 2. Core Collaboration Model
All work MUST follow this sequence: Design -> Codex-Ready Prompt -> Verify -> Implement -> Accept -> Freeze. This sequence applies equally to code and documentation. LLMs MUST treat both artifact types with the same rigor, verification standard, and acceptance gate.

## 3. Role of the Human
The human decides direction, scope, and final acceptance. The human MUST explicitly approve or freeze work. Silence MUST NOT be interpreted as approval.

## 4. Role of the LLM
The LLM MUST propose work through Codex-ready prompts when drafting implementation instructions. The LLM MUST NOT auto-draft final artifacts unless the human explicitly requests direct drafting. The LLM MUST NOT assume authority to implement, refactor, or change scope on its own.

## 5. Codex-Ready Prompts (Definition)
A Codex-ready prompt is an implementation instruction that can be executed directly without ambiguity. Every Codex-ready prompt MUST include:
- Objective
- Constraints
- Required structure
- Definition of Done
- Output rules

If any required component is missing, the prompt SHOULD be treated as incomplete.

## 6. Drafting Rules
LLMs MUST NOT inline large artifacts by default. LLMs SHOULD prefer instructing Codex to generate artifacts through explicit execution prompts. Any exception requires explicit human request.

## 7. Verification & Acceptance
All outputs MUST be verified before acceptance. Acceptance MUST be explicit and recorded in the conversation. Until explicit acceptance is given, artifacts remain provisional.

## 8. Frozen Ground Rule
Once an artifact is frozen, it MUST NOT be modified without explicit human instruction. "Small cleanup" or "minor improvement" MUST NOT be applied implicitly. Any post-freeze change requires a new explicit instruction and acceptance cycle.

## 9. Failure Modes to Avoid
LLMs MUST avoid the following behaviors:
- Over-helping beyond requested scope
- Silent refactors
- Mixing design and implementation in the same step without instruction
- Skipping verification before acceptance

These are workflow violations, not stylistic issues.

## 10. How New LLM Sessions Should Use This File
Every new LLM session MUST read this file first before proposing or executing work. Compliance with this contract is mandatory for all collaboration in this repository.
