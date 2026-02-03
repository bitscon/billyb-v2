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

## Operational Modes

Billy recognizes two explicit modes:

- `/plan` — default read-only mode (analysis, reasoning, outlining). No filesystem writes or execution.
- `/engineer` — explicit engineering mode that produces artifacts under `v2/billy_engineering/workspace/` and stops for approval.

## Billy v2 Single‑Server Deployment Guide

This guide explains how to deploy Billy v2—along with the optional Agent Zero integration—on a single Linux host. It assumes your development and production environments run on the same machine and that you have basic familiarity with the command line.

### Prerequisites

- A Linux server (Ubuntu or similar).
- Python 3.10 or newer with pip installed.
- git installed to clone the repository.
- Optionally, a running MongoDB instance if you want to enable Billy's key/value memory endpoints.
- Optionally, Docker installed if you plan to run tools inside containers.
- Access to the Billy v2 repository (bitscon/billyb‑v2) and the Agent Zero code base.

### Step 1: Obtain the code

Clone the repository or copy the provided archive onto your server. The repository contains the core code under v2/, the adapter layer under adapter_impl/, design docs under integration_artifacts/, as well as tests and an evaluation harness.

```bash
# Using git
git clone https://github.com/bitscon/billyb-v2.git
cd billyb-v2

# OR, copy the extracted `final_repo` from the project ZIP
# and rename it to billyb-v2
```

### Step 2: Create a virtual environment

Using a virtual environment isolates your Python dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
```

### Step 3: Install dependencies

Billy uses FastAPI and Uvicorn to serve its HTTP endpoints. Install the required packages:

```bash
pip install fastapi uvicorn pydantic pymongo

# Optional: install prometheus_client if you want metrics for observability
pip install prometheus_client
```

If you plan to enable Agent Zero integration, ensure that the Agent Zero code base is checked out on disk and that its python/ package is accessible. The integration code will load tools from this location when the feature flag is set.

### Step 4: Configure environment variables

Create a .env file in the repository root with values appropriate for your environment. For example:

```bash
# Enable Mongo memory storage (optional)
BILLY_DB_ENGINE=mongo
BILLY_MONGO_URI=mongodb://127.0.0.1:27017
BILLY_MONGO_DB=billy

# Enable Agent Zero integration (set to "true" to expose additional endpoints)
ENABLE_AGENT_ZERO_INTEGRATION=true

# Path to your Agent Zero checkout (absolute path recommended)
AGENT_ZERO_ROOT=/opt/agent-zero-main
```

If ENABLE_AGENT_ZERO_INTEGRATION is not set (or is not "true"), Billy runs in its default mode. The AGENT_ZERO_ROOT variable should point at the directory where the Agent Zero repository is located.

### Step 5: Run the API server

There are two common ways to run Billy on a single server.

#### Development mode

For quick local testing, run Uvicorn directly with auto‑reload:

```bash
uvicorn v2.api:app --host 0.0.0.0 --port 8000 --reload
```

You can then visit http://localhost:8000/health to check that the service is running. Using --reload causes Uvicorn to restart whenever code changes, which is convenient during development.

#### Production mode with systemd

For persistent operation, run Billy as a systemd service. First, copy your repository to a stable location, e.g. /opt/billyb-v2. Then create a unit file at /etc/systemd/system/billyb-v2.service with the following content:

```ini
[Unit]
Description=Billy v2 API
After=network.target

[Service]
Type=simple
User=billyuser         # replace with a dedicated service user
WorkingDirectory=/opt/billyb-v2
EnvironmentFile=/opt/billyb-v2/.env
ExecStart=/opt/billyb-v2/.venv/bin/uvicorn v2.api:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
```

This configuration is adapted from a typical FastAPI systemd setup. Replace billyuser with a non‑privileged user that owns the files. After saving the service file, run:

```bash
sudo systemctl daemon-reload
sudo systemctl enable billyb-v2
sudo systemctl start billyb-v2
```

The service will now start automatically at boot and restart on failure.

### Step 6: Accessing Billy

With the server running, you can interact with Billy using the following endpoints:

- GET /health – returns service status and Mongo connectivity.
- POST /ask with JSON { "prompt": "your question" } – returns Billy's response.
- GET /v1/models and POST /v1/chat/completions – minimal OpenAI‑style endpoints.
- POST /v1/memory/put and GET /v1/memory/get – store and retrieve key/value pairs (requires Mongo).

When ENABLE_AGENT_ZERO_INTEGRATION=true, additional Agent Zero helper endpoints are available:

- GET /v1/a0/tools – list available Agent Zero tools.
- GET /v1/a0/tool/{name} – retrieve the schema for a specific tool.
- POST /v1/a0/tool/{name}/run – execute a tool (optionally with use_docker=true).
- POST /v1/a0/memory/put and GET /v1/a0/memory/get – use Agent Zero's memory store (currently a stub).

### Step 7: Updating and restarting

To deploy updates, pull the latest code, reinstall dependencies if needed, and restart the service:

```bash
cd /opt/billyb-v2
git pull
source .venv/bin/activate
pip install -U fastapi uvicorn pydantic pymongo
sudo systemctl restart billyb-v2
```

### Notes

- If Mongo is not configured, the memory endpoints will return an error. Set BILLY_DB_ENGINE=mongo in .env and ensure MongoDB is running to use them.
- Docker execution is experimental. Ensure Docker is installed and configured before calling tools with use_docker=true.
- Running both development and production on a single host is acceptable for a personal LAN. Use different ports or enable/disable integration features via environment variables to avoid conflicts.
- The systemd service file shown here is based on general FastAPI deployment recommendations, which describe creating a unit file in /etc/systemd/system/ and enabling it.

Following this guide will let you run Billy v2—along with its optional Agent Zero helpers—on a single Linux server with minimal complexity. Adjust paths and environment variables to suit your own setup.
