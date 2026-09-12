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
from .strategy import (BASE_NOTIONAL, DEFAULT_PARAMS, MAX_LOSS_FRAC, WINDOWS, analyze, attribute,
                       decide, learn_params, run_trade)

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "data" / "results.json"
LEDGER = ROOT / "data" / "ledger.csv"
WEB_DATA = ROOT / "web" / "data.json"
START_BALANCE = 100_000.0


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec="minutes").replace("+00:00", "Z")


def metrics(rows: list[dict], key: str) -> dict:
    pnl = [r[key]["net"] if r.get(key) else 0.0 for r in rows]
    traded = [r[key] for r in rows if r.get(key)]
    eq, peak, mdd = 0.0, 0.0, 0.0
    curve = []
    for p in pnl:
        eq += p
        peak = max(peak, eq)
        mdd = min(mdd, eq - peak)
        curve.append(round(eq, 2))
    tp = [t["net"] for t in traded]
    return {
        "total_net_pnl": round(sum(pnl), 2), "trades": len(traded),
        "no_trades": len(rows) - len(traded),
        "hit_rate": round(sum(p > 0 for p in tp) / len(tp), 3) if tp else None,
        "avg_pnl_per_trade": round(statistics.fmean(tp), 2) if tp else None,
        "pnl_std_per_trade": round(statistics.stdev(tp), 2) if len(tp) > 1 else None,
        "max_drawdown": round(mdd, 2),
        "avg_holding_hours": round(statistics.fmean(t["holding_hours"] for t in traded), 1) if traded else None,
        "return_on_start_balance_pct": round(sum(pnl) / START_BALANCE * 100, 3),
        "equity_curve": curve,
    }


def _source_text(event):
    return edgar.html_to_text(fetch(event["source"]["press_release_url"]))


def _slim_sim(sim):
    if not sim:
        return None
    return {k: sim[k] for k in ("net", "gross_mid", "fees", "slippage", "funding", "entry_ms", "exit_ms",
                                "stopped", "holding_hours", "funding_data", "legs")}


def replay(*, use_ai: bool = True, allow_llm_calls: bool = True, verbose: bool = True) -> dict:
    events = load_events()
    analyzed = []
    for ev in events:
        snap = load_snapshot(ev["event_id"])
        analyzed.append((ev, snap, analyze(ev, snap)))

    rows, orders, balance = [], [], START_BALANCE
    for i, (ev, snap, a) in enumerate(analyzed):
        history = [h for (_, _, h) in analyzed[:i]
                   if "times" in h and h["times"]["t_exit"] <= ev["release_ms"]]
        params = learn_params(history)
        interp = None
        if use_ai and "residual" in a and ev["surprise"]:
            interp = interpret(ev, a, _source_text(ev), allow_call=allow_llm_calls)
        dec = decide(ev, a, params, interp if use_ai else None)

        row = {"event_id": ev["event_id"], "params": params, "decision": dec,
               "interpretation": interp, "residual": None, "naive": None, "unhedged": None}
        if dec["decision"] == "TRADE":
            sim = run_trade(ev, snap, a, dec["direction"], dec["size"])
            if sim:
                row["residual"] = {**_slim_sim(sim), "attribution": attribute(ev, snap, a, sim, dec["direction"])}
                for o in sim["orders"]:
                    orders.append({**o, "time_utc": iso(o["time_ms"])})
                balance += sim["net"]
                row["balance_after"] = balance
            unh = run_trade(ev, snap, a, dec["direction"], dec["size"], hedged=False, tag="unhedged")
            row["unhedged"] = _slim_sim(unh)
        if ev["surprise"] and a["gates"].get("market_data", (False,))[0]:
            d = 1 if ev["surprise"]["revenue_surprise_pct"] > 0 else -1
            row["naive_direction"] = d
            row["naive"] = _slim_sim(run_trade(ev, snap, a, d, 1.0, hedged=False, tag="naive"))
        row["analysis"] = {k: v for k, v in a.items() if k not in ("counterfactual",)}
        row["analysis"]["gates"] = {k: {"pass": v[0], "detail": v[1]} for k, v in a["gates"].items()}
        rows.append(row)
        if verbose:
            r = row["residual"]
            print(f"  {ev['event_id']:<16} {dec['decision']:<8} "
                  f"res={a.get('residual', float('nan')) * 100:+6.2f}% "
                  f"params={params['mode']:+d}/{params['k']} "
                  f"pnl={r['net'] if r else 0:+9.2f}  {','.join(dec['reasons'])}", flush=True)

    summary = {k: metrics(rows, k) for k in ("residual", "naive", "unhedged")}
    summary["no_trade"] = metrics(rows, "__none__")
    warm = [r for r in rows if r["params"]["source"] == "walk-forward"]
    summary_post_warmup = {k: metrics(warm, k) for k in ("residual", "naive", "unhedged")}
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model_version": MODEL_VERSION, "extractor_version": EXTRACTOR_VERSION,
        "config": {"lookback_days": LOOKBACK_DAYS, "beta_windows_days": WINDOWS, "obs_hours": OBS_HOURS,
                   "hold_hours": HOLD_HOURS, "base_notional": BASE_NOTIONAL, "max_loss_frac": MAX_LOSS_FRAC,
                   "default_params": DEFAULT_PARAMS, "ai_gate": use_ai, "start_balance": START_BALANCE},
        "evaluation": "expanding-window walk-forward: parameters for each event are fit only on events "
                      "whose exit precedes that event's release; no event is scored with parameters "
                      "trained on itself",
        "summary": summary, "summary_post_warmup": summary_post_warmup,
        "events": [ev for ev, _, _ in analyzed], "rows": rows, "orders": orders,
        "final_balance": balance,
    }


def write_outputs(result: dict, web_extra: dict | None = None):
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(result, indent=1, default=_json_default), encoding="utf-8")
    with LEDGER.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["time_utc", "tag", "leg", "symbol", "type", "side", "qty", "price", "notional", "fee"])
        for o in result["orders"]:
            w.writerow([o["time_utc"], o["tag"], o["leg"], o["symbol"], o["type"], o["side"],
                        f"{o['qty']:.6f}", f"{o['price']:.4f}", f"{o['notional']:.2f}", f"{o['fee']:.4f}"])
    WEB_DATA.parent.mkdir(parents=True, exist_ok=True)
    WEB_DATA.write_text(json.dumps({**result, **(web_extra or {})}, default=_json_default), encoding="utf-8")


def _json_default(o):
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
        return None
    raise TypeError(type(o))
