import v2.core.command_interpreter as interpreter


def _set_flags(*, phase3: bool, phase4: bool, phase4_explain: bool, phase5: bool, phase8: bool) -> None:
    interpreter.set_phase3_enabled(phase3)
    interpreter.set_phase4_enabled(phase4)
    interpreter.set_phase4_explanation_enabled(phase4_explain)
    interpreter.set_phase5_enabled(phase5)
    interpreter.set_phase8_enabled(phase8)
    interpreter.set_phase8_approval_mode("step")


def _teardown() -> None:
    _set_flags(phase3=False, phase4=False, phase4_explain=False, phase5=False, phase8=False)
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()


def test_capture_llm_response_explicitly():
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase16-capture"
    try:
        first = interpreter.process_conversational_turn(
            "tell me a joke",
            session_id=session_id,
            llm_responder=lambda _u, _e: "A deterministic joke.",
        )
        assert first["response"] == "A deterministic joke."

        captured = interpreter.process_conversational_turn(
            "capture this",
            session_id=session_id,
            llm_responder=lambda _u, _e: "unused",
        )
        governed = captured["governed_result"]
        assert governed["type"] == "content_captured"
        content_id = governed["captured_content"]["content_id"]

        stored = interpreter.get_captured_content_by_id(content_id)
        assert stored is not None
        assert stored["text"] == "A deterministic joke."
        assert stored["source"] == "llm"
        assert stored["origin_turn_id"] == first["correlation_id"]
    finally:
        _teardown()


def test_ambiguous_capture_attempt_is_rejected():
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase16-ambiguous"
    try:
        response = interpreter.process_conversational_turn(
            "capture",
            session_id=session_id,
            llm_responder=lambda _u, _e: "unused",
        )
        governed = response["governed_result"]
        assert governed["type"] == "capture_rejected"
        assert "ambiguous capture request" in governed["message"].lower()
    finally:
        _teardown()


def test_captured_content_can_be_referenced_in_write_intent():
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase16-reference"
    try:
        interpreter.process_conversational_turn(
            "tell me a joke",
            session_id=session_id,
            llm_responder=lambda _u, _e: "Captured joke text.",
        )
        interpreter.process_conversational_turn(
            "remember the last response as joke",
            session_id=session_id,
            llm_responder=lambda _u, _e: "unused",
        )

        request = interpreter.process_user_message("save that joke in a text file in your home directory")
        assert request["type"] == "approval_required"
        entities = request["envelope"]["entities"]
        captured_entities = [entity for entity in entities if entity.get("name") == "captured_content"]
        assert len(captured_entities) == 1
        assert captured_entities[0]["label"] == "joke"
        assert captured_entities[0]["text"] == "Captured joke text."
    finally:
        _teardown()


def test_multiple_captures_with_same_label_are_disambiguated():
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase16-disambiguation"
    try:
        interpreter.process_conversational_turn(
            "tell me a joke",
            session_id=session_id,
            llm_responder=lambda _u, _e: "First text.",
        )
        interpreter.process_conversational_turn(
            "capture this with label note",
            session_id=session_id,
            llm_responder=lambda _u, _e: "unused",
        )
        interpreter.process_conversational_turn(
            "tell me another joke",
            session_id=session_id,
            llm_responder=lambda _u, _e: "Second text.",
        )
        interpreter.process_conversational_turn(
            "store this content with label note",
            session_id=session_id,
            llm_responder=lambda _u, _e: "unused",
        )

        response = interpreter.process_user_message("save that note in a text file in your home directory")
        assert response["type"] == "capture_reference_rejected"
        assert "ambiguous" in response["message"].lower()
    finally:
        _teardown()


def test_capture_metadata_is_stored_and_retrievable():
    interpreter.configure_memory_store("in_memory")
    interpreter.configure_capture_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase16-metadata"
    try:
        turn = interpreter.process_conversational_turn(
            "tell me a joke",
            session_id=session_id,
            llm_responder=lambda _u, _e: "Metadata text.",
        )
        interpreter.process_conversational_turn(
            "remember the last response as meta",
            session_id=session_id,
            llm_responder=lambda _u, _e: "unused",
        )

        items = interpreter.get_captured_content_last(1)
        assert len(items) == 1
        item = items[0]
        assert item["content_id"].startswith("cc-")
        assert item["type"] == "text"
        assert item["source"] == "llm"
        assert item["text"] == "Metadata text."
        assert item["label"] == "meta"
        assert item["session_id"] == session_id
        assert item["origin_turn_id"] == turn["correlation_id"]

        by_label = interpreter.get_captured_content_by_label("meta")
        assert len(by_label) == 1
        assert by_label[0]["content_id"] == item["content_id"]
    finally:
        _teardown()
