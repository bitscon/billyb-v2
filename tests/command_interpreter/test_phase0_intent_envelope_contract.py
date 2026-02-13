import importlib
import json
from pathlib import Path

import jsonschema
import pytest


FIXTURES_DIR = Path("tests/command_interpreter/fixtures")
SCHEMA_PATH = Path("schemas/intent_envelope.schema.json")


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _fixture_paths() -> list[Path]:
    return sorted(FIXTURES_DIR.glob("*.json"))


def _load_fixture(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_interpreter_callable():
    try:
        module = importlib.import_module("v2.core.command_interpreter")
    except ModuleNotFoundError:
        pytest.fail(
            "Phase 1 implementation missing: create v2.core.command_interpreter with an interpreter callable."
        )

    func = getattr(module, "interpret_utterance", None)
    if not callable(func):
        pytest.fail(
            "Phase 1 implementation missing: v2.core.command_interpreter.interpret_utterance is required."
        )
    return func


def test_schema_is_valid_json_schema():
    schema = _load_schema()
    jsonschema.Draft202012Validator.check_schema(schema)


def test_fixtures_exist():
    assert _fixture_paths(), "Expected at least one fixture in tests/command_interpreter/fixtures/."


@pytest.mark.parametrize("fixture_path", _fixture_paths(), ids=lambda p: p.stem)
def test_expected_envelope_in_fixture_validates_against_schema(fixture_path: Path):
    schema = _load_schema()
    payload = _load_fixture(fixture_path)
    assert "input" in payload and isinstance(payload["input"], str) and payload["input"].strip()
    assert "expected_envelope" in payload and isinstance(payload["expected_envelope"], dict)
    jsonschema.validate(payload["expected_envelope"], schema)


@pytest.mark.parametrize("fixture_path", _fixture_paths(), ids=lambda p: p.stem)
def test_interpreter_matches_golden_fixture(fixture_path: Path):
    payload = _load_fixture(fixture_path)
    interpret_utterance = _load_interpreter_callable()
    actual = interpret_utterance(payload["input"])
    assert actual == payload["expected_envelope"]


@pytest.mark.parametrize(
    "fixture_name",
    [
        "chat_cool_thing_to_drink.json",
        "broken_transcript_where_are_you.json",
    ],
)
def test_benign_inputs_are_not_rejected(fixture_name: str):
    payload = _load_fixture(FIXTURES_DIR / fixture_name)
    interpret_utterance = _load_interpreter_callable()
    actual = interpret_utterance(payload["input"])

    assert actual["lane"] != "REJECT"
    assert actual["policy"]["allowed"] is True


@pytest.mark.parametrize("fixture_path", _fixture_paths(), ids=lambda p: p.stem)
def test_interpreter_output_contains_required_top_level_fields(fixture_path: Path):
    required_fields = {
        "utterance",
        "lane",
        "intent",
        "entities",
        "confidence",
        "requires_approval",
        "policy",
        "next_prompt",
    }
    payload = _load_fixture(fixture_path)
    interpret_utterance = _load_interpreter_callable()
    actual = interpret_utterance(payload["input"])

    assert required_fields.issubset(actual.keys())
