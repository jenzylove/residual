"""One watcher cycle, windowless, and publish it to the site.

Run by the ResidualWatcher scheduled task through pythonw.exe (no console window).
Writes data/watcher.log, refreshes web/live.json, and pushes when something happened
(a new event, a closed position) or at most once an hour, so the deployed page stays alive.
"""
import json, os, subprocess, sys, time, traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
LOG = os.path.join(ROOT, "data", "watcher.log")
LIVE = os.path.join(ROOT, "web", "live.json")
STAMP = os.path.join(ROOT, "data", ".last_push")
PUSH_EVERY = 3600  # seconds, when nothing happened
# On a GitHub Actions runner nothing survives between runs unless it is committed, so the whole watcher
# state goes into the commit, and a new event is replayed before it is published.
CI = os.environ.get("GITHUB_ACTIONS") == "true"
STATE = ["web/live.json", "data/live_log.jsonl", "data/watcher.log", "data/live_pending.json",
         "data/live_positions.json", "data/demo_open_pairs.jsonl", "data/demo_strategy_trades.jsonl",
         "data/events.json", "data/snapshots", "data/sources", "data/interpretations", "data/consensus"]
RESULTS = ["data/results.json", "data/ledger.csv", "web/data.json", "web/events.json", "web/ledger.csv"]


def log(obj):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, default=str) + "\n")


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=120)


def publish(rec, changed):
    from residual.live import load_live_log
    recent = load_live_log(20)
    payload = {"checked_at": rec.get("checked_at"), "decision": rec.get("decision"), "reason": rec.get("reason"),
               "next_estimated_release": rec.get("next_estimated_release"),
               "market_probe": (rec.get("market_probe") or [])[:6],
               "new_events": rec.get("new_events") or [], "closed_positions": rec.get("closed_positions") or [],
               "recent": [{k: r.get(k) for k in ("checked_at", "decision", "reason")} for r in recent],
               "published_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    with open(LIVE, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))
    if CI:  # no local stamp file on a runner: the last watcher commit is the clock
        out = git("log", "-1", "--format=%ct", "--grep=^watcher:").stdout.strip()
        last = int(out) if out else 0
    else:
        last = os.path.getmtime(STAMP) if os.path.exists(STAMP) else 0
    if not CI and not changed and time.time() - last < PUSH_EVERY:  # a runner keeps nothing, so it always pushes
        return "skipped"
    replayed = False
    if CI and rec.get("new_events"):
        r = subprocess.run([sys.executable, "-m", "residual", "replay"], cwd=ROOT, capture_output=True, text=True, timeout=1500)
        replayed = r.returncode == 0
    paths = (STATE + (RESULTS if replayed else [])) if CI else ["web/live.json", "data/live_log.jsonl", "data/watcher.log"]
    git("add", *[x for x in paths if os.path.exists(os.path.join(ROOT, x))])
    c = git("commit", "-m", f"watcher: {rec.get('checked_at')} {rec.get('decision')}" + (" (replayed)" if replayed else ""))
    if c.returncode != 0 and "nothing to commit" in (c.stdout + c.stderr):
        return "nothing to commit"
    if replayed:
        subprocess.run([sys.executable, "-m", "residual", "version"], cwd=ROOT, capture_output=True, timeout=60)
        git("add", "web/version.json")
        git("commit", "-m", "Version stamp after watcher replay")
    git("pull", "--rebase", "--autostash")  # the repo moves under the watcher while work continues
    p = git("push")
    open(STAMP, "w").write(str(time.time()))
    if p.returncode == 0:
        return "pushed"
    return "push failed: " + ((p.stderr or p.stdout).strip()[:160] or f"exit {p.returncode}")


def close_due_demo_pairs():
    """Flatten any held Demo pair whose holding period has elapsed. Held pairs exist so a Demo
    execution is a real trade with a holding period rather than an instant round trip."""
    try:
        p = subprocess.run([sys.executable, "-m", "residual", "demo-close-due"],
                           cwd=ROOT, capture_output=True, text=True, timeout=300)
        out = (p.stdout or "").strip()
        return json.loads(out) if out.startswith("{") else {"error": (p.stderr or out)[:160]}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


try:
    from residual.live import watch
    rec = watch()
    rec["demo_close"] = close_due_demo_pairs()
    changed = bool(rec.get("new_events") or rec.get("closed_positions") or (rec.get("demo_close") or {}).get("closed"))
    entry = {k: rec.get(k) for k in ("checked_at", "decision", "reason")} | {"demo_close": rec.get("demo_close")}
    if CI:  # log before publishing, or the line dies with the runner
        log(entry | {"publish": "github actions"})
        publish(rec, changed)
    else:
        log(entry | {"publish": publish(rec, changed)})
except Exception as e:
    log({"checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "decision": "ERROR",
         "reason": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-300:]})
