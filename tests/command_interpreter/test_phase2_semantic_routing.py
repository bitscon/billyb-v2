import v2.core.command_interpreter as interpreter


def test_semantic_routing_success_for_help_lane():
    utterance = "help me understand billy configuration"
    phase1 = interpreter._interpret_phase1(utterance)
    lane, confidence = interpreter._semantic_lane_router.route_lane(utterance)
    actual = interpreter.interpret_utterance(utterance)

    assert lane == "HELP"
    assert confidence >= interpreter._SEMANTIC_CONFIDENCE_THRESHOLD
    assert phase1["lane"] != "HELP"
    assert actual["lane"] == "HELP"


def test_low_confidence_routes_to_phase1_fallback():
    utterance = "zxqv 9911"
    phase1 = interpreter._interpret_phase1(utterance)
    lane, confidence = interpreter._semantic_lane_router.route_lane(utterance)
    actual = interpreter.interpret_utterance(utterance)

    assert lane == "CLARIFY"
    assert confidence < interpreter._SEMANTIC_CONFIDENCE_THRESHOLD
    assert actual == phase1


def test_phase1_output_is_unchanged_when_fallback_is_used():
    utterance = "qzv blorp"
    phase1 = interpreter._interpret_phase1(utterance)
    _lane, confidence = interpreter._semantic_lane_router.route_lane(utterance)
    actual = interpreter.interpret_utterance(utterance)

    assert confidence < interpreter._SEMANTIC_CONFIDENCE_THRESHOLD
    assert actual == phase1
