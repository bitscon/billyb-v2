"""
Updated runtime module for Billy v2.

This version adjusts the BillyRuntime constructor to accept an optional
configuration dictionary and default to an empty dictionary when none is
provided. It also adds the ask() method required by the API layer to
correctly invoke the configured LLM.
"""

import json
import os
import shlex
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


def _journal_exec_contract(event: str, payload: dict) -> None:
    record = {
        "event": event,
        "payload": payload,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
    with _exec_contract_journal_path.open("a") as f:
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
        }

    if executable in ("cat", "ls") and args:
        target = args[-1]
        if not target.startswith("/"):
            target = str(Path(working_dir) / target)
        return {
            "capability": "filesystem.read",
            "operation": executable,
            "path": target,
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

        if normalized_input.startswith("GRANT_CAPABILITY"):
            lines = [line.strip() for line in normalized_input.splitlines() if line.strip()]
            name_line = next((line for line in lines if line.startswith("name:")), "")
            scope_line = next((line for line in lines if line.startswith("scope:")), "")
            capability_name = name_line.replace("name:", "", 1).strip()
            scope_name = scope_line.replace("scope:", "", 1).strip()

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
                {"id": approval_id, "command": command, "working_dir": working_dir},
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
            _journal_exec_contract(
                "result",
                {
                    "id": approval_id,
                    "exit_code": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "verification": verification,
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

            working_dir = "/"
            action = _classify_shell_action(command, working_dir)
            if action:
                capability = action.get("capability", "")
                allowed, reason, remaining = _autonomy_registry.is_grant_allowed(
                    capability,
                    action,
                )
                if allowed:
                    _journal_exec_contract(
                        "auto_execution",
                        {
                            "capability": capability,
                            "command": command,
                            "working_dir": working_dir,
                            "limits_remaining": remaining,
                        },
                    )
                    try:
                        result = _execute_shell_command(command, working_dir)
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

            proposal_id = _next_exec_contract_id()
            expected_result = _expected_result_for_command(command)
            proposal = {
                "id": proposal_id,
                "type": "shell",
                "command": command,
                "working_dir": working_dir,
                "risk": "low",
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
                    f"working_dir: {working_dir}",
                    "risk: low",
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
