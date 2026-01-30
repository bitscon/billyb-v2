# Billy v2 Agent Zero Integration (Final Build)

This repository contains Billy v2 code integrated with Agent Zero helpers.

## Structure

- `v2/` – The original Billy v2 codebase with a patched `api.py` that exposes optional Agent Zero endpoints behind a feature flag.  All other core files (`config.yaml`, `core/`, `docs/`) remain unchanged.
- `adapter_impl/` – The adapter layer bridging Billy’s tool, memory and trace contracts to Agent Zero components.  Includes local and Docker runners, observability hooks and interfaces.
- `tests/` – Unit and integration tests for adapters, including new tests for the Docker runner.
- `evaluation/` – A behavioural evaluation harness for exercising tools and memory in a controlled way.
- `integration_artifacts/` – High‑level documents: architecture maps, inventories, reuse candidates, boundary contracts, threat model and a rollout plan.

## Feature Flags

Set the environment variable `ENABLE_AGENT_ZERO_INTEGRATION=true` in your deployment to enable the new `/v1/a0/*` endpoints in `v2/api.py`.  Otherwise, Billy runs normally.

Refer to the documentation in `integration_artifacts/` for guidance on rollout, security and maintenance.
