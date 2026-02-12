import json
from pathlib import Path
import v2.core.runtime as runtime_mod
from v2.core.runtime import run_turn

def test_happy_path_execution(tmp_path, monkeypatch):
    # isolate var directories
    base = tmp_path / "var"
    monkeypatch.chdir(tmp_path)

    # run hello tool
    result = run_turn(user_input="run hello", session_context={})

    assert result["status"] == "success"
    assert result["tool_calls"]
    assert "artifact" in result["tool_calls"][0]

    artifact_path = Path(result["tool_calls"][0]["artifact"])
    assert artifact_path.exists()

def test_memory_write_and_read(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    write = run_turn(user_input="remember: test memory", session_context={})
    assert write["status"] == "success"

    read = run_turn(user_input="recall", session_context={})
    assert "test memory" in read["final_output"]

def test_trace_emitted(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = run_turn(user_input="run hello", session_context={})
    trace_id = result["trace_id"]

    trace_dir = Path(runtime_mod._trace_sink.base_dir)
    trace_file = trace_dir / f"{trace_id}.jsonl"

    assert trace_file.exists()

    lines = trace_file.read_text().splitlines()
    events = [json.loads(l) for l in lines]

    assert any(e["event_type"] == "tool_run_start" for e in events)
    assert any(e["event_type"] == "tool_run_end" for e in events)
