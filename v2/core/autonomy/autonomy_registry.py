import os
import time
from datetime import datetime
from core.contracts.loader import ContractViolation


class AutonomyRegistry:
    """
    Runtime-owned autonomy policy registry with limits enforcement.
    """

    def __init__(self):
        self._policies: dict[str, dict] = {}
        self._history: dict[str, list[float]] = {}
        self._step_history: dict[str, set[str]] = {}
        self._grants: dict[str, dict] = {}
        self._grant_history: dict[str, list[float]] = {}
        self._grant_counts: dict[str, int] = {}

    def register(self, policy: dict) -> None:
        if not isinstance(policy, dict):
            raise ContractViolation("Autonomy policy must be an object")
        autonomy = policy.get("autonomy", {})
        capability = autonomy.get("capability")
        if not capability:
            raise ContractViolation("Autonomy policy missing capability")
        self._policies[capability] = policy

    def revoke_autonomy(self, capability: str) -> None:
        if capability in self._policies:
            self._policies[capability]["autonomy"]["enabled"] = False
        if capability in self._grants:
            self._grants[capability]["enabled"] = False

    def grant_capability(
        self,
        capability: str,
        scope: dict,
        limits: dict,
        risk_level: str,
        grantor: str,
        mode: str = "approval",
        expires_at: float | None = None,
    ) -> dict:
        if not capability:
            raise ContractViolation("Capability name required")
        if not isinstance(scope, dict):
            raise ContractViolation("Capability scope must be an object")
        if not isinstance(limits, dict):
            raise ContractViolation("Capability limits must be an object")
        record = {
            "capability": capability,
            "scope": scope,
            "limits": limits,
            "risk_level": risk_level,
            "grantor": grantor,
            "mode": mode,
            "expires_at": expires_at,
            "granted_at": datetime.utcnow().isoformat() + "Z",
            "enabled": True,
        }
        self._grants[capability] = record
        return record

    def get_grant(self, capability: str) -> dict | None:
        return self._grants.get(capability)

    def is_grant_allowed(self, capability: str, action: dict) -> tuple[bool, str, dict]:
        grant = self._grants.get(capability)
        if not grant:
            return False, "Capability not granted", {}
        if not grant.get("enabled"):
            return False, "Capability revoked", {}
        expires_at = grant.get("expires_at")
        if expires_at and time.time() > expires_at:
            grant["enabled"] = False
            return False, "Capability expired", {}

        scope = grant.get("scope", {})
        limits = grant.get("limits", {})
        allowed_paths = scope.get("allowed_paths", [])
        deny_patterns = scope.get("deny_patterns", [])
        target_path = action.get("path")

        if target_path:
            normalized = os.path.abspath(target_path)
            if allowed_paths:
                allowed = any(normalized.startswith(os.path.abspath(p)) for p in allowed_paths)
                if not allowed:
                    return False, "Capability scope violation", {}
            if any(pattern in normalized for pattern in deny_patterns):
                return False, "Capability scope violation", {}
        else:
            if allowed_paths or deny_patterns:
                return False, "Capability scope violation", {}

        max_actions = int(limits.get("max_actions_per_session", 0) or 0)
        max_per_minute = int(limits.get("max_actions_per_minute", 0) or 0)
        now = time.time()
        history = self._grant_history.setdefault(capability, [])
        history[:] = [t for t in history if now - t <= 60]
        count = self._grant_counts.get(capability, 0)

        if max_actions and count >= max_actions:
            return False, "Capability limits exceeded", {
                "remaining_session": 0,
                "remaining_minute": 0 if max_per_minute else None,
            }
        if max_per_minute and len(history) >= max_per_minute:
            remaining = max_per_minute - len(history)
            return False, "Capability limits exceeded", {
                "remaining_session": max(0, max_actions - count) if max_actions else None,
                "remaining_minute": max(0, remaining),
            }

        remaining_session = max(0, max_actions - count) if max_actions else None
        remaining_minute = max(0, max_per_minute - len(history)) if max_per_minute else None
        return True, "ok", {
            "remaining_session": remaining_session,
            "remaining_minute": remaining_minute,
        }

    def consume_grant(self, capability: str) -> dict:
        now = time.time()
        history = self._grant_history.setdefault(capability, [])
        history.append(now)
        self._grant_counts[capability] = self._grant_counts.get(capability, 0) + 1

        grant = self._grants.get(capability, {})
        limits = grant.get("limits", {})
        max_actions = int(limits.get("max_actions_per_session", 0) or 0)
        max_per_minute = int(limits.get("max_actions_per_minute", 0) or 0)
        history[:] = [t for t in history if now - t <= 60]
        remaining_session = max(0, max_actions - self._grant_counts.get(capability, 0)) if max_actions else None
        remaining_minute = max(0, max_per_minute - len(history)) if max_per_minute else None
        return {
            "remaining_session": remaining_session,
            "remaining_minute": remaining_minute,
        }

    def is_autonomy_allowed(self, capability: str, context: dict) -> tuple[bool, str]:
        policy = self._policies.get(capability)
        if not policy:
            return False, "Autonomy policy violation or exhausted"

        autonomy = policy.get("autonomy", {})
        if not autonomy.get("enabled"):
            return False, "Autonomy policy violation or exhausted"

        scope = autonomy.get("scope", {})
        max_steps = scope.get("max_steps", 0)
        max_executions = scope.get("max_executions", 0)
        window = scope.get("time_window_seconds", 0)

        now = time.time()
        history = self._history.setdefault(capability, [])
        step_hist = self._step_history.setdefault(capability, set())

        if window:
            history[:] = [t for t in history if now - t <= window]
        if max_executions and len(history) >= max_executions:
            return False, "Autonomy policy violation or exhausted"

        step_id = context.get("step_id")
        if max_steps and step_id:
            if len(step_hist) >= max_steps and step_id not in step_hist:
                return False, "Autonomy policy violation or exhausted"

        return True, "ok"

    def consume_autonomy(self, capability: str, context: dict) -> None:
        now = time.time()
        history = self._history.setdefault(capability, [])
        history.append(now)
        step_id = context.get("step_id")
        if step_id:
            self._step_history.setdefault(capability, set()).add(step_id)
