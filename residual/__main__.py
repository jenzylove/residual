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
    from .pipeline import replay, size_study, write_outputs
    from .live import load_live_log
    res = replay(use_ai=not args.no_ai, allow_llm_calls=not args.offline)
    res["size_study"] = size_study()
    # Demo-executable mode: same method, restricted to instruments Bitget Demo actually lists
    from . import universe
    dm = replay(use_ai=not args.no_ai, allow_llm_calls=False, verbose=False,
                hedge_pool=universe.demo_hedge_pool, tickers=set(universe.demo_companies()))
    res["demo_mode"] = {
        "companies": universe.demo_companies(), "hedge_pool": universe.DEMO_LISTED_STOCKS,
        "note": "Bitget Demo lists no index or sector ETF, so this mode hedges with the best fitting "
                "Demo listed stock. Same gates, same walk-forward, same size; its own scoring.",
        "summary": dm["summary"], "summary_conservative_funding": dm["summary_conservative_funding"],
        "rows": [{"event_id": r["event_id"],
                  "decision": {k: r["decision"].get(k) for k in ("decision", "direction", "size", "structure", "reasons")},
                  "hedge": r["analysis"].get("hedge") or {}, "residual": r["analysis"].get("residual"),
                  "net": (r.get("residual") or {}).get("net")} for r in dm["rows"]],
    }
    if not args.no_ai:
        core = replay(use_ai=False, verbose=False)
        res["ablation_no_ai"] = {"summary": core["summary"],
                                 "decisions": {r["event_id"]: r["decision"]["decision"] for r in core["rows"]}}
    from . import demo, net
    operator = {"execution_adapter": "bitget_demo" if demo.configured() else "local_paper",
                "demo_credentials_configured": demo.configured(), "demo_product_type": demo.PRODUCT_TYPE,
                "doh_fallback_enabled": net.DOH_FALLBACK, "replay_mode": "offline" if args.offline else "online",
                "ai_gate": not args.no_ai}
    write_outputs(res, {"live_log": load_live_log(), "operator": operator, "demo_evidence": demo_evidence(),
                        "demo_strategy_trades": demo_strategy_trades()})
    s = res["summary"]
    for k in ("residual", "unhedged", "naive", "no_trade"):
        m = s[k]
        print(f"{k:<10} pnl={m['total_net_pnl']:>10.2f} trades={m['trades']:>2} hit={m['hit_rate']} mdd={m['max_drawdown']}")


def demo_strategy_trades():
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent / "data" / "demo_strategy_trades.jsonl"
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()][-5:]


def demo_evidence():
    """Real Bitget Demo execution evidence from the last passing keyrun, if any (published on the site)."""
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent / "data" / "keyrun_report.json"
    if not p.exists():
        return None
    r = json.loads(p.read_text(encoding="utf-8"))
    rt = next((s for s in r.get("steps", []) if s["step"].startswith("roundtrip") and s.get("ok")), None)
    if not r.get("all_ok") or not rt:
        return None
    placed = [e for e in r.get("exchange_log", []) if e["path"].endswith("place-order") and e.get("code") == "00000"]
    return {"executed_at": r["started_at"], "venue": "Bitget Demo Trading (USDT-FUTURES, paptrading header)",
            "purpose": "execution test pair; not a strategy trade", "pair": rt["step"].split(" ")[1],
            "orders": rt["result"]["orders"], "realized": rt["result"]["realized"],
            "accepted_orders": len(placed), "position_mode": next(
                (("hedge_mode" if "tradeSide" in e["body"] else "one_way_mode") for e in placed), None)}


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
    from .live import LIVE_LOG, watch
    while True:
        try:
            rec = watch()
            print(json.dumps({k: rec[k] for k in ("checked_at", "decision", "reason")}, indent=1))
        except Exception as e:  # one failed poll (network, SEC, Bitget) must not end the watcher
            err = {"checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "decision": "ERROR",
                   "reason": f"{type(e).__name__}: {e}"}
            LIVE_LOG.parent.mkdir(parents=True, exist_ok=True)
            with LIVE_LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps(err) + "\n")
            print(json.dumps(err, indent=1))
            if not args.loop:
                sys.exit(1)
        if not args.loop:
            break
        time.sleep(args.loop)


def cmd_keyrun(args):
    """The whole Bitget Demo test run in one command; writes data/keyrun_report.json."""
    from pathlib import Path
    from . import demo, live, net, universe
    report = {"started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "steps": []}
    out = Path(__file__).resolve().parent.parent / "data" / "keyrun_report.json"

    def step(name, fn):
        t = time.time()
        try:
            res = fn()
            report["steps"].append({"step": name, "ok": True, "seconds": round(time.time() - t, 1), "result": res})
            print(f"[ok]   {name}")
            return res
        except Exception as e:
            report["steps"].append({"step": name, "ok": False, "error": f"{type(e).__name__}: {e}"})
            print(f"[FAIL] {name}: {e}")
            return None

    def finish():
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        report["all_ok"] = all(s["ok"] for s in report["steps"])
        out.write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
        print(("ALL STEPS PASSED" if report["all_ok"] else "SOME STEPS FAILED") + f" -> {out}")
        sys.exit(0 if report["all_ok"] else 1)

    step("credentials present", lambda: demo.configured() or (_ for _ in ()).throw(demo.DemoError(
        "set BITGET_DEMO_API_KEY / SECRET / PASSPHRASE in .env.local")))
    if not report["steps"][-1]["ok"]:
        return finish()
    def reachable():
        q = live.probe(universe.MARKET)
        if "error" in q:
            raise RuntimeError(f"public ticker failed: {q['error']}")
        return {"doh_fallback": net.DOH_FALLBACK, "ticker": q}
    step("public Bitget API reachable", reachable)
    client = step("authenticate", lambda: demo.BitgetDemo())
    if client is None:
        return finish()
    def account():
        accts = client.accounts()
        if not accts:
            raise demo.DemoError(f"no demo futures account for product type {demo.PRODUCT_TYPE}; activate or fund "
                                 "Demo Trading futures, or set BITGET_DEMO_PRODUCT_TYPE")
        avail = sum(float(a.get("available") or 0) for a in accts)
        if avail < args.notional * 3:
            raise demo.DemoError(f"demo USDT-M futures balance is {avail:,.2f} USDT. Demo funds land in the demo spot "
                                 "wallet; in the Bitget app (Demo Trading) use Assets > Transfer, from Spot to "
                                 "USDT-M Futures. The Demo API does not support transfers.")
        return [(a.get("marginCoin"), a.get("available")) for a in accts]
    step("demo account", account)
    strategy_hedges = ["QQQUSDT", "SPYUSDT", "SMHUSDT"]
    coverage = step("demo symbol coverage", lambda: {s: client.demo_symbol(s) for s in
                    [universe.sym(t) for t in universe.COMPANIES] + strategy_hedges + ["AAPLUSDT", "TSLAUSDT"]})
    if coverage is not None:
        report["strategy_tradeable_on_demo"] = {
            "companies": [s for s in (universe.sym(t) for t in universe.COMPANIES) if coverage.get(s)],
            "hedges": [s for s in strategy_hedges if coverage.get(s)],
        }
        if not report["strategy_tradeable_on_demo"]["hedges"]:
            report["note"] = ("None of the strategy's hedge instruments (QQQ, SPY, SMH) are listed on Bitget Demo, "
                              "so live strategy pairs will be NO_TRADE on Demo. The roundtrip below uses a Demo "
                              "listed stock as the second leg purely to test execution.")
    if coverage and not args.skip_roundtrip:
        company = next((s for s in ("NVDAUSDT", "AMDUSDT", "METAUSDT") if coverage.get(s)), None)
        hedge = next((s for s in strategy_hedges + ["AAPLUSDT", "TSLAUSDT"] if coverage.get(s) and s != company), None)
        if company and hedge:
            def rt():
                legs = client.open_pair([{"live_symbol": company, "side": 1, "notional": args.notional},
                                         {"live_symbol": hedge, "side": -1, "notional": args.notional}], "keyrun")
                closed = client.close_pair(legs, "keyrun")
                return {"orders": [{"symbol": l["demo_symbol"], "open": l["open_order"]["orderId"],
                                    "close": l["close_order"]["orderId"], "open_px": l["open_order"]["priceAvg"],
                                    "close_px": l["close_order"]["priceAvg"]} for l in closed],
                        "realized": demo.realized(closed)}
            step(f"roundtrip {company}/{hedge} ${args.notional}", rt)
        else:
            step("roundtrip", lambda: (_ for _ in ()).throw(demo.DemoError(
                "no universe company and hedge are both listed on Bitget Demo")))
    step("live watcher pass", lambda: {k: v for k, v in live.watch().items() if k in ("decision", "reason")})
    report["exchange_log"] = client.log
    finish()


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


def cmd_demo_strategy_trade(args):
    """Execute a real past strategy TRADE decision on Bitget Demo with its original fitted hedge, then close it.
    Refuses before any order when that hedge is not listed. Evidence -> data/demo_strategy_trades.jsonl."""
    from pathlib import Path
    from . import demo, market
    from .strategy import analyze
    res = json.loads((Path(__file__).resolve().parent.parent / "data" / "results.json").read_text(encoding="utf-8"))
    evs = {e["event_id"]: e for e in res["events"]}
    c = demo.BitgetDemo()
    source_rows = res["demo_mode"]["rows"] if args.mode == "demo" else res["rows"]
    rows = [r for r in source_rows if r["decision"]["decision"] == "TRADE"
            and (not args.event or r["event_id"] == args.event)
            and c.demo_symbol(evs[r["event_id"]]["company_symbol"])]
    if not rows:
        raise demo.DemoError("no strategy TRADE decision whose company is listed on Bitget Demo")
    r = rows[-1]
    ev = evs[r["event_id"]]
    snap = market.load_snapshot(ev["event_id"])
    from . import universe
    a = analyze(ev, snap, universe.demo_hedge_pool(ev["ticker"]) if args.mode == "demo" else None)
    hedge = a.get("hedge")
    if not hedge:
        raise demo.DemoError("strategy decision has no hedge; strict Demo mode refuses an unpaired trade")
    if not c.demo_symbol(hedge["symbol"]):
        raise demo.DemoError(
            f"{hedge['symbol']} not on Bitget Demo; strict Demo mode refuses a substitute hedge"
        )
    d, n = r["decision"]["direction"], args.notional
    legs = [{"live_symbol": ev["company_symbol"], "side": d, "notional": n}]
    legs.append({"live_symbol": hedge["symbol"], "side": -d, "notional": abs(hedge["beta"]) * n})
    tag = "st" + time.strftime("%m%d%H%M%S")
    opened = c.open_pair(legs, tag)
    closed = c.close_pair(opened, tag)
    rec = {"tag": tag, "executed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "event_id": ev["event_id"],
           "decision": {k: r["decision"].get(k) for k in ("direction", "structure", "size")},
           "strategy_hedge": hedge["symbol"], "hedge_used": hedge["symbol"],
           "hedge_substitute": None, "hedge_beta": hedge["beta"],
           "orders": [{"symbol": l["demo_symbol"], "side": "long" if l["side"] > 0 else "short",
                       "open": l["open_order"]["orderId"], "open_px": l["open_order"]["priceAvg"],
                       "close": l["close_order"]["orderId"], "close_px": l["close_order"]["priceAvg"]} for l in closed],
           "realized": demo.realized(closed), "note": "replayed decision executed at today's prices on Bitget Demo"}
    out = Path(__file__).resolve().parent.parent / "data" / "demo_strategy_trades.jsonl"
    with out.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, default=str) + "\n")
    print(json.dumps({k: rec[k] for k in ("event_id", "decision", "strategy_hedge", "hedge_used", "orders", "realized")}, indent=1, default=str))


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
    st = sub.add_parser("demo-strategy-trade", help="execute a real past strategy TRADE decision on Bitget Demo")
    st.add_argument("--event"); st.add_argument("--notional", type=float, default=100.0)
    st.add_argument("--mode", choices=("strategy", "demo"), default="demo",
                    help="demo: the Demo-executable mode (default); strategy: the main mode")
    kr = sub.add_parser("keyrun", help="full Bitget Demo test run -> data/keyrun_report.json")
    kr.add_argument("--notional", type=float, default=50.0)
    kr.add_argument("--skip-roundtrip", action="store_true")
    a = sub.add_parser("all"); a.add_argument("--no-ai", action="store_true"); a.add_argument("--offline", action="store_true")
    args = p.parse_args()
    if args.cmd == "all":
        args.since, args.until, args.refresh = "2025-10-15", None, False
        cmd_build(args); cmd_snapshot(args); cmd_replay(args)
    elif args.cmd == "keyrun":
        cmd_keyrun(args)
    elif args.cmd.startswith("demo-"):
        from .demo import DemoError
        try:
            {"demo-check": cmd_demo_check, "demo-roundtrip": cmd_demo_roundtrip,
             "demo-strategy-trade": cmd_demo_strategy_trade}[args.cmd](args)
        except DemoError as e:
            print(f"Bitget Demo: {e}")
            if "credentials missing" in str(e):
                print("Set BITGET_DEMO_API_KEY / BITGET_DEMO_API_SECRET / BITGET_DEMO_API_PASSPHRASE in .env.local "
                      "(see .env.example).")
            sys.exit(2)
    else:
        {"build": cmd_build, "snapshot": cmd_snapshot, "replay": cmd_replay, "verify": cmd_verify,
         "live": cmd_live, "serve": cmd_serve, "demo-check": cmd_demo_check,
         "demo-roundtrip": cmd_demo_roundtrip}[args.cmd](args)


if __name__ == "__main__":
    main()
