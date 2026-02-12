from v2.core.trace.trace_inspector import TraceInspector
from v2.core.runtime import run_turn

def test_trace_inspector(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = run_turn(user_input="run hello", session_context={})
    trace_id = result["trace_id"]

    inspector = TraceInspector()
    traces = inspector.list_traces()
    assert trace_id in traces

    events = inspector.load(trace_id)
    assert len(events) > 0

    summary = inspector.summarize(trace_id)
    assert summary["trace_id"] == trace_id
    assert "tool_runner" in summary["components"]
