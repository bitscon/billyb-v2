# This file is located at /home/billyb/workspaces/billy/v2/core/charter.py
    from pathlib import Path

    # --- PATHING ---
    # This is a relative path from the project root.
    CHARTER_PATH = "charter/billy-sys-prompt"

    def load_charter(root_path: str) -> str:
        """
        Loads the Billy charter from the charter/ directory.
        `root_path` will be '/home/billyb/workspaces/billy/v2'.
        """
        # This correctly combines the root path with the charter path to get the full location.
        # Result: /home/billyb/workspaces/billy/v2/charter/billy_charter.md
        full_path = Path(root_path) / CHARTER_PATH
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                charter_content = f.read()
            print("✅ Charter loaded successfully.")
            return charter_content
        except FileNotFoundError:
            print(f"❌ CRITICAL: Charter file not found at {full_path}")
            print("    Please ensure 'billy_charter.md' exists in the 'charter' directory.")
            # Return a failsafe string to prevent crashes during development
            return "You are a helpful assistant. The charter file was not found."
