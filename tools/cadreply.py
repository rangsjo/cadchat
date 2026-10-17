"""Claude's reply channel:  python tools/cadreply.py "text" [--status] [--model ID]
The reply goes to the chat of the current project (CADCHAT_ROOT, else the project around the cwd, else the last used one) and is tagged
with the model of the latest question unless --model says otherwise."""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cadwatch import read_jsonl


def reply(root, text, status=False, model=None):
    cad = Path(root) / ".cad"
    cad.mkdir(exist_ok=True)
    if model is None:
        users = [m for m in read_jsonl(cad / "chat.jsonl") if m.get("role") == "user"]
        model = users[-1].get("model") if users else None
    with open(cad / "chat.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"id": time.strftime("%H%M%S"), "role": "status" if status else "assistant", "text": text, "model": model}) + "\n")


if __name__ == "__main__":
    import projects
    argv = sys.argv[1:]
    model = argv[argv.index("--model") + 1] if "--model" in argv else None
    words = [a for i, a in enumerate(argv) if a not in ("--status", "--model") and (i == 0 or argv[i - 1] != "--model")]
    reply(projects.resolve_project(), " ".join(words), status="--status" in argv, model=model)
