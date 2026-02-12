import v2.core.runtime as runtime_mod


def test_barn_inspection_query_returns_structured_resolution():
    response = runtime_mod.run_turn("Where is my CMDB?", {})
    payload = response.get("final_output")

    assert response["status"] == "success"
    assert isinstance(payload, dict)
    assert "message" in payload
    assert "inspection" in payload["message"].lower()


def test_barn_inspection_action_no_longer_suggests_legacy_ops_route():
    response = runtime_mod.run_turn("restart nginx", {})
    output = (response.get("final_output") or "").lower()
    assert response["status"] == "success"
    assert "/ops " not in output
