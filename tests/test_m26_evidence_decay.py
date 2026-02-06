from datetime import datetime, timedelta, timezone

import core.evidence as evidence
import core.introspection as introspection
from core.failure_modes import evaluate_failure_modes, RuntimeContext
from core.task_graph import TaskNode


def _setup_evidence(tmp_path, monkeypatch, trace_id="trace-1"):
    monkeypatch.setattr(evidence, "EVIDENCE_DIR", tmp_path / "evidence")
    evidence.EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    evidence._CURRENT_TRACE_ID = None
    evidence.load_evidence(trace_id)


def _task(description: str) -> TaskNode:
    now = datetime.now(timezone.utc)
    return TaskNode(
        task_id="task-1",
        parent_id=None,
        description=description,
        status="ready",
        depends_on=[],
        created_at=now,
        updated_at=now,
        block_reason=None,
    )


def test_expired_evidence_treated_as_missing(tmp_path, monkeypatch):
    _setup_evidence(tmp_path, monkeypatch)
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(evidence, "_now", lambda: base)
    evidence.record_evidence(
        claim="nginx running",
        source_type="command",
        source_ref="systemctl status nginx",
        raw_content="active",
        ttl_seconds=1,
    )
    now = base + timedelta(seconds=5)
    assert evidence.get_best_evidence_for_claim("nginx running", now) is None
    assert evidence.needs_revalidation("nginx running", now) is True


def test_ttl_enforced_expires_at(tmp_path, monkeypatch):
    _setup_evidence(tmp_path, monkeypatch)
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(evidence, "_now", lambda: base)
    entry = evidence.record_evidence(
        claim="ports open",
        source_type="command",
        source_ref="ss -ltnp",
        raw_content="LISTEN",
        ttl_seconds=10,
    )
    assert entry.expires_at == base + timedelta(seconds=10)


def test_conflicting_evidence_blocks_progress(tmp_path, monkeypatch):
    _setup_evidence(tmp_path, monkeypatch)
    evidence.record_evidence(
        claim="nginx running",
        source_type="command",
        source_ref="systemctl status nginx",
        raw_content="active",
    )
    evidence.record_evidence(
        claim="nginx running",
        source_type="command",
        source_ref="systemctl status nginx",
        raw_content="inactive",
    )
    task = _task("claim: nginx running")
    failure = evaluate_failure_modes(task, RuntimeContext(trace_id="trace-1", user_input="", via_ops=False))
    assert failure.status == "refuse"
    assert failure.failure_code == "EVIDENCE_CONFLICT"


def test_confidence_zero_on_expiry(tmp_path, monkeypatch):
    _setup_evidence(tmp_path, monkeypatch)
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(evidence, "_now", lambda: base)
    evidence.record_evidence(
        claim="container n8n running",
        source_type="introspection",
        source_ref="m25:containers",
        raw_content="running",
        ttl_seconds=1,
    )
    now = base + timedelta(seconds=5)
    assert evidence.confidence_for_claim("container n8n running", now) == 0.0


def test_m25_refreshes_expired_evidence(tmp_path, monkeypatch):
    _setup_evidence(tmp_path, monkeypatch)
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(evidence, "_now", lambda: base)
    evidence.record_evidence(
        claim="host.hostname",
        source_type="introspection",
        source_ref="m25:host",
        raw_content="old-host",
        ttl_seconds=1,
    )
    monkeypatch.setattr(evidence, "_now", lambda: base + timedelta(seconds=4))
    monkeypatch.setattr(introspection, "_probe_host", lambda: {"hostname": "new-host"})
    introspection.collect_environment_snapshot(["host"])
    now = base + timedelta(seconds=5)
    assert evidence.needs_revalidation("host.hostname", now) is False


def test_m26_does_not_override_m23_refusals(tmp_path, monkeypatch):
    _setup_evidence(tmp_path, monkeypatch)
    task = _task("/exec rm /tmp/data.txt")
    failure = evaluate_failure_modes(task, RuntimeContext(trace_id="trace-1", user_input="", via_ops=False))
    assert failure.status == "refuse"
    assert failure.failure_code == "IRREVERSIBLE_NO_ACK"
