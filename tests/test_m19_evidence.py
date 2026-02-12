import pytest

import v2.core.evidence as evidence
from v2.core.contracts.loader import ContractViolation


def _reset_evidence():
    evidence._CURRENT_TRACE_ID = None


def _setup_tmp_evidence(tmp_path, monkeypatch, trace_id="trace-1"):
    monkeypatch.setattr(evidence, "EVIDENCE_DIR", tmp_path / "evidence")
    evidence.EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    _reset_evidence()
    evidence.load_evidence(trace_id)


def test_evidence_persists_after_reload(tmp_path, monkeypatch):
    _setup_tmp_evidence(tmp_path, monkeypatch)
    entry = evidence.record_evidence(
        claim="service nginx is running",
        source_type="command",
        source_ref="systemctl status nginx",
        raw_content="active (running)",
    )

    _reset_evidence()
    evidence.load_evidence("trace-1")
    records = evidence.list_evidence("service nginx is running")

    assert len(records) == 1
    assert records[0].content_hash == entry.content_hash


def test_hash_is_deterministic(tmp_path, monkeypatch):
    _setup_tmp_evidence(tmp_path, monkeypatch)
    first = evidence.record_evidence(
        claim="ports open",
        source_type="command",
        source_ref="ss -ltnp",
        raw_content="LISTEN 0 128",
    )
    second = evidence.record_evidence(
        claim="ports open",
        source_type="command",
        source_ref="ss -ltnp",
        raw_content="LISTEN 0 128",
    )

    assert first.content_hash == second.content_hash


def test_claims_without_evidence_are_rejected(tmp_path, monkeypatch):
    _setup_tmp_evidence(tmp_path, monkeypatch)
    with pytest.raises(ContractViolation):
        evidence.assert_claim_known("missing claim")


def test_evidence_is_immutable(tmp_path, monkeypatch):
    _setup_tmp_evidence(tmp_path, monkeypatch)
    evidence.record_evidence(
        claim="config present",
        source_type="file",
        source_ref="/etc/nginx/nginx.conf",
        raw_content="user nginx;",
    )
    evidence.record_evidence(
        claim="config present",
        source_type="file",
        source_ref="/etc/nginx/nginx.conf",
        raw_content="worker_processes auto;",
    )

    records = evidence.list_evidence("config present")
    assert len(records) == 2


def test_multiple_claims_tracked_independently(tmp_path, monkeypatch):
    _setup_tmp_evidence(tmp_path, monkeypatch)
    evidence.record_evidence(
        claim="claim-a",
        source_type="test",
        source_ref="pytest -q",
        raw_content="1 passed",
    )
    evidence.record_evidence(
        claim="claim-b",
        source_type="observation",
        source_ref="manual",
        raw_content="observed",
    )

    assert evidence.has_evidence("claim-a") is True
    assert evidence.has_evidence("claim-b") is True
    assert evidence.has_evidence("claim-c") is False
