"""Residual strategy: deterministic analysis, risk gates, walk-forward parameters."""
import math

from . import universe
from .factors import (DAY, HOUR, basket_returns, basket_window_return, corwin_schultz, decompose,
                      fit, hedge_fit, hourly_returns, index, median_quote_volume, open_at,
                      price_at, window_return)
from .paper import simulate

WINDOWS = (7, 14, 21)            # beta estimation lookbacks (days); primary = 14
PRIMARY = 14
BASE_NOTIONAL = 2_500.0          # company-leg notional (USDT) at full size; sized to Bitget after-hours
                                 # liquidity (the size study in results.json shows $10k fails the gate far more)
MAX_LOSS_FRAC = 0.025            # pair stop: 2.5% of company notional
MIN_HEDGE_R2 = 0.10
MAX_SPREAD = 0.003               # 30 bps estimated spread
MAX_PARTICIPATION = 0.25         # notional vs median hourly quote volume
MIN_SIZE_FRACTION = 0.2          # below a fifth of base notional the costs stop being worth it
RETRACE_MAX = 0.5                # reaction already half-reversed -> complete
MIN_COVERAGE = 0.6               # fraction of lookback hours that must exist
DEFAULT_PARAMS = {"mode": 1, "k": 2.0}
GRID = [(m, k) for m in (1, -1) for k in (1.0, 2.0, 3.0, 5.0)]
MIN_TRAIN = 6

AI_SIZE = {"durable": 1.0, "temporary": 0.5, "contradicted_by_guidance": 0.5,
           "already_priced": 0.0, "too_uncertain": 0.0}


def _coverage(idx, start, end):
    return sum(1 for t in idx if start <= t < end) / max(1, (end - start) // HOUR)


def analyze(event: dict, snap: dict | None, hedge_pool: list[str] | None = None) -> dict:
    """Everything that is known at decision time, plus counterfactual outcomes."""
    a = {"event_id": event["event_id"], "gates": {}}
    g = a["gates"]
    g["event_data"] = (event["status"] == "complete",
                       "all required earnings fields verified" if event["status"] == "complete"
                       else "missing/unverified: " + ", ".join(event["validation"]["missing_required"]))
    if snap is None:
        g["market_data"] = (False, "no market snapshot")
        return a
    w = snap["window"]
    t_pre, t_obs, t_exit = w["t_pre"], w["t_obs"], w["t_exit"]
    a["times"] = w
    C, M = event["company_symbol"], universe.MARKET
    idx = {s: index(rows) for s, rows in snap["candles"].items()}
    look0 = t_pre - max(WINDOWS) * DAY

    problems = []
    for s in (C, M):
        if s not in idx:
            problems.append(f"{s} not listed on Bitget for this window")
            continue
        cov = _coverage(idx[s], look0, t_pre)
        if cov < MIN_COVERAGE:
            problems.append(f"{s} history covers {cov:.0%} of {max(WINDOWS)}d lookback")
        if price_at(idx[s], t_pre) is None or price_at(idx[s], t_obs) is None:
            problems.append(f"{s} missing price at event window")
    peers = {s: idx[s] for s in universe.peer_symbols(event["ticker"])
             if s in idx and _coverage(idx[s], look0, t_pre) >= MIN_COVERAGE
             and price_at(idx[s], t_pre) and price_at(idx[s], t_obs)}
    if len(peers) < 2:
        problems.append(f"sector basket has {len(peers)} usable peers (need 2)")
    a["peers"] = sorted(peers)
    if problems:
        g["market_data"] = (False, "; ".join(problems))
        return a
    g["market_data"] = (True, f"company, market and {len(peers)} sector peers cover the lookback")

    # factor models over several lookbacks
    fits = {}
    for d in WINDOWS:
        start = t_pre - d * DAY
        fits[d] = fit(hourly_returns(idx[C], start, t_pre), hourly_returns(idx[M], start, t_pre),
                      basket_returns(peers, start, t_pre))
    if not fits[PRIMARY]:
        g["market_data"] = (False, "not enough overlapping hours to estimate betas")
        return a
    R_c = window_return(idx[C], t_pre, t_obs)
    R_m = window_return(idx[M], t_pre, t_obs)
    R_s, n_s = basket_window_return(peers, t_pre, t_obs)
    spread_c = corwin_schultz(idx[C], t_pre - 7 * DAY, t_pre)
    decs = {d: decompose(f, R_c, R_m, R_s, spread_c) for d, f in fits.items() if f}
    a.update({
        "model": fits[PRIMARY], "robustness_models": {str(d): f for d, f in fits.items()},
        "decomposition": decs[PRIMARY],
        "robustness_residuals": {str(d): x["residual"] for d, x in decs.items()},
        "prices": {"company_pre": price_at(idx[C], t_pre), "company_obs": price_at(idx[C], t_obs),
                   "market_pre": price_at(idx[M], t_pre), "market_obs": price_at(idx[M], t_obs)},
        "window_returns": {"company": R_c, "market": R_m, "sector_basket": R_s, "sector_members": n_s},
    })
    residual = decs[PRIMARY]["residual"]

    # hedge instrument: best historical fit among tradeable proxies
    start = t_pre - PRIMARY * DAY
    rc = hourly_returns(idx[C], start, t_pre)
    cands = []
    pool = hedge_pool if hedge_pool is not None else universe.hedge_symbols(event["ticker"])
    etfs = set(universe.hedge_symbols(event["ticker"]))
    for h in pool:
        if h in idx and _coverage(idx[h], start, t_pre) >= MIN_COVERAGE and price_at(idx[h], t_obs):
            hf = hedge_fit(rc, hourly_returns(idx[h], start, t_pre))
            if hf:
                cands.append({"symbol": h, "kind": "index_etf" if h in etfs else "demo_stock", **hf})
    a["hedge_candidates"] = cands
    best = max(cands, key=lambda c: c["r2"]) if cands else None
    if not best or best["r2"] < MIN_HEDGE_R2:
        g["hedge"] = (False, "no hedge instrument with R2 >= %.2f" % MIN_HEDGE_R2
                      if cands else "no hedge instrument listed with enough history")
    else:
        g["hedge"] = (True, f"{best['symbol']} beta {best['beta']:.2f}, R2 {best['r2']:.2f}")
    a["hedge"] = best

    # costs and liquidity
    fee = float(snap["contracts"].get(C, {}).get("takerFeeRate") or 0.0006)
    slip_c = max(spread_c / 2 if spread_c == spread_c else 0.0, 0.0002) + 0.0001
    if best:
        sp_h = corwin_schultz(idx[best["symbol"]], t_pre - 7 * DAY, t_pre)
        slip_h = max(sp_h / 2 if sp_h == sp_h else 0.0, 0.0002) + 0.0001
        fee_h = float(snap["contracts"].get(best["symbol"], {}).get("takerFeeRate") or 0.0006)
        round_trip = 2 * (fee + slip_c) + abs(best["beta"]) * 2 * (fee_h + slip_h)
    else:
        slip_h, round_trip = None, 2 * (fee + slip_c)
    mqv = median_quote_volume(idx[C], t_pre - 7 * DAY, t_pre)
    participation = BASE_NOTIONAL / mqv if mqv > 0 else math.inf
    # Thin after-hours books do not disqualify a release; they cap the size it can carry. The cap
    # is the largest notional that stays inside MAX_PARTICIPATION of observed pre-event volume,
    # measured before the release, so this changes size and never the decision to look.
    liquidity_size = min(1.0, (MAX_PARTICIPATION * mqv) / BASE_NOTIONAL) if mqv > 0 else 0.0
    liquidity_size = round(liquidity_size, 4)
    a["costs"] = {"taker_fee": fee, "spread_est_company": spread_c, "slip_company": slip_c,
                  "slip_hedge": slip_h, "round_trip": round_trip,
                  "median_hourly_quote_volume": mqv, "participation": participation,
                  "liquidity_size": liquidity_size,
                  "liquidity_capped_notional": round(BASE_NOTIONAL * liquidity_size, 2)}
    liq_ok = spread_c <= MAX_SPREAD and liquidity_size >= MIN_SIZE_FRACTION
    g["liquidity"] = (liq_ok, f"spread est {spread_c * 1e4:.1f} bps, book carries "
                              f"${BASE_NOTIONAL * liquidity_size:,.0f} of the ${BASE_NOTIONAL:,.0f} base "
                              f"(participation cap {MAX_PARTICIPATION:.0%} of median hourly volume)")

    # robustness across model assumptions
    signs = {math.copysign(1, r) for r in a["robustness_residuals"].values()}
    robust = len(signs) == 1 and all(abs(r) >= round_trip for r in a["robustness_residuals"].values())
    g["robust"] = (robust, "residual sign and size stable across %s-day betas" % "/".join(map(str, WINDOWS))
                   if robust else "residual changes sign or falls below cost across beta windows")

    # reaction completeness: has the early move already half-reversed?
    path = [math.log(price_at(idx[C], t) / a["prices"]["company_pre"])
            for t in range(t_pre + HOUR, t_obs + HOUR, HOUR) if price_at(idx[C], t)]
    peak = max(path, key=abs) if path else 0.0
    retrace = 0.0 if not peak else (1 - R_c / peak if R_c * peak > 0 else 1.0)
    a["reaction_path"] = path
    g["reaction_open"] = (retrace < RETRACE_MAX, f"move retraced {retrace:.0%} from its early peak")

    # counterfactual outcomes (used ONLY to train later events)
    a["counterfactual"] = {}
    if best:
        for d in (1, -1):
            sim = run_trade(event, snap, a, d, 1.0)
            # train on the conservative-funding outcome so missing funding never flatters a rule
            a["counterfactual"][str(d)] = sim["net_conservative"] if sim else None
    a["residual"] = residual
    s = event.get("surprise") or {}
    a["surprise_sign"] = (1 if s["guidance_surprise_pct"] > 0 else -1 if s["guidance_surprise_pct"] < 0 else 0) if s else 0
    c = event.get("consensus") or {}
    a["consensus_surprise_pct"] = c.get("consensus_surprise_pct") if c.get("quality") == "ok" else None
    a["consensus_sign"] = 0 if a["consensus_surprise_pct"] is None else (
        1 if a["consensus_surprise_pct"] > 0 else -1 if a["consensus_surprise_pct"] < 0 else 0)
    return a


# Only these rules were present before the historical sample was scored, so
# only these rules may influence the walk-forward strategy.  Consensus arrived
# later and remains visible as a post-hoc diagnostic baseline, never a selector
# candidate.  This separation prevents a future replay from silently turning
# exploratory data into an apparently pre-declared strategy rule.
SELECTOR_VARIANTS = ("residual", "headline", "agreement")
DIAGNOSTIC_VARIANTS = ("consensus",)
VARIANTS = SELECTOR_VARIANTS + DIAGNOSTIC_VARIANTS


def variant_direction(v: str, a: dict, params: dict) -> int:
    rs = int(math.copysign(1, a["residual"]))
    if v == "residual":
        return int(params["mode"]) * rs
    if v == "headline":          # guidance-surprise direction, still hedged and gated
        return a.get("surprise_sign", 0)
    if v == "agreement":         # only when the company move and the surprise point the same way
        return rs if rs == a.get("surprise_sign") else 0
    if v == "consensus":         # post-hoc analyst-EPS diagnostic; not eligible for strategy selection
        return a.get("consensus_sign", 0)
    raise ValueError(v)


def _eligible(h):
    return h.get("counterfactual") and all(h["gates"].get(k, (False,))[0] for k in
                                           ("event_data", "market_data", "hedge", "liquidity", "robust", "reaction_open"))


def learn_variant(history: list[dict], params: dict) -> dict:
    train = [h for h in history if _eligible(h) and abs(h["residual"]) >= params["k"] * h["costs"]["round_trip"]]
    scores = {}
    for v in VARIANTS:
        scores[v] = round(sum((h["counterfactual"].get(str(d)) or 0.0) for h in train
                              if (d := variant_direction(v, h, params)) != 0), 2)
    if len(train) < MIN_TRAIN:
        return {"variant": "residual", "source": f"prior (only {len(train)} eligible training events)",
                "scores": scores, "eligible_variants": list(SELECTOR_VARIANTS)}
    best = max(SELECTOR_VARIANTS, key=lambda v: (scores[v], -SELECTOR_VARIANTS.index(v)))
    return {"variant": best, "source": "walk-forward", "n_train": len(train), "scores": scores,
            "eligible_variants": list(SELECTOR_VARIANTS)}


def _legs(event, a, direction, size, hedged=True):
    n = BASE_NOTIONAL * size
    legs = [{"symbol": event["company_symbol"], "side": direction, "notional": n,
             "slip": a["costs"]["slip_company"], "role": "company"}]
    if hedged and a.get("hedge"):
        legs.append({"symbol": a["hedge"]["symbol"], "side": -direction,
                     "notional": abs(a["hedge"]["beta"]) * n, "slip": a["costs"]["slip_hedge"], "role": "hedge"})
    return legs


def run_trade(event, snap, a, direction, size, hedged=True, tag="residual"):
    w = a["times"]
    return simulate(snap, _legs(event, a, direction, size, hedged), w["t_obs"], w["t_exit"],
                    MAX_LOSS_FRAC * BASE_NOTIONAL * size, f"{tag}:{event['event_id']}")


def attribute(event, snap, a, sim, direction) -> dict:
    """Split realized pair P&L into residual, factor error, slippage, fees, funding, timing."""
    idx = {s: index(r) for s, r in snap["candles"].items()}
    C, M = event["company_symbol"], universe.MARKET
    t0, t1 = sim["entry_ms"], sim["exit_ms"]
    comp = next(l for l in sim["legs"] if l["role"] == "company")
    n = comp["notional"]
    R_c = math.log(comp["exit_mid"] / comp["entry_mid"])
    R_m = window_return(idx[M], t0, t1) or 0.0
    peers = {s: idx[s] for s in a["peers"]}
    R_s, _ = basket_window_return(peers, t0, t1)
    mdl = a["model"]
    factor_pred = mdl["beta_market"] * R_m + mdl["beta_sector"] * ((R_s or 0.0) - mdl["b_sector_market"] * R_m)
    residual_pnl = direction * n * (R_c - factor_pred)
    timing = 0.0
    for l in sim["legs"]:
        side = 1 if l["side"] == "long" else -1
        o, c = open_at(idx[l["symbol"]], t0), price_at(idx[l["symbol"]], t0)
        if o and c:
            timing += side * l["notional"] * (o / c - 1)
    hedge = next((l for l in sim["legs"] if l["role"] == "hedge"), None)
    return {
        "company_leg": comp["net"], "hedge_leg": hedge["net"] if hedge else 0.0,
        "residual": residual_pnl, "factor_error": sim["gross_mid"] - residual_pnl,
        "slippage": -sim["slippage"], "fees": -sim["fees"], "funding": sim["funding"],
        "timing_signal_to_fill": timing, "net": sim["net"],
        "hold_returns": {"company": R_c, "market": R_m, "sector_basket": R_s, "factor_predicted": factor_pred},
    }


def learn_params(history: list[dict]) -> dict:
    """Pick direction mode and entry threshold from strictly earlier events."""
    train = [h for h in history if _eligible(h)]
    if len(train) < MIN_TRAIN:
        return {**DEFAULT_PARAMS, "source": f"prior (only {len(train)} eligible training events)",
                "n_train": len(train)}
    best, best_pnl = None, -math.inf
    for mode, k in GRID:
        pnl = sum(h["counterfactual"][str(int(mode * math.copysign(1, h["residual"])))] or 0.0
                  for h in train if abs(h["residual"]) >= k * h["costs"]["round_trip"])
        if pnl > best_pnl + 1e-9:
            best, best_pnl = (mode, k), pnl
    return {"mode": best[0], "k": best[1], "source": "walk-forward", "n_train": len(train),
            "train_pnl": best_pnl, "train_events": [h["event_id"] for h in train]}


def decide(event, a, params, interp) -> dict:
    g = dict(a["gates"])
    if "residual" in a:
        thr = params["k"] * a["costs"]["round_trip"]
        g["residual_vs_cost"] = (abs(a["residual"]) >= thr,
                                 f"|residual| {abs(a['residual']) * 100:.2f}% vs threshold {thr * 100:.2f}% "
                                 f"({params['k']}x round-trip cost)")
    size = 0.0
    if interp is None:
        g["ai_interpretation"] = (True, "AI gate disabled for this run")
        size = 1.0
    elif interp.get("status") != "ok":
        g["ai_interpretation"] = (False, f"interpretation {interp.get('status', 'unavailable')}: "
                                         f"{interp.get('detail', 'no validated LLM output')}")
    else:
        size = AI_SIZE[interp["label"]]
        g["ai_interpretation"] = (size > 0, f"{interp['label']} (confidence {interp['confidence']:.2f}) -> size x{size}")
    failed = [k for k, v in g.items() if not v[0]]
    if failed or "residual" not in a:
        return {"decision": "NO_TRADE", "reasons": failed or ["analysis incomplete"],
                "gates": {k: {"pass": v[0], "detail": v[1]} for k, v in g.items()}, "size": 0.0}
    direction = int(params["mode"] * math.copysign(1, a["residual"]))
    # The book, not the conviction, sets the ceiling: size down to what the venue can absorb.
    liquidity_size = float(a["costs"].get("liquidity_size", 1.0))
    size = round(size * liquidity_size, 4)
    return {
        "decision": "TRADE", "direction": direction, "size": size,
        "structure": ("long company / short hedge" if direction > 0 else "short company / long hedge"),
        "gates": {k: {"pass": v[0], "detail": v[1]} for k, v in g.items()}, "reasons": [],
    }
