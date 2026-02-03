import os
import shutil
import json
from pathlib import Path
import subprocess
import time

def setup_tree(root: Path, version="v1.2.3"):
    live = root / "v2" / "agent_zero"
    billy = live / ".billy"
    art = billy / "artifacts" / version / "agent_zero"

    (live / "python").mkdir(parents=True, exist_ok=True)
    (billy / "promotion").mkdir(parents=True, exist_ok=True)
    (billy / "artifacts" / version / "agent_zero").mkdir(parents=True, exist_ok=True)

    (live / "LIVE_MARKER").write_text("live\n")
    (art / "ARTIFACT_MARKER").write_text("artifact\n")

    (billy / "state.json").write_text(json.dumps({
        "current_state": "PROMOTING",
        "active_operation": {"type": "upgrade", "target_version": version},
        "last_failure": None
    }))

    return live, billy, art

import sys
sys.path.append(str(Path(__file__).parent.parent.parent.parent.parent))

def run_promote(root: Path, version="v1.2.3"):
    from v2.agent_zero.commands import promote_command
    return promote_command(version)

def test_promotion_success(tmp_path: Path):
    live, billy, art = setup_tree(tmp_path)
    res = run_promote(tmp_path)
    assert res["status"] == "success"
    assert (tmp_path / "v2" / "agent_zero" / "ARTIFACT_MARKER").exists()
    assert (tmp_path / "v2" / "agent_zero.prev" / "LIVE_MARKER").exists()
    report = json.loads((billy / "promotion" / "latest_report.json").read_text())
    assert report["status"] == "PROMOTED"

def test_swap_failure_autorollback(tmp_path: Path):
    live, billy, art = setup_tree(tmp_path)
    shutil.rmtree(tmp_path / "v2" / "agent_zero")
    (tmp_path / "v2" / "agent_zero").write_text("BLOCK")
    res = run_promote(tmp_path)
    assert res["status"] != "success"
    state = json.loads((billy / "state.json").read_text())
    assert state["current_state"] == "FAILED"

def test_smoke_failure_no_auto_rollback(tmp_path: Path):
    live, billy, art = setup_tree(tmp_path)
    (art / "prompts").mkdir(parents=True, exist_ok=True)
    res = run_promote(tmp_path)
    assert res["status"] != "success"
    assert (tmp_path / "v2" / "agent_zero" / "ARTIFACT_MARKER").exists()
    state = json.loads((billy / "state.json").read_text())
    assert state["current_state"] == "FAILED"
