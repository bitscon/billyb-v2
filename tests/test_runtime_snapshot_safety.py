import v2.core.runtime as runtime_mod


def test_render_introspection_snapshot_handles_none():
    rendered = runtime_mod._render_introspection_snapshot(None, "task-1")

    assert "INTROSPECTION:" in rendered
    assert "services checked: 0" in rendered
    assert "containers checked: 0" in rendered
    assert "listening sockets: 0" in rendered
    assert "paths checked: 0" in rendered
