import json
import yaml

class OutputGuard:
    """
    Guards and parses LLM output. Fail closed.
    """

    FORBIDDEN_PHRASES = [
        "i am an ai",
        "chatbot",
        "language model",
    ]

    HEDGING_PHRASES = [
        "might",
        "maybe",
        "could try",
    ]

    EXECUTION_PHRASES = [
        "execute",
        "run",
        "/exec",
        "/apply",
        "/step",
    ]

    def guard(self, output, plan_mode: bool = False) -> dict:
        errors = []
        parsed = None

        if isinstance(output, dict):
            parsed = output
        elif isinstance(output, str):
            parsed = self._parse_text(output)
            if parsed is None:
                errors.append("Output is not valid YAML or JSON")
        else:
            errors.append("Output is not a string or object")

        text = output if isinstance(output, str) else json.dumps(output)
        lowered = text.lower()

        for phrase in self.FORBIDDEN_PHRASES:
            if phrase in lowered:
                errors.append(f"Forbidden identity phrase: {phrase}")

        for phrase in self.HEDGING_PHRASES:
            if phrase in lowered:
                errors.append(f"Hedging language detected: {phrase}")

        if plan_mode:
            for phrase in self.EXECUTION_PHRASES:
                if phrase in lowered:
                    errors.append("Execution intent detected in /plan mode")
                    break

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "parsed": parsed,
        }

    def _parse_text(self, text: str):
        try:
            return json.loads(text)
        except Exception:
            pass
        try:
            return yaml.safe_load(text)
        except Exception:
            return None
