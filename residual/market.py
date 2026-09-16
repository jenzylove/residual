"""Market snapshots: the reproducible Bitget input file for each event."""
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from . import bitget, universe
from .factors import DAY, HOUR

ROOT = Path(__file__).resolve().parent.parent
SNAP_DIR = ROOT / "data" / "snapshots"

LOOKBACK_DAYS = 21
OBS_HOURS = 2      # early reaction window after the release hour
HOLD_HOURS = 24    # event horizon after entry


def event_times(release_ms: int) -> dict:
    t_pre = release_ms - release_ms % HOUR
    t_obs = t_pre + OBS_HOURS * HOUR
    return {"t_pre": t_pre, "t_obs": t_obs, "t_exit": t_obs + HOLD_HOURS * HOUR,
            "t_start": t_pre - LOOKBACK_DAYS * DAY}


_funding_cache: dict[str, list] = {}


def _funding(symbol: str) -> list:
    if symbol not in _funding_cache:
        try:
            _funding_cache[symbol] = bitget.funding_history(symbol)
        except Exception:
            _funding_cache[symbol] = []
    return _funding_cache[symbol]


def build_snapshot(event: dict, contracts: dict, *, now_ms: int | None = None) -> dict:
    now_ms = now_ms or int(time.time() * 1000)
    tm = event_times(event["release_ms"])
    end = min(tm["t_exit"] + 2 * HOUR, now_ms - now_ms % HOUR)
    symbols = {}
    for s in universe.snapshot_symbols(event["ticker"]):
        rows = bitget.hourly_candles(s, tm["t_start"] - HOUR, end)
        if rows:
            symbols[s] = [[r["t"], r["o"], r["h"], r["l"], r["c"], r["qv"]] for r in rows]
    funding = {}
    funding_symbols = ([universe.sym(event["ticker"])] +
                       universe.hedge_symbols(event["ticker"]) +
                       universe.demo_hedge_pool(event["ticker"]))
    for s in dict.fromkeys(funding_symbols):
        hist = _funding(s)
        funding[s] = {
            "earliest_available": hist[0]["t"] if hist else None,
            "settlements": [x for x in hist if tm["t_obs"] - 8 * HOUR <= x["t"] <= tm["t_exit"] + 8 * HOUR],
        }
    return {
        "event_id": event["event_id"],
        "source": "Bitget REST v2 /api/v2/mix/market/history-candles (USDT-FUTURES, 1H)",
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "window": tm,
        "contracts": {s: {k: contracts[s].get(k) for k in ("takerFeeRate", "makerFeeRate", "launchTime", "fundInterval")}
                      for s in symbols if s in contracts},
        "funding": funding,
        "candles": symbols,
    }


def merge_funding(old: dict | None, new: dict) -> dict:
    """Bitget only serves ~90 days of funding history, so a later refetch covers LESS of the past.
    Keep the earliest coverage ever captured and the union of all settlements; never shrink."""
    if not old:
        return new
    out = {}
    for s in set(old) | set(new):
        o, n = old.get(s) or {}, new.get(s) or {}
        starts = [x for x in (o.get("earliest_available"), n.get("earliest_available")) if x is not None]
        by_t = {x["t"]: x for x in o.get("settlements", [])}
        by_t.update({x["t"]: x for x in n.get("settlements", [])})
        out[s] = {"earliest_available": min(starts) if starts else None,
                  "settlements": [by_t[t] for t in sorted(by_t)]}
    return out


def save_snapshot(snap: dict) -> Path:
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    p = SNAP_DIR / f"{snap['event_id']}.json"
    if p.exists():  # refresh: funding coverage must never shrink
        old = json.loads(p.read_text(encoding="utf-8"))
        snap["funding"] = merge_funding(old.get("funding"), snap.get("funding", {}))
    p.write_text(json.dumps(snap, separators=(",", ":")), encoding="utf-8")
    return p


def load_snapshot(event_id: str) -> dict | None:
    p = SNAP_DIR / f"{event_id}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
