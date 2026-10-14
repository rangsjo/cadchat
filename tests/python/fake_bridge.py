"""Stand-in for creo/bridge/CreoBridge.java: same JSON-lines protocol, state kept in a file the test controls."""
import json
import os
import shutil
import sys

STATE = os.environ["FAKE_CREO_STATE"]


def load():
    with open(STATE, encoding="utf-8") as f:
        return json.load(f)


def save(s):
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(s, f)


for line in sys.stdin:
    req = json.loads(line) if line.strip() else None
    if req is None:
        continue
    s = load()
    s.setdefault("log", []).append({k: v for k, v in req.items() if k != "id"})
    cmd, reply = req["cmd"], {"id": req["id"], "ok": True}
    fail = s.get("fail", {})
    if cmd in fail:
        reply = {"id": req["id"], "ok": False, "error": fail[cmd]}
    elif cmd == "quit":
        save(s)
        print(json.dumps(reply), flush=True)
        break
    elif cmd == "connect":
        if not s.get("creo_running", True):
            reply = {"id": req["id"], "ok": False, "error": "XToolkitNotFound: no Creo Parametric process found"}
        else:
            s["connected"] = True
    elif cmd == "status":
        reply.update(connected=s.get("connected", False), model=s.get("model"), fingerprint=s.get("fp", ""))
    elif cmd == "params":
        reply["params"] = s.get("params", [])
    elif cmd == "set":
        for p in s.get("params", []):
            if p["name"] == req["name"]:
                p["value"] = req["value"]
                s["fp"] = str(float(s.get("fp", "0")) + 1)
                break
        else:
            reply = {"id": req["id"], "ok": False, "error": f"no parameter or dimension named {req['name']}"}
    elif cmd == "export_step":
        shutil.copy(s["step_src"], req["path"])
    elif cmd == "hang":
        import time
        time.sleep(60)
    save(s)
    print(json.dumps(reply), flush=True)
