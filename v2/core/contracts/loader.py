import yaml
from jsonschema import validate, ValidationError
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]
CONTRACTS_DIR = BASE_DIR / "docs" / "contracts" / "schemas"


class ContractViolation(Exception):
    pass


def load_schema(name: str) -> dict:
    schema_path = CONTRACTS_DIR / name
    if not schema_path.exists():
        raise ContractViolation(f"Missing required contract schema: {schema_path}")

    with open(schema_path, "r") as f:
        return yaml.safe_load(f)


def validate_tool_spec(tool_spec: dict) -> None:
    schema = load_schema("tool-spec.schema.yaml")
    try:
        validate(instance=tool_spec, schema=schema)
    except ValidationError as e:
        raise ContractViolation(f"ToolSpec validation failed: {e.message}")


def validate_trace_event(event: dict) -> None:
    schema = load_schema("trace-event.schema.yaml")
    try:
        validate(instance=event, schema=schema)
    except ValidationError as e:
        raise ContractViolation(f"TraceEvent validation failed: {e.message}")
