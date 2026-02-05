import v2.core.runtime as runtime_mod


def test_barn_inspection_required(monkeypatch):
    def fake_ask(self, prompt: str) -> str:
        return "I don't see that in the documents."

    monkeypatch.setattr(runtime_mod.BillyRuntime, "ask", fake_ask)

    response = runtime_mod.run_turn("Where is my CMDB?", {})
    output = (response.get("final_output") or "").lower()

    assert "inspecting the barn" in output
    assert "systemd" in output
    assert "docker" in output
    assert "ports" in output
    assert "config" in output


def test_barn_inspection_action_requires_ops():
    response = runtime_mod.run_turn("restart nginx", {})
    output = (response.get("final_output") or "").lower()
    assert "inspecting the barn" in output
    assert "/ops restart nginx" in output
