# Phase 5 — Testing, Security, and Observability

    ## Goal
    Prove the integration is correct, safe, and operable: tests pass, policies hold, and behavior is observable.

    ## Deliverables
    - Test suites:
      - unit tests for adapters
      - integration tests for DockerRunner tool execution
      - end-to-end “golden path” tests
    - Threat model doc:
      - `docs/security/threat-model-agent-tools.md`
    - Observability:
      - structured logs with trace IDs
      - metrics for tool execution (latency, failures, queue depth)
      - optional tracing export (OpenTelemetry if used in Billy)

    ## Actions (step-by-step)

    ### 5.1 — Unit tests for adapters
    - Tool schema mapping tests:
      - valid args
      - invalid args
      - missing required fields
    - Error mapping tests:
      - Agent Zero exceptions -> Billy error format
    - Trace emission tests:
      - events emitted in expected order

    **Success criteria**
    - Adapter logic is deterministic and well-covered.

    ### 5.2 — DockerRunner integration tests
    Test cases:
    - Run a “hello world” tool image
    - Enforce timeout (tool sleeps too long -> killed)
    - Enforce memory/CPU constraints (where testable)
    - Verify workspace mount contains outputs
    - Verify network policy (offline tool cannot reach network)

    **Success criteria**
    - Docker execution is reliable and policy-compliant.

    ### 5.3 — Security controls verification
    - Confirm:
      - no privileged containers
      - restricted mounts
      - secrets not logged
      - default-deny network for untrusted tools
    - Add regression tests or runtime assertions where feasible.

    **Success criteria**
    - You can demonstrate controls with evidence (test logs, configs).

    ### 5.4 — Observability implementation
    Minimum metrics:
    - tool_runs_total{tool,status}
    - tool_run_duration_seconds{tool}
    - tool_queue_depth
    - docker_runner_failures_total{reason}
    - agent_turn_latency_seconds

    Logs:
    - Structured JSON logs recommended
    - Include:
      - request_id
      - user_id/tenant_id if applicable
      - persona_id
      - tool_name
      - container_id

    Traces:
    - Optional but recommended:
      - span per LLM call
      - span per tool run

    **Success criteria**
    - On-call can diagnose “why did the agent fail” quickly.

    ### 5.5 — Behavioral evaluation (LLM/agent quality)
    - Create a small eval set:
      - tool-using prompts
      - memory-using prompts
      - adversarial prompts (prompt injection attempts)
    - Compare:
      - baseline Billy
      - Billy + Agent Zero adapter(s)
    - Track:
      - success rate
      - tool correctness
      - latency and cost

    **Success criteria**
    - Integration improves something measurable without unacceptable regressions.

    ## Definition of Done (DoD)
    - CI runs tests for adapters + DockerRunner.
    - Threat model written and reviewed.
    - Metrics/logs available in dev/prod-like environment.

    ## Risks & mitigations
    - Risk: Flaky tests due to Docker environment.
      - Mitigation: deterministic images, pinned versions, generous timeouts, isolated runners.
    - Risk: Prompt injection causes tool misuse.
      - Mitigation: policy layer; explicit tool permissions; “human approval” mode for sensitive tools.