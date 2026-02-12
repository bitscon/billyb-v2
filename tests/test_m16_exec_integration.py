import pytest

import v2.core.runtime as runtime_mod


@pytest.mark.parametrize(
    "user_input, expected_fragment",
    [
        ("/exec rm /home/billyb/workspaces/billyb-v2/tmp_m16.txt", "legacy interaction '/exec'"),
        ("/exec git push", "legacy interaction '/exec'"),
        ("APPROVE exec-20260212-001", "legacy approval command"),
        ("GRANT_CAPABILITY\nname: git.push\nscope: default", "legacy capability-grant command"),
        ("/revoke_autonomy git.push", "legacy interaction '/revoke_autonomy'"),
    ],
)
def test_legacy_execution_pathways_are_hard_rejected(user_input: str, expected_fragment: str):
    result = runtime_mod.run_turn(user_input, {"trace_id": "trace-m16-legacy"})

    assert result["status"] == "error"
    assert expected_fragment in result["final_output"]
