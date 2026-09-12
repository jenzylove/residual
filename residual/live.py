"""Live watcher: polls SEC EDGAR for the next eligible earnings release in the
universe, builds the event record, and decides with live Bitget data.

Each run appends one record to data/live_log.jsonl:
  * no new release   -> NO_TRADE ("no eligible event"), with estimated next dates
                        and a live Bitget liquidity probe for the universe
  * new release      -> event record is added to data/events.json, then
                        PENDING (reaction window still open), NO_TRADE (gates), or
                        TRADE (paper pair opened at live bid/ask from the order book)
Open live positions are closed on a later run once their horizon has passed.
"""
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import bitget, edgar, events, market, universe
from .interpret import interpret
from .strategy import BASE_NOTIONAL, MAX_LOSS_FRAC, analyze, decide, learn_params

ROOT = Path(__file__).resolve().parent.parent
LIVE_LOG = ROOT / "data" / "live_log.jsonl"
POSITIONS = ROOT / "data" / "live_positions.json"


def load_live_log(limit: int = 100) -> list[dict]:
    if not LIVE_LOG.exists():
        return []
    lines = LIVE_LOG.read_text(encoding="utf-8").splitlines()
    return [json.loads(x) for x in lines[-limit:] if x.strip()]


def _append(rec: dict):
    LIVE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with LIVE_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, default=str) + "\n")


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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


def _positions() -> list[dict]:
    return json.loads(POSITIONS.read_text(encoding="utf-8")) if POSITIONS.exists() else []


def _save_positions(p):
    POSITIONS.write_text(json.dumps(p, indent=1), encoding="utf-8")


def _mark_position(pos: dict):
    """Return current combined mid P&L and quotes, or None on probe failure."""
    pnl, quotes = 0.0, {}
    for leg in pos["legs"]:
        q = probe(leg["symbol"])
        if q.get("error") or q.get("bid") is None or q.get("ask") is None:
            return None, None
        quotes[leg["symbol"]] = q
        mid = (q["bid"] + q["ask"]) / 2
        pnl += leg["side"] * (mid - leg["entry_price"]) * leg["qty"]
    return pnl, quotes


def _close_position(pos: dict, reason: str, quotes: dict | None = None):
    net = 0.0
    for leg in pos["legs"]:
        q = (quotes or {}).get(leg["symbol"]) or probe(leg["symbol"])
        if q.get("error") or q.get("bid") is None or q.get("ask") is None:
            return None
        px = q["bid"] if leg["side"] > 0 else q["ask"]
        fee = leg["fee_rate"] * leg["qty"] * px
        leg.update({"exit_price": px, "exit_fee": fee, "exit_quote": q})
        net += leg["side"] * (px - leg["entry_price"]) * leg["qty"] - leg["entry_fee"] - fee
    pos.update({"status": "closed", "closed_at": _now_iso(), "close_reason": reason, "net_pnl": net})
    return pos


def _close_due_positions(now_ms: int) -> list[dict]:
    closed, keep = [], []
    for pos in _positions():
        if pos["status"] != "open":
            keep.append(pos)
            continue
        reason = "horizon" if now_ms >= pos["exit_due_ms"] else None
        pnl, quotes = _mark_position(pos)
        if reason is None and pnl is not None and pnl <= -float(pos.get("max_loss", float("inf"))):
            reason = "stop"
        if reason:
            done = _close_position(pos, reason, quotes)
            if done is not None:
                closed.append(done)
            else:
                keep.append(pos)
        else:
            keep.append(pos)
    if closed:
        _save_positions(keep)
    return closed


def _open_position(event, a, dec, contracts: dict | None = None) -> dict:
    legs = []
    n = BASE_NOTIONAL * dec["size"]
    contracts = contracts or {}
    spec = [(event["company_symbol"], dec["direction"], n)]
    if a.get("hedge"):
        spec.append((a["hedge"]["symbol"], -dec["direction"], abs(a["hedge"]["beta"]) * n))
    for sym, side, notional in spec:
        q = probe(sym)
        if q.get("error") or q.get("ask") is None or q.get("bid") is None:
            raise RuntimeError(f"live quote unavailable for {sym}: {q.get('error', 'missing bid/ask')}")
        px = q["ask"] if side > 0 else q["bid"]
        fee_rate = float(contracts.get(sym, {}).get("takerFeeRate") or 0.0006)
        qty = notional / px
        legs.append({"symbol": sym, "side": side, "qty": qty, "entry_price": px, "fee_rate": fee_rate,
                     "entry_fee": fee_rate * qty * px, "entry_quote": q})
    pos = {"event_id": event["event_id"], "status": "open", "opened_at": _now_iso(),
           "exit_due_ms": int(time.time() * 1000) + market.HOLD_HOURS * 3_600_000,
           "max_loss": MAX_LOSS_FRAC * BASE_NOTIONAL * dec["size"], "legs": legs}
    _save_positions(_positions() + [pos])
    return pos


def _history_params(dataset, before_ms):
    hist = []
    for ev in dataset:
        if ev["release_ms"] >= before_ms:
            continue
        snap = market.load_snapshot(ev["event_id"])
        a = analyze(ev, snap)
        if "times" in a and a["times"]["t_exit"] <= before_ms:
            hist.append(a)
    return learn_params(hist)


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
            if i and f["accession"] not in known and f["accepted_et"][:10] > last_known.get(t, "2025-10-15"):
                new.append((f, filings[i - 1]))

    rec = {"checked_at": _now_iso(), "universe": list(universe.COMPANIES),
           "next_estimated_release": dict(sorted(next_est.items(), key=lambda kv: kv[1])),
           "closed_positions": closed}
    if not new:
        rec.update({"decision": "NO_TRADE", "reason": "no eligible earnings release since the last recorded event",
                    "market_probe": [probe(universe.sym(t)) for t in universe.COMPANIES] + [probe(universe.MARKET)]})
        _append(rec)
        return rec

    contracts = bitget.contracts(cache=False)
    outcomes = []
    for f, prev in new:
        ev = events.build_event(f, prev)
        dataset = sorted([e for e in dataset if e["event_id"] != ev["event_id"]] + [ev], key=lambda e: e["release_ms"])
        events.save_events(dataset)
        tm = market.event_times(ev["release_ms"])
        out = {"event_id": ev["event_id"], "event_status": ev["status"], "release_utc": ev["release_utc"]}
        if now_ms < tm["t_obs"]:
            out.update({"decision": "PENDING", "reason": f"reaction window closes {datetime.fromtimestamp(tm['t_obs'] / 1000, timezone.utc).isoformat()}"})
            outcomes.append(out)
            continue
        snap = market.build_snapshot(ev, contracts, now_ms=now_ms)
        market.save_snapshot(snap)
        a = analyze(ev, snap)
        params = _history_params(dataset, ev["release_ms"])
        interp = None
        if "residual" in a and ev["surprise"]:
            interp = interpret(ev, a, edgar.html_to_text(edgar.fetch(ev["source"]["press_release_url"])))
        dec = decide(ev, a, params, interp)
        entry_open = tm["t_obs"] <= now_ms < tm["t_obs"] + 3_600_000
        if dec["decision"] == "TRADE" and not entry_open:
            dec = {**dec, "decision": "NO_TRADE", "reasons": ["entry_window_passed"],
                   "note": "signal qualified but the live entry window (t_obs to t_obs+1h) has passed; see replay"}
        out.update({"decision": dec["decision"], "reason": ", ".join(dec["reasons"]) or dec.get("structure"),
                    "residual": a.get("residual"), "params": params, "gates": dec["gates"],
                    "interpretation": {k: interp.get(k) for k in ("status", "label", "confidence", "detail")} if interp else None})
        if dec["decision"] == "TRADE":
            out["position"] = _open_position(ev, a, dec, contracts)
        outcomes.append(out)
    rec.update({"decision": ",".join(o["decision"] for o in outcomes),
                "reason": f"{len(outcomes)} new event record(s) added", "new_events": outcomes})
    _append(rec)
    return rec
