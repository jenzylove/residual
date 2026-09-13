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
    from . import demo, net
    operator = {"execution_adapter": "bitget_demo" if demo.configured() else "local_paper",
                "demo_credentials_configured": demo.configured(), "demo_product_type": demo.PRODUCT_TYPE,
                "doh_fallback_enabled": net.DOH_FALLBACK, "replay_mode": "offline" if args.offline else "online",
                "ai_gate": not args.no_ai}
    write_outputs(res, {"live_log": load_live_log(), "operator": operator})
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
            raw = events.source_raw(f["source_url"], f["source_sha256"], allow_network=not args.offline)
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


def cmd_demo_check(args):
    """Authenticate against Bitget Demo Trading and map the universe to demo contracts."""
    from . import demo, universe
    c = demo.BitgetDemo()
    acct = c.accounts()
    print("auth ok · product", demo.PRODUCT_TYPE, "· accounts:",
          [(a.get("marginCoin"), a.get("available")) for a in acct])
    syms = [universe.sym(t) for t in universe.COMPANIES] + ["QQQUSDT", "SPYUSDT", "SMHUSDT"]
    for s in syms:
        print(f"  {s:<10} -> {c.demo_symbol(s) or 'NOT LISTED on demo'}")
    print(f"{len(c.contracts())} demo contracts listed")


def cmd_demo_roundtrip(args):
    """Open and immediately close one small hedged pair on Bitget Demo; save exchange records."""
    from pathlib import Path
    from . import demo
    c = demo.BitgetDemo()
    tag = "rt" + time.strftime("%m%d%H%M%S")
    legs = c.open_pair([{"live_symbol": args.company, "side": 1, "notional": args.notional},
                        {"live_symbol": args.hedge, "side": -1, "notional": args.notional}], tag)
    closed = c.close_pair(legs, tag)
    rec = {"tag": tag, "executed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "legs": closed, "realized": demo.realized(closed), "exchange_log": c.log}
    out = Path(__file__).resolve().parent.parent / "data" / "demo_roundtrips.jsonl"
    with out.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, default=str) + "\n")
    for l in closed:
        print(f"  {l['demo_symbol']:<12} open {l['open_order']['orderId']} @ {l['open_order']['priceAvg']}"
              f"  close {l['close_order']['orderId']} @ {l['close_order']['priceAvg']}")
    print("realized", rec["realized"], "->", out)


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
    r.add_argument("--offline", action="store_true",
                   help="no network at all: committed sources, snapshots and cached interpretations only")
    v = sub.add_parser("verify"); v.add_argument("-v", "--verbose", action="store_true")
    v.add_argument("--offline", action="store_true", help="use only the committed data/sources archive")
    l = sub.add_parser("live"); l.add_argument("--loop", type=int, default=0, help="poll every N seconds")
    sv = sub.add_parser("serve"); sv.add_argument("--port", type=int, default=8000)
    sub.add_parser("demo-check", help="verify Bitget Demo credentials and demo symbol coverage")
    rt = sub.add_parser("demo-roundtrip", help="open+close one small hedged pair on Bitget Demo")
    rt.add_argument("--company", default="NVDAUSDT"); rt.add_argument("--hedge", default="QQQUSDT")
    rt.add_argument("--notional", type=float, default=50.0)
    a = sub.add_parser("all"); a.add_argument("--no-ai", action="store_true"); a.add_argument("--offline", action="store_true")
    args = p.parse_args()
    if args.cmd == "all":
        args.since, args.until, args.refresh = "2025-10-15", None, False
        cmd_build(args); cmd_snapshot(args); cmd_replay(args)
    elif args.cmd.startswith("demo-"):
        from .demo import DemoError
        try:
            {"demo-check": cmd_demo_check, "demo-roundtrip": cmd_demo_roundtrip}[args.cmd](args)
        except DemoError as e:
            print(f"Bitget Demo: {e}\nSet BITGET_DEMO_API_KEY / BITGET_DEMO_API_SECRET / BITGET_DEMO_API_PASSPHRASE "
                  "in .env.local (see .env.example).")
            sys.exit(2)
    else:
        {"build": cmd_build, "snapshot": cmd_snapshot, "replay": cmd_replay, "verify": cmd_verify,
         "live": cmd_live, "serve": cmd_serve, "demo-check": cmd_demo_check,
         "demo-roundtrip": cmd_demo_roundtrip}[args.cmd](args)


if __name__ == "__main__":
    main()
