from pathlib import Path

import v2.core.runtime as runtime_mod
import v2.core.task_graph as tg
import v2.core.evidence as evidence
import v2.core.capability_contracts as ccr
import v2.core.plans_hamp as plans


def _setup_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(tg, "TASK_GRAPH_DIR", tmp_path / "task_graph")
    tg.TASK_GRAPH_DIR.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(evidence, "EVIDENCE_DIR", tmp_path / "evidence")
    evidence.EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(ccr, "CAPABILITY_DIR", tmp_path / "capabilities")
    ccr.CAPABILITY_DIR.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(plans, "PLANS_DIR", tmp_path / "plans")
    plans.PLANS_DIR.mkdir(parents=True, exist_ok=True)
    tg._GRAPHS.clear()
    tg._CURRENT_TRACE_ID = None
    evidence._CURRENT_TRACE_ID = None


def _write_contract(dir_path: Path, capability: str, ops_required: bool, evidence_list: list[str]):
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / f"{capability}.yaml").write_text(
        "\n".join(
            [
                f"capability: {capability}",
                "risk_level: high",
                "requires:",
                f"  ops_required: {'true' if ops_required else 'false'}",
                f"  evidence: {evidence_list}",
                "guarantees:",
                "  - journal_entry_created",
            ]
        ),
        encoding="utf-8",
    )


def test_plan_cannot_be_created_for_blocked_task(tmp_path, monkeypatch):
    _setup_dirs(tmp_path, monkeypatch)
    tg.load_graph("trace-1")
    task_id = tg.create_task("claim:blocked")
    tg.block_task(task_id, "blocked for test")
    tg.save_graph("trace-1")
    response = runtime_mod.run_turn("plan", {"trace_id": "trace-1"})
    assert "PLAN PROPOSAL" not in response["final_output"]
    assert plans.list_plans() == []


def test_plan_cannot_be_created_if_failure_mode_exists(tmp_path, monkeypatch):
    _setup_dirs(tmp_path, monkeypatch)
    tg.load_graph("trace-1")
    task_id = tg.create_task("claim:nginx running")
    tg.update_status(task_id, "ready")
    tg.save_graph("trace-1")
    response = runtime_mod.run_turn("plan", {"trace_id": "trace-1"})
    assert "REFUSAL" in response["final_output"]
    assert plans.list_plans() == []


def test_plan_cannot_be_auto_approved(tmp_path, monkeypatch):
    _setup_dirs(tmp_path, monkeypatch)
    _write_contract(ccr.CAPABILITY_DIR, "filesystem.write", False, [])
    tg.load_graph("trace-1")
    task_id = tg.create_task("/exec touch /tmp/m24.txt")
    tg.update_status(task_id, "ready")
    tg.save_graph("trace-1")
    response = runtime_mod.run_turn("plan", {"trace_id": "trace-1"})
    output = response["final_output"]
    assert "PLAN PROPOSAL" in output
    plan_id = output.split("plan_id:", 1)[1].splitlines()[0].strip()
    plan = plans.get_plan(plan_id)
    assert plan.approved is False


def test_approved_plan_is_immutable(tmp_path, monkeypatch):
    _setup_dirs(tmp_path, monkeypatch)
    _write_contract(ccr.CAPABILITY_DIR, "filesystem.write", False, [])
    tg.load_graph("trace-1")
    task_id = tg.create_task("/exec touch /tmp/m24.txt")
    tg.update_status(task_id, "ready")
    tg.save_graph("trace-1")
    proposal = runtime_mod.run_turn("plan", {"trace_id": "trace-1"})
    plan_id = proposal["final_output"].split("plan_id:", 1)[1].splitlines()[0].strip()
    runtime_mod.run_turn(f"APPROVE PLAN {plan_id}", {"trace_id": "trace-1"})
    response = runtime_mod.run_turn("plan", {"trace_id": "trace-1"})
    assert "PLAN PROPOSAL" not in response["final_output"]


def test_steps_cannot_be_skipped_or_reordered(tmp_path, monkeypatch):
    _setup_dirs(tmp_path, monkeypatch)
    _write_contract(ccr.CAPABILITY_DIR, "filesystem.write", False, [])
    tg.load_graph("trace-1")
    task_id = tg.create_task("/exec touch /tmp/m24a.txt")
    tg.update_status(task_id, "ready")
    tg.save_graph("trace-1")
    step1 = plans.PlanStep(
        step_id="s1",
        description="/exec touch /tmp/m24a.txt",
        required_evidence=[],
        required_capability="filesystem.write",
        ops_required=False,
        failure_modes=[],
    )
    step2 = plans.PlanStep(
        step_id="s2",
        description="/exec touch /tmp/m24b.txt",
        required_evidence=[],
        required_capability="filesystem.write",
        ops_required=False,
        failure_modes=[],
    )
    plan = plans.create_plan(task_id, [step1, step2])
    plans.approve_plan(plan.plan_id)
    response = runtime_mod.run_turn("ignored", {"trace_id": "trace-1"})
    assert "step_id: s1" in response["final_output"]


def test_failure_mode_blocks_step_after_approval(tmp_path, monkeypatch):
    _setup_dirs(tmp_path, monkeypatch)
    tg.load_graph("trace-1")
    task_id = tg.create_task("claim:nginx running")
    tg.update_status(task_id, "ready")
    tg.save_graph("trace-1")
    step = plans.PlanStep(
        step_id="s1",
        description="claim:nginx running",
        required_evidence=["nginx running"],
        required_capability="",
        ops_required=False,
        failure_modes=[],
    )
    plan = plans.create_plan(task_id, [step])
    plans.approve_plan(plan.plan_id)
    response = runtime_mod.run_turn("ignored", {"trace_id": "trace-1"})
    assert "REFUSAL" in response["final_output"]


def test_ops_required_per_step(tmp_path, monkeypatch):
    _setup_dirs(tmp_path, monkeypatch)
    _write_contract(ccr.CAPABILITY_DIR, "restart_service", True, [])
    tg.load_graph("trace-1")
    task_id = tg.create_task("/ops restart nginx")
    tg.update_status(task_id, "ready")
    tg.save_graph("trace-1")
    proposal = runtime_mod.run_turn("plan", {"trace_id": "trace-1"})
    plan_id = proposal["final_output"].split("plan_id:", 1)[1].splitlines()[0].strip()
    response = runtime_mod.run_turn(f"APPROVE PLAN {plan_id}", {"trace_id": "trace-1"})
    assert "NEXT STEP: /ops restart nginx" in response["final_output"]


def test_new_plan_id_required_after_change(tmp_path, monkeypatch):
    _setup_dirs(tmp_path, monkeypatch)
    _write_contract(ccr.CAPABILITY_DIR, "filesystem.write", False, [])
    tg.load_graph("trace-1")
    task_id = tg.create_task("/exec touch /tmp/m24.txt")
    tg.update_status(task_id, "ready")
    tg.save_graph("trace-1")
    proposal = runtime_mod.run_turn("plan", {"trace_id": "trace-1"})
    plan_id = proposal["final_output"].split("plan_id:", 1)[1].splitlines()[0].strip()
    plans.approve_plan(plan_id)
    response = runtime_mod.run_turn("plan", {"trace_id": "trace-1"})
    assert "PLAN PROPOSAL" not in response["final_output"]
