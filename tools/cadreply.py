"""Claude's reply channel:  python tools/cadreply.py "text" [--status]"""
import json, sys, time
from pathlib import Path

CAD = Path(__file__).resolve().parent.parent / ".cad"
CAD.mkdir(exist_ok=True)
args = [a for a in sys.argv[1:] if a != "--status"]
role = "status" if "--status" in sys.argv else "assistant"
with open(CAD / "chat.jsonl", "a", encoding="utf-8") as f:
    f.write(json.dumps({"id": time.strftime("%H%M%S"), "role": role, "text": " ".join(args)}) + "\n")
