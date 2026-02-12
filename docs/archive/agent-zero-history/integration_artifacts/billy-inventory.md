# Billy v2 Inventory

This document provides a concise inventory of the main components, entrypoints and configuration files in the **billyb‑v2** repository.  Understanding where things live is the first step in any integration effort.

## Runtime entrypoints

- **CLI entrypoint – `main.py`**
  
  The `main.py` script acts as a simple command‑line front end.  It inserts the project root into the Python path, constructs a `BillyRuntime` instance and passes the first command‑line argument as the user’s prompt.  After calling `runtime.ask()`, it prints the response.  There is no tooling or concurrency layer; this script simply wraps the runtime.

- **API entrypoint – `api.py`**

  The `api.py` module exposes a FastAPI application.  It instantiates `BillyRuntime` with a root path and defines a handful of endpoints:
  
  | Endpoint | Purpose | Notes |
  | --- | --- | --- |
  | `/health` | Return status, root path, and Mongo connection flags. | Does not depend on the LLM. |
  | `/ask` (POST) | Accept a JSON body with a `prompt` and return the answer from `runtime.ask()`. | Simple wrapper around the runtime. |
  | `/v1/models` | Return a minimal model list for compatibility with OpenAI clients. | Always returns a single `billy-v2` model. |
  | `/v1/chat/completions` | Emulate the OpenAI chat completion API.  It extracts the last user message and calls `runtime.ask()`. | Ignores streaming and other advanced options. |
  | `/v1/memory/put` | Store a key/value pair in MongoDB if the Mongo engine is enabled. | Tags and timestamps are added. |
  | `/v1/memory/get` | Retrieve a stored value from MongoDB. | Returns `{found: False}` if the key is absent. |

  The presence of these endpoints means that Billy already exposes a minimal API surface.  However, there is no concept of tools, actions or agent loops exposed at the API level.

## Runtime / agent loop

- **Core loop – `core/runtime.py`**

  `BillyRuntime` orchestrates the entire conversation flow.  On initialization it:

  1. Loads configuration from `config.yaml` (via the `_load_config()` helper).
  2. Loads the canonical charter by scanning `docs/charter/NN_TITLE.md` files.  A failure to load the charter will not stop the server but will leave the runtime without guardrails.
  3. Assumes the default operational mode of `/plan` (read-only) unless explicitly invoked otherwise.

  The `ask()` method is invoked for every user prompt.  It:

  - Checks for explicit `/engineer` requests and, if present, enforces artifact production.
  - Builds a **system prompt** that includes a deterministic identity fallback and the full charter text.
  - Calls `core/llm_api.py:get_completion()` with the assembled messages and configuration.  There is no tool invocation, planning loop or asynchronous streaming – the completion is synchronous and blocking.
  - Post‑processes the answer with `_identity_guard()` to mask any leaked identity phrasing.

  **Summary:** Billy’s core loop is a single roundtrip to the LLM per request.  There is no built‑in notion of tools, multiple turns, or reflection.  All side effects (memory storage) must be invoked via separate API endpoints.

## Tool invocation / registry

- **Status:** *absent*.  At present Billy v2 does **not** implement a tool registry or tool execution framework.  The runtime simply calls the configured LLM.  There is no code that discovers tool definitions, validates arguments, or runs them in isolated environments.  Introducing a tool layer is therefore one of the primary tasks for integration.

## Memory / storage layer

- **Mongo‑backed key/value memory:**

  `api.py` conditionally enables a simple memory store when the environment variable `BILLY_DB_ENGINE=mongo` is set.  It connects to MongoDB using parameters from `.env` or environment variables, exposes `memory_put` and `memory_get` endpoints, and stores values in the `memory` collection keyed by `key`.  This store does not support vector embeddings, summarization or retrieval across conversations.

- **In‑memory conversation state:**

  Outside of the Mongo endpoints, there is no other memory subsystem.  The runtime does not persist conversation history across requests; each call to `ask()` is stateless beyond the operational mode.

## Persona / charter system

- **Charter loader – `core/charter.py`**

  Loads all Markdown files in `docs/charter/` whose names start with a two‑digit prefix and concatenates them.  The resulting text is inserted into the system prompt for every request.  This is Billy’s only persona mechanism – there is no user‑modifiable persona beyond editing the charter files.

## Configuration and initialization

- **Config file – `config.yaml`**

  Defines the LLM provider (`provider`), API key (`api_key`), base URL (`base_url`) and model name (`model_name`).  Supported providers include `openai`, `openrouter` and `ollama`; if not specified, the provider defaults to OpenAI and keys are read from environment variables.

- **Environment variables – `.env`**

  Optional.  Used primarily to configure MongoDB connection for memory endpoints.

## Security and secrets handling

- **API keys:** loaded from `config.yaml` or environment.  Keys are not redacted by default.
  
- **Memory secrets:** if Mongo is enabled, secrets are injected via environment variables.  There is no explicit secret masking in logs or outputs.

## Summary

Billy v2 is intentionally minimal: it wraps an LLM call with a charter system and exposes a couple of API endpoints.  There is no tool framework, planner, or advanced memory.  Consequently, integration work will primarily involve **adding** these capabilities – ideally by reusing them from Agent Zero rather than writing them from scratch.
