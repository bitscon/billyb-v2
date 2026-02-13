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
    interpreter.reset_phase5_state()


def _all_strings(value):
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        out = []
        for item in value.values():
            out.extend(_all_strings(item))
        return out
    if isinstance(value, list):
        out = []
        for item in value:
            out.extend(_all_strings(item))
        return out
    return []


def test_structured_events_logged_across_major_phase_boundaries():
    interpreter.configure_memory_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase13-1"
    try:
        first = interpreter.process_conversational_turn(
            "create an empty text file in your home directory",
            session_id=session_id,
            llm_responder=lambda _u, _e: "unused",
        )
        assert first["governed_result"]["type"] == "approval_required"
        second = interpreter.process_conversational_turn(
            "approve",
            session_id=session_id,
            llm_responder=lambda _u, _e: "unused",
        )
        assert second["governed_result"]["type"] == "executed"

        trace = interpreter.get_observability_trace(session_id)
        assert trace.session_id == session_id
        assert trace.event_count == len(trace.events)
        assert trace.event_count > 0

        event_types = {event.event_type for event in trace.events}
        required = {
            "conversational_turn_started",
            "utterance_received",
            "utterance_interpreted",
            "policy_evaluated",
            "approval_requested",
            "approval_response",
            "tool_invocation_attempt",
            "tool_invocation_result",
            "memory_recorded",
            "conversational_turn_completed",
        }
        assert required.issubset(event_types)
        assert all(event.session_id == session_id for event in trace.events)
        assert all(event.correlation_id for event in trace.events)
        assert all(event.phase for event in trace.events)
        assert all(event.timestamp for event in trace.events)
    finally:
        _teardown()


def test_correlation_ids_link_events_by_turn():
    interpreter.configure_memory_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase13-2"
    try:
        interpreter.process_conversational_turn(
            "tell me a joke",
            session_id=session_id,
            llm_responder=lambda _u, _e: "joke",
        )
        interpreter.process_conversational_turn(
            "qzv blorp",
            session_id=session_id,
            llm_responder=lambda _u, _e: "unused",
        )

        trace = interpreter.get_observability_trace(session_id)
        correlations = {event.correlation_id for event in trace.events}
        assert len(correlations) >= 2
        for correlation in correlations:
            correlated = [event for event in trace.events if event.correlation_id == correlation]
            assert len(correlated) >= 2
            assert all(event.session_id == session_id for event in correlated)
    finally:
        _teardown()


def test_session_replay_report_is_chronological_and_complete():
    interpreter.configure_memory_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase13-3"
    try:
        interpreter.process_conversational_turn(
            "create an empty text file in your home directory",
            session_id=session_id,
            llm_responder=lambda _u, _e: "unused",
        )
        interpreter.process_conversational_turn(
            "approve",
            session_id=session_id,
            llm_responder=lambda _u, _e: "unused",
        )

        trace = interpreter.get_observability_trace(session_id)
        timestamps = [event.timestamp for event in trace.events]
        assert timestamps == sorted(timestamps)
        assert any(event.event_type == "approval_requested" for event in trace.events)
        assert any(event.event_type == "approval_response" for event in trace.events)
        assert any(event.event_type == "tool_invocation_result" for event in trace.events)
    finally:
        _teardown()


def test_metrics_capture_counts_and_latencies_without_behavior_change():
    interpreter.configure_memory_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    try:
        first = interpreter.process_user_message("create an empty text file in your home directory")
        second = interpreter.process_user_message("approve")
        assert first["type"] == "approval_required"
        assert second["type"] == "executed"

        metrics = interpreter.get_observability_metrics()
        assert metrics.counters.get("interpreter_calls", 0) >= 2
        assert metrics.counters.get("policy_decisions", 0) >= 1
        assert metrics.counters.get("execution_attempts", 0) >= 1
        assert metrics.counters.get("plan_building_calls", 0) >= 0

        interpreter_latency = metrics.latencies_ms.get("interpreter_call_latency_ms")
        execution_latency = metrics.latencies_ms.get("execution_attempt_latency_ms")
        assert interpreter_latency is not None
        assert execution_latency is not None
        assert interpreter_latency["count"] >= 2
        assert execution_latency["count"] >= 1
        assert interpreter_latency["avg_ms"] >= 0.0
        assert execution_latency["avg_ms"] >= 0.0
    finally:
        _teardown()


def test_sensitive_user_content_is_masked_in_telemetry():
    interpreter.configure_memory_store("in_memory")
    interpreter.reset_phase5_state()
    _set_flags(phase3=False, phase4=True, phase4_explain=False, phase5=True, phase8=False)
    session_id = "sess-phase13-4"
    secret = "super-secret-phrase-123"
    try:
        interpreter.process_conversational_turn(
            f"tell me a joke about {secret}",
            session_id=session_id,
            llm_responder=lambda _u, _e: f"echo {secret}",
        )
        trace = interpreter.get_observability_trace(session_id)
        assert trace.event_count > 0

        all_values = []
        for event in trace.events:
            all_values.extend(_all_strings(event.metadata))

        assert not any(secret in value for value in all_values)
        assert any(value.startswith("<masked:len=") for value in all_values)
    finally:
        _teardown()
