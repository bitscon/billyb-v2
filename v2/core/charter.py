from pathlib import Path

def load_charter(root_path: str) -> str:
    """
    Load all canonical charter documents in numeric order and concatenate them
    into a single system prompt.

    Canonical directory:
      <root>/docs/charter/

    Files must be named like:
      00_SOMETHING.md, 01_SOMETHING.md, ...
    """
    charter_dir = Path(root_path) / "docs" / "charter"

    if not charter_dir.exists():
        raise RuntimeError(f"CRITICAL: Charter directory not found: {charter_dir}")

    files = sorted(
        p for p in charter_dir.iterdir()
        if p.is_file()
        and p.suffix.lower() == ".md"
        and p.name[:2].isdigit()
    )

    if not files:
        raise RuntimeError(f"CRITICAL: No numbered charter files found in {charter_dir}")

    sections: list[str] = []
    for f in files:
        sections.append(f"\n\n# ===== {f.name} =====\n\n")
        sections.append(f.read_text(encoding="utf-8"))

    print(f"✅ Loaded {len(files)} charter files from {charter_dir}")
    return "".join(sections)
