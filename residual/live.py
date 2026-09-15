"""Live watcher: polls SEC EDGAR for the next eligible earnings release in the
universe, builds the event record, and decides with live Bitget data.

Each run appends one record to data/live_log.jsonl. Lifecycle of an event:
  new filing      -> event record added to data/events.json
  before t_obs    -> PENDING (stored in data/live_pending.json, re-checked every run)
  t_obs..t_obs+1h -> decision with live data: NO_TRADE (gates) or TRADE
                     (paper pair opened at the live bid/ask from the order book)
  after t_obs+1h  -> NO_TRADE (entry window passed); replay still scores it
  after horizon   -> open paper position closed at the live bid/ask
With no new filing and nothing pending the run records NO_TRADE plus a live
Bitget liquidity probe. Paper only: no orders are sent to Bitget.
"""
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import bitget, demo, edgar, events, market, universe
from .interpret import interpret
from .strategy import BASE_NOTIONAL, analyze, decide, learn_params

ROOT = Path(__file__).resolve().parent.parent
LIVE_LOG = ROOT / "data" / "live_log.jsonl"
POSITIONS = ROOT / "data" / "live_positions.json"
PENDING = ROOT / "data" / "live_pending.json"
HOUR_MS = 3_600_000


def load_live_log(limit: int = 100) -> list[dict]:
    if not LIVE_LOG.exists():
        return []
    lines = LIVE_LOG.read_text(encoding="utf-8").splitlines()
    return [json.loads(x) for x in lines[-limit:] if x.strip()]


def _read(p: Path, default):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def _write(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=1, default=str), encoding="utf-8")


def _append(rec: dict):
    LIVE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with LIVE_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, default=str) + "\n")


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec="seconds")


def probe(symbol: str) -> dict:
    """Live top-of-book, spread and depth within 10 bps for one instrument."""
    try:
        tk = bitget.ticker(symbol)
        book = bitget.depth(symbol)
        bid, ask = float(tk["bidPr"]), float(tk["askPr"])
        mid = (bid + ask) / 2
        near = lambda side, ok: sum(float(p) * float(q) for p, q in book[side] if ok(float(p)))
        return {"symbol": symbol, "bid": bid, "ask": ask, "last": float(tk["lastPr"]),
                "spread_bps": round((ask - bid) / mid * 1e4, 2),
                "bid_depth_10bps_usdt": round(near("bids", lambda p: p >= mid * 0.999), 0),
                "ask_depth_10bps_usdt": round(near("asks", lambda p: p <= mid * 1.001), 0),
                "funding_rate": float(tk.get("fundingRate") or 0), "ts": int(tk["ts"])}
    except Exception as e:
        return {"symbol": symbol, "error": str(e)}


def _close_due_positions(now_ms: int) -> list[dict]:
    positions, closed = _read(POSITIONS, []), []
    for pos in positions:
        if pos["status"] != "open" or now_ms < pos["exit_due_ms"]:
            continue
        if pos.get("execution") == "bitget_demo":
            try:
                client = demo.BitgetDemo()
                legs = client.close_pair(pos["demo_legs"], f"{pos['event_id']}-close")
                pos.update({"status": "closed", "closed_at": _iso(now_ms), "demo_legs": legs,
                            "realized": demo.realized(legs), "net_pnl": demo.realized(legs)["net"],
                            "exchange_log": pos.get("exchange_log", []) + client.log})
                closed.append(pos)
            except Exception as e:
                pos["close_error"] = str(e)  # retried on the next run
            continue
        net = 0.0
        for leg in pos["legs"]:
            q = probe(leg["symbol"])
            if "error" in q:
                break
            px = q["bid"] if leg["side"] > 0 else q["ask"]
            fee = leg["fee_rate"] * leg["qty"] * px
            leg.update({"exit_price": px, "exit_fee": fee, "exit_quote": q})
            net += leg["side"] * (px - leg["entry_price"]) * leg["qty"] - leg["entry_fee"] - fee
        else:
            pos.update({"status": "closed", "closed_at": _iso(now_ms), "net_pnl": net,
                        "funding": "not charged: live funding settlements are not tracked for paper positions"})
            closed.append(pos)
    if closed:
        _write(POSITIONS, positions)
    return closed


def _open_position(event, a, dec, now_ms, snap=None) -> tuple[dict | None, str | None]:
    """Open the pair. With Bitget Demo credentials, both legs are real Demo Trading orders
    (all-or-nothing); otherwise they are local paper fills at the live bid/ask."""
    n = BASE_NOTIONAL * dec["size"]
    hedge = a.get("hedge")
    if demo.configured():
        try:
            client = demo.BitgetDemo()
            if hedge and not client.demo_symbol(hedge["symbol"]):
                # Never turn a strategy pair into a different pair on the execution path.
                # A substitute stock changes the instrument exposure and invalidates the
                # strategy's recorded hedge.  Refuse before placing either leg.
                return None, f"hedge {hedge['symbol']} not listed on Bitget Demo; strict Demo mode refuses substitution"
            spec = [(event["company_symbol"], dec["direction"], n)]
            if hedge:
                spec.append((hedge["symbol"], -dec["direction"], abs(hedge["beta"]) * n))
            legs = client.open_pair([{"live_symbol": s, "side": sd, "notional": nt} for s, sd, nt in spec],
                                    event["event_id"].replace("-", "")[:20])
        except Exception as e:
            return None, f"bitget demo execution failed: {e}"
        pos = {"event_id": event["event_id"], "status": "open", "opened_at": _iso(now_ms),
               "execution": "bitget_demo", "exit_due_ms": now_ms + market.HOLD_HOURS * HOUR_MS,
               "hedge_substitute": None, "demo_legs": legs, "exchange_log": client.log}
        _write(POSITIONS, _read(POSITIONS, []) + [pos])
        return pos, None
    spec = [(event["company_symbol"], dec["direction"], n)]
    if hedge:
        spec.append((hedge["symbol"], -dec["direction"], abs(hedge["beta"]) * n))
    legs = []
    for sym, side, notional in spec:
        q = probe(sym)
        if "error" in q:
            return None, "live order book unavailable at entry"
        px = q["ask"] if side > 0 else q["bid"]
        qty = notional / px
        legs.append({"symbol": sym, "side": side, "qty": qty, "entry_price": px, "fee_rate": 0.0006,
                     "entry_fee": 0.0006 * qty * px, "entry_quote": q})
    pos = {"event_id": event["event_id"], "status": "open", "opened_at": _iso(now_ms), "execution": "local_paper",
           "exit_due_ms": now_ms + market.HOLD_HOURS * HOUR_MS, "legs": legs}
    _write(POSITIONS, _read(POSITIONS, []) + [pos])
    return pos, None


def _history_params(dataset, before_ms):
    hist = []
    for ev in dataset:
        if ev["release_ms"] >= before_ms:
            continue
        a = analyze(ev, market.load_snapshot(ev["event_id"]))
        if "times" in a and a["times"]["t_exit"] <= before_ms:
            hist.append(a)
    return learn_params(hist)


def evaluate(ev: dict, dataset: list[dict], now_ms: int, contracts: dict) -> dict:
    tm = market.event_times(ev["release_ms"])
    out = {"event_id": ev["event_id"], "event_status": ev["status"], "release_utc": ev["release_utc"]}
    if now_ms < tm["t_obs"]:
        out.update({"decision": "PENDING", "reason": f"reaction window closes {_iso(tm['t_obs'])}"})
        return out
    snap = market.build_snapshot(ev, contracts, now_ms=now_ms)
    market.save_snapshot(snap)
    a = analyze(ev, snap)
    params = _history_params(dataset, ev["release_ms"])
    interp = None
    if "residual" in a and ev["surprise"]:
        raw = events.source_raw(ev["source"]["press_release_url"], ev["source"]["sha256"])
        interp = interpret(ev, a, edgar.html_to_text(raw))
    dec = decide(ev, a, params, interp)
    if dec["decision"] == "TRADE" and not (tm["t_obs"] <= now_ms < tm["t_obs"] + HOUR_MS):
        dec = {**dec, "decision": "NO_TRADE", "reasons": ["entry_window_passed"]}
    out.update({"decision": dec["decision"], "reason": ", ".join(dec["reasons"]) or dec.get("structure"),
                "residual": a.get("residual"), "params": params, "gates": dec["gates"],
                "interpretation": {k: interp.get(k) for k in ("status", "label", "confidence", "detail")} if interp else None})
    if dec["decision"] == "TRADE":
        pos, err = _open_position(ev, a, dec, now_ms, snap)
        if pos is None:
            out.update({"decision": "NO_TRADE", "reason": err})
        else:
            out["position"] = pos
    return out


def watch(now_ms: int | None = None) -> dict:
    now_ms = now_ms or int(time.time() * 1000)
    dataset = events.load_events()
    known = {e["accession"] for e in dataset}
    last_known = {}
    for e in dataset:
        last_known[e["ticker"]] = max(last_known.get(e["ticker"], ""), e["release_utc"][:10])

    closed = _close_due_positions(now_ms)
    new, next_est = [], {}
    for t in universe.COMPANIES:
        filings = edgar.earnings_filings(t, cache=False)
        if filings:
            last = datetime.fromisoformat(filings[-1]["accepted_et"])
            next_est[t] = (last + timedelta(days=91)).date().isoformat()
        for i, f in enumerate(filings):
            if i and f["accession"] not in known and f["accepted_et"][:10] >= last_known.get(t, "2025-10-15"):
                new.append((f, filings[i - 1]))

    rec = {"checked_at": _iso(now_ms), "universe": list(universe.COMPANIES),
           "next_estimated_release": dict(sorted(next_est.items(), key=lambda kv: kv[1])),
           "closed_positions": closed}
    for f, prev in new:
        ev = events.build_event(f, prev)
        dataset = sorted([e for e in dataset if e["event_id"] != ev["event_id"]] + [ev],
                         key=lambda e: e["release_ms"])
        events.save_events(dataset)
        pending = _read(PENDING, [])
        if ev["event_id"] not in pending:
            _write(PENDING, pending + [ev["event_id"]])

    pending = _read(PENDING, [])
    if not pending:
        rec.update({"decision": "NO_TRADE", "reason": "no eligible earnings release since the last recorded event",
                    "market_probe": [probe(universe.sym(t)) for t in universe.COMPANIES] + [probe(universe.MARKET)]})
        _append(rec)
        return rec

    contracts = bitget.contracts(cache=False)
    by_id = {e["event_id"]: e for e in dataset}
    outcomes, still = [], []
    for eid in pending:
        out = evaluate(by_id[eid], dataset, now_ms, contracts)
        outcomes.append(out)
        if out["decision"] == "PENDING":
            still.append(eid)
    _write(PENDING, still)
    rec.update({"decision": ",".join(o["decision"] for o in outcomes),
                "reason": f"{len(new)} new event record(s) added; {len(outcomes)} event(s) evaluated",
                "new_events": outcomes})
    _append(rec)
    return rec
