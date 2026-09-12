"""RESIDUAL command line.

  python -m residual build       # SEC EDGAR -> verified earnings dataset (data/events.json)
  python -m residual snapshot    # Bitget hourly candles/funding per event (data/snapshots/)
  python -m residual replay      # walk-forward replay + baselines -> data/results.json, ledger, web/data.json
  python -m residual verify      # re-verify every numeric earnings field against its source
  python -m residual live        # watch EDGAR for the next eligible event, record decision or NO_TRADE
  python -m residual serve       # dashboard at http://localhost:8000
  python -m residual all         # build + snapshot + replay
"""
import argparse
import json
import sys
import time

from . import bitget, edgar, events, market
from .extract import verify_field
from .net import fetch


def cmd_build(args):
    evs = events.build_dataset(since=args.since, until=args.until)
    events.save_events(evs)
    print(f"{len(evs)} events, {sum(e['status'] == 'complete' for e in evs)} complete -> {events.EVENTS_FILE}")


def cmd_snapshot(args):
    contracts = bitget.contracts(cache=False)
    now = int(time.time() * 1000)
    for ev in events.load_events():
        old = market.load_snapshot(ev["event_id"])
        done = old and max((r[0] for r in old["candles"].get(ev["company_symbol"], [[0]])), default=0) \
            >= market.event_times(ev["release_ms"])["t_exit"]
        if old and done and not args.refresh:
            continue
        snap = market.build_snapshot(ev, contracts, now_ms=now)
        market.save_snapshot(snap)
        print(f"  {ev['event_id']:<16} symbols={len(snap['candles']):>2} "
              f"company_rows={len(snap['candles'].get(ev['company_symbol'], []))}", flush=True)


def cmd_replay(args):
    from .pipeline import replay, write_outputs
    from .live import load_live_log
    res = replay(use_ai=not args.no_ai, allow_llm_calls=not args.offline)
    if not args.no_ai:
        core = replay(use_ai=False, verbose=False)
        res["ablation_no_ai"] = {"summary": core["summary"],
                                 "decisions": {r["event_id"]: r["decision"]["decision"] for r in core["rows"]}}
    write_outputs(res, {"live_log": load_live_log()})
    s = res["summary"]
    for k in ("residual", "unhedged", "naive", "no_trade"):
        m = s[k]
        print(f"{k:<10} pnl={m['total_net_pnl']:>10.2f} trades={m['trades']:>2} hit={m['hit_rate']} mdd={m['max_drawdown']}")


def cmd_verify(args):
    bad = 0
    for ev in events.load_events():
        for name, f in ev["earnings"].items():
            if not f:
                continue
            raw = fetch(f["source_url"])
            ok, detail = verify_field(f, edgar.html_to_text(raw), raw)
            bad += not ok
            if not ok or args.verbose:
                print(f"{ev['event_id']:<16} {name:<24} {'OK ' if ok else 'BAD'} {detail}  [{f['snippet'][:70]}]")
    print("all numeric fields verified" if not bad else f"{bad} fields FAILED verification")
    sys.exit(1 if bad else 0)


def cmd_live(args):
    from .live import watch
    while True:
        rec = watch()
        print(json.dumps({k: rec[k] for k in ("checked_at", "decision", "reason")}, indent=1))
        if not args.loop:
            break
        time.sleep(args.loop)


def cmd_serve(args):
    import functools
    import http.server
    from pathlib import Path
    web = Path(__file__).resolve().parent.parent / "web"
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(web))
    print(f"RESIDUAL dashboard: http://localhost:{args.port}")
    http.server.ThreadingHTTPServer(("", args.port), handler).serve_forever()


def main():
    p = argparse.ArgumentParser(prog="residual")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build"); b.add_argument("--since", default="2025-10-15"); b.add_argument("--until")
    s = sub.add_parser("snapshot"); s.add_argument("--refresh", action="store_true")
    r = sub.add_parser("replay"); r.add_argument("--no-ai", action="store_true", help="disable the AI gate")
    r.add_argument("--offline", action="store_true", help="use cached interpretations only")
    v = sub.add_parser("verify"); v.add_argument("-v", "--verbose", action="store_true")
    l = sub.add_parser("live"); l.add_argument("--loop", type=int, default=0, help="poll every N seconds")
    sv = sub.add_parser("serve"); sv.add_argument("--port", type=int, default=8000)
    a = sub.add_parser("all"); a.add_argument("--no-ai", action="store_true"); a.add_argument("--offline", action="store_true")
    args = p.parse_args()
    if args.cmd == "all":
        args.since, args.until, args.refresh = "2025-10-15", None, False
        cmd_build(args); cmd_snapshot(args); cmd_replay(args)
    else:
        {"build": cmd_build, "snapshot": cmd_snapshot, "replay": cmd_replay, "verify": cmd_verify,
         "live": cmd_live, "serve": cmd_serve}[args.cmd](args)


if __name__ == "__main__":
    main()
