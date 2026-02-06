import json

import core.evidence as evidence
import core.introspection as introspection


def _setup_evidence(tmp_path, monkeypatch, trace_id="trace-1"):
    monkeypatch.setattr(evidence, "EVIDENCE_DIR", tmp_path / "evidence")
    evidence.EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    evidence._CURRENT_TRACE_ID = None
    evidence.load_evidence(trace_id)


def test_snapshot_contains_only_allowed_categories(tmp_path, monkeypatch):
    _setup_evidence(tmp_path, monkeypatch)
    monkeypatch.setattr(introspection, "_probe_host", lambda: {"hostname": "test-host"})
    snapshot = introspection.collect_environment_snapshot(["host"])
    assert snapshot.host["hostname"] == "test-host"
    assert snapshot.services == {}
    assert snapshot.containers == {}
    assert snapshot.filesystem == {}
    assert snapshot.network == {}


def test_evidence_recorded_for_each_fact(tmp_path, monkeypatch):
    _setup_evidence(tmp_path, monkeypatch)
    monkeypatch.setattr(
        introspection,
        "_probe_host",
        lambda: {"hostname": "test-host", "os": "linux"},
    )
    introspection.collect_environment_snapshot(["host"])

    hostname_records = evidence.list_evidence("host.hostname")
    os_records = evidence.list_evidence("host.os")
    assert hostname_records
    assert os_records
    assert hostname_records[0].source_type == "introspection"


def test_ttl_applied_to_evidence(tmp_path, monkeypatch):
    _setup_evidence(tmp_path, monkeypatch)
    monkeypatch.setattr(introspection, "_probe_host", lambda: {"hostname": "test-host"})
    introspection.collect_environment_snapshot(["host"])
    records = evidence.list_evidence("host.hostname")
    assert records[0].ttl_seconds == introspection.DEFAULT_TTL_SECONDS


def test_missing_tools_handled_safely(tmp_path, monkeypatch):
    _setup_evidence(tmp_path, monkeypatch)
    monkeypatch.setattr(introspection.shutil, "which", lambda _: None)
    snapshot = introspection.collect_environment_snapshot(["containers"])
    assert snapshot.containers["runtime"] is None
    assert snapshot.containers["available"] is False


def test_invalid_scope_refused(tmp_path, monkeypatch):
    _setup_evidence(tmp_path, monkeypatch)
    try:
        introspection.collect_environment_snapshot(["invalid"])
        assert False, "Expected IntrospectionError"
    except introspection.IntrospectionError as exc:
        assert exc.code == "SCOPE_INVALID"


def test_readonly_commands_only():
    forbidden = {"rm", "touch", "mkdir", "dd", "mkfs"}
    assert not (forbidden & introspection.READONLY_COMMANDS)
