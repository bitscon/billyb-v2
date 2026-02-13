"""Phase 14 human-governed policy and contract evolution utilities.

This module is additive and read/write governance tooling only. It does not
change runtime enforcement behavior by itself.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
import difflib

import yaml


KIND_POLICY = "policy"
KIND_TOOL_CONTRACT = "tool_contract"
SUPPORTED_KINDS = {KIND_POLICY, KIND_TOOL_CONTRACT}

_PHASE4_DEFAULT_POLICY = {
    "allowed": False,
    "risk_level": "critical",
    "requires_approval": True,
    "reason": "Policy denied by default: no matching deterministic policy rule.",
}


@dataclass(frozen=True)
class VersionMetadata:
    version_id: str
    author: str
    timestamp: str
    change_summary: str


@dataclass(frozen=True)
class VersionRecord:
    metadata: VersionMetadata
    payload: Dict[str, Any]
    previous_version_id: str | None = None
    source_draft_id: str | None = None


@dataclass(frozen=True)
class DraftRecord:
    draft_id: str
    kind: str
    author: str
    timestamp: str
    change_summary: str
    payload: Dict[str, Any]
    modifications: Dict[str, Any]
    status: str
    reviewer: str | None = None
    reviewed_at: str | None = None
    review_notes: str | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_policy_path() -> Path:
    return _repo_root() / "v2" / "contracts" / "intent_policy_rules.yaml"


def _default_tool_contract_path() -> Path:
    return _repo_root() / "v2" / "contracts" / "intent_tool_contracts.yaml"


def _default_store_dir() -> Path:
    return _repo_root() / "v2" / "state" / "policy_evolution"


def _yaml_dump(payload: Dict[str, Any]) -> str:
    return yaml.safe_dump(payload, sort_keys=True)


class PolicyContractEvolutionStore:
    def __init__(
        self,
        *,
        store_dir: str | Path | None = None,
        policy_path: str | Path | None = None,
        tool_contract_path: str | Path | None = None,
    ) -> None:
        self._store_dir = Path(store_dir) if store_dir is not None else _default_store_dir()
        self._policy_path = Path(policy_path) if policy_path is not None else _default_policy_path()
        self._tool_contract_path = (
            Path(tool_contract_path) if tool_contract_path is not None else _default_tool_contract_path()
        )

        self._store_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_json_file(self._versions_path(KIND_POLICY))
        self._ensure_json_file(self._versions_path(KIND_TOOL_CONTRACT))
        self._ensure_json_file(self._drafts_path(KIND_POLICY))
        self._ensure_json_file(self._drafts_path(KIND_TOOL_CONTRACT))
        self._bootstrap_if_needed()

    def list_versions(self, kind: str) -> List[Dict[str, Any]]:
        self._assert_kind(kind)
        return [copy.deepcopy(item["metadata"]) for item in self._read_json(self._versions_path(kind))]

    def list_drafts(self, kind: str, *, status: str | None = None) -> List[Dict[str, Any]]:
        self._assert_kind(kind)
        drafts = self._read_json(self._drafts_path(kind))
        if status is not None:
            drafts = [draft for draft in drafts if draft.get("status") == status]
        return copy.deepcopy(drafts)

    def create_draft(
        self,
        *,
        kind: str,
        author: str,
        change_summary: str,
        payload: Dict[str, Any],
        modifications: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        self._assert_kind(kind)
        author = str(author).strip()
        change_summary = str(change_summary).strip()
        if not author:
            raise ValueError("Draft author is required.")
        if not change_summary:
            raise ValueError("Draft change_summary is required.")

        normalized_payload = self._validate_payload(kind, payload)
        draft = DraftRecord(
            draft_id=self._next_id(kind, "draft"),
            kind=kind,
            author=author,
            timestamp=_now_iso(),
            change_summary=change_summary,
            payload=normalized_payload,
            modifications=copy.deepcopy(modifications or {}),
            status="pending",
            reviewer=None,
            reviewed_at=None,
            review_notes=None,
        )
        drafts = self._read_json(self._drafts_path(kind))
        drafts.append(self._draft_to_dict(draft))
        self._write_json(self._drafts_path(kind), drafts)
        return self.get_draft(kind=kind, draft_id=draft.draft_id)

    def get_draft(self, *, kind: str, draft_id: str) -> Dict[str, Any]:
        self._assert_kind(kind)
        for draft in self._read_json(self._drafts_path(kind)):
            if str(draft.get("draft_id")) == draft_id:
                return copy.deepcopy(draft)
        raise ValueError(f"Draft not found: {draft_id}")

    def review_draft(
        self,
        *,
        kind: str,
        draft_id: str,
        reviewer: str,
        decision: str,
        review_notes: str = "",
    ) -> Dict[str, Any]:
        self._assert_kind(kind)
        reviewer = str(reviewer).strip()
        if not reviewer:
            raise ValueError("Reviewer is required.")
        decision = str(decision).strip().lower()
        if decision not in {"approve", "reject"}:
            raise ValueError("Decision must be 'approve' or 'reject'.")

        drafts = self._read_json(self._drafts_path(kind))
        updated = None
        for draft in drafts:
            if str(draft.get("draft_id")) != draft_id:
                continue
            if draft.get("status") != "pending":
                raise ValueError("Only pending drafts can be reviewed.")
            draft["status"] = "approved" if decision == "approve" else "rejected"
            draft["reviewer"] = reviewer
            draft["reviewed_at"] = _now_iso()
            draft["review_notes"] = str(review_notes)
            updated = copy.deepcopy(draft)
            break
        if updated is None:
            raise ValueError(f"Draft not found: {draft_id}")
        self._write_json(self._drafts_path(kind), drafts)
        return updated

    def activate_approved_draft(
        self,
        *,
        kind: str,
        draft_id: str,
        author: str,
        change_summary: str | None = None,
    ) -> Dict[str, Any]:
        self._assert_kind(kind)
        author = str(author).strip()
        if not author:
            raise ValueError("Activation author is required.")

        draft = self.get_draft(kind=kind, draft_id=draft_id)
        if draft.get("status") != "approved":
            raise ValueError("Only approved drafts can be activated.")

        versions = self._read_json(self._versions_path(kind))
        previous_version_id = str(versions[-1]["metadata"]["version_id"]) if versions else None
        summary = str(change_summary).strip() if change_summary is not None else str(draft["change_summary"])
        if not summary:
            raise ValueError("Activation change_summary is required.")

        metadata = VersionMetadata(
            version_id=self._next_id(kind, "version"),
            author=author,
            timestamp=_now_iso(),
            change_summary=summary,
        )
        version = VersionRecord(
            metadata=metadata,
            payload=copy.deepcopy(draft["payload"]),
            previous_version_id=previous_version_id,
            source_draft_id=draft_id,
        )
        versions.append(self._version_to_dict(version))
        self._write_json(self._versions_path(kind), versions)
        self._write_active_payload(kind, version.payload)
        return copy.deepcopy(self._version_to_dict(version))

    def get_version(self, *, kind: str, version_id: str) -> Dict[str, Any]:
        self._assert_kind(kind)
        for version in self._read_json(self._versions_path(kind)):
            if str(version.get("metadata", {}).get("version_id")) == version_id:
                return copy.deepcopy(version)
        raise ValueError(f"Version not found: {version_id}")

    def diff_versions(self, *, kind: str, from_version_id: str, to_version_id: str) -> Dict[str, Any]:
        self._assert_kind(kind)
        left = self.get_version(kind=kind, version_id=from_version_id)
        right = self.get_version(kind=kind, version_id=to_version_id)
        left_yaml = _yaml_dump(left["payload"]).splitlines()
        right_yaml = _yaml_dump(right["payload"]).splitlines()
        diff_lines = list(
            difflib.unified_diff(
                left_yaml,
                right_yaml,
                fromfile=from_version_id,
                tofile=to_version_id,
                lineterm="",
            )
        )
        return {
            "kind": kind,
            "from_version_id": from_version_id,
            "to_version_id": to_version_id,
            "changed": bool(diff_lines),
            "diff": diff_lines,
            "from_change_summary": left["metadata"]["change_summary"],
            "to_change_summary": right["metadata"]["change_summary"],
        }

    def revert_to_version(
        self,
        *,
        kind: str,
        version_id: str,
        author: str,
        change_summary: str,
    ) -> Dict[str, Any]:
        self._assert_kind(kind)
        author = str(author).strip()
        change_summary = str(change_summary).strip()
        if not author:
            raise ValueError("Revert author is required.")
        if not change_summary:
            raise ValueError("Revert change_summary is required.")

        target = self.get_version(kind=kind, version_id=version_id)
        versions = self._read_json(self._versions_path(kind))
        previous_version_id = str(versions[-1]["metadata"]["version_id"]) if versions else None

        metadata = VersionMetadata(
            version_id=self._next_id(kind, "version"),
            author=author,
            timestamp=_now_iso(),
            change_summary=change_summary,
        )
        version = VersionRecord(
            metadata=metadata,
            payload=copy.deepcopy(target["payload"]),
            previous_version_id=previous_version_id,
            source_draft_id=None,
        )
        versions.append(self._version_to_dict(version))
        self._write_json(self._versions_path(kind), versions)
        self._write_active_payload(kind, version.payload)
        return copy.deepcopy(self._version_to_dict(version))

    def simulate_draft(self, *, kind: str, draft_id: str, envelopes: List[Dict[str, Any]]) -> Dict[str, Any]:
        self._assert_kind(kind)
        if not isinstance(envelopes, list):
            raise ValueError("Simulation envelopes must be a list.")

        draft = self.get_draft(kind=kind, draft_id=draft_id)
        current_payload = self._read_active_payload(kind)
        proposed_payload = copy.deepcopy(draft["payload"])

        if kind == KIND_POLICY:
            return self._simulate_policy_draft(
                draft=draft,
                current_payload=current_payload,
                proposed_payload=proposed_payload,
                envelopes=envelopes,
            )
        return self._simulate_tool_contract_draft(
            draft=draft,
            current_payload=current_payload,
            proposed_payload=proposed_payload,
            envelopes=envelopes,
        )

    # -------------------------
    # Simulation internals
    # -------------------------
    def _simulate_policy_draft(
        self,
        *,
        draft: Dict[str, Any],
        current_payload: Dict[str, Any],
        proposed_payload: Dict[str, Any],
        envelopes: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        current_rules = current_payload.get("rules", {}) if isinstance(current_payload, dict) else {}
        proposed_rules = proposed_payload.get("rules", {}) if isinstance(proposed_payload, dict) else {}

        divergences = []
        for idx, envelope in enumerate(envelopes):
            lane = str((envelope or {}).get("lane", "CLARIFY"))
            intent = str((envelope or {}).get("intent", "clarify.request_context"))
            before = self._resolve_policy_rule(current_rules, lane, intent)
            after = self._resolve_policy_rule(proposed_rules, lane, intent)
            changed = (
                bool(before["allowed"]) != bool(after["allowed"])
                or str(before["risk_level"]) != str(after["risk_level"])
                or bool(before["requires_approval"]) != bool(after["requires_approval"])
            )
            if changed:
                divergences.append(
                    {
                        "index": idx,
                        "lane": lane,
                        "intent": intent,
                        "before": before,
                        "after": after,
                    }
                )

        return {
            "kind": KIND_POLICY,
            "draft_id": draft["draft_id"],
            "advisory_only": True,
            "envelopes_simulated": len(envelopes),
            "divergence_count": len(divergences),
            "divergences": divergences,
            "summary": (
                "Dry-run policy simulation only. No runtime policy was modified."
                if divergences
                else "No allow/deny/risk divergence detected in simulation set."
            ),
        }

    def _simulate_tool_contract_draft(
        self,
        *,
        draft: Dict[str, Any],
        current_payload: Dict[str, Any],
        proposed_payload: Dict[str, Any],
        envelopes: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        current_map = self._intent_to_tool_name(current_payload)
        proposed_map = self._intent_to_tool_name(proposed_payload)
        divergences = []
        for idx, envelope in enumerate(envelopes):
            intent = str((envelope or {}).get("intent", ""))
            before = current_map.get(intent)
            after = proposed_map.get(intent)
            if before != after:
                divergences.append(
                    {
                        "index": idx,
                        "intent": intent,
                        "before_tool_name": before,
                        "after_tool_name": after,
                    }
                )

        return {
            "kind": KIND_TOOL_CONTRACT,
            "draft_id": draft["draft_id"],
            "advisory_only": True,
            "envelopes_simulated": len(envelopes),
            "divergence_count": len(divergences),
            "divergences": divergences,
            "summary": (
                "Dry-run tool contract simulation only. No runtime contract mapping was modified."
                if divergences
                else "No tool contract selection divergence detected in simulation set."
            ),
        }

    # -------------------------
    # Payload validation
    # -------------------------
    def _validate_payload(self, kind: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("Draft payload must be an object.")
        normalized = copy.deepcopy(payload)

        if kind == KIND_POLICY:
            rules = normalized.get("rules")
            if not isinstance(rules, dict):
                raise ValueError("Policy payload must include rules object.")
            for key, rule in rules.items():
                if not isinstance(key, str):
                    raise ValueError("Policy rule key must be a string.")
                if not isinstance(rule, dict):
                    raise ValueError(f"Policy rule '{key}' must be an object.")
                for required in ("allowed", "risk_level", "requires_approval", "reason"):
                    if required not in rule:
                        raise ValueError(f"Policy rule '{key}' missing field: {required}")
                if not isinstance(rule["allowed"], bool):
                    raise ValueError(f"Policy rule '{key}' field 'allowed' must be boolean.")
                if not isinstance(rule["requires_approval"], bool):
                    raise ValueError(f"Policy rule '{key}' field 'requires_approval' must be boolean.")
                if not isinstance(rule["risk_level"], str) or not rule["risk_level"].strip():
                    raise ValueError(f"Policy rule '{key}' field 'risk_level' must be non-empty string.")
                if not isinstance(rule["reason"], str) or not rule["reason"].strip():
                    raise ValueError(f"Policy rule '{key}' field 'reason' must be non-empty string.")
            return normalized

        contracts = normalized.get("contracts")
        if not isinstance(contracts, list):
            raise ValueError("Tool contract payload must include contracts list.")
        seen_intents = set()
        for idx, contract in enumerate(contracts):
            if not isinstance(contract, dict):
                raise ValueError(f"Contract at index {idx} must be an object.")
            for required in (
                "tool_name",
                "intent",
                "description",
                "input_schema",
                "output_schema",
                "risk_level",
                "side_effects",
            ):
                if required not in contract:
                    raise ValueError(f"Contract at index {idx} missing field: {required}")
            if not isinstance(contract["tool_name"], str) or not contract["tool_name"].strip():
                raise ValueError(f"Contract at index {idx} field 'tool_name' must be non-empty string.")
            if not isinstance(contract["intent"], str) or not contract["intent"].strip():
                raise ValueError(f"Contract at index {idx} field 'intent' must be non-empty string.")
            intent = contract["intent"].strip()
            if intent in seen_intents:
                raise ValueError(f"Duplicate intent mapping in contract payload: {intent}")
            seen_intents.add(intent)
            if not isinstance(contract["description"], str) or not contract["description"].strip():
                raise ValueError(f"Contract at index {idx} field 'description' must be non-empty string.")
            if not isinstance(contract["input_schema"], dict):
                raise ValueError(f"Contract at index {idx} field 'input_schema' must be object.")
            if not isinstance(contract["output_schema"], dict):
                raise ValueError(f"Contract at index {idx} field 'output_schema' must be object.")
            if not isinstance(contract["risk_level"], str) or not contract["risk_level"].strip():
                raise ValueError(f"Contract at index {idx} field 'risk_level' must be non-empty string.")
            if not isinstance(contract["side_effects"], bool):
                raise ValueError(f"Contract at index {idx} field 'side_effects' must be boolean.")
        return normalized

    # -------------------------
    # Persistence internals
    # -------------------------
    def _assert_kind(self, kind: str) -> None:
        if kind not in SUPPORTED_KINDS:
            raise ValueError(f"Unsupported evolution kind: {kind}")

    def _versions_path(self, kind: str) -> Path:
        return self._store_dir / f"{kind}_versions.json"

    def _drafts_path(self, kind: str) -> Path:
        return self._store_dir / f"{kind}_drafts.json"

    def _active_path(self, kind: str) -> Path:
        if kind == KIND_POLICY:
            return self._policy_path
        return self._tool_contract_path

    @staticmethod
    def _ensure_json_file(path: Path) -> None:
        if not path.exists():
            path.write_text("[]\n", encoding="utf-8")

    @staticmethod
    def _read_json(path: Path) -> List[Dict[str, Any]]:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError(f"Invalid store file format: {path}")
        return data

    @staticmethod
    def _write_json(path: Path, payload: List[Dict[str, Any]]) -> None:
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def _read_active_payload(self, kind: str) -> Dict[str, Any]:
        path = self._active_path(kind)
        if not path.exists():
            raise ValueError(f"Active {kind} file not found: {path}")
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(payload, dict):
            raise ValueError(f"Active {kind} file is invalid: {path}")
        return self._validate_payload(kind, payload)

    def _write_active_payload(self, kind: str, payload: Dict[str, Any]) -> None:
        path = self._active_path(kind)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    def _bootstrap_if_needed(self) -> None:
        for kind in (KIND_POLICY, KIND_TOOL_CONTRACT):
            versions_path = self._versions_path(kind)
            versions = self._read_json(versions_path)
            if versions:
                continue
            payload = self._read_active_payload(kind)
            metadata = VersionMetadata(
                version_id=self._next_id(kind, "version", versions_override=versions),
                author="system.bootstrap",
                timestamp=_now_iso(),
                change_summary="Bootstrap from active snapshot.",
            )
            record = VersionRecord(
                metadata=metadata,
                payload=payload,
                previous_version_id=None,
                source_draft_id=None,
            )
            versions.append(self._version_to_dict(record))
            self._write_json(versions_path, versions)

    def _next_id(self, kind: str, record_type: str, versions_override: List[Dict[str, Any]] | None = None) -> str:
        if record_type == "version":
            versions = versions_override if versions_override is not None else self._read_json(self._versions_path(kind))
            return f"{kind}-v{len(versions) + 1:04d}"
        drafts = self._read_json(self._drafts_path(kind))
        return f"{kind}-d{len(drafts) + 1:04d}"

    @staticmethod
    def _version_to_dict(record: VersionRecord) -> Dict[str, Any]:
        return {
            "metadata": {
                "version_id": record.metadata.version_id,
                "author": record.metadata.author,
                "timestamp": record.metadata.timestamp,
                "change_summary": record.metadata.change_summary,
            },
            "payload": copy.deepcopy(record.payload),
            "previous_version_id": record.previous_version_id,
            "source_draft_id": record.source_draft_id,
        }

    @staticmethod
    def _draft_to_dict(record: DraftRecord) -> Dict[str, Any]:
        return {
            "draft_id": record.draft_id,
            "kind": record.kind,
            "author": record.author,
            "timestamp": record.timestamp,
            "change_summary": record.change_summary,
            "payload": copy.deepcopy(record.payload),
            "modifications": copy.deepcopy(record.modifications),
            "status": record.status,
            "reviewer": record.reviewer,
            "reviewed_at": record.reviewed_at,
            "review_notes": record.review_notes,
        }

    @staticmethod
    def _resolve_policy_rule(rules: Dict[str, Any], lane: str, intent: str) -> Dict[str, Any]:
        direct_key = f"{lane}::{intent}"
        lane_key = f"{lane}::*"
        if direct_key in rules and isinstance(rules[direct_key], dict):
            return copy.deepcopy(rules[direct_key])
        if lane_key in rules and isinstance(rules[lane_key], dict):
            return copy.deepcopy(rules[lane_key])
        return copy.deepcopy(_PHASE4_DEFAULT_POLICY)

    @staticmethod
    def _intent_to_tool_name(payload: Dict[str, Any]) -> Dict[str, str]:
        contracts = payload.get("contracts", []) if isinstance(payload, dict) else []
        mapping: Dict[str, str] = {}
        for contract in contracts:
            if not isinstance(contract, dict):
                continue
            intent = contract.get("intent")
            tool_name = contract.get("tool_name")
            if not isinstance(intent, str) or not intent.strip():
                continue
            if not isinstance(tool_name, str) or not tool_name.strip():
                continue
            if intent in mapping:
                continue
            mapping[intent] = tool_name
        return mapping


def default_policy_contract_evolution_store(
    *,
    store_dir: str | Path | None = None,
    policy_path: str | Path | None = None,
    tool_contract_path: str | Path | None = None,
) -> PolicyContractEvolutionStore:
    return PolicyContractEvolutionStore(
        store_dir=store_dir,
        policy_path=policy_path,
        tool_contract_path=tool_contract_path,
    )
