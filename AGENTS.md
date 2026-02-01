# Agent Instructions for billyb-v2

This document provides essential information for AI agents working within the `billyb-v2` repository.

## Project Overview

`billyb-v2` is a Python-based AI project that can be run as a command-line application or a web service. It has a modular architecture that allows for different components to be swapped out, as seen with the "Agent Zero" integration.

The core of the application is the `BillyRuntime`, which is responsible for processing user requests. The project is exposed to the outside world via a command-line interface (`v2/main.py`) and a FastAPI web server (`v2/api.py`).

## Commands

### Testing

The project uses `pytest` for testing. To run the tests, use the following command:

```bash
pytest -q
```

## Code Organization

- **`adapter_impl/`**: Contains adapter classes that bridge the core application with external services or implementations, such as "Agent Zero". This is a key part of the project's modular design.
- **`v2/`**: The main application directory.
    - **`main.py`**: The command-line interface for the application.
    - **`api.py`**: The FastAPI-based web service.
    - **`core/`**: Contains the core logic of the application, including the `BillyRuntime`.
- **`tests/`**: Contains unit tests for the project.

## Key Patterns

### Modular Architecture and Adapters

The project is designed to be modular, using an adapter pattern to integrate with different services. The `adapter_impl` directory is a clear example of this, providing a bridge to "Agent Zero". When adding new integrations, follow this pattern by creating a new adapter class.

### Multiple Execution Modes

The application can be run in two ways:

1.  **Command-Line Interface**: By running `v2/main.py`, you can interact with the application directly from the terminal.
2.  **Web Service**: The `v2/api.py` file launches a FastAPI server, which exposes the application's functionality through a REST API. This includes an OpenAI-compatible endpoint.

### Configuration

The application can be configured using environment variables. For example, `BILLY_DB_ENGINE` can be set to "mongo" to enable MongoDB integration. When working with the application, be aware of a potential `.env` file in the `v2/` directory that may contain environment-specific settings.
