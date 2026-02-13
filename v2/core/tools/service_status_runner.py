"""
Frozen inert implementation artifact for tool.service.status.v1.

This module is intentionally not wired into runtime execution paths.
Execution remains disabled by design.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Dict, List, Literal, Optional, Protocol, Sequence, Tuple, Union


# Approved input schema (from "DRAFT — Tool Definition: service.status (with clarification)").
SERVICE_STATUS_INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "service.status input",
    "type": "object",
    "additionalProperties": False,
    "required": ["service_name"],
    "properties": {
        "service_name": {
            "type": "string",
            "minLength": 1,
            "maxLength": 128,
            "pattern": r"^[A-Za-z0-9_.@:-]+$",
            "description": (
                "Service unit identifier. Non-empty. "
                "Must not contain shell metacharacters or whitespace."
            ),
        }
    },
}


AllowedActiveState = Literal[
    "active",
    "inactive",
    "failed",
    "activating",
    "deactivating",
    "unknown",
]
ErrorCode = Literal[
    "service_not_found",
    "permission_denied",
    "execution_not_authorized",
]
AuditEventName = Literal[
    "invocation_attempted",
    "invocation_blocked",
    "invocation_succeeded",
]


@dataclass(frozen=True)
class NormalizedServiceRequest:
    service_name_input: str
    service_name_canonical: str


@dataclass(frozen=True)
class SuccessResult:
    service_name: str
    active_state: AllowedActiveState
    sub_state: str
    uptime: str
    message: str


@dataclass(frozen=True)
class ErrorResult:
    service_name: str
    error_code: ErrorCode
    message: str


@dataclass(frozen=True)
class DraftAuditEvent:
    event: AuditEventName
    tool_id: str
    service_name_canonical: str
    details: str


ToolResult = Union[SuccessResult, ErrorResult]


class ServiceStatusAdapter(Protocol):
    """
    Adapter contract for read-only service inspection runners.

    Responsibilities are intentionally separated:
    1) input validation
    2) normalization
    3) execution
    4) result mapping
    """

    def validate_input(self, payload: Dict[str, Any]) -> List[str]:
        ...

    def normalize_input(self, payload: Dict[str, Any]) -> NormalizedServiceRequest:
        ...

    def execute(self, request: NormalizedServiceRequest) -> Dict[str, Any]:
        ...

    def map_result(self, request: NormalizedServiceRequest, raw_result: Dict[str, Any]) -> ToolResult:
        ...


class ServiceStatusRunner:
    """
    Frozen inert implementation for tool.service.status.v1.

    This class is non-executable by design: execution always returns
    execution_not_authorized and never touches host OS state.
    """

    tool_id = "tool.service.status.v1"
    domain = "os_admin"
    risk_level = "read-only"
    host_scope = "barn_only"
    maturity_level_required = "global_level_4"

    _service_pattern = re.compile(str(SERVICE_STATUS_INPUT_SCHEMA["properties"]["service_name"]["pattern"]))

    def validate_input(self, payload: Dict[str, Any]) -> List[str]:
        """
        Validate payload strictly against approved JSON schema fields.
        """
        errors: List[str] = []
        schema = SERVICE_STATUS_INPUT_SCHEMA

        if not isinstance(payload, dict):
            return ["payload must be an object"]

        required = schema.get("required", [])
        for field in required:
            if field not in payload:
                errors.append(f"missing required field: {field}")

        if schema.get("additionalProperties") is False:
            for key in payload.keys():
                if key not in schema["properties"]:
                    errors.append(f"unexpected field: {key}")

        value = payload.get("service_name")
        props = schema["properties"]["service_name"]
        if not isinstance(value, str):
            errors.append("service_name must be a string")
            return errors

        if len(value) < int(props["minLength"]):
            errors.append("service_name must be non-empty")
        if len(value) > int(props["maxLength"]):
            errors.append("service_name exceeds maximum length")
        if not self._service_pattern.fullmatch(value):
            errors.append("service_name contains invalid characters")

        return errors

    def normalize_input(self, payload: Dict[str, Any]) -> NormalizedServiceRequest:
        """
        Normalization policy (approved):
        - append `.service` when missing
        - preserve canonical normalized value for audit output
        """
        service_name_input = str(payload["service_name"]).strip()
        if service_name_input.endswith(".service"):
            canonical = service_name_input
        else:
            canonical = f"{service_name_input}.service"
        return NormalizedServiceRequest(
            service_name_input=service_name_input,
            service_name_canonical=canonical,
        )

    def execute(self, request: NormalizedServiceRequest) -> Dict[str, Any]:
        """
        DISABLED EXECUTION STUB.

        Guard: execution authorization is checked before any OS interaction.
        Guard: read-only enforcement is explicit.
        Guard: no shell access.
        Guard: no pipes, redirects, globbing, chaining, or inline commands.

        This implementation intentionally never calls systemd, subprocess, or host OS APIs.
        """
        return {
            "status": "blocked",
            "error_code": "execution_not_authorized",
            "service_name": request.service_name_canonical,
            "message": "Execution is disabled for tool.service.status.v1 in this implementation.",
        }

    def map_result(self, request: NormalizedServiceRequest, raw_result: Dict[str, Any]) -> ToolResult:
        """
        Map internal raw results into public tool result structures.
        """
        error_code = str(raw_result.get("error_code", "")).strip()
        message = str(raw_result.get("message", "")).strip()
        service_name = str(raw_result.get("service_name", request.service_name_canonical)).strip()

        if error_code == "service_not_found":
            return ErrorResult(
                service_name=service_name,
                error_code="service_not_found",
                message=message or "Service unit was not found.",
            )
        if error_code == "permission_denied":
            return ErrorResult(
                service_name=service_name,
                error_code="permission_denied",
                message=message or "Permission denied for service inspection.",
            )
        if error_code == "execution_not_authorized":
            return ErrorResult(
                service_name=service_name,
                error_code="execution_not_authorized",
                message=message or "Execution is not authorized.",
            )

        if raw_result.get("status") == "success":
            return SuccessResult(
                service_name=service_name,
                active_state=str(raw_result.get("active_state", "unknown")),
                sub_state=str(raw_result.get("sub_state", "unknown")),
                uptime=str(raw_result.get("uptime", "unknown")),
                message=message or "Service status resolved.",
            )

        return ErrorResult(
            service_name=service_name,
            error_code="execution_not_authorized",
            message=message or "Execution is not authorized.",
        )

    def build_audit_events(
        self,
        request: NormalizedServiceRequest,
        result: ToolResult,
    ) -> List[DraftAuditEvent]:
        """
        Draft audit hooks:
        - invocation_attempted
        - invocation_blocked (execution_not_authorized)
        - invocation_succeeded (defined, but not reachable with execution disabled)
        """
        events = [
            DraftAuditEvent(
                event="invocation_attempted",
                tool_id=self.tool_id,
                service_name_canonical=request.service_name_canonical,
                details="Attempt recorded.",
            )
        ]
        if isinstance(result, ErrorResult) and result.error_code == "execution_not_authorized":
            events.append(
                DraftAuditEvent(
                    event="invocation_blocked",
                    tool_id=self.tool_id,
                    service_name_canonical=request.service_name_canonical,
                    details="Blocked: execution_not_authorized.",
                )
            )
            return events

        # Unreachable while execution is disabled.
        events.append(
            DraftAuditEvent(
                event="invocation_succeeded",
                tool_id=self.tool_id,
                service_name_canonical=request.service_name_canonical,
                details="Succeeded (not reachable while execution is disabled).",
            )
        )
        return events

    def invoke_inert(
        self, payload: Dict[str, Any]
    ) -> Tuple[Optional[ToolResult], List[str], Sequence[DraftAuditEvent]]:
        """
        Inert orchestration path:
        - validate input
        - normalize input
        - run disabled execution stub
        - map result
        - build audit hooks
        """
        validation_errors = self.validate_input(payload)
        if validation_errors:
            return None, validation_errors, []

        normalized = self.normalize_input(payload)
        raw_result = self.execute(normalized)
        mapped = self.map_result(normalized, raw_result)
        audit_events = self.build_audit_events(normalized, mapped)
        return mapped, [], audit_events


TEST_DEFINITIONS_SPEC = [
    {
        "name": "valid_input_blocked_execution",
        "description": (
            "Given {'service_name': 'nginx'} the inert pipeline validates input, "
            "normalizes to 'nginx.service', and returns ErrorResult with "
            "error_code='execution_not_authorized'."
        ),
    },
    {
        "name": "invalid_input_schema_failure",
        "description": (
            "Given invalid payloads (empty service_name, metacharacters, unexpected fields), "
            "validation fails before normalization/execution and returns schema errors."
        ),
    },
    {
        "name": "normalization_correctness",
        "description": (
            "Given 'nginx' -> canonical 'nginx.service'; given 'nginx.service' -> unchanged. "
            "Canonical name is used in mapped errors and audit events."
        ),
    },
    {
        "name": "non_goals",
        "description": (
            "No systemd interaction, no OS calls, and no OS mocks. "
            "Tests are specification-only and non-executable with execution disabled."
        ),
    },
]


IMPLEMENTATION_STATUS = "frozen_non_executable"
