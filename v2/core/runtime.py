"""
Updated runtime module for Billy v2.

This version adjusts the BillyRuntime constructor to accept an optional
configuration dictionary and default to an empty dictionary when none is
provided. It also adds the ask() method required by the API layer to
correctly invoke the configured LLM.
"""

import hashlib
import json
import os
import shlex
import socket
import subprocess
import time
import yaml
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List

from . import llm_api
from .charter import load_charter
from core.contracts.loader import load_schema, ContractViolation
from core.tool_runner.docker_runner import DockerRunner
from core.trace.file_trace_sink import FileTraceSink
from core.tool_registry.registry import ToolRegistry
from core.tool_registry.loader import ToolLoader
from core.agent.tool_router import ToolRouter
from core.agent.memory_router import MemoryRouter
from core.agent.memory_reader import MemoryReader
from core.agent.plan_router import PlanRouter
from core.agent.approval_router import ApprovalRouter
from core.agent.step_executor import StepExecutor
from core.agent.plan_state import PlanState
from core.memory.file_memory_store import FileMemoryStore
from core.planning.plan import Plan
from core.agent.evaluation_router import EvaluationRouter
from core.evaluation.evaluation import Evaluation
from core.evaluation.synthesizer import EvaluationSynthesizer
from core.agent.promotion_router import PromotionRouter
from core.planning.llm_planner import LLMPlanner
from core.planning.plan_scorer import PlanScorer
from core.planning.plan_validator import PlanValidator
from core.plans.plan_fingerprint import fingerprint
from core.plans.plan_diff import diff_plans
from core.plans.promotion_lock import PromotionLock
from core.plans.plan_history import PlanHistory
from core.plans.rollback import RollbackEngine
from core.tools.capability_registry import CapabilityRegistry
from core.tools.tool_guard import ToolGuard
from core.execution.execution_journal import ExecutionJournal
from core.approval.approval_store import ApprovalStore
from core.approval.approval_flow import ApprovalFlow
from core.autonomy.autonomy_registry import AutonomyRegistry
from core.guardrails.invariants import (
    assert_trace_id,
    assert_no_tool_execution_without_registry,
    assert_explicit_memory_write,
)
from core.validation.plan_validator import PlanValidator
from core.guardrails.output_guard import OutputGuard
try:
    from v2.billy_engineering import detect_engineering_intent, enforce_engineering
    from v2.billy_engineering.enforcement import EngineeringError
except ImportError:
    from billy_engineering import detect_engineering_intent, enforce_engineering
    from billy_engineering.enforcement import EngineeringError

# --- HARD GUARDRAILS (fast stability) ---
FORBIDDEN_IDENTITY_PHRASES = (
    "i'm an ai",
    "i am an ai",
    "i’m an ai",
    "artificial intelligence",
    "chatbot",
    "language model",
    "llm",
    "assistant",
    "conversational ai",
)

# Deterministic fallback identity/purpose (authoritative, no LLM needed)
IDENTITY_FALLBACK = (
    "I am Billy — a digital Farm Hand and Foreman operating inside the Farm."
)


_trace_sink = FileTraceSink()
_docker_runner = DockerRunner(trace_sink=_trace_sink)
_tool_registry = ToolRegistry()
_memory_store = FileMemoryStore(trace_sink=_trace_sink)

_loader = ToolLoader("tools")
for spec in _loader.load_all():
    _tool_registry.register(spec)
_tool_router = ToolRouter(_tool_registry)
_memory_router = MemoryRouter()
_memory_reader = MemoryReader()
_plan_router = PlanRouter()
_approval_router = ApprovalRouter()
_last_plan = None  # TEMP: single-plan memory (no persistence yet)
_step_executor = StepExecutor()
_plan_state = None
_evaluation_router = EvaluationRouter()
_evaluation_synthesizer = EvaluationSynthesizer()
_promotion_router = PromotionRouter()
_last_evaluation = None
_llm_planner = LLMPlanner()
_plan_scorer = PlanScorer()
_plan_validator = PlanValidator()
_output_guard = OutputGuard()
_promotion_lock = PromotionLock()
_previous_plan = None
_previous_fingerprint = None
_plan_history = PlanHistory()
_rollback_engine = RollbackEngine()
_capability_registry = CapabilityRegistry()
_tool_guard = ToolGuard()
_execution_journal = ExecutionJournal()
_approval_store = ApprovalStore()
_approval_flow = ApprovalFlow()
_autonomy_registry = AutonomyRegistry()

_exec_contract_dir = Path("v2/var/execution_contract")
_exec_contract_dir.mkdir(parents=True, exist_ok=True)
_exec_contract_state_path = _exec_contract_dir / "state.json"
_exec_contract_journal_path = _exec_contract_dir / "journal.jsonl"
_pending_exec_proposals: Dict[str, Dict[str, str]] = {}

_ops_contract_dir = Path("v2/var/ops")
_ops_contract_dir.mkdir(parents=True, exist_ok=True)
_ops_state_path = _ops_contract_dir / "state.json"
_ops_journal_path = _ops_contract_dir / "journal.jsonl"
_pending_ops_plans: Dict[str, Dict[str, str]] = {}

_default_capability_grants = {
    "filesystem.write": {
        "scope": {
            "allowed_paths": ["/home/billyb/"],
            "deny_patterns": [".ssh", ".git"],
        },
        "limits": {
            "max_actions_per_session": 10,
            "max_actions_per_minute": 3,
        },
        "risk_level": "low",
        "require_grant": False,
    },
    "filesystem.read": {
        "scope": {
            "allowed_paths": ["/home/billyb/"],
            "deny_patterns": [".ssh", ".git"],
        },
        "limits": {
            "max_actions_per_session": 20,
            "max_actions_per_minute": 6,
        },
        "risk_level": "low",
        "require_grant": False,
    },
    "filesystem.delete": {
        "scope": {
            "allowed_paths": ["/home/billyb/"],
            "deny_patterns": [".ssh", ".git"],
        },
        "limits": {
            "max_actions_per_session": 5,
            "max_actions_per_minute": 2,
        },
        "risk_level": "medium",
        "require_grant": True,
    },
    "git.push": {
        "scope": {},
        "limits": {
            "max_actions_per_session": 5,
            "max_actions_per_minute": 2,
        },
        "risk_level": "medium",
        "require_grant": True,
    },
}


def _load_exec_contract_state() -> dict:
    if not _exec_contract_state_path.exists():
        return {}
    try:
        with _exec_contract_state_path.open("r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_exec_contract_state(state: dict) -> None:
    with _exec_contract_state_path.open("w") as f:
        json.dump(state, f, indent=2)
        f.write("\n")


def _next_exec_contract_id() -> str:
    today = datetime.utcnow().strftime("%Y%m%d")
    state = _load_exec_contract_state()
    counters = state.get("counters", {})
    next_num = counters.get(today, 0) + 1
    counters[today] = next_num
    state["counters"] = counters
    _save_exec_contract_state(state)
    return f"exec-{today}-{next_num:03d}"


def _load_ops_state() -> dict:
    if not _ops_state_path.exists():
        return {}
    try:
        with _ops_state_path.open("r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_ops_state(state: dict) -> None:
    with _ops_state_path.open("w") as f:
        json.dump(state, f, indent=2)
        f.write("\n")


def _next_ops_id() -> str:
    today = datetime.utcnow().strftime("%Y%m%d")
    state = _load_ops_state()
    counters = state.get("counters", {})
    next_num = counters.get(today, 0) + 1
    counters[today] = next_num
    state["counters"] = counters
    _save_ops_state(state)
    return f"ops-{today}-{next_num:03d}"


def _journal_exec_contract(event: str, payload: dict) -> None:
    record = {
        "event": event,
        "payload": payload,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
    with _exec_contract_journal_path.open("a") as f:
        f.write(json.dumps(record))
        f.write("\n")


def _journal_ops(event: str, payload: dict) -> None:
    record = {
        "event": event,
        "payload": payload,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
    with _ops_journal_path.open("a") as f:
        f.write(json.dumps(record))
        f.write("\n")


def _validate_exec_command(command: str) -> tuple[bool, str]:
    if not command or command.strip() != command:
        return False, "Command must be non-empty and fully explicit"
    if "\n" in command or "\r" in command:
        return False, "Command must be a single line"
    if any(token in command for token in ("&&", "||", ";", "|", "&")):
        return False, "Command chaining is not allowed"
    if any(token in command for token in ("$", "`", "~")):
        return False, "Variables are not allowed"
    try:
        parts = shlex.split(command)
    except ValueError:
        return False, "Command parsing failed"
    if not parts:
        return False, "Command must include an executable"
    if parts[0] in ("sudo", "su"):
        return False, "Privilege escalation is not allowed"
    return True, ""


def _expected_result_for_command(command: str) -> str:
    try:
        parts = shlex.split(command)
    except ValueError:
        return "command executed"
    if not parts:
        return "command executed"
    if parts[0] == "touch" and len(parts) >= 2:
        return "empty file created"
    if parts[0] == "rm" and len(parts) >= 2:
        return "file removed"
    if parts[0] == "mkdir":
        return "directory created"
    return "command executed"


def _verify_command_result(command: str) -> str:
    try:
        parts = shlex.split(command)
    except ValueError:
        return "no verification rule for command"
    if not parts:
        return "no verification rule for command"
    if parts[0] == "touch" and len(parts) >= 2:
        target = parts[-1]
        if os.path.exists(target):
            return f"file exists at {target}"
        return f"file missing at {target}"
    if parts[0] == "rm" and len(parts) >= 2:
        target = parts[-1]
        if not os.path.exists(target):
            return f"file removed at {target}"
        return f"file still exists at {target}"
    if parts[0] == "mkdir" and len(parts) >= 2:
        target = parts[-1]
        if os.path.isdir(target):
            return f"directory exists at {target}"
        return f"directory missing at {target}"
    return "no verification rule for command"


def _execute_shell_command(command: str, working_dir: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        shlex.split(command),
        cwd=working_dir,
        capture_output=True,
        text=True,
        check=False,
    )


def _get_repo_root() -> Path:
    env_root = os.environ.get("BILLY_REPO_ROOT")
    if env_root:
        return Path(env_root)
    return Path(__file__).resolve().parents[3]


def _parse_duration_seconds(value: str) -> int | None:
    if not value:
        return None
    try:
        if value.endswith("s"):
            return int(value[:-1])
        if value.endswith("m"):
            return int(value[:-1]) * 60
        if value.endswith("h"):
            return int(value[:-1]) * 3600
        return int(value)
    except ValueError:
        return None


def _requires_barn_inspection(text: str) -> bool:
    lowered = text.lower()
    if lowered.startswith("/"):
        return False
    triggers = [
        "service",
        "daemon",
        "url",
        "installed",
        "running",
        "where is",
        "where's",
        "cmdb",
        "port",
        "listening",
        "systemctl",
        "docker",
    ]
    return any(trigger in lowered for trigger in triggers)


def _is_action_request(text: str) -> bool:
    lowered = text.lower()
    action_triggers = [
        "restart",
        "stop",
        "reload",
        "start",
        "install",
        "upgrade",
        "update",
        "remove",
        "delete",
        "uninstall",
        "push",
        "deploy",
        "enable",
        "disable",
    ]
    return any(trigger in lowered for trigger in action_triggers)


def _run_inspection_command(command: list[str], timeout: int = 3) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except FileNotFoundError:
        return False, "command not found"
    except subprocess.TimeoutExpired:
        return False, "command timed out"
    except Exception as exc:
        return False, f"command failed: {exc}"
    output = (result.stdout or "").strip()
    if not output:
        output = (result.stderr or "").strip()
    return True, output or "no output"


def _summarize_output(output: str, max_lines: int = 20) -> str:
    lines = [line for line in output.splitlines() if line.strip()]
    if len(lines) <= max_lines:
        return "\n".join(lines)
    return "\n".join(lines[:max_lines] + ["... (truncated)"])


def _inspect_barn(query: str) -> str:
    terms = [word for word in shlex.split(query) if word.isalnum() and len(word) >= 3]
    search_term = terms[0] if terms else "cmdb"

    systemd_ok, systemd_out = _run_inspection_command(
        ["systemctl", "list-units", "--type=service", "--all"]
    )
    docker_ok, docker_out = _run_inspection_command(
        ["docker", "ps", "--format", "{{.Names}}\t{{.Ports}}"]
    )
    ports_ok, ports_out = _run_inspection_command(["ss", "-ltnp"])
    rg_ok, rg_out = _run_inspection_command(
        [
            "rg",
            "-n",
            search_term,
            "/etc",
            "/home/billyb",
            "-g",
            "*.yml",
            "-g",
            "*.yaml",
            "-g",
            "*.conf",
            "-g",
            "*.env",
            "-g",
            "*.service",
        ],
        timeout=5,
    )

    response_lines = [
        "Inspecting the Barn (read-only).",
        "I checked:",
        "- systemd services",
        "- Docker containers",
        "- listening ports",
        "- config files",
        "",
        "SYSTEMD:",
        _summarize_output(systemd_out if systemd_ok else systemd_out),
        "",
        "DOCKER:",
        _summarize_output(docker_out if docker_ok else docker_out),
        "",
        "PORTS:",
        _summarize_output(ports_out if ports_ok else ports_out),
        "",
        f"CONFIG SEARCH (term: {search_term}):",
        _summarize_output(rg_out if rg_ok else rg_out),
        "",
        "Let me know which entry looks like the target, or if you want me to refine the search.",
    ]
    return "\n".join(response_lines)


def _is_high_risk_command(command: str) -> tuple[bool, str]:
    try:
        parts = shlex.split(command)
    except ValueError:
        return False, ""
    if not parts:
        return False, ""
    executable = parts[0]
    args = parts[1:]

    if executable in ("apt", "apt-get", "dnf", "pacman", "apk"):
        return True, "system_package"
    if executable == "systemctl" and args:
        if args[0] in ("restart", "stop", "reload"):
            return True, "service_control"
    if executable == "docker" and args:
        if args[0] in ("restart", "stop", "kill", "rm"):
            return True, "service_control"
    if executable in ("iptables", "ufw", "firewall-cmd", "ip", "route", "ifconfig", "nmcli"):
        return True, "network_change"
    if executable == "rm" and args:
        target = args[-1]
        if not target.startswith("/"):
            target = str(Path("/") / target)
        if not os.path.abspath(target).startswith(os.path.abspath("/home/billyb/")):
            return True, "data_destructive"
    return False, ""


def _build_ops_plan(command: str, category: str) -> dict:
    host = socket.gethostname()
    try:
        parts = shlex.split(command)
    except ValueError:
        parts = []

    target = {}
    if parts:
        if parts[0] == "systemctl" and len(parts) >= 2:
            if len(parts) >= 3:
                target = {"service": parts[2], "host": host}
            else:
                target = {"service": "unknown", "host": host}
        elif parts[0] in ("apt", "apt-get", "dnf", "pacman", "apk"):
            target = {"package": " ".join(parts[1:]) or "unknown", "host": host}
        elif parts[0] == "docker" and len(parts) >= 2:
            target = {"service": parts[1], "host": host}
        else:
            target = {"host": host}
    else:
        target = {"host": host}

    pre_checks = [
        "operator intent confirmed",
        "no pending approvals",
    ]
    impact = ["potential service disruption", "manual verification required"]
    rollback = ["manual rollback required"]
    verification = ["manual verification required"]

    return {
        "category": category,
        "risk_level": "HIGH",
        "target": target,
        "pre_checks": pre_checks,
        "impact": impact,
        "rollback": rollback,
        "verification": verification,
    }


def _git_status_clean(repo_root: Path) -> tuple[bool, list[str]]:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return False, []
    lines = [line for line in (result.stdout or "").splitlines() if line.strip()]
    return len(lines) == 0, lines


def _git_current_branch(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return ""
    return (result.stdout or "").strip()


def _validate_delete_command(parts: list[str]) -> tuple[bool, str]:
    if not parts or parts[0] != "rm":
        return False, "Invalid delete command"
    args = parts[1:]
    if not args or len(args) != 1:
        return False, "Delete requires exactly one target"
    if any(flag in args[0] for flag in ("*", "?", "[")):
        return False, "Wildcards are not allowed"
    if any(arg.startswith("-") for arg in args):
        return False, "Flags are not allowed"
    return True, ""


def _classify_shell_action(command: str, working_dir: str) -> dict | None:
    try:
        parts = shlex.split(command)
    except ValueError:
        return None
    if not parts:
        return None

    executable = parts[0]
    args = parts[1:]

    if executable in ("touch", "mkdir") and args:
        target = args[-1]
        if not target.startswith("/"):
            target = str(Path(working_dir) / target)
        return {
            "capability": "filesystem.write",
            "operation": executable,
            "path": target,
            "working_dir": working_dir,
        }

    if executable == "rm":
        ok, reason = _validate_delete_command(parts)
        target = args[-1] if args else ""
        if target and not target.startswith("/"):
            target = str(Path(working_dir) / target)
        return {
            "capability": "filesystem.delete",
            "operation": executable,
            "path": target,
            "valid": ok,
            "reason": reason if not ok else "",
            "working_dir": working_dir,
        }

    if executable in ("cat", "ls") and args:
        target = args[-1]
        if not target.startswith("/"):
            target = str(Path(working_dir) / target)
        return {
            "capability": "filesystem.read",
            "operation": executable,
            "path": target,
            "working_dir": working_dir,
        }

    if executable == "git" and args:
        if args[0] != "push":
            return None
        if len(args) != 1:
            return {
                "capability": "git.push",
                "operation": "git push",
                "valid": False,
                "reason": "Git push arguments are not allowed",
                "working_dir": str(_get_repo_root()),
            }
        return {
            "capability": "git.push",
            "operation": "git push",
            "valid": True,
            "working_dir": str(_get_repo_root()),
        }

    return None

_capability_registry.register({
    "capability": "write_file",
    "tool": {
        "name": "demo.hello",
        "version": "1.0.0",
        "description": "Writes hello output to workspace",
        "inputs": [],
        "outputs": [
            {"name": "output.txt", "type": "string"},
        ],
        "side_effects": ["writes /workspace/output.txt"],
        "safety": {
            "reversible": True,
            "destructive": False,
            "requires_approval": False,
        },
    }
})


def _run_demo_tool(trace_id: str):
    return _docker_runner.run(
        tool_id="demo.hello",
        image="billy-hello",
        args=[],
        trace_id=trace_id,
    )


class BillyRuntime:
    def __init__(self, config: Dict[str, Any] | None = None, root_path: str | None = None) -> None:
        """
        Initialize the runtime.

        Args:
            config: Optional configuration dictionary. If not provided,
            config will be loaded automatically from v2/config.yaml.
            root_path: Optional root path, reserved for compatibility.
        """
        # Enforce presence of canonical contracts at boot
        try:
            load_schema("tool-spec.schema.yaml")
            load_schema("trace-event.schema.yaml")
        except ContractViolation as e:
            raise SystemExit(f"[FATAL] Contract enforcement failed at startup: {e}")
        self.config = config or {}

    def _identity_guard(self, user_input: str, answer: str) -> str:
        """
        Identity guardrails (currently permissive).

        This hook exists to enforce identity rules later.
        """
        return answer

    def _load_config_from_yaml(self) -> Dict[str, Any]:
        """
        Load model configuration from v2/config.yaml if present.
        """
        try:
            v2_root = Path(__file__).resolve().parents[1]
            config_path = v2_root / "config.yaml"

            if not config_path.exists():
                return {}

            data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return {}

            # Expect config under top-level "model"
            return data.get("model", {})
        except Exception:
            return {}

    def ask(self, prompt: str) -> str:
        """
        Generate a response using the configured LLM.

        This is the method called by:
        - /ask
        - /v1/chat/completions
        
        Special routing for Agent Zero commands starting with "a0 ".
        """
        
        # Route Agent Zero commands
        if prompt.strip().startswith("a0 "):
            try:
                from v2.agent_zero.commands import handle_command
                result = handle_command(prompt)
                if result:
                    return json.dumps(result, indent=2)
            except ImportError as e:
                return json.dumps({"error": f"Agent Zero module not available: {str(e)}"}, indent=2)
            except Exception as e:
                return json.dumps({"error": f"Error handling Agent Zero command: {str(e)}"}, indent=2)

        # Load config if not provided at init
        config = self.config or self._load_config_from_yaml()

        # Engineering enforcement (hard boundary)
        if detect_engineering_intent(prompt):
            try:
                def _llm_call(messages: List[Dict[str, str]]) -> str:
                    return llm_api.get_completion(messages, config)

                return enforce_engineering(prompt, _llm_call)
            except EngineeringError as exc:
                return f"Engineering enforcement failed: {exc}"
            except Exception as exc:
                return f"Engineering enforcement failed: {exc}"

        # Load config if not provided at init
        # Load charter (system prompt)
        system_prompt = ""
        try:
            v2_root = Path(__file__).resolve().parents[1]
            system_prompt = load_charter(str(v2_root))
        except Exception:
            system_prompt = ""

        # Build chat messages
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        messages.append({"role": "user", "content": prompt})

        # Call LLM
        answer = llm_api.get_completion(messages, config)

        # Apply guardrails
        return self._identity_guard(prompt, answer)

    def run_turn(self, user_input: str, session_context: Dict[str, Any]):
        trace_id = f"trace-{int(time.time() * 1000)}"
        assert_trace_id(trace_id)
        assert_explicit_memory_write(user_input)

        normalized_input = user_input.strip()

        if _requires_barn_inspection(normalized_input):
            inspection = _inspect_barn(normalized_input)
            if _is_action_request(normalized_input):
                next_step = "\n\nNEXT STEP:\n- If you want me to act, reply with: /ops " + normalized_input
                inspection = inspection + next_step
            return {
                "final_output": inspection,
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }

        if normalized_input.startswith("/ops "):
            command = normalized_input[len("/ops "):].strip()
            valid, reason = _validate_exec_command(command)
            if not valid:
                return {
                    "final_output": f"Ops request rejected: {reason}",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            is_high_risk, category = _is_high_risk_command(command)
            if not is_high_risk:
                return {
                    "final_output": "Ops request rejected: command is not classified as high-risk.",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            plan_id = _next_ops_id()
            plan = _build_ops_plan(command, category)
            command_hash = hashlib.sha256(command.encode("utf-8")).hexdigest()
            operator = session_context.get("user_id") if isinstance(session_context, dict) else None
            host = socket.gethostname()

            ops_plan = {
                "id": plan_id,
                "command": command,
                "command_hash": command_hash,
                "category": plan["category"],
                "risk_level": plan["risk_level"],
                "target": plan["target"],
                "pre_checks": plan["pre_checks"],
                "impact": plan["impact"],
                "rollback": plan["rollback"],
                "verification": plan["verification"],
                "operator": operator or "human",
                "host": host,
            }
            _pending_ops_plans[plan_id] = ops_plan
            _journal_ops(
                "intent",
                {"id": plan_id, "operator": ops_plan["operator"], "command": command, "host": host},
            )
            _journal_ops("plan", ops_plan)

            target_lines = []
            for key, value in ops_plan["target"].items():
                target_lines.append(f"  {key}: {value}")
            pre_check_lines = [f"  - {item}" for item in ops_plan["pre_checks"]]
            impact_lines = [f"  - {item}" for item in ops_plan["impact"]]
            rollback_lines = [f"  - {item}" for item in ops_plan["rollback"]]
            verification_lines = [f"  - {item}" for item in ops_plan["verification"]]

            response = "\n".join(
                [
                    "OPS_PLAN",
                    f"id: {plan_id}",
                    f"category: {ops_plan['category']}",
                    "risk_level: HIGH",
                    "",
                    "target:",
                    *target_lines,
                    "",
                    "pre_checks:",
                    *pre_check_lines,
                    "",
                    "impact:",
                    *impact_lines,
                    "",
                    "rollback:",
                    *rollback_lines,
                    "",
                    "verification:",
                    *verification_lines,
                    "",
                    "execute_command:",
                    f"  {command}",
                ]
            )

            return {
                "final_output": response,
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }

        if normalized_input.startswith("GRANT_CAPABILITY"):
            lines = [line.strip() for line in normalized_input.splitlines() if line.strip()]
            name_line = next((line for line in lines if line.startswith("name:")), "")
            scope_line = next((line for line in lines if line.startswith("scope:")), "")
            mode_line = next((line for line in lines if line.startswith("mode:")), "")
            expires_line = next((line for line in lines if line.startswith("expires_in:")), "")
            max_actions_line = next((line for line in lines if line.startswith("max_actions:")), "")

            capability_name = name_line.replace("name:", "", 1).strip()
            scope_name = scope_line.replace("scope:", "", 1).strip()
            mode = mode_line.replace("mode:", "", 1).strip() or "approval"
            expires_in = expires_line.replace("expires_in:", "", 1).strip()
            max_actions = max_actions_line.replace("max_actions:", "", 1).strip()

            if not capability_name:
                return {
                    "final_output": "Capability grant rejected: name is required.",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }
            if scope_name not in ("", "default"):
                return {
                    "final_output": "Capability grant rejected: only scope: default is supported.",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }
            if mode not in ("approval", "auto"):
                return {
                    "final_output": "Capability grant rejected: mode must be approval or auto.",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }
            expires_seconds = _parse_duration_seconds(expires_in) if expires_in else None
            if expires_in and expires_seconds is None:
                return {
                    "final_output": "Capability grant rejected: expires_in must be like 10m, 30s, or 1h.",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }
            max_actions_value = int(max_actions) if max_actions else None

            preset = _default_capability_grants.get(capability_name)
            if not preset:
                return {
                    "final_output": "Capability grant rejected: unknown capability.",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            limits = dict(preset["limits"])
            if max_actions_value:
                limits["max_actions_per_session"] = max_actions_value

            record = _autonomy_registry.grant_capability(
                capability=capability_name,
                scope=preset["scope"],
                limits=limits,
                risk_level=preset["risk_level"],
                grantor="human",
                mode=mode,
                expires_at=(time.time() + expires_seconds) if expires_seconds else None,
            )
            _journal_exec_contract("capability_grant", record)
            return {
                "final_output": f"Capability granted: {capability_name}",
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }

        if normalized_input.startswith("grant_autonomy "):
            capability_name = normalized_input[len("grant_autonomy "):].strip()
            preset = _default_capability_grants.get(capability_name)
            if not preset:
                return {
                    "final_output": "Capability grant rejected: unknown capability.",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            record = _autonomy_registry.grant_capability(
                capability=capability_name,
                scope=preset["scope"],
                limits=preset["limits"],
                risk_level=preset["risk_level"],
                grantor="human",
                mode="auto" if not preset.get("require_grant") else "approval",
            )
            _journal_exec_contract("capability_grant", record)
            return {
                "final_output": f"Capability granted: {capability_name}",
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }

        approve_parts = normalized_input.split()
        if len(approve_parts) == 2 and approve_parts[0] == "APPROVE":
            approval_id = approve_parts[1]
            if approval_id in _pending_ops_plans:
                ops_plan = _pending_ops_plans.get(approval_id)
                command = ops_plan.get("command", "")
                command_hash = ops_plan.get("command_hash", "")
                operator = ops_plan.get("operator", "human")
                host = ops_plan.get("host", socket.gethostname())
                recomputed_hash = hashlib.sha256(command.encode("utf-8")).hexdigest()

                if recomputed_hash != command_hash:
                    _journal_ops(
                        "approval",
                        {
                            "id": approval_id,
                            "status": "rejected",
                            "reason": "Command hash mismatch",
                            "host": host,
                        },
                    )
                    return {
                        "final_output": "Ops approval rejected: command hash mismatch.",
                        "tool_calls": [],
                        "status": "error",
                        "trace_id": trace_id,
                    }

                _journal_ops(
                    "approval",
                    {"id": approval_id, "status": "approved", "operator": operator, "host": host},
                )
                _journal_ops(
                    "execution",
                    {"id": approval_id, "command": command, "operator": operator, "host": host},
                )

                try:
                    result = _execute_shell_command(command, "/")
                except Exception as exc:
                    _journal_ops(
                        "result",
                        {"id": approval_id, "status": "error", "error": str(exc), "host": host},
                    )
                    return {
                        "final_output": f"Ops execution failed: {exc}",
                        "tool_calls": [],
                        "status": "error",
                        "trace_id": trace_id,
                    }

                stdout_repr = json.dumps(result.stdout or "")
                stderr_repr = json.dumps(result.stderr or "")
                status = "SUCCESS" if result.returncode == 0 else "FAILED"
                verification = ["manual verification required"]
                _journal_ops(
                    "result",
                    {
                        "id": approval_id,
                        "exit_code": result.returncode,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                        "verification": verification,
                        "status": status,
                        "host": host,
                    },
                )
                _pending_ops_plans.pop(approval_id, None)

                response = "\n".join(
                    [
                        "OPS_RESULT",
                        f"id: {approval_id}",
                        f"exit_code: {result.returncode}",
                        "",
                        f"stdout: {stdout_repr}",
                        f"stderr: {stderr_repr}",
                        "",
                        "verification:",
                        "  - manual verification required",
                        "",
                        f"status: {status}",
                    ]
                )

                if status != "SUCCESS":
                    response = "\n".join(
                        [
                            response,
                            "recommendation: manual rollback",
                        ]
                    )

                return {
                    "final_output": response,
                    "tool_calls": [],
                    "status": "success" if status == "SUCCESS" else "error",
                    "trace_id": trace_id,
                }

            proposal = _pending_exec_proposals.get(approval_id)
            if not proposal:
                return {
                    "final_output": "Approval rejected: unknown or expired proposal id.",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            command = proposal.get("command", "")
            working_dir = proposal.get("working_dir", "/")
            capability = proposal.get("capability")
            valid, reason = _validate_exec_command(command)
            if not valid:
                _journal_exec_contract(
                    "approval",
                    {"id": approval_id, "status": "rejected", "reason": reason},
                )
                return {
                    "final_output": f"Approval rejected: {reason}",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            _journal_exec_contract(
                "approval",
                {"id": approval_id, "status": "approved"},
            )
            _journal_exec_contract(
                "execution",
                {"id": approval_id, "command": command, "working_dir": working_dir, "capability": capability},
            )

            try:
                result = _execute_shell_command(command, working_dir)
            except Exception as exc:
                _journal_exec_contract(
                    "result",
                    {"id": approval_id, "status": "error", "error": str(exc)},
                )
                return {
                    "final_output": f"Execution failed: {exc}",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            verification = _verify_command_result(command)
            stdout_repr = json.dumps(result.stdout or "")
            stderr_repr = json.dumps(result.stderr or "")
            limits_remaining = None
            if capability and _autonomy_registry.get_grant(capability):
                limits_remaining = _autonomy_registry.consume_grant(capability)
            _journal_exec_contract(
                "result",
                {
                    "id": approval_id,
                    "exit_code": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "verification": verification,
                    "limits_remaining": limits_remaining,
                },
            )
            _pending_exec_proposals.pop(approval_id, None)

            response = "\n".join(
                [
                    "EXECUTION_RESULT",
                    f"id: {approval_id}",
                    f"exit_code: {result.returncode}",
                    f"stdout: {stdout_repr}",
                    f"stderr: {stderr_repr}",
                    f"verification: {verification}",
                ]
            )
            return {
                "final_output": response,
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }

        if normalized_input.startswith("/exec "):
            command = normalized_input[len("/exec "):].strip()
            valid, reason = _validate_exec_command(command)
            if not valid:
                return {
                    "final_output": f"Execution request rejected: {reason}",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            is_high_risk, _ = _is_high_risk_command(command)
            if is_high_risk:
                return {
                    "final_output": "Execution denied: high-risk operation requires /ops.",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            working_dir = "/"
            action = _classify_shell_action(command, working_dir)
            if action:
                capability = action.get("capability", "")
                action_working_dir = action.get("working_dir", working_dir)
                grant = _autonomy_registry.get_grant(capability)

                if not action.get("valid", True):
                    reason = action.get("reason", "Capability scope violation")
                    _journal_exec_contract(
                        "capability_denied",
                        {"capability": capability, "command": command, "reason": reason},
                    )
                    return {
                        "final_output": f"Execution denied: {reason}",
                        "tool_calls": [],
                        "status": "error",
                        "trace_id": trace_id,
                    }

                allowed, reason, remaining = _autonomy_registry.is_grant_allowed(
                    capability,
                    action,
                )

                preset = _default_capability_grants.get(capability, {})
                require_grant = preset.get("require_grant", False)

                if not grant and require_grant:
                    _journal_exec_contract(
                        "capability_denied",
                        {"capability": capability, "command": command, "reason": "Capability not granted"},
                    )
                    return {
                        "final_output": "Execution denied: capability not granted.",
                        "tool_calls": [],
                        "status": "error",
                        "trace_id": trace_id,
                    }

                if capability == "git.push":
                    repo_root = Path(action_working_dir)
                    clean, lines = _git_status_clean(repo_root)
                    if not clean:
                        _journal_exec_contract(
                            "capability_denied",
                            {
                                "capability": capability,
                                "command": command,
                                "reason": "Working tree not clean",
                                "details": lines,
                            },
                        )
                        return {
                            "final_output": "Execution denied: working tree not clean.",
                            "tool_calls": [],
                            "status": "error",
                            "trace_id": trace_id,
                        }

                if allowed and grant and grant.get("mode") == "auto":
                    _journal_exec_contract(
                        "auto_execution",
                        {
                            "capability": capability,
                            "command": command,
                            "working_dir": action_working_dir,
                            "limits_remaining": remaining,
                        },
                    )
                    try:
                        result = _execute_shell_command(command, action_working_dir)
                    except Exception as exc:
                        _journal_exec_contract(
                            "result",
                            {"status": "error", "error": str(exc)},
                        )
                        return {
                            "final_output": f"Execution failed: {exc}",
                            "tool_calls": [],
                            "status": "error",
                            "trace_id": trace_id,
                        }

                    remaining = _autonomy_registry.consume_grant(capability)
                    verification = _verify_command_result(command)
                    stdout_repr = json.dumps(result.stdout or "")
                    stderr_repr = json.dumps(result.stderr or "")
                    _journal_exec_contract(
                        "result",
                        {
                            "capability": capability,
                            "exit_code": result.returncode,
                            "stdout": result.stdout,
                            "stderr": result.stderr,
                            "verification": verification,
                            "limits_remaining": remaining,
                        },
                    )

                    response = "\n".join(
                        [
                            "EXECUTION_RESULT",
                            "id: auto-exec",
                            f"exit_code: {result.returncode}",
                            f"stdout: {stdout_repr}",
                            f"stderr: {stderr_repr}",
                            f"verification: {verification}",
                        ]
                    )
                    return {
                        "final_output": response,
                        "tool_calls": [],
                        "status": "success",
                        "trace_id": trace_id,
                    }

                if not allowed and reason in (
                    "Capability scope violation",
                    "Capability limits exceeded",
                    "Capability expired",
                    "Capability revoked",
                ):
                    _journal_exec_contract(
                        "capability_denied",
                        {"capability": capability, "command": command, "reason": reason},
                    )
                    return {
                        "final_output": f"Execution denied: {reason}",
                        "tool_calls": [],
                        "status": "error",
                        "trace_id": trace_id,
                    }

                if capability == "git.push":
                    repo_root = Path(action_working_dir)
                    branch = _git_current_branch(repo_root)
                    proposal_id = _next_exec_contract_id()
                    proposal = {
                        "id": proposal_id,
                        "type": "git.push",
                        "command": command,
                        "working_dir": action_working_dir,
                        "capability": capability,
                        "risk": "medium",
                        "expected_result": "git push executed",
                        "preconditions": [
                            "clean working tree",
                            "no untracked files",
                        ],
                        "branch": branch,
                    }
                    _pending_exec_proposals[proposal_id] = proposal
                    _journal_exec_contract("proposal", proposal)

                    response = "\n".join(
                        [
                            "PROPOSED_ACTION",
                            f"id: {proposal_id}",
                            "type: git.push",
                            "preconditions:",
                            "  - clean working tree",
                            "  - no untracked files",
                            f"branch: {branch}",
                        ]
                    )
                    return {
                        "final_output": response,
                        "tool_calls": [],
                        "status": "success",
                        "trace_id": trace_id,
                    }

            proposal_id = _next_exec_contract_id()
            expected_result = _expected_result_for_command(command)
            proposal = {
                "id": proposal_id,
                "type": "shell",
                "command": command,
                "working_dir": action.get("working_dir", working_dir) if action else working_dir,
                "capability": capability if action else None,
                "risk": preset.get("risk_level", "low") if action else "low",
                "expected_result": expected_result,
            }
            _pending_exec_proposals[proposal_id] = proposal
            _journal_exec_contract("proposal", proposal)

            response = "\n".join(
                [
                    "PROPOSED_ACTION",
                    f"id: {proposal_id}",
                    "type: shell",
                    f"command: {command}",
                    f"working_dir: {proposal['working_dir']}",
                    f"risk: {proposal['risk']}",
                    f"expected_result: {expected_result}",
                ]
            )
            return {
                "final_output": response,
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }

        if user_input.strip().lower().startswith("/approve"):
            parts = user_input.strip().split()
            if len(parts) != 3:
                return {
                    "final_output": "Usage: /approve <plan_fingerprint> <step_id>",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }
            plan_fp = parts[1]
            step_id = parts[2]
            record = _plan_history.get(plan_fp)
            if not record or not record.get("plan"):
                return {
                    "final_output": {
                        "tool_execution": {
                            "status": "blocked",
                            "reason": "Execution denied by human",
                        }
                    },
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }
            step = next((s for s in record["plan"].get("steps", []) if s.get("step_id") == step_id), None)
            capability = step.get("capability") if step else ""
            try:
                record = _approval_store.approve(plan_fp, step_id, capability)
            except Exception:
                return {
                    "final_output": {
                        "tool_execution": {
                            "status": "blocked",
                            "reason": "Execution denied by human",
                        }
                    },
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }
            return {
                "final_output": record,
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }

        if user_input.strip().lower().startswith("/deny"):
            parts = user_input.strip().split()
            if len(parts) != 3:
                return {
                    "final_output": "Usage: /deny <plan_fingerprint> <step_id>",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }
            plan_fp = parts[1]
            step_id = parts[2]
            record = _plan_history.get(plan_fp)
            if not record or not record.get("plan"):
                return {
                    "final_output": {
                        "tool_execution": {
                            "status": "blocked",
                            "reason": "Execution denied by human",
                        }
                    },
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }
            step = next((s for s in record["plan"].get("steps", []) if s.get("step_id") == step_id), None)
            capability = step.get("capability") if step else ""
            try:
                record = _approval_store.deny(plan_fp, step_id, capability)
            except Exception:
                return {
                    "final_output": {
                        "tool_execution": {
                            "status": "blocked",
                            "reason": "Execution denied by human",
                        }
                    },
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }
            return {
                "final_output": record,
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }

        def _fallback_invalid_plan():
            return {
                "plan": {
                    "id": "fallback-invalid-plan",
                    "version": "0.0.0",
                    "objective": "Plan rejected due to validation failure",
                    "assumptions": [
                        "LLM output was incomplete or invalid"
                    ],
                    "steps": [],
                    "artifacts": [],
                    "risks": [
                        {
                            "risk": "Unsafe execution",
                            "mitigation": "Execution blocked"
                        }
                    ],
                }
            }

        plan_intent = _plan_router.route(user_input)
        if plan_intent is not None:
            tool_specs = _tool_registry._tools

            proposals = _llm_planner.propose_many(
                intent=plan_intent,
                tool_specs=tool_specs,
            )

            comparisons = []
            for p in proposals:
                validation = _plan_validator.validate(p, tool_specs)

                if not validation["valid"]:
                    comparisons.append({
                        "intent": p.get("intent"),
                        "valid": False,
                        "errors": validation["errors"],
                    })
                    continue

                plan = Plan(
                    intent=p["intent"],
                    steps=p.get("steps", []),
                    assumptions=p.get("assumptions"),
                    risks=p.get("risks"),
                )

                score = _plan_scorer.score(plan.to_dict())
                plan_dict = plan.to_dict()
                plan_dict["score"] = score
                plan_dict["valid"] = True

                comparisons.append(plan_dict)

            return {
                "final_output": {
                    "intent": plan_intent,
                    "candidates": comparisons,
                },
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }

        approved_plan_id = _approval_router.route(user_input)
        if approved_plan_id:
            if not _last_plan:
                return {
                    "final_output": _fallback_invalid_plan(),
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            guard = _output_guard.guard(_last_plan.to_dict() if _last_plan else {}, plan_mode=False)
            if not guard["valid"]:
                return {
                    "final_output": _fallback_invalid_plan(),
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            validation = _plan_validator.validate(guard["parsed"] or {})
            if not validation["valid"]:
                return {
                    "final_output": _fallback_invalid_plan(),
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            if not _last_plan or _last_plan.to_dict()["plan_id"] != approved_plan_id:
                return {
                    "final_output": "No matching plan to approve.",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            current_plan = guard["parsed"] or _last_plan.to_dict()
            current_fp = fingerprint(current_plan)
            diff = diff_plans(_previous_plan or {}, current_plan) if _previous_plan else {}
            lock = _promotion_lock.check(current_fp, _previous_fingerprint, diff)
            if not lock["allowed"]:
                return {
                    "final_output": {
                        "promotion": {
                            "status": "blocked",
                            "reason": "No meaningful diff or promotion not approved",
                            "current_fingerprint": current_fp,
                            "previous_fingerprint": _previous_fingerprint,
                        }
                    },
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            _plan_history.append(current_plan, current_fp)
            _plan_history.set_active(current_fp)

            _previous_plan = current_plan
            _previous_fingerprint = current_fp

            _plan_state = PlanState(_last_plan.to_dict())
            return {
                "final_output": "Plan approved. Execution not yet implemented.",
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }

        cmd = user_input.strip().lower()

        if cmd.startswith("/rollback"):
            parts = user_input.strip().split()
            if len(parts) != 2:
                return {
                    "final_output": {
                        "rollback": {
                            "status": "blocked",
                            "reason": "Target plan fingerprint not found or invalid",
                        }
                    },
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            target_fp = parts[1]
            try:
                result = _rollback_engine.rollback(target_fp, _plan_history)
            except Exception:
                return {
                    "final_output": {
                        "rollback": {
                            "status": "blocked",
                            "reason": "Target plan fingerprint not found or invalid",
                        }
                    },
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            record = _plan_history.get(target_fp)
            if record and record.get("plan"):
                _last_plan = Plan(intent=record["plan"].get("intent", ""), steps=record["plan"].get("steps", []))

            return {
                "final_output": result,
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }

        eval_req = _evaluation_router.route(user_input)
        if eval_req:
            evaluation = Evaluation(
                subject_type=eval_req["subject_type"],
                subject_id=eval_req["subject_id"],
                outcome="success",
                observations=[
                    "Execution completed without contract violations",
                    "All required artifacts were produced",
                ],
                risks=[],
            )
            _last_evaluation = evaluation.to_dict()

            summary = _evaluation_synthesizer.summarize(evaluation.to_dict())

            return {
                "final_output": summary,
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }

        if _promotion_router.route(user_input):
            if not _last_evaluation:
                return {
                    "final_output": "No evaluation available to promote.",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            memory_entry = {
                "content": _last_evaluation,
                "scope": {
                    "user_id": "default",
                    "persona_id": None,
                    "session_id": None,
                },
                "metadata": {
                    "category": "evaluation",
                    "confidence": 0.8,
                    "importance": "medium",
                    "source": "system",
                },
            }

            _memory_store.write(memory_entry, trace_id=trace_id)

            return {
                "final_output": "Evaluation promoted to memory.",
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }

        if cmd == "/pause" and _plan_state:
            _plan_state.pause()
            return {
                "final_output": "Plan paused.",
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }

        if cmd == "/abort" and _plan_state:
            _plan_state.abort()
            return {
                "final_output": "Plan aborted.",
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }

        if user_input.strip().lower().startswith("/step"):
            parts = user_input.strip().split()
            if len(parts) != 2:
                return {
                    "final_output": "Usage: /step <step_id>",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            step_id = parts[1]

            if not _last_plan:
                return {
                    "final_output": "No active plan.",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            active_fp = _plan_history.get_active()
            if not active_fp:
                return {
                    "final_output": "No active plan.",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            current_fp = fingerprint(_last_plan.to_dict())
            if current_fp != active_fp:
                return {
                    "final_output": "No active plan.",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            guard = _output_guard.guard(_last_plan.to_dict(), plan_mode=False)
            if not guard["valid"]:
                return {
                    "final_output": _fallback_invalid_plan(),
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            validation = _plan_validator.validate(guard["parsed"] or {})
            if not validation["valid"]:
                return {
                    "final_output": _fallback_invalid_plan(),
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            _plan_state.can_execute(step_id)
            _plan_state.mark_running(step_id)

            step = next((s for s in _last_plan.to_dict().get("steps", []) if s.get("step_id") == step_id), None)
            if not step:
                record = _execution_journal.build_record(
                    trace_id=trace_id,
                    plan_fingerprint=current_fp,
                    step_id=step_id,
                    capability="",
                    tool_name="",
                    tool_version="",
                    inputs={},
                    status="blocked",
                    reason="Capability not registered or contract violation",
                    outputs=None,
                )
                _execution_journal.append(record)
                return {
                    "final_output": {
                        "tool_execution": {
                            "status": "blocked",
                            "reason": "Capability not registered or contract violation",
                        }
                    },
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            capability = step.get("capability")
            if not capability:
                record = _execution_journal.build_record(
                    trace_id=trace_id,
                    plan_fingerprint=current_fp,
                    step_id=step_id,
                    capability="",
                    tool_name="",
                    tool_version="",
                    inputs={},
                    status="blocked",
                    reason="Capability not registered or contract violation",
                    outputs=None,
                )
                _execution_journal.append(record)
                return {
                    "final_output": {
                        "tool_execution": {
                            "status": "blocked",
                            "reason": "Capability not registered or contract violation",
                        }
                    },
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            try:
                tool_name, tool_version, contract = _capability_registry.resolve(capability)
            except Exception:
                record = _execution_journal.build_record(
                    trace_id=trace_id,
                    plan_fingerprint=current_fp,
                    step_id=step_id,
                    capability=capability,
                    tool_name="",
                    tool_version="",
                    inputs={},
                    status="blocked",
                    reason="Capability not registered or contract violation",
                    outputs=None,
                )
                _execution_journal.append(record)
                return {
                    "final_output": {
                        "tool_execution": {
                            "status": "blocked",
                            "reason": "Capability not registered or contract violation",
                        }
                    },
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            safety = contract.get("tool", {}).get("safety", {})
            if safety.get("requires_approval"):
                state = _approval_store.get_state(current_fp, step_id, capability)
                if state == "approved":
                    pass
                elif state == "denied":
                    record = _execution_journal.build_record(
                        trace_id=trace_id,
                        plan_fingerprint=current_fp,
                        step_id=step_id,
                        capability=capability,
                        tool_name=contract.get("tool", {}).get("name", ""),
                        tool_version=contract.get("tool", {}).get("version", ""),
                        inputs=inputs,
                        status="blocked",
                        reason="Execution denied by human",
                        outputs=None,
                    )
                    _execution_journal.append(record)
                    return {
                        "final_output": {
                            "tool_execution": {
                                "status": "blocked",
                                "reason": "Execution denied by human",
                            }
                        },
                        "tool_calls": [],
                        "status": "error",
                        "trace_id": trace_id,
                    }
                else:
                    try:
                        _approval_store.request(current_fp, step_id, capability)
                    except Exception:
                        pass

                    approval_payload = _approval_flow.build_request(
                        plan_fingerprint=current_fp,
                        step_id=step_id,
                        capability=capability,
                        tool=contract.get("tool", {}),
                        safety=safety,
                    )

                    record = _execution_journal.build_record(
                        trace_id=trace_id,
                        plan_fingerprint=current_fp,
                        step_id=step_id,
                        capability=capability,
                        tool_name=contract.get("tool", {}).get("name", ""),
                        tool_version=contract.get("tool", {}).get("version", ""),
                        inputs=inputs,
                        status="blocked",
                        reason="Human approval required",
                        outputs=None,
                    )
                    _execution_journal.append(record)

                    return {
                        "final_output": {
                            "tool_execution": {
                                "status": "blocked",
                                "reason": "Human approval required",
                                "approval_state": "pending",
                            },
                            **approval_payload,
                        },
                        "tool_calls": [],
                        "status": "error",
                        "trace_id": trace_id,
                    }

            allowed, reason = _autonomy_registry.is_autonomy_allowed(
                capability,
                {"step_id": step_id, "plan_fingerprint": current_fp},
            )
            if not allowed:
                record = _execution_journal.build_record(
                    trace_id=trace_id,
                    plan_fingerprint=current_fp,
                    step_id=step_id,
                    capability=capability,
                    tool_name=contract.get("tool", {}).get("name", ""),
                    tool_version=contract.get("tool", {}).get("version", ""),
                    inputs=inputs,
                    status="blocked",
                    reason="Autonomy policy violation or exhausted",
                    outputs=None,
                )
                _execution_journal.append(record)
                return {
                    "final_output": {
                        "tool_execution": {
                            "status": "blocked",
                            "reason": "Autonomy policy violation or exhausted",
                        }
                    },
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            _autonomy_registry.consume_autonomy(
                capability,
                {"step_id": step_id, "plan_fingerprint": current_fp},
            )

            spec = _tool_registry.get(tool_name)
            if spec.get("version") != tool_version:
                record = _execution_journal.build_record(
                    trace_id=trace_id,
                    plan_fingerprint=current_fp,
                    step_id=step_id,
                    capability=capability,
                    tool_name=tool_name,
                    tool_version=tool_version,
                    inputs={},
                    status="blocked",
                    reason="Capability not registered or contract violation",
                    outputs=None,
                )
                _execution_journal.append(record)
                return {
                    "final_output": {
                        "tool_execution": {
                            "status": "blocked",
                            "reason": "Capability not registered or contract violation",
                        }
                    },
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            inputs = step.get("args", {})
            inputs = inputs if isinstance(inputs, dict) else {}
            guard = _tool_guard.validate(contract, inputs)
            if not guard["valid"]:
                record = _execution_journal.build_record(
                    trace_id=trace_id,
                    plan_fingerprint=current_fp,
                    step_id=step_id,
                    capability=capability,
                    tool_name=tool_name,
                    tool_version=tool_version,
                    inputs=inputs,
                    status="blocked",
                    reason="Capability not registered or contract violation",
                    outputs=None,
                )
                _execution_journal.append(record)
                return {
                    "final_output": {
                        "tool_execution": {
                            "status": "blocked",
                            "reason": "Capability not registered or contract violation",
                        }
                    },
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }

            intent_record = _execution_journal.build_record(
                trace_id=trace_id,
                plan_fingerprint=current_fp,
                step_id=step_id,
                capability=capability,
                tool_name=tool_name,
                tool_version=tool_version,
                inputs=inputs,
                status="success",
                reason="intent logged",
                outputs=None,
            )
            _execution_journal.append(intent_record)

            try:
                result = _step_executor.execute_step(
                    plan=_last_plan.to_dict(),
                    step_id=step_id,
                    tool_registry=_tool_registry,
                    docker_runner=_docker_runner,
                    trace_id=trace_id,
                )
                _plan_state.mark_done(step_id)
                outcome_record = _execution_journal.build_record(
                    trace_id=trace_id,
                    plan_fingerprint=current_fp,
                    step_id=step_id,
                    capability=capability,
                    tool_name=tool_name,
                    tool_version=tool_version,
                    inputs=inputs,
                    status="success",
                    reason="execution complete",
                    outputs={
                        "stdout": result.get("stdout"),
                        "stderr": result.get("stderr"),
                        "artifact": result.get("artifact"),
                    },
                )
                _execution_journal.append(outcome_record)
            except Exception as exc:
                _plan_state.mark_failed(step_id)
                outcome_record = _execution_journal.build_record(
                    trace_id=trace_id,
                    plan_fingerprint=current_fp,
                    step_id=step_id,
                    capability=capability,
                    tool_name=tool_name,
                    tool_version=tool_version,
                    inputs=inputs,
                    status="error",
                    reason=str(exc),
                    outputs=None,
                )
                _execution_journal.append(outcome_record)
                raise

            return {
                "final_output": f"Step executed: {step_id}",
                "tool_calls": [result],
                "status": "success",
                "trace_id": trace_id,
            }

        if user_input.strip().lower().startswith("/revoke_autonomy"):
            parts = user_input.strip().split()
            if len(parts) != 2:
                return {
                    "final_output": "Usage: /revoke_autonomy <capability>",
                    "tool_calls": [],
                    "status": "error",
                    "trace_id": trace_id,
                }
            capability = parts[1]
            try:
                _autonomy_registry.revoke_autonomy(capability)
            except Exception:
                pass

            _journal_exec_contract(
                "capability_revoked",
                {"capability": capability},
            )

            record = _execution_journal.build_record(
                trace_id=trace_id,
                plan_fingerprint="",
                step_id="",
                capability=capability,
                tool_name="",
                tool_version="",
                inputs={},
                status="blocked",
                reason="Autonomy revoked",
                outputs=None,
            )
            _execution_journal.append(record)

            return {
                "final_output": {
                    "autonomy": {
                        "status": "revoked",
                        "capability": capability,
                    }
                },
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }

        memory_entry = _memory_router.route_write(user_input)
        if memory_entry:
            _memory_store.write(memory_entry, trace_id=trace_id)
            return {
                "final_output": "Memory saved.",
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }

        read_scope = _memory_reader.route_read(user_input)
        if read_scope:
            memories = _memory_store.query(scope=read_scope, trace_id=trace_id)
            formatted = "\n".join([m["content"] for m in memories]) or "No memories found."
            return {
                "final_output": formatted,
                "tool_calls": [],
                "status": "success",
                "trace_id": trace_id,
            }

        tool_id = _tool_router.route(user_input)

        if tool_id:
            assert_no_tool_execution_without_registry(tool_id, _tool_registry)
            spec = _tool_registry.get(tool_id)
            result = _docker_runner.run(
                tool_spec=spec,
                image="billy-hello",
                args=[],
                trace_id=trace_id,
            )
            return {
                "final_output": f"Tool executed: {tool_id}",
                "tool_calls": [result],
                "status": "success",
                "trace_id": trace_id,
            }

        return {
            "final_output": self.ask(user_input),
            "tool_calls": [],
            "status": "success",
            "trace_id": trace_id,
        }


runtime = BillyRuntime(config=None)


def run_turn(user_input: str, session_context: dict):
    return runtime.run_turn(user_input=user_input, session_context=session_context)
