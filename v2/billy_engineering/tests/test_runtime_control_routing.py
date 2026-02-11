from pathlib import Path


def test_control_routing_plan_prefix_is_precise():
    runtime_source = Path("v2/core/runtime.py").read_text(encoding="utf-8")

    assert 'or normalized.lower() == "plan"' in runtime_source
    assert 'or normalized.lower().startswith("plan ")' in runtime_source
    assert 'or normalized.lower().startswith("plan")' not in runtime_source
