"""Phase 35 explicit proposal submission (human-confirmed, non-executing)."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping

from v2.core.proposal_governance import REQUIRED_INTENT_CLASS, create_proposal


_EXPLICIT_CONFIRMATION_PATTERNS = (
    re.compile(r"^\s*submit proposal\s*$", re.IGNORECASE),
    re.compile(r"^\s*yes[, ]+\s*submit(?:\s+this)?\s+proposal\s*$", re.IGNORECASE),
    re.compile(r"^\s*i confirm[, ]+\s*submit(?:\s+this)?\s+proposal\s*$", re.IGNORECASE),
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _normalize_confirmation(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _is_explicit_submission_confirmation(text: str) -> bool:
    candidate = str(text or "")
    return any(pattern.fullmatch(candidate) is not None for pattern in _EXPLICIT_CONFIRMATION_PATTERNS)


def _parse_iso8601(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_iso8601(value: str | None) -> str | None:
    parsed = _parse_iso8601(str(value or ""))
    if parsed is None:
        return None
    return parsed.isoformat().replace("+00:00", "Z")


def _draft_fingerprint_payload(draft_artifact: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "draft_id": str(draft_artifact.get("draft_id", "")).strip(),
        "intent_class": str(draft_artifact.get("intent_class", "")).strip(),
        "originating_turn_id": str(draft_artifact.get("originating_turn_id", "")).strip(),
        "governance_context": copy.deepcopy(dict(draft_artifact.get("governance_context", {}) or {})),
        "advisory_fingerprint": str(draft_artifact.get("advisory_fingerprint", "")).strip(),
        "created_at": str(draft_artifact.get("created_at", "")).strip(),
    }


def compute_proposal_draft_fingerprint(draft_artifact: Mapping[str, Any]) -> str:
    return _digest(_draft_fingerprint_payload(draft_artifact))


def build_phase33_proposal_draft(
    *,
    originating_turn_id: str,
    governance_context: Mapping[str, Any],
    advisory_fingerprint: str,
    created_at: str,
) -> Dict[str, Any]:
    """Build a deterministic Phase 33 proposal draft artifact (inert)."""
    turn_id = str(originating_turn_id).strip()
    advisory = str(advisory_fingerprint).strip()
    normalized_created_at = _normalize_iso8601(created_at)
    context = dict(governance_context or {})

    draft_basis = {
        "originating_turn_id": turn_id,
        "governance_context": copy.deepcopy(context),
        "advisory_fingerprint": advisory,
        "created_at": normalized_created_at or str(created_at).strip(),
    }
    draft_id = f"proposal-draft-{_digest(draft_basis)[:16]}"
    draft = {
        "draft_id": draft_id,
        "intent_class": REQUIRED_INTENT_CLASS,
        "originating_turn_id": turn_id,
        "governance_context": copy.deepcopy(context),
        "advisory_fingerprint": advisory,
        "created_at": normalized_created_at or str(created_at).strip(),
        "execution_enabled": False,
        "approved": False,
        "executed": False,
    }
    draft["draft_fingerprint"] = compute_proposal_draft_fingerprint(draft)
    return copy.deepcopy(draft)


@dataclass(frozen=True)
class ProposalSubmissionResult:
    ok: bool
    reason_code: str
    receipt: Dict[str, Any] | None


class ProposalSubmissionLedger:
    """Append-only ledger for successful Phase 35 submissions."""

    def __init__(self) -> None:
        self._records: List[Dict[str, Any]] = []
        self._consumed_confirmation_tokens: set[str] = set()
        self._submitted_draft_fingerprints: Dict[str, str] = {}

    def reset(self) -> None:
        self._records.clear()
        self._consumed_confirmation_tokens.clear()
        self._submitted_draft_fingerprints.clear()

    def get_ledger(self) -> List[Dict[str, Any]]:
        return copy.deepcopy(self._records)

    def _append_submission_record(self, *, submission_id: str, payload: Mapping[str, Any]) -> Dict[str, Any]:
        previous_hash = ""
        if self._records:
            previous_hash = str(self._records[-1].get("record_hash", ""))
        record = {
            "record_id": f"proposal-submission-ledger-{len(self._records) + 1:08d}",
            "recorded_at": _utc_now_iso(),
            "previous_record_hash": previous_hash,
            "event_type": "proposal_submitted",
            "submission_id": str(submission_id),
            "payload": copy.deepcopy(dict(payload)),
        }
        record["record_hash"] = _digest(
            {
                "record_id": record["record_id"],
                "recorded_at": record["recorded_at"],
                "previous_record_hash": record["previous_record_hash"],
                "event_type": record["event_type"],
                "submission_id": record["submission_id"],
                "payload": record["payload"],
            }
        )
        self._records.append(copy.deepcopy(record))
        return copy.deepcopy(record)

    def submit_draft_proposal(
        self,
        *,
        draft_artifact: Mapping[str, Any] | None,
        confirmation_text: str,
        request_draft_fingerprint: str,
        submitted_at: str | None = None,
    ) -> ProposalSubmissionResult:
        if not _is_explicit_submission_confirmation(confirmation_text):
            return ProposalSubmissionResult(
                ok=False,
                reason_code="SUBMISSION_CONFIRMATION_REQUIRED",
                receipt=None,
            )

        if not isinstance(draft_artifact, Mapping):
            return ProposalSubmissionResult(
                ok=False,
                reason_code="SUBMISSION_DRAFT_REQUIRED",
                receipt=None,
            )

        draft = dict(draft_artifact)
        required = {
            "draft_id",
            "intent_class",
            "originating_turn_id",
            "governance_context",
            "advisory_fingerprint",
            "created_at",
            "draft_fingerprint",
        }
        if any(field not in draft for field in required):
            return ProposalSubmissionResult(
                ok=False,
                reason_code="SUBMISSION_DRAFT_INVALID",
                receipt=None,
            )
        if str(draft.get("intent_class", "")).strip() != REQUIRED_INTENT_CLASS:
            return ProposalSubmissionResult(
                ok=False,
                reason_code="SUBMISSION_DRAFT_INTENT_INVALID",
                receipt=None,
            )
        if not isinstance(draft.get("governance_context"), Mapping):
            return ProposalSubmissionResult(
                ok=False,
                reason_code="SUBMISSION_DRAFT_CONTEXT_INVALID",
                receipt=None,
            )

        computed_fingerprint = compute_proposal_draft_fingerprint(draft)
        declared_fingerprint = str(draft.get("draft_fingerprint", "")).strip()
        request_fingerprint = str(request_draft_fingerprint).strip()
        if not declared_fingerprint:
            return ProposalSubmissionResult(
                ok=False,
                reason_code="SUBMISSION_DRAFT_FINGERPRINT_REQUIRED",
                receipt=None,
            )
        if declared_fingerprint != computed_fingerprint:
            return ProposalSubmissionResult(
                ok=False,
                reason_code="SUBMISSION_DRAFT_FINGERPRINT_INVALID",
                receipt=None,
            )
        if not request_fingerprint:
            return ProposalSubmissionResult(
                ok=False,
                reason_code="SUBMISSION_REQUEST_FINGERPRINT_REQUIRED",
                receipt=None,
            )
        if request_fingerprint != computed_fingerprint:
            return ProposalSubmissionResult(
                ok=False,
                reason_code="SUBMISSION_DRAFT_FINGERPRINT_MISMATCH",
                receipt=None,
            )

        confirmation_token = _digest(
            {
                "confirmation_text": _normalize_confirmation(confirmation_text),
                "draft_fingerprint": computed_fingerprint,
            }
        )
        if confirmation_token in self._consumed_confirmation_tokens:
            return ProposalSubmissionResult(
                ok=False,
                reason_code="SUBMISSION_CONFIRMATION_REPLAYED",
                receipt=None,
            )
        if computed_fingerprint in self._submitted_draft_fingerprints:
            return ProposalSubmissionResult(
                ok=False,
                reason_code="SUBMISSION_DRAFT_ALREADY_SUBMITTED",
                receipt=None,
            )

        governance_context = copy.deepcopy(dict(draft.get("governance_context", {}) or {}))
        governance_context["phase35_submission"] = {
            "draft_id": str(draft.get("draft_id", "")).strip(),
            "draft_fingerprint": computed_fingerprint,
            "advisory_fingerprint": str(draft.get("advisory_fingerprint", "")).strip(),
            "confirmation_token": confirmation_token,
        }
        create_result = create_proposal(
            intent_class=REQUIRED_INTENT_CLASS,
            originating_turn_id=str(draft.get("originating_turn_id", "")).strip(),
            governance_context=governance_context,
            expiration_time=None,
        )
        if not create_result.ok or create_result.proposal is None:
            return ProposalSubmissionResult(
                ok=False,
                reason_code=f"SUBMISSION_CREATE_PROPOSAL_FAILED:{create_result.reason_code}",
                receipt=None,
            )

        normalized_submitted_at = _normalize_iso8601(submitted_at)
        submitted_at_value = normalized_submitted_at or _utc_now_iso()
        submission_id = f"proposal-submission-{_digest({'proposal_id': create_result.proposal['proposal_id'], 'token': confirmation_token})[:16]}"
        receipt = {
            "type": "proposal_submission_receipt",
            "submission_id": submission_id,
            "submitted_at": submitted_at_value,
            "proposal_id": str(create_result.proposal.get("proposal_id", "")),
            "proposal_state": str(create_result.proposal.get("state", "")),
            "draft_id": str(draft.get("draft_id", "")).strip(),
            "originating_turn_id": str(draft.get("originating_turn_id", "")).strip(),
            "draft_fingerprint": computed_fingerprint,
            "advisory_fingerprint": str(draft.get("advisory_fingerprint", "")).strip(),
            "confirmation_token": confirmation_token,
            "execution_enabled": False,
            "approved": False,
            "executed": False,
        }

        self._consumed_confirmation_tokens.add(confirmation_token)
        self._submitted_draft_fingerprints[computed_fingerprint] = submission_id
        self._append_submission_record(
            submission_id=submission_id,
            payload={
                "receipt": receipt,
                "proposal_ledger_record_id": str((create_result.ledger_entry or {}).get("record_id", "")),
                "reason_code": "PROPOSAL_DRAFT_SUBMITTED",
            },
        )
        return ProposalSubmissionResult(
            ok=True,
            reason_code="PROPOSAL_DRAFT_SUBMITTED",
            receipt=copy.deepcopy(receipt),
        )


_PROPOSAL_SUBMISSION_LEDGER = ProposalSubmissionLedger()


def submit_draft_proposal(
    *,
    draft_artifact: Mapping[str, Any] | None,
    confirmation_text: str,
    request_draft_fingerprint: str,
    submitted_at: str | None = None,
) -> ProposalSubmissionResult:
    return _PROPOSAL_SUBMISSION_LEDGER.submit_draft_proposal(
        draft_artifact=draft_artifact,
        confirmation_text=confirmation_text,
        request_draft_fingerprint=request_draft_fingerprint,
        submitted_at=submitted_at,
    )


def get_proposal_submission_ledger() -> List[Dict[str, Any]]:
    return _PROPOSAL_SUBMISSION_LEDGER.get_ledger()


def reset_proposal_submission_ledger() -> None:
    _PROPOSAL_SUBMISSION_LEDGER.reset()

