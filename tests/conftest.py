import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V2_PATH = ROOT / "v2"
if str(V2_PATH) not in sys.path:
    sys.path.insert(0, str(V2_PATH))
