from pathlib import Path

import pytest
import yaml

from v2.core.policy_evolution import (
    KIND_POLICY,
    KIND_TOOL_CONTRACT,
    PolicyContractEvolutionStore,
)


def _policy_payload() -> dict:
    return {
        "rules": {
            "CHAT::chat.general": {
                "allowed": True,
                "risk_level": "low",
                "requires_approval": False,
                "reason": "Chat allowed.",
            },
            "PLAN::plan.create_empty_file": {
                "allowed": True,
                "risk_level": "medium",
                "requires_approval": True,
                "reason": "Plan requires approval.",
            },
            "PLAN::plan.user_action_request": {
                "allowed": True,
                "risk_level": "medium",
                "requires_approval": True,
                "reason": "Action requires approval.",
            },
        }
    }


def _tool_contract_payload() -> dict:
    return {
        "contracts": [
            {
                "tool_name": "stub.filesystem.create_empty_file",
                "intent": "plan.create_empty_file",
                "description": "Create empty file",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
                "risk_level": "medium",
                "side_effects": True,
            },
            {
                "tool_name": "stub.actions.generic_plan_request",
                "intent": "plan.user_action_request",
                "description": "Generic plan action",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
                "risk_level": "medium",
                "side_effects": True,
            },
        ]
    }


def _store(tmp_path: Path) -> PolicyContractEvolutionStore:
    contracts_dir = tmp_path / "contracts"
    contracts_dir.mkdir(parents=True, exist_ok=True)
    policy_path = contracts_dir / "intent_policy_rules.yaml"
    tool_path = contracts_dir / "intent_tool_contracts.yaml"
    policy_path.write_text(yaml.safe_dump(_policy_payload(), sort_keys=False), encoding="utf-8")
    tool_path.write_text(yaml.safe_dump(_tool_contract_payload(), sort_keys=False), encoding="utf-8")

    return PolicyContractEvolutionStore(
        store_dir=tmp_path / "state" / "policy_evolution",
        policy_path=policy_path,
        tool_contract_path=tool_path,
    )


def _sample_envelopes() -> list[dict]:
    return [
        {"lane": "PLAN", "intent": "plan.create_empty_file"},
        {"lane": "PLAN", "intent": "plan.user_action_request"},
        {"lane": "CHAT", "intent": "chat.general"},
    ]


def test_draft_creation_with_metadata_and_invalid_draft_rejection(tmp_path: Path):
    store = _store(tmp_path)
    payload = _policy_payload()
    payload["rules"]["PLAN::plan.create_empty_file"]["allowed"] = False

    draft = store.create_draft(
        kind=KIND_POLICY,
        author="alice",
        change_summary="Tighten create_empty_file policy",
        payload=payload,
        modifications={"changed_rules": ["PLAN::plan.create_empty_file"]},
    )
    assert draft["draft_id"].startswith("policy-d")
    assert draft["author"] == "alice"
    assert draft["change_summary"] == "Tighten create_empty_file policy"
    assert draft["status"] == "pending"
    assert draft["modifications"]["changed_rules"] == ["PLAN::plan.create_empty_file"]

    with pytest.raises(ValueError, match="rules object"):
        store.create_draft(
            kind=KIND_POLICY,
            author="alice",
            change_summary="invalid",
            payload={"not_rules": {}},
        )

    with pytest.raises(ValueError, match="Duplicate intent mapping"):
        invalid_contracts = _tool_contract_payload()
        invalid_contracts["contracts"].append(
            {
                "tool_name": "stub.actions.duplicate",
                "intent": "plan.user_action_request",
                "description": "duplicate",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
                "risk_level": "medium",
                "side_effects": True,
            }
        )
        store.create_draft(
            kind=KIND_TOOL_CONTRACT,
            author="alice",
            change_summary="invalid duplicate intent",
            payload=invalid_contracts,
        )


def test_draft_review_approve_and_reject_workflow(tmp_path: Path):
    store = _store(tmp_path)

    draft_a = store.create_draft(
        kind=KIND_POLICY,
        author="alice",
        change_summary="policy draft a",
        payload=_policy_payload(),
    )
    approved = store.review_draft(
        kind=KIND_POLICY,
        draft_id=draft_a["draft_id"],
        reviewer="bob",
        decision="approve",
        review_notes="Looks good",
    )
    assert approved["status"] == "approved"
    assert approved["reviewer"] == "bob"
    assert approved["review_notes"] == "Looks good"

    draft_b = store.create_draft(
        kind=KIND_POLICY,
        author="alice",
        change_summary="policy draft b",
        payload=_policy_payload(),
    )
    rejected = store.review_draft(
        kind=KIND_POLICY,
        draft_id=draft_b["draft_id"],
        reviewer="carol",
        decision="reject",
        review_notes="Insufficient justification",
    )
    assert rejected["status"] == "rejected"
    assert rejected["reviewer"] == "carol"

    pending_draft = store.create_draft(
        kind=KIND_POLICY,
        author="alice",
        change_summary="policy pending",
        payload=_policy_payload(),
    )
    with pytest.raises(ValueError, match="approved drafts"):
        store.activate_approved_draft(
            kind=KIND_POLICY,
            draft_id=pending_draft["draft_id"],
            author="alice",
        )


def test_simulation_reports_policy_and_contract_divergences(tmp_path: Path):
    store = _store(tmp_path)
    envelopes = _sample_envelopes()

    updated_policy = _policy_payload()
    updated_policy["rules"]["PLAN::plan.create_empty_file"]["allowed"] = False
    policy_draft = store.create_draft(
        kind=KIND_POLICY,
        author="alice",
        change_summary="deny create_empty_file",
        payload=updated_policy,
    )
    policy_sim = store.simulate_draft(kind=KIND_POLICY, draft_id=policy_draft["draft_id"], envelopes=envelopes)
    assert policy_sim["advisory_only"] is True
    assert policy_sim["divergence_count"] == 1
    assert policy_sim["divergences"][0]["intent"] == "plan.create_empty_file"
    assert policy_sim["divergences"][0]["before"]["allowed"] is True
    assert policy_sim["divergences"][0]["after"]["allowed"] is False

    updated_contracts = _tool_contract_payload()
    updated_contracts["contracts"][1]["tool_name"] = "stub.actions.alt_plan_request"
    tool_draft = store.create_draft(
        kind=KIND_TOOL_CONTRACT,
        author="alice",
        change_summary="swap plan.user_action_request tool",
        payload=updated_contracts,
    )
    tool_sim = store.simulate_draft(kind=KIND_TOOL_CONTRACT, draft_id=tool_draft["draft_id"], envelopes=envelopes)
    assert tool_sim["advisory_only"] is True
    assert tool_sim["divergence_count"] == 1
    assert tool_sim["divergences"][0]["intent"] == "plan.user_action_request"
    assert tool_sim["divergences"][0]["before_tool_name"] == "stub.actions.generic_plan_request"
    assert tool_sim["divergences"][0]["after_tool_name"] == "stub.actions.alt_plan_request"


def test_version_listing_and_diff_after_approved_activation(tmp_path: Path):
    store = _store(tmp_path)
    before = store.list_versions(KIND_POLICY)
    assert len(before) == 1
    assert before[0]["version_id"] == "policy-v0001"

    updated = _policy_payload()
    updated["rules"]["PLAN::plan.create_empty_file"]["reason"] = "Changed reason for test."
    draft = store.create_draft(
        kind=KIND_POLICY,
        author="alice",
        change_summary="update reason",
        payload=updated,
    )
    store.review_draft(kind=KIND_POLICY, draft_id=draft["draft_id"], reviewer="bob", decision="approve")
    activated = store.activate_approved_draft(kind=KIND_POLICY, draft_id=draft["draft_id"], author="bob")
    assert activated["metadata"]["version_id"] == "policy-v0002"
    assert activated["source_draft_id"] == draft["draft_id"]

    versions = store.list_versions(KIND_POLICY)
    assert [item["version_id"] for item in versions] == ["policy-v0001", "policy-v0002"]
    diff = store.diff_versions(kind=KIND_POLICY, from_version_id="policy-v0001", to_version_id="policy-v0002")
    assert diff["changed"] is True
    assert any("Changed reason for test." in line for line in diff["diff"])


def test_revert_restores_previous_active_payload(tmp_path: Path):
    store = _store(tmp_path)
    policy_path = tmp_path / "contracts" / "intent_policy_rules.yaml"

    changed = _policy_payload()
    changed["rules"]["PLAN::plan.create_empty_file"]["allowed"] = False
    changed_draft = store.create_draft(
        kind=KIND_POLICY,
        author="alice",
        change_summary="deny create",
        payload=changed,
    )
    store.review_draft(kind=KIND_POLICY, draft_id=changed_draft["draft_id"], reviewer="bob", decision="approve")
    store.activate_approved_draft(kind=KIND_POLICY, draft_id=changed_draft["draft_id"], author="bob")

    active_after_change = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    assert active_after_change["rules"]["PLAN::plan.create_empty_file"]["allowed"] is False

    reverted = store.revert_to_version(
        kind=KIND_POLICY,
        version_id="policy-v0001",
        author="carol",
        change_summary="revert to baseline policy",
    )
    assert reverted["metadata"]["version_id"] == "policy-v0003"

    active_after_revert = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    assert active_after_revert["rules"]["PLAN::plan.create_empty_file"]["allowed"] is True
    versions = store.list_versions(KIND_POLICY)
    assert [item["version_id"] for item in versions] == ["policy-v0001", "policy-v0002", "policy-v0003"]
