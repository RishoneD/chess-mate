import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Local Windows development: Stockfish is installed outside the synced folder
if not os.environ.get("STOCKFISH_PATH") and os.environ.get("LOCALAPPDATA"):
    local = (Path(os.environ["LOCALAPPDATA"]) / "check-mate-tools" / "stockfish"
             / "stockfish" / "stockfish-windows-x86-64-universal.exe")
    if local.is_file():
        os.environ["STOCKFISH_PATH"] = str(local)
