"""Replay, walk-forward evaluation, baselines, ledger and UI data export."""
import csv
import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path

from . import MODEL_VERSION, edgar
from .events import load_events
from .extract import EXTRACTOR_VERSION
from .interpret import interpret
from .market import HOLD_HOURS, LOOKBACK_DAYS, OBS_HOURS, load_snapshot
from .net import fetch
from . import strategy
from .strategy import (DEFAULT_PARAMS, MAX_LOSS_FRAC, VARIANTS, WINDOWS, analyze, attribute, decide,
                       learn_params, learn_variant, run_trade, variant_direction)

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "data" / "results.json"
LEDGER = ROOT / "data" / "ledger.csv"
WEB_DATA = ROOT / "web" / "data.json"
START_BALANCE = 100_000.0


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec="minutes").replace("+00:00", "Z")


def risk_ratios(rows: list[dict], traded: list[dict]) -> dict:
    """Sharpe and Sortino, per trade (return on company notional) and on daily P&L (annualised, 365 days:
    Bitget perpetuals trade every day). Daily series spans the first release to the last exit, flat days = 0."""
    out = {"sharpe_per_trade": None, "sortino_per_trade": None, "sharpe_daily_ann": None,
           "sortino_daily_ann": None, "days": 0}
    if not traded:
        return out
    rets = [t["net"] / next(l["notional"] for l in t["legs"] if l["role"] == "company") for t in traded]
    if len(rets) > 1 and statistics.stdev(rets) > 0:
        out["sharpe_per_trade"] = round(statistics.fmean(rets) / statistics.stdev(rets), 3)
    down = [r for r in rets if r < 0]
    if down:
        dd = math.sqrt(sum(r * r for r in down) / len(rets))
        out["sortino_per_trade"] = round(statistics.fmean(rets) / dd, 3) if dd > 0 else None
    t0 = min(r["_release_ms"] for r in rows) // 86_400_000
    t1 = max([t["exit_ms"] for t in traded] + [r["_release_ms"] for r in rows]) // 86_400_000
    daily = [0.0] * (t1 - t0 + 1)
    for t in traded:
        daily[t["exit_ms"] // 86_400_000 - t0] += t["net"] / START_BALANCE
    out["days"] = len(daily)
    if len(daily) > 1 and statistics.stdev(daily) > 0:
        out["sharpe_daily_ann"] = round(statistics.fmean(daily) / statistics.stdev(daily) * math.sqrt(365), 3)
    neg = [d for d in daily if d < 0]
    if neg:
        dd = math.sqrt(sum(d * d for d in neg) / len(daily))
        out["sortino_daily_ann"] = round(statistics.fmean(daily) / dd * math.sqrt(365), 3) if dd > 0 else None
    return out


def metrics(rows: list[dict], key: str, basis: str = "primary") -> dict:
    """primary: only trades with complete Bitget funding data count (others are excluded, P&L 0).
    conservative: every trade counts, unavailable funding charged at the worst observed rate.
    observed_zero: every trade counts, unavailable funding taken as zero (comparison only)."""
    pnl, traded, excluded = [], [], 0
    for r in rows:
        t = r.get(key)
        if not t:
            pnl.append(0.0)
        elif basis == "primary" and t["funding_data"] != "complete":
            excluded += 1
            pnl.append(0.0)
        else:
            v = t["net_conservative"] if basis == "conservative" else t["net"]
            pnl.append(v)
            traded.append({**t, "net": v})
    eq, peak, mdd = 0.0, 0.0, 0.0
    curve = []
    for p in pnl:
        eq += p
        peak = max(peak, eq)
        mdd = min(mdd, eq - peak)
        curve.append(round(eq, 2))
    tp = [t["net"] for t in traded]
    ratios = risk_ratios(rows, traded)
    return {
        **ratios,
        "basis": basis, "total_net_pnl": round(sum(pnl), 2), "trades": len(traded),
        "excluded_funding_unavailable": excluded,
        "no_trades": len(rows) - len(traded) - excluded,
        "hit_rate": round(sum(p > 0 for p in tp) / len(tp), 3) if tp else None,
        "avg_pnl_per_trade": round(statistics.fmean(tp), 2) if tp else None,
        "pnl_std_per_trade": round(statistics.stdev(tp), 2) if len(tp) > 1 else None,
        "max_drawdown": round(mdd, 2),
        "avg_holding_hours": round(statistics.fmean(t["holding_hours"] for t in traded), 1) if traded else None,
        "return_on_start_balance_pct": round(sum(pnl) / START_BALANCE * 100, 3),
        "equity_curve": curve,
    }


def _source_text(event, allow_network=True):
    from .events import source_raw
    return edgar.html_to_text(source_raw(event["source"]["press_release_url"], event["source"]["sha256"],
                                         allow_network=allow_network))


def _slim_sim(sim):
    if not sim:
        return None
    return {k: sim[k] for k in ("net", "net_conservative", "gross_mid", "fees", "slippage", "funding",
                                "funding_conservative", "entry_ms", "exit_ms", "stopped", "holding_hours",
                                "funding_data", "legs")}


def funding_caps(snaps) -> dict[str, float]:
    """Largest absolute funding rate observed per symbol across all stored settlements."""
    caps: dict[str, float] = {}
    for snap in snaps:
        for s, info in (snap or {}).get("funding", {}).items():
            for x in info.get("settlements", []):
                caps[s] = max(caps.get(s, 0.0), abs(x["rate"]))
    return caps


def replay(*, use_ai: bool = True, allow_llm_calls: bool = True, verbose: bool = True,
           hedge_pool=None, tickers=None) -> dict:
    events = [e for e in load_events() if e["status"] != "not_an_earnings_release"]
    if tickers:
        events = [e for e in events if e['ticker'] in tickers]
    snaps = {ev["event_id"]: load_snapshot(ev["event_id"]) for ev in events}
    caps = funding_caps(snaps.values())
    worst = max(caps.values(), default=0.0)
    for snap in snaps.values():
        for s, info in (snap or {}).get("funding", {}).items():
            # a symbol with no nonzero observed settlement gets the worst rate seen on any symbol
            info["max_abs_rate_observed"] = caps.get(s) or worst
    analyzed = []
    for ev in events:
        snap = snaps[ev["event_id"]]
        pool = hedge_pool(ev['ticker']) if callable(hedge_pool) else hedge_pool
        analyzed.append((ev, snap, analyze(ev, snap, pool)))

    rows, orders, balance = [], [], START_BALANCE
    for i, (ev, snap, a) in enumerate(analyzed):
        history = [h for (_, _, h) in analyzed[:i]
                   if "times" in h and h["times"]["t_exit"] <= ev["release_ms"]]
        params = learn_params(history)
        interp = None
        if use_ai and "residual" in a and ev["surprise"]:
            interp = interpret(ev, a, _source_text(ev, allow_network=allow_llm_calls), allow_call=allow_llm_calls)
        dec = decide(ev, a, params, interp if use_ai else None)
        sel = learn_variant(history, params)

        row = {"event_id": ev["event_id"], "_release_ms": ev["release_ms"], "params": params, "decision": dec,
               "variant": sel, "interpretation": interp, "residual": None, "naive": None, "unhedged": None}
        if dec["decision"] == "TRADE":
            # every pre-declared variant, scored on its own (published whether it wins or loses)
            for v in VARIANTS:
                d = variant_direction(v, a, params)
                row[f"v_{v}"] = _slim_sim(run_trade(ev, snap, a, d, dec["size"], tag=f"v_{v}")) if d else None
            # the strategy itself follows the variant chosen from earlier events only
            d = variant_direction(sel["variant"], a, params)
            dec["gates"]["variant"] = {"pass": d != 0, "detail": f"{sel['variant']} rule ({sel['source']})"
                                       + ("" if d else ": company move and surprise disagree")}
            if d == 0:
                dec.update({"decision": "NO_TRADE", "reasons": ["variant"], "size": 0.0})
            else:
                dec.update({"direction": d, "structure": "long company / short hedge" if d > 0 else "short company / long hedge"})
        if dec["decision"] == "TRADE":
            sim = run_trade(ev, snap, a, dec["direction"], dec["size"])
            if sim:
                row["residual"] = {**_slim_sim(sim), "attribution": attribute(ev, snap, a, sim, dec["direction"])}
                for o in sim["orders"]:
                    orders.append({**o, "time_utc": iso(o["time_ms"])})
                balance += sim["net_conservative"]  # equals net when funding data is complete
                row["balance_after"] = balance
            unh = run_trade(ev, snap, a, dec["direction"], dec["size"], hedged=False, tag="unhedged")
            row["unhedged"] = _slim_sim(unh)
        if ev["surprise"] and a["gates"].get("market_data", (False,))[0]:
            d = 1 if ev["surprise"]["guidance_surprise_pct"] > 0 else -1
            row["naive_direction"] = d
            row["naive"] = _slim_sim(run_trade(ev, snap, a, d, 1.0, hedged=False, tag="naive"))
            # like-for-like baseline: headline direction on exactly the events Residual traded, same size
            if row["residual"]:
                row["naive_same_events"] = _slim_sim(run_trade(ev, snap, a, d, dec["size"], hedged=False,
                                                               tag="naive_same"))
        row["analysis"] = {k: v for k, v in a.items() if k not in ("counterfactual",)}
        row["analysis"]["gates"] = {k: {"pass": v[0], "detail": v[1]} for k, v in a["gates"].items()}
        rows.append(row)
        if verbose:
            r = row["residual"]
            print(f"  {ev['event_id']:<16} {dec['decision']:<8} "
                  f"res={a.get('residual', float('nan')) * 100:+6.2f}% "
                  f"params={params['mode']:+d}/{params['k']} "
                  f"pnl={r['net'] if r else 0:+9.2f}  {','.join(dec['reasons'])}", flush=True)

    keys = ("residual", "unhedged", "naive_same_events", "naive") + tuple(f"v_{v}" for v in VARIANTS)
    summary = {k: metrics(rows, k) for k in keys}
    summary["no_trade"] = metrics(rows, "__none__")
    summary_conservative = {k: metrics(rows, k, "conservative") for k in keys}
    summary_conservative["no_trade"] = metrics(rows, "__none__", "conservative")
    summary_observed_zero = {k: metrics(rows, k, "observed_zero") for k in keys}
    # last 90 days of real history, as the Alpha Factory track reportedly asks for
    last = max(r["_release_ms"] for r in rows)
    recent = [r for r in rows if r["_release_ms"] >= last - 90 * 86_400_000]
    summary_90d = {k: metrics(recent, k) for k in keys} if recent else {}
    summary_90d_window = {"from_ms": min(r["_release_ms"] for r in recent), "to_ms": last, "events": len(recent)} if recent else None
    warm = [r for r in rows if r["params"]["source"] == "walk-forward"]
    summary_post_warmup = {k: metrics(warm, k) for k in ("residual", "naive", "unhedged")}
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model_version": MODEL_VERSION, "extractor_version": EXTRACTOR_VERSION,
        "config": {"lookback_days": LOOKBACK_DAYS, "beta_windows_days": WINDOWS, "obs_hours": OBS_HOURS,
                   "hold_hours": HOLD_HOURS, "base_notional": strategy.BASE_NOTIONAL, "max_loss_frac": MAX_LOSS_FRAC,
                   "variants": VARIANTS,
                   "default_params": DEFAULT_PARAMS, "ai_gate": use_ai, "start_balance": START_BALANCE},
        "evaluation": "expanding-window walk-forward: parameters for each event are fit only on events "
                      "whose exit precedes that event's release; no event is scored with parameters "
                      "trained on itself",
        "summary": summary, "summary_conservative_funding": summary_conservative,
        "summary_observed_zero_funding": summary_observed_zero,
        "summary_last_90d": summary_90d, "summary_last_90d_window": summary_90d_window,
        "funding_caps": caps, "summary_post_warmup": summary_post_warmup,
        "events": [ev for ev, _, _ in analyzed], "rows": rows, "orders": orders,
        "final_balance": balance,
    }


def _finite(o):
    """Replace NaN/Infinity with None: browsers reject them in JSON (Python's json accepts them)."""
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: _finite(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_finite(v) for v in o]
    return o


def size_study(sizes=(1_000, 2_500, 5_000, 10_000)) -> list[dict]:
    """Re-run the whole walk-forward at several company-leg sizes (offline, cached AI answers)."""
    keep, out = strategy.BASE_NOTIONAL, []
    try:
        for n in sizes:
            strategy.BASE_NOTIONAL = float(n)
            r = replay(use_ai=True, allow_llm_calls=False, verbose=False)
            rows = r["rows"]
            out.append({"notional": n,
                        "trades": sum(x["decision"]["decision"] == "TRADE" for x in rows),
                        "liquidity_rejects": sum("liquidity" in x["decision"]["reasons"] for x in rows),
                        "primary": {k: {f: r["summary"][k][f] for f in ("total_net_pnl", "trades", "sharpe_daily_ann", "max_drawdown")}
                                    for k in ("residual", "naive_same_events")},
                        "conservative": {k: {f: r["summary_conservative_funding"][k][f] for f in ("total_net_pnl", "trades", "sharpe_daily_ann")}
                                         for k in ("residual", "naive_same_events")}})
    finally:
        strategy.BASE_NOTIONAL = keep
    return out


def write_outputs(result: dict, web_extra: dict | None = None):
    result = _finite(result)
    web_extra = _finite(web_extra or {})
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(result, indent=1, allow_nan=False, default=_json_default), encoding="utf-8")
    with LEDGER.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["time_utc", "tag", "leg", "symbol", "type", "side", "qty", "price", "notional", "fee"])
        for o in result["orders"]:
            w.writerow([o["time_utc"], o["tag"], o["leg"], o["symbol"], o["type"], o["side"],
                        f"{o['qty']:.6f}", f"{o['price']:.4f}", f"{o['notional']:.2f}", f"{o['fee']:.4f}"])
    WEB_DATA.parent.mkdir(parents=True, exist_ok=True)
    WEB_DATA.write_text(json.dumps({**result, **web_extra}, allow_nan=False, default=_json_default), encoding="utf-8")
    # downloadable copies for the site
    import shutil
    shutil.copyfile(LEDGER, WEB_DATA.parent / "ledger.csv")
    shutil.copyfile(ROOT / "data" / "events.json", WEB_DATA.parent / "events.json")


def _json_default(o):
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
        return None
    raise TypeError(type(o))
