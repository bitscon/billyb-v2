# Rollout Plan for Billy v2 ←→ Agent Zero Integration

This document outlines a practical plan for deploying the Billy v2 ↔ Agent Zero integration into your
“barn” Linux server.  It is based on the Phase 6 goals described in the integration plan and
incorporates lessons learned from the testing and observability work in Phase 5.

## 1. Deployment stages

Roll the integration out in increments to limit blast radius and allow rapid rollback:

1. **Development only** – Enable the adapters, tool runner and memory integration only on
   your development box.  Use the evaluation harness (`evaluation/evaluate_integration.py`) to
   perform smoke tests.  Confirm that metrics are emitted and trace events appear in logs.
2. **Internal/staging** – Deploy to a staging environment identical to production but not
   user‑facing.  Exercise the API endpoints under load and run end‑to‑end tests.  Monitor
   error rates, tool latencies and container resource consumption.
3. **Limited production** – Toggle the integration on for a small percentage of real users via a
   feature flag (`ENABLE_AGENT_ZERO_INTEGRATION`).  Continue monitoring metrics and logs,
   ensuring that fallback to baseline Billy remains available.
4. **Full production** – Once metrics and user feedback show no regressions, enable the
   integration for all traffic.  Keep the feature flag in place for at least one release
   window so you can rapidly disable the integration if issues arise.

At each stage, define go/no‑go criteria (e.g. <5 % error rate, 95th percentile tool latency below
the baseline, zero container escapes).  If a criterion fails, either fix the issue or roll
back to the previous stage.

## 2. Rollback strategy

The integration should be encapsulated behind a single feature flag.  Disabling the flag
completely reverts to the legacy Billy runtime (no tool system, simple memory).  Do not
remove the baseline code until the integration has been stable for several releases.  Keep
Docker disabled for one release window after enabling adapter integration.

Rollback checklist:

1. Set `ENABLE_AGENT_ZERO_INTEGRATION` to `false` in your environment or config.
2. Set `USE_DOCKER_RUNNER` to `false` (if Docker execution was enabled).
3. Restart the Billy API to apply changes.
4. Verify that requests route through the legacy `BillyRuntime.ask()` path.

## 3. Migration and compatibility

Agent Zero’s tool definitions may evolve.  If you need to change tool schemas or memory
formats in the future:

* Provide migration scripts to convert stored memory or configuration files.
* Support dual‑read/dual‑write for memory backends during a transition period.  For example,
  write to both the existing Mongo collection and the new vector store until you are
  comfortable deprecating the old path.
* Document deprecation schedules and communicate them to your team so that clients can
  prepare for changes.

## 4. Maintenance strategy for Agent Zero reuse

We recommend pinning the Agent Zero dependency to tagged releases (e.g. `v1.2.3`) and
updating on a regular cadence (monthly or quarterly).  Record the commit or tag used in a
`AGENT_ZERO_VERSION` file and update your `requirements.txt` accordingly.  For each upgrade:

1. Review the Agent Zero changelog for breaking changes or security patches.
2. Run the full adapter test suite (`tests/test_adapters.py` and `tests/test_docker_runner.py`).
3. Run the evaluation harness to ensure behaviour remains acceptable.
4. Update documentation if new tools or features are introduced.

Apply security patches within 48 hours of disclosure.  Use dependency scanning tools to
receive alerts about vulnerabilities in third‑party packages.

## 5. Operational scaling plan

If your production workload increases beyond the capacity of a single host:

* Deploy multiple Billy instances behind a load balancer.  Use a container orchestrator
  (Docker Swarm, Kubernetes) to manage replicas.
* Enforce per‑tenant quotas and implement a job queue to prevent one user from exhausting
  resources.  The observability module’s `tool_queue_depth` metric can help inform scaling
  decisions.
* Stress test the system under realistic load.  Simulate long‑running and memory‑intensive
  tool runs to observe how the Docker runner behaves.  Adjust CPU and memory limits in
  configuration (`default_limits` in `DockerToolRunner`) to prevent contention.

## 6. Conclusion

By following this rollout plan, you minimise risk and maintain the ability to recover
quickly.  Combined with the test suite, threat model and observability instrumentation
implemented in Phase 5, this plan provides a clear path to deploy the Billy v2 ↔ Agent Zero
integration onto your barn server with confidence.