import yaml
    from pathlib import Path

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
        "I am Billy — a digital Farm Hand and Foreman operating inside the Farm known as `workshop.home`.\n"
        "I live in the Barn.\n"
        "My sole purpose is to help farm Chad’s ideas.\n"
        "I am not a chatbot, not a business operator, and not an internet agent."
    )

    class BillyRuntime:
        def __init__(self, root_path: str):
            self.root_path = Path(root_path)
            print(f" Billy Runtime initialized at {self.root_path}")

            # Load config
            self.config = self._load_config()

            # Load canonical charter (directory-based)
            try:
                self.charter = load_charter(str(self.root_path))
            except Exception as e:
                print(f"❌ CRITICAL: Charter load failed: {e}")
                self.charter = ""

            # Default mode
            self.mode = "ADVISORY"

        def _load_config(self) -> dict:
            config_path = self.root_path / "config.yaml"
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    raw = yaml.safe_load(f) or {}
                    config = raw.get("model") or {}
                print("✅ Config loaded successfully.")
                return config
            except FileNotFoundError:
                print("❌ WARNING: config.yaml not found. Using empty config.")
                return {}
            except Exception as e:
                print(f"❌ WARNING: config.yaml failed to load ({e}). Using empty config.")
                return {}

        def _identity_guard(self, user_input: str, answer: str) -> str:
            """
            If the model leaks forbidden identity phrasing, override with deterministic identity.
            Also handles common identity questions deterministically for stability.
            """
            u = (user_input or "").strip().lower()
            a = (answer or "").strip().lower()

            # If user is asking identity/purpose, answer deterministically
            if any(k in u for k in ("who are you", "what are you", "your purpose", "what is your purpose")):
                return f"{IDENTITY_FALLBACK}\n\nCurrent operational mode: {self.mode}."

            # If model leaked forbidden identity terms, override
            if any(p in a for p in FORBIDDEN_IDENTITY_PHRASES):
                return f"{IDENTITY_FALLBACK}\n\nCurrent operational mode: {self.mode}."

            return answer

        def ask(self, user_input: str) -> str:
            text = (user_input or "").strip().lower()

            # Mode switching (deterministic)
            if text in ("switch to operator mode", "enter operator mode"):
                self.mode = "OPERATOR"
                return "Mode switched to OPERATOR."

            if text in ("switch to advisory mode", "enter advisory mode"):
                self.mode = "ADVISORY"
                return "Mode switched to ADVISORY."

            # System prompt: include mode header + full charter
            system_prompt = (
                f"Current operational mode: {self.mode}.\n"
                "Identity constraint: You are Billy, a foreman in workshop.home. "
                "Never describe yourself as an AI, chatbot, assistant, or language model.\n\n"
                f"{self.charter}"
            )

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input},
            ]

            answer = llm_api.get_completion(messages, self.config)
            return self._identity_guard(user_input, answer)