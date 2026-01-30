# Phase 3 — Docker Runtime & Scaling (Billy-Managed)

    ## Goal
    Make Docker a first-class execution substrate that Billy manages directly, enabling safe tool execution and scalable
 concurrency.

    This phase assumes: **Billy already has Docker access**, and we will operationalize it.

    ## Deliverables
    - A Billy “DockerRunner” (name illustrative) implementing `ToolRunner`
    - Container execution policies:
      - resource limits
      - network policies
      - filesystem mounts
      - secrets injection strategy
    - Concurrency and scaling controls:
      - local worker pool + queue
      - optional Docker Compose scale or Docker Swarm mode
    - Documentation:
      - `docs/docker-execution.md`
      - `docs/tool-images.md`
    - Example tool container images:
      - at least 1–3 reference tool images + Dockerfiles

    ## Design principles
    - Default-deny network for untrusted tools (enable explicit egress allowlists)
    - Non-root containers where possible
    - Read-only filesystem where possible
    - Explicit timeouts for all tool runs
    - Structured logs and trace IDs propagated into container runs

    ## Actions (step-by-step)

    ### 3.1 — Define tool execution model
    Decide and document:
    - What constitutes a “tool”:
      - command
      - container image
      - arguments schema
      - expected outputs (stdout/json/artifacts)
    - What artifacts are allowed:
      - output files in a dedicated workspace directory
      - size limits

    **Success criteria**
    - There is a single canonical “ToolSpec” describing container execution.

    ### 3.2 — Implement Docker-based tool runner
    Implement a runner that can:
    - Pull/build images as needed
    - Create container with:
      - CPU/memory limits
      - timeout enforcement
      - workspace volume mount
      - optional read-only root fs
      - environment variables (non-secret)
    - Capture:
      - stdout/stderr
      - exit code
      - produced artifacts
    - Emit trace events for:
      - image pull
      - container create/start/stop
      - resource limit triggers
      - timeout kills

    **Success criteria**
    - A tool can be executed end-to-end purely through Docker with deterministic results.

    ### 3.3 — Secrets strategy (Docker-safe)
    Define how tools access secrets:
    - Prefer:
      - Billy keeps secrets and proxies requests (tool never sees secret)
    - If secret must be provided:
      - inject as environment variables only for that run
      - never write secrets to workspace
      - never log secrets
    - Document:
      - which tools are allowed secrets
      - approvals/permissions

    **Success criteria**
    - Secrets are not present in logs, traces, or persisted artifacts.

    ### 3.4 — Add concurrency controls (local scaling)
    Implement a queue with worker pool:
    - Config:
      - max concurrent tool containers
      - per-tool concurrency limits
      - per-user or per-tenant limits (if multi-tenant)
    - Backpressure:
      - return “queued” status or stream progress events

    **Success criteria**
    - Billy can handle bursts without crashing Docker host.

    ### 3.5 — Add horizontal scaling strategy (Docker-native)
    Pick an incremental path:

    Option A (fast): **Docker Compose scaling**
    - Use Compose profiles for tool workers
    - Scale worker service replicas

    Option B (next): **Docker Swarm**
    - Billy can submit tasks to Swarm
    - Use overlay networks and resource constraints

    Document:
    - which option is supported now
    - what is required to move to the next

    **Success criteria**
    - You can run multiple concurrent tool executions reliably and observe utilization.

    ### 3.6 — Security hardening checklist
    - Drop capabilities (cap-drop all; add only required)
    - No privileged containers
    - Use seccomp/apparmor profiles where feasible
    - Constrain network:
      - none by default
      - allowlist per tool (DNS/http only if needed)
    - File system:
      - mount only workspace
      - use tmpfs for temp
    - Image provenance:
      - pin versions (digests)
      - scan images (optional but recommended)

    **Success criteria**
    - A documented baseline policy exists and is enforced by runner defaults.

    ## Definition of Done (DoD)
    - DockerRunner exists and is used by at least one tool.
    - Resource limits + timeouts + trace events are enforced.
    - Concurrency controls prevent overload.
    - Docs exist for building/running tool images and scaling workers.

    ## Risks & mitigations
    - Risk: Docker daemon becomes a single point of failure.
      - Mitigation: health checks, retries, circuit breaker, and worker isolation.
    - Risk: Tools require network but policy blocks it.
      - Mitigation: per-tool allowlist, plus an “offline tool” default mode.