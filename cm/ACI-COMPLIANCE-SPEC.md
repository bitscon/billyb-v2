Agentic Cognitive Infrastructure (ACI)
Compliance Specification v1.0
Status

Specification type: Normative

Scope: Protocol compliance only

Normative phase range: Phases 27–69

Execution authority: Out of scope

This document defines compliance, not capability

1. Purpose

This specification defines the minimum requirements a system MUST satisfy to claim ACI Compliance.

ACI Compliance certifies that a system:

Preserves human authority supremacy

Prevents authority leakage

Enforces deterministic governance boundaries

Separates cognition from execution

Produces auditable, append-only protocol artifacts

Compliance does not imply intelligence, usefulness, or performance.

Compliance implies governance correctness.

2. Definitions

Human Authority Root (HAR):
The sole origin of permission, authorization, approval, and revocation.

Protocol Artifact:
An immutable, structured record defined by a phase contract.

Phase:
A discrete governance boundary with deterministic validation and rejection behavior.

Execution:
Any action that mutates external state, invokes tools, performs I/O, or triggers effects beyond protocol record creation.

Fail-Closed:
Missing or invalid prerequisites must result in rejection or invalid state, never implicit acceptance.

3. Compliance Levels
3.1 Full ACI Compliance

A system implementing all normative requirements in Sections 4–11.

3.2 Partial Compliance (Non-Certifiable)

Systems that selectively implement concepts but fail mandatory controls MUST NOT claim ACI compliance.

No “ACI-inspired” branding is permitted under this spec.

4. Authority Model Requirements (MANDATORY)

A compliant system MUST:

Treat human-issued artifacts as the only source of authority.

Prohibit inferred, implicit, heuristic, or probabilistic authorization.

Enforce explicit revocation and supersession semantics.

Ensure downstream artifacts become invalid when upstream authority is revoked.

Prevent agents, models, or orchestrators from generating net-new authority.

❌ Systems that infer permission from context are non-compliant.

5. Phase Separation Requirements (MANDATORY)

A compliant system MUST:

Separate cognition, planning, authorization, and execution-adjacent concerns into distinct phases.

Enforce phase ordering and dependency constraints.

Prevent any phase from assuming downstream rights.

Encode separation as protocol contracts, not runtime conventions.

❌ Systems where planning and execution coexist in the same control loop are non-compliant.

6. Determinism Requirements (MANDATORY)

Each phase MUST define and enforce:

Deterministic validation order.

Deterministic rejection codes.

Explicit rejection code priority ordering.

Fail-closed behavior for missing, expired, revoked, or mismatched artifacts.

❌ Heuristic retries, fallback paths, or silent recovery violate compliance.

7. Immutability & Audit Requirements (MANDATORY)

A compliant system MUST:

Treat all protocol artifacts as write-once.

Enforce append-only mutation semantics.

Represent revocation via additional artifacts, never overwrite.

Preserve full lineage across artifacts.

Produce auditable rejection outcomes.

❌ Mutable protocol state invalidates compliance.

8. Execution Boundary Requirements (MANDATORY)

Up to and including Phase 69, a compliant system MUST:

Keep execution_enabled = false.

Treat execution as external, non-cognitive, and replaceable.

Prevent protocol artifacts from triggering execution.

Forbid callbacks, retries, escalation, or follow-on control.

Restrict final boundary to declarative handoff only.

❌ Systems that “quietly execute” after planning are non-compliant.

9. Anti-Replay & Uniqueness Requirements (MANDATORY)

A compliant system MUST:

Enforce single-use semantics where defined.

Prevent replay of attempts, authorizations, and handoffs.

Reject duplicate artifacts deterministically.

Bind artifacts to explicit environment scope.

❌ Reusable authority tokens violate compliance.

10. Intent Handling Requirements (MANDATORY)

A compliant system MUST:

Treat intent resolution as non-executing.

Surface only admissible protocol actions to the human.

Never auto-issue authority artifacts.

Halt and wait on ambiguity or uncertainty.

❌ Systems that “decide for the user” violate compliance.

11. Forbidden Behaviors (ABSOLUTE)

The following behaviors permanently disqualify ACI compliance:

Implicit permission inference

Autonomous execution

Silent retries or fallbacks

Executor callbacks

Hidden control flow

Authority escalation by model inference

Context-based permission carryover

Memory-based authorization inference

12. Compliance Verification

Compliance MAY be demonstrated by:

Static audit of protocol contracts

Artifact lineage verification

Deterministic rejection testing

Replay attack simulation

Authority revocation tests

ACI compliance is verifiable, not subjective.

13. Branding & Trademark Usage (Non-Normative)

“ACI-Compliant” may be used only by systems meeting this spec.

The ACI name refers to the protocol, not any implementation.

Claiming compliance without verification is prohibited.

14. Relationship to Implementations (Non-Normative)

ACI does not mandate:

Model choice

Runtime architecture

Language

Deployment topology

User experience

ACI mandates governance correctness only.

Billy is an example implementation, not a requirement.

15. Final Statement

ACI Compliance is not about intelligence.

It is about trustworthy cognition under human authority.

A system is either compliant — or it is not.

There is no middle ground.
