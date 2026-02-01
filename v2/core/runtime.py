"""
Updated runtime module for Billy v2.

This version adjusts the BillyRuntime constructor to accept an optional
configuration dictionary and default to an empty dictionary when none is
provided. It also adds the ask() method required by the API layer to
correctly invoke the configured LLM.
"""

import yaml
from pathlib import Path
from typing import Dict, Any, List

from . import llm_api
from .charter import load_charter

# --- HARD GUARDRAILS (fast stability) ---
FORBIDDEN_IDENTITY_PHRASES = (
    "i'm an ai",
    "i am an ai",
    "i’m an ai",
    "artificial intelligence",
    "chatbot",
    "language model",
    "llm",
    "assistant",
    "conversational ai",
)

# Deterministic fallback identity/purpose (authoritative, no LLM needed)
IDENTITY_FALLBACK = (
    "I am Billy — a digital Farm Hand and Foreman operating inside the Farm."
)


class BillyRuntime:
    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        """
        Initialize the runtime.

        Args:
            config: Optional configuration dictionary. If not provided,
            config will be loaded automatically from v2/config.yaml.
        """
        self.config = config or {}

    def _identity_guard(self, user_input: str, answer: str) -> str:
        """
        Identity guardrails (currently permissive).

        This hook exists to enforce identity rules later.
        """
        return answer

    def _load_config_from_yaml(self) -> Dict[str, Any]:
        """
        Load model configuration from v2/config.yaml if present.
        """
        try:
            v2_root = Path(__file__).resolve().parents[1]
            config_path = v2_root / "config.yaml"

            if not config_path.exists():
                return {}

            data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return {}

            # Expect config under top-level "model"
            return data.get("model", {})
        except Exception:
            return {}

    def ask(self, prompt: str) -> str:
        """
        Generate a response using the configured LLM.

        This is the method called by:
        - /ask
        - /v1/chat/completions
        """

        # Load config if not provided at init
        config = self.config or self._load_config_from_yaml()

        # Load charter (system prompt)
        system_prompt = ""
        try:
            v2_root = Path(__file__).resolve().parents[1]
            system_prompt = load_charter(str(v2_root))
        except Exception:
            system_prompt = ""

        # Build chat messages
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        messages.append({"role": "user", "content": prompt})

        # Call LLM
        answer = llm_api.get_completion(messages, config)

        # Apply guardrails
        return self._identity_guard(prompt, answer)
