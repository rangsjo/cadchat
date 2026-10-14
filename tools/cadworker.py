"""Warm build worker: a long-lived Python process that runs model scripts on request, so build123d (about 1.4 s to
import) is loaded once instead of on every rebuild. Protocol: one JSON object per line on stdin
{"script": path} or {"import": path, "name": id}; one JSON reply per line on the real stdout {"ok", "error", "out", "pid", "ms"}."""
import contextlib
import io
import json
import os
import runpy
import sys
import time
import traceback


def main():
    chan = sys.__stdout__
    try:
        import build123d  # noqa: F401  (pre-load the expensive import)
    except Exception:
        pass
    for line in sys.stdin:
        if not line.strip():
            continue
        req = json.loads(line)
        out = io.StringIO()
        t = time.perf_counter()
        ok, err = True, ""
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                if "import" in req:
                    import exchange
                    exchange.import_to_model(req["import"], req["name"])
                else:
                    runpy.run_path(req["script"], run_name="__main__")
        except SystemExit as e:
            ok = e.code in (None, 0)
            err = "" if ok else f"script exited with {e.code}"
        except BaseException:
            ok, err = False, traceback.format_exc()[-600:]
        chan.write(json.dumps({"id": req.get("id"), "ok": ok, "error": err, "out": out.getvalue()[-2000:], "pid": os.getpid(),
                               "ms": round((time.perf_counter() - t) * 1000)}) + "\n")
        chan.flush()


if __name__ == "__main__":
    main()
