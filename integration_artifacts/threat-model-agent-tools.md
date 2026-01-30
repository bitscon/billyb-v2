# Threat Model – Agent Tools Integration

This document assesses the security risks introduced by integrating Agent Zero components into Billy via adapters.  It follows the deliverables described in the *Phase 5 – Testing, Security and Observability* plan.

## Overview

Billy currently executes all external code within a Docker‑based runner under strict resource and network policies.  Agent Zero introduces a catalogue of tools (Python classes) that can perform tasks such as web browsing, document querying and memory manipulation.  Exposing these tools through adapters expands Billy’s attack surface:

* **Untrusted tool code** – third‑party or community‑contributed tools may execute arbitrary Python code with access to secrets, the filesystem or the network.
* **Supply‑chain dependencies** – Agent Zero depends on external libraries (e.g. `litellm`, `langchain`, vector stores) which could harbour vulnerabilities or supply‑chain attacks.
* **Prompt‑injection channels** – tool outputs may be fed back into LLM prompts, enabling indirect prompt injection if not sanitised.
* **Memory leakage** – tools interfacing with the memory subsystem could expose sensitive data across personas or sessions if boundaries are not enforced.
* **Container escape** – if Docker configurations are lax (e.g. privileged containers, mounted host sockets) a malicious tool could break isolation.
* **Network exfiltration** – tools with network capability could exfiltrate data to external servers or perform SSRF if the network policy is overly permissive.

## Assets and Actors

**Assets**:

* Billy’s secrets (API keys, configuration values)
* User data and messages
* Stored memories and embeddings
* Host filesystem on the worker nodes
* Network connectivity to internal services (e.g. vector DB, MongoDB)

**Actors**:

* **Developers** writing tools for Agent Zero or Billy
* **End users** sending prompts that could trigger tool execution
* **Attackers** attempting to misuse tools via prompt injection or malicious contributions
* **System operators** managing Docker policies and monitoring logs

## Threats and Mitigations

### Remote Code Execution (RCE)

*Threat*: Tools may run arbitrary Python code.  A compromised tool could execute shell commands, access the network or read/write files outside its intended scope.

*Mitigations*:

* Run all tool code in non‑privileged Docker containers with read‑only filesystem mounts and no access to the host Docker socket.
* Apply seccomp and AppArmor profiles to block dangerous syscalls.
* Drop network privileges by default; require explicit permission flags per tool.  Use an egress proxy to restrict destinations.
* Use Billy’s `ToolRunner` to enforce CPU/memory limits and timeouts (see test plan in Phase 5.2).

### Supply‑chain Attacks

*Threat*: Agent Zero’s dependencies (e.g. `litellm`, `langchain`) could be compromised, introducing malicious code.

*Mitigations*:

* Pin dependency versions and verify checksums during build.
* Use a trusted proxy or mirror for Python packages; enable Dependabot to watch for CVEs.
* Run continuous integration scans (e.g. safety, Snyk) on Agent Zero and Billy.

### Prompt Injection and Data Exfiltration

*Threat*: Output from tools might be injected back into LLM prompts, allowing attackers to manipulate the agent or extract secrets (e.g. by inserting `{{secrets}}`).

*Mitigations*:

* Normalise and sanitise tool outputs before including them in prompts.
* Use a strict template for tool results (e.g. JSON) to avoid arbitrary text injection.
* Implement a allowlist of allowed tool names and arguments; require human approval for high‑risk tools.
* Leverage Billy’s moral compass and charter enforcement to detect and block suspicious instructions.

### Memory Leakage Across Personas

*Threat*: Tools operating on memory might retrieve data from other personas or sessions.

*Mitigations*:

* Introduce namespace isolation in the `MemoryStore` adapter, keyed by persona and user ID.
* Enforce role‑based access: only the requesting persona can read/write its own memories.
* Add audit trails for memory queries; integrate with the `TraceSink`.

### Container Breakout

*Threat*: A tool could escape its Docker sandbox and access host resources.

*Mitigations*:

* Use user namespaces and drop capabilities (no `--privileged` flag).
* Mount only specific directories (e.g. `/workspace` for tool outputs) with read/write; mount others as read‑only.
* Do not mount sensitive sockets (`/var/run/docker.sock`); implement a separate orchestrator for launching containers.

### Network Exfiltration and SSRF

*Threat*: Tools with network access could send data to attacker‑controlled servers or query internal services.

*Mitigations*:

* Default network policy is `deny`; require explicit permission for outbound connections per tool.
* Use egress filtering (e.g. IPTables rules) to restrict allowed destinations.
* Inspect DNS requests and block resolution of internal domains.

## Residual Risks

Even with the above mitigations, residual risk remains.  Attackers may leverage zero‑day vulnerabilities in Python or container runtimes, or exploit misconfigurations.  Regular audits, timely patching and defence‑in‑depth are essential.

## Conclusion

Integrating Agent Zero tools into Billy expands functionality but introduces new threats.  By running tools in constrained containers, sanitising outputs, isolating memory and hardening dependencies, we can reduce the attack surface.  Continuous testing (see Phase 5.1 and 5.2) and observability (Phase 5.4) will ensure early detection of issues and support safe iteration on this integration.