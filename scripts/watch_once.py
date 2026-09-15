"""One watcher cycle, windowless. Used by the ResidualWatcher scheduled task via pythonw.exe.

pythonw has no console, so nothing pops up; every result and error is appended to data/watcher.log.
"""
import json, os, sys, time, traceback
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

def log(obj):
    with open(os.path.join(ROOT, "data", "watcher.log"), "a", encoding="utf-8") as f:
        f.write(json.dumps(obj) + "\n")

try:
    from residual.live import watch
    rec = watch()
    log({k: rec.get(k) for k in ("checked_at", "decision", "reason")})
except Exception as e:
    log({"checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "decision": "ERROR",
         "reason": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-400:]})
