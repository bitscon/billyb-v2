from __future__ import annotations

import json

import v2.core.runtime as runtime_mod
from v2.core.aci_issuance_ledger import ACIIssuanceLedger, build_receipt_envelope


def test_ledger_append_only_and_lookup_paths(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"
    ledger = ACIIssuanceLedger(ledger_path=ledger_path)

    first = ledger.append_issued_artifact(
        phase_id=28,
        contract_name="inspection_capabilities_gate.v1",
        issuer_identity_id="human",
        environment_id="env-a",
        lineage_refs=[],
        request_context={"reason": "seed"},
        lineage_required=False,
    )
    assert first.ok is True
    assert first.record is not None
    first_id = str(first.record["artifact_id"])

    second = ledger.append_issued_artifact(
        phase_id=29,
        contract_name="inspection_result_binding.v1",
        issuer_identity_id="human",
        environment_id="env-a",
        lineage_refs=[first_id],
        request_context={"reason": "downstream"},
        lineage_required=True,
    )
    assert second.ok is True
    assert second.record is not None

    lines = [line for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 2

    by_id = ledger.lookup_by_artifact_id(first_id)
    assert by_id is not None
    assert by_id["artifact_id"] == first_id

    by_phase = ledger.lookup_by_phase_id(29)
    assert len(by_phase) == 1
    assert by_phase[0]["artifact_id"] == second.record["artifact_id"]

    by_lineage = ledger.lookup_by_lineage_reference(first_id)
    assert len(by_lineage) == 1
    assert by_lineage[0]["artifact_id"] == second.record["artifact_id"]


def test_ledger_lookup_returns_immutable_copies(tmp_path):
    ledger = ACIIssuanceLedger(ledger_path=tmp_path / "ledger.jsonl")
    append = ledger.append_issued_artifact(
        phase_id=28,
        contract_name="inspection_capabilities_gate.v1",
        issuer_identity_id="human",
        environment_id="env-a",
        lineage_refs=[],
        request_context={},
        lineage_required=False,
    )
    assert append.ok is True
    assert append.record is not None
    artifact_id = str(append.record["artifact_id"])
    expected_digest = str(append.record["input_digest"])

    mutated = ledger.lookup_by_artifact_id(artifact_id)
    assert mutated is not None
    mutated["input_digest"] = "tampered"
    mutated["artifact"]["contract_name"] = "tampered"

    reloaded = ledger.lookup_by_artifact_id(artifact_id)
    assert reloaded is not None
    assert reloaded["input_digest"] == expected_digest
    assert reloaded["artifact"]["contract_name"] == "inspection_capabilities_gate.v1"


def test_ledger_replay_guard_rejects_duplicate_transition_for_same_lineage(tmp_path):
    ledger = ACIIssuanceLedger(ledger_path=tmp_path / "ledger.jsonl")
    root = ledger.append_issued_artifact(
        phase_id=28,
        contract_name="inspection_capabilities_gate.v1",
        issuer_identity_id="human",
        environment_id="env-a",
        lineage_refs=[],
        request_context={},
        lineage_required=False,
    )
    assert root.ok is True
    assert root.record is not None
    root_id = str(root.record["artifact_id"])

    first = ledger.append_issued_artifact(
        phase_id=29,
        contract_name="inspection_result_binding.v1",
        issuer_identity_id="human",
        environment_id="env-a",
        lineage_refs=[root_id],
        request_context={},
        lineage_required=True,
    )
    assert first.ok is True

    duplicate = ledger.append_issued_artifact(
        phase_id=29,
        contract_name="inspection_result_binding.v1",
        issuer_identity_id="human",
        environment_id="env-a",
        lineage_refs=[root_id],
        request_context={"repeat": True},
        lineage_required=True,
    )
    assert duplicate.ok is False
    assert duplicate.reason_code == "ISSUANCE_DUPLICATE_FOR_LINEAGE"


def test_ledger_lineage_validation_is_fail_closed(tmp_path):
    ledger = ACIIssuanceLedger(ledger_path=tmp_path / "ledger.jsonl")

    missing_required = ledger.append_issued_artifact(
        phase_id=29,
        contract_name="inspection_result_binding.v1",
        issuer_identity_id="human",
        environment_id="env-a",
        lineage_refs=[],
        request_context={},
        lineage_required=True,
    )
    assert missing_required.ok is False
    assert missing_required.reason_code == "ISSUANCE_LINEAGE_REQUIRED"

    upstream = ledger.append_issued_artifact(
        phase_id=28,
        contract_name="inspection_capabilities_gate.v1",
        issuer_identity_id="human",
        environment_id="env-a",
        lineage_refs=[],
        request_context={},
        lineage_required=False,
    )
    assert upstream.ok is True
    assert upstream.record is not None
    upstream_id = str(upstream.record["artifact_id"])

    mismatch = ledger.append_issued_artifact(
        phase_id=29,
        contract_name="inspection_result_binding.v1",
        issuer_identity_id="human",
        environment_id="env-b",
        lineage_refs=[upstream_id],
        request_context={},
        lineage_required=True,
    )
    assert mismatch.ok is False
    assert mismatch.reason_code == "ISSUANCE_ENVIRONMENT_MISMATCH"

    missing_upstream = ledger.append_issued_artifact(
        phase_id=29,
        contract_name="inspection_result_binding.v1",
        issuer_identity_id="human",
        environment_id="env-a",
        lineage_refs=["artifact-p28-99999999"],
        request_context={},
        lineage_required=True,
    )
    assert missing_upstream.ok is False
    assert missing_upstream.reason_code == "ISSUANCE_UPSTREAM_NOT_FOUND"


def test_runtime_confirmation_issues_receipt_without_execution_leakage(tmp_path):
    ledger_path = tmp_path / "runtime-ledger.jsonl"
    runtime = runtime_mod.BillyRuntime(config={}, aci_ledger_path=str(ledger_path))
    context = {
        "trace_id": "trace-aci-receipt-1",
        "current_phase": 27,
        "environment_id": "env-a",
        "issuer_identity_id": "human-1",
    }

    proposal = runtime.run_turn("approve and authorize the next governance artifact", context)
    assert proposal["final_output"]["type"] == "proposal"
    assert proposal["execution_enabled"] is False
    assert all(value is False for value in proposal["authority_guarantees"].values())
    assert proposal["tool_calls"] == []

    confirm = runtime.run_turn("confirm issuance", context)
    assert confirm["status"] == "success"
    assert confirm["final_output"]["type"] == "receipt"
    assert confirm["final_output"]["phase_id"] == 28
    assert confirm["final_output"]["contract_name"] == "inspection_capabilities_gate.v1"
    assert confirm["execution_enabled"] is False
    assert all(value is False for value in confirm["authority_guarantees"].values())
    assert confirm["tool_calls"] == []

    receipt_record = runtime._aci_issuance_ledger.lookup_by_artifact_id(confirm["final_output"]["artifact_id"])
    assert receipt_record is not None
    rebuilt = build_receipt_envelope(receipt_record)
    assert rebuilt["artifact_id"] == confirm["final_output"]["artifact_id"]

    persisted_lines = [line for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(persisted_lines) == 1
    parsed = json.loads(persisted_lines[0])
    assert parsed["artifact_id"] == confirm["final_output"]["artifact_id"]


def test_runtime_confirmation_replay_is_rejected(tmp_path):
    runtime = runtime_mod.BillyRuntime(config={}, aci_ledger_path=str(tmp_path / "runtime-ledger.jsonl"))
    context = {
        "trace_id": "trace-aci-replay",
        "current_phase": 27,
        "environment_id": "env-a",
        "issuer_identity_id": "human-1",
    }
    runtime.run_turn("approve and authorize the next governance artifact", context)
    first = runtime.run_turn("confirm issuance", context)
    assert first["final_output"]["type"] == "receipt"

    replay = runtime.run_turn("confirm issuance", context)
    assert replay["status"] == "error"
    assert replay["final_output"]["type"] == "refusal"
    assert replay["final_output"]["reason_code"] == "ISSUANCE_CONFIRMATION_REPLAYED"
    assert replay["execution_enabled"] is False


def test_runtime_lineage_ambiguity_is_rejected(tmp_path):
    ledger_path = tmp_path / "runtime-ledger.jsonl"
    runtime = runtime_mod.BillyRuntime(config={}, aci_ledger_path=str(ledger_path))
    seed_ledger = ACIIssuanceLedger(ledger_path=ledger_path)
    seed_ledger.append_issued_artifact(
        phase_id=28,
        contract_name="seed_a.v1",
        issuer_identity_id="human",
        environment_id="env-a",
        lineage_refs=[],
        request_context={},
        lineage_required=False,
    )
    seed_ledger.append_issued_artifact(
        phase_id=28,
        contract_name="seed_b.v1",
        issuer_identity_id="human",
        environment_id="env-a",
        lineage_refs=[],
        request_context={},
        lineage_required=False,
    )

    context = {
        "trace_id": "trace-aci-lineage-ambiguous",
        "current_phase": 28,
        "environment_id": "env-a",
        "issuer_identity_id": "human-1",
    }
    proposal = runtime.run_turn("approve and authorize the next governance artifact", context)
    assert proposal["final_output"]["type"] == "proposal"

    confirm = runtime.run_turn("confirm issuance", context)
    assert confirm["status"] == "error"
    assert confirm["final_output"]["type"] == "refusal"
    assert confirm["final_output"]["reason_code"] == "ISSUANCE_LINEAGE_AMBIGUOUS"


def test_revocation_invalidates_downstream_admissibility_without_mutation(tmp_path):
    ledger = ACIIssuanceLedger(ledger_path=tmp_path / "ledger.jsonl")
    upstream = ledger.append_issued_artifact(
        phase_id=28,
        contract_name="inspection_capabilities_gate.v1",
        issuer_identity_id="human",
        environment_id="env-a",
        lineage_refs=[],
        request_context={},
        lineage_required=False,
    )
    assert upstream.ok is True
    assert upstream.record is not None
    upstream_id = str(upstream.record["artifact_id"])

    revoked = ledger.append_revocation_record(
        revoked_artifact_id=upstream_id,
        revocation_reason="human_withdrawal",
        issuer_identity_id="human",
        environment_id="env-a",
        request_context={},
    )
    assert revoked.ok is True
    assert revoked.record is not None
    assert revoked.record["contract_name"] == "revocation_record.v1"

    downstream = ledger.append_issued_artifact(
        phase_id=29,
        contract_name="inspection_result_binding.v1",
        issuer_identity_id="human",
        environment_id="env-a",
        lineage_refs=[upstream_id],
        request_context={},
        lineage_required=True,
    )
    assert downstream.ok is False
    assert downstream.reason_code == "ISSUANCE_UPSTREAM_REVOKED"

    still_readable = ledger.lookup_by_artifact_id(upstream_id)
    assert still_readable is not None
    assert still_readable["artifact_id"] == upstream_id


def test_supersession_creates_deterministic_replacement_chain(tmp_path):
    ledger = ACIIssuanceLedger(ledger_path=tmp_path / "ledger.jsonl")
    root = ledger.append_issued_artifact(
        phase_id=28,
        contract_name="inspection_capabilities_gate.v1",
        issuer_identity_id="human",
        environment_id="env-a",
        lineage_refs=[],
        request_context={},
        lineage_required=False,
    )
    assert root.ok is True
    assert root.record is not None
    root_id = str(root.record["artifact_id"])

    old = ledger.append_issued_artifact(
        phase_id=29,
        contract_name="inspection_result_binding.v1",
        issuer_identity_id="human",
        environment_id="env-a",
        lineage_refs=[root_id],
        request_context={},
        lineage_required=True,
    )
    assert old.ok is True
    assert old.record is not None
    old_id = str(old.record["artifact_id"])

    replacement = ledger.append_issued_artifact(
        phase_id=30,
        contract_name="delegation_envelope.v1",
        issuer_identity_id="human",
        environment_id="env-a",
        lineage_refs=[root_id],
        request_context={},
        lineage_required=True,
    )
    assert replacement.ok is True
    assert replacement.record is not None
    replacement_id = str(replacement.record["artifact_id"])

    revoked = ledger.append_revocation_record(
        revoked_artifact_id=old_id,
        revocation_reason="replace_with_newer",
        issuer_identity_id="human",
        environment_id="env-a",
        request_context={},
    )
    assert revoked.ok is True

    superseded = ledger.append_supersession_record(
        superseded_artifact_id=old_id,
        replacement_artifact_id=replacement_id,
        issuer_identity_id="human",
        environment_id="env-a",
        request_context={},
    )
    assert superseded.ok is True
    assert superseded.record is not None
    assert superseded.record["contract_name"] == "supersession_record.v1"
    assert ledger.get_supersession_replacement(old_id) == replacement_id
    assert ledger.is_artifact_revoked(old_id) is True


def test_revocation_and_supersession_replay_are_rejected(tmp_path):
    ledger = ACIIssuanceLedger(ledger_path=tmp_path / "ledger.jsonl")
    root = ledger.append_issued_artifact(
        phase_id=28,
        contract_name="inspection_capabilities_gate.v1",
        issuer_identity_id="human",
        environment_id="env-a",
        lineage_refs=[],
        request_context={},
        lineage_required=False,
    )
    assert root.ok is True
    assert root.record is not None
    root_id = str(root.record["artifact_id"])

    old = ledger.append_issued_artifact(
        phase_id=29,
        contract_name="inspection_result_binding.v1",
        issuer_identity_id="human",
        environment_id="env-a",
        lineage_refs=[root_id],
        request_context={},
        lineage_required=True,
    )
    assert old.ok is True
    assert old.record is not None
    old_id = str(old.record["artifact_id"])

    replacement = ledger.append_issued_artifact(
        phase_id=30,
        contract_name="delegation_envelope.v1",
        issuer_identity_id="human",
        environment_id="env-a",
        lineage_refs=[root_id],
        request_context={},
        lineage_required=True,
    )
    assert replacement.ok is True
    assert replacement.record is not None
    replacement_id = str(replacement.record["artifact_id"])

    first_revoke = ledger.append_revocation_record(
        revoked_artifact_id=old_id,
        revocation_reason="withdraw",
        issuer_identity_id="human",
        environment_id="env-a",
        request_context={},
    )
    assert first_revoke.ok is True
    replay_revoke = ledger.append_revocation_record(
        revoked_artifact_id=old_id,
        revocation_reason="withdraw_again",
        issuer_identity_id="human",
        environment_id="env-a",
        request_context={},
    )
    assert replay_revoke.ok is False
    assert replay_revoke.reason_code == "REVOCATION_ALREADY_REVOKED"

    first_supersede = ledger.append_supersession_record(
        superseded_artifact_id=old_id,
        replacement_artifact_id=replacement_id,
        issuer_identity_id="human",
        environment_id="env-a",
        request_context={},
    )
    assert first_supersede.ok is True
    replay_supersede = ledger.append_supersession_record(
        superseded_artifact_id=old_id,
        replacement_artifact_id=replacement_id,
        issuer_identity_id="human",
        environment_id="env-a",
        request_context={},
    )
    assert replay_supersede.ok is False
    assert replay_supersede.reason_code == "SUPERSESSION_ALREADY_EXISTS"


def test_runtime_revoke_and_supersede_flow_is_confirmation_gated_and_non_executing(tmp_path):
    ledger_path = tmp_path / "runtime-ledger.jsonl"
    runtime = runtime_mod.BillyRuntime(config={}, aci_ledger_path=str(ledger_path))
    base_context = {
        "trace_id": "trace-aci-revoke-supersede",
        "current_phase": 27,
        "environment_id": "env-a",
        "issuer_identity_id": "human-1",
    }

    issued = runtime.run_turn("approve and authorize the next governance artifact", dict(base_context))
    assert issued["final_output"]["type"] == "proposal"
    issued_receipt = runtime.run_turn("confirm issuance", dict(base_context))
    assert issued_receipt["final_output"]["type"] == "receipt"
    old_artifact_id = str(issued_receipt["final_output"]["artifact_id"])

    # Seed a replacement artifact in the same environment and phase class.
    seeded = runtime._aci_issuance_ledger.append_issued_artifact(
        phase_id=29,
        contract_name="inspection_result_binding.v1",
        issuer_identity_id="human-1",
        environment_id="env-a",
        lineage_refs=[old_artifact_id],
        request_context={},
        lineage_required=True,
    )
    assert seeded.ok is True
    assert seeded.record is not None
    replacement_artifact_id = str(seeded.record["artifact_id"])

    revoke = runtime.run_turn(f"revoke {old_artifact_id}", dict(base_context))
    assert revoke["final_output"]["type"] == "proposal"
    assert revoke["final_output"]["next_artifact"] == "revocation_record.v1"
    revoke_receipt = runtime.run_turn("confirm issuance", dict(base_context))
    assert revoke_receipt["final_output"]["type"] == "receipt"
    assert revoke_receipt["final_output"]["contract_name"] == "revocation_record.v1"
    assert revoke_receipt["execution_enabled"] is False
    assert all(value is False for value in revoke_receipt["authority_guarantees"].values())
    assert revoke_receipt["tool_calls"] == []

    revoke_replay = runtime.run_turn(f"revoke {old_artifact_id}", dict(base_context))
    assert revoke_replay["status"] == "error"
    assert revoke_replay["final_output"]["type"] == "refusal"
    assert revoke_replay["final_output"]["reason_code"] in {
        "REVOCATION_ALREADY_REVOKED",
        "REVOCATION_ALREADY_SUPERSEDED",
    }

    supersede = runtime.run_turn(
        f"supersede {old_artifact_id} with {replacement_artifact_id}",
        dict(base_context),
    )
    assert supersede["final_output"]["type"] == "proposal"
    assert supersede["final_output"]["next_artifact"] == "supersession_record.v1"
    supersede_receipt = runtime.run_turn("confirm issuance", dict(base_context))
    assert supersede_receipt["final_output"]["type"] == "receipt"
    assert supersede_receipt["final_output"]["contract_name"] == "supersession_record.v1"
    assert supersede_receipt["execution_enabled"] is False
    assert all(value is False for value in supersede_receipt["authority_guarantees"].values())
    assert supersede_receipt["tool_calls"] == []

    supersede_replay = runtime.run_turn(
        f"supersede {old_artifact_id} with {replacement_artifact_id}",
        dict(base_context),
    )
    assert supersede_replay["status"] == "error"
    assert supersede_replay["final_output"]["type"] == "refusal"
    assert supersede_replay["final_output"]["reason_code"] == "SUPERSESSION_ALREADY_EXISTS"
