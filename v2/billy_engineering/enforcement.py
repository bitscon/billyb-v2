from __future__ import annotations

import re
from typing import Callable

from .schemas import validate_plan, validate_verify, validate_artifact
from .state import update_state
from .workspace import create_task_dir, write_artifact

DEPLOYMENT_TRIGGERS = [
    "deploy",
    "release",
    "ship",
    "rollout",
    "production",
]


class EngineeringError(RuntimeError):
    pass


def detect_engineering_intent(prompt: str) -> bool:
    return prompt.strip().lower().startswith("/engineer")


def _detect_deployment_language(prompt: str) -> str | None:
    lowered = prompt.lower()
    for word in DEPLOYMENT_TRIGGERS:
        if re.search(rf"\b{re.escape(word)}\b", lowered):
            return word
    return None


def _build_engineering_system_prompt() -> str:
    return (
        "### PLAN.md\n"
        "Problem Statement:\n"
        "\n"
        "Objectives:\n"
        "\n"
        "Scope:\n"
        "\n"
        "Non-Goals:\n"
        "\n"
        "Constraints:\n"
        "\n"
        "Assumptions:\n"
        "\n"
        "Proposed Approach:\n"
        "\n"
        "\n"
        "### ARTIFACT.md\n"
        "Definitions:\n"
        "\n"
        "Rules:\n"
        "\n"
        "Invariants:\n"
        "\n"
        "Forbidden Behaviors:\n"
        "\n"
        "Failure Conditions:\n"
        "\n"
        "\n"
        "### VERIFY.md\n"
        "What was verified:\n"
        "\n"
        "How it was verified:\n"
        "\n"
        "What was not verified:\n"
        "\n"
        "Pass:\n"
        "\n"
        "Fail:\n"
    )


def _extract_artifacts(text: str) -> tuple[str, str, str]:
    """
    Extracts PLAN.md, ARTIFACT.md, VERIFY.md from plain text.
    Accepts Markdown headers with one or more '#' characters.
    Requires all three to be present and non-empty.
    """

    header_pattern = re.compile(
        r"(?m)^\s*(#+)\s*(PLAN\.md|ARTIFACT\.md|VERIFY\.md)\s*$"
    )

    matches = list(header_pattern.finditer(text))
    if not matches:
        raise EngineeringError("No artifact headers found.")

    sections: dict[str, str] = {}

    for i, match in enumerate(matches):
        name = match.group(2)
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)

        content = text[start:end].strip()
        if not content:
            raise EngineeringError(f"{name} is empty.")

        sections[name] = content

    missing = {"PLAN.md", "ARTIFACT.md", "VERIFY.md"} - sections.keys()
    if missing:
        raise EngineeringError(f"{', '.join(sorted(missing))} is missing.")

    return (
        sections["PLAN.md"],
        sections["ARTIFACT.md"],
        sections["VERIFY.md"],
    )


def enforce_engineering(
    prompt: str,
    llm_call: Callable[[list[dict[str, str]]], str],
) -> str:
    deployment_word = _detect_deployment_language(prompt)
    if deployment_word:
        raise EngineeringError(
            f"Deployment language '{deployment_word}' detected. Billy does not deploy."
        )

    template = (
        "### PLAN.md\n"
        "Problem Statement:\n\n"
        "Objectives:\n\n"
        "Scope:\n\n"
        "Non-Goals:\n\n"
        "Constraints:\n\n"
        "Assumptions:\n\n"
        "Proposed Approach:\n\n"
        "### ARTIFACT.md\n"
        "Definitions:\n\n"
        "Rules:\n\n"
        "Invariants:\n\n"
        "Forbidden Behaviors:\n\n"
        "Failure Conditions:\n\n"
        "### VERIFY.md\n"
        "What was verified:\n\n"
        "How it was verified:\n\n"
        "What was not verified:\n\n"
        "Pass:\n\n"
        "Fail:\n"
    )

    messages = [
        {"role": "system", "content": _build_engineering_system_prompt()},
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": template},
    ]

    raw = llm_call(messages)

    plan_text, artifact_text, verify_text = _extract_artifacts(raw)

    plan_result = validate_plan(plan_text)
    artifact_result = validate_artifact(artifact_text)
    verify_result = validate_verify(verify_text)

    errors = (
        plan_result.errors
        + artifact_result.errors
        + verify_result.errors
    )
    if errors:
        raise EngineeringError("; ".join(errors))

    task_dir = create_task_dir(prompt)

    plan_path = write_artifact(task_dir, "PLAN.md", plan_text)
    artifact_path = write_artifact(task_dir, "ARTIFACT.md", artifact_text)
    verify_path = write_artifact(task_dir, "VERIFY.md", verify_text)

    update_state(
        phase="awaiting_approval",
        current_task_id=task_dir.name,
    )

    return (
        "Artifacts written:\n"
        f"- {plan_path}\n"
        f"- {artifact_path}\n"
        f"- {verify_path}\n\n"
        "Artifacts are ready for review. Do you approve promotion to the next phase?"
    )
