"""Deterministic factor decomposition on hourly Bitget candles.

Candle rows are [open_time_ms, open, high, low, close, quote_volume]. The price
"at" time T is the close of the candle that opened at T - 1h.

Model (per event, estimated on pre-event hours only):
    s_ex = r_sector - b_sm * r_market           (sector return orthogonal to market)
    r_c  = a + beta_m * r_market + beta_s * s_ex + e
Over the event window the observed company log return splits into
    market contribution  = beta_m * R_m
    sector contribution  = beta_s * (R_s - b_sm * R_m)
    liquidity effect     = expected bid/ask bounce (half the estimated spread)
    residual             = R_c - market - sector - liquidity
"""
import math
import statistics

HOUR = 3_600_000
DAY = 24 * HOUR


def index(rows) -> dict[int, list]:
    return {int(r[0]): r for r in rows}


def price_at(idx: dict, t: int):
    r = idx.get(t - HOUR)
    return r[4] if r else None


def open_at(idx: dict, t: int):
    r = idx.get(t)
    return r[1] if r else None


def hourly_returns(idx: dict, start: int, end: int) -> dict[int, float]:
    out = {}
    for t, r in idx.items():
        if start <= t < end and (t - HOUR) in idx:
            p0, p1 = idx[t - HOUR][4], r[4]
            if p0 > 0 and p1 > 0:
                out[t] = math.log(p1 / p0)
    return out


def basket_returns(peer_idx: dict[str, dict], start: int, end: int, min_members: int = 2) -> dict[int, float]:
    per = [hourly_returns(ix, start, end) for ix in peer_idx.values()]
    out = {}
    for t in set().union(*per) if per else []:
        vals = [p[t] for p in per if t in p]
        if len(vals) >= min_members:
            out[t] = sum(vals) / len(vals)
    return out


def _cov(x, y):
    mx, my = sum(x) / len(x), sum(y) / len(y)
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (len(x) - 1)


def fit(rc: dict, rm: dict, rs: dict) -> dict | None:
    ts = sorted(set(rc) & set(rm) & set(rs))
    if len(ts) < 48:
        return None
    c = [rc[t] for t in ts]
    m = [rm[t] for t in ts]
    s = [rs[t] for t in ts]
    vm = _cov(m, m)
    if vm <= 0:
        return None
    b_sm = _cov(s, m) / vm
    sx = [a - b_sm * b for a, b in zip(s, m)]
    vsx = _cov(sx, sx)
    beta_m = _cov(c, m) / vm
    beta_s = _cov(c, sx) / vsx if vsx > 0 else 0.0
    alpha = statistics.fmean(c) - beta_m * statistics.fmean(m) - beta_s * statistics.fmean(sx)
    resid = [ci - alpha - beta_m * mi - beta_s * si for ci, mi, si in zip(c, m, sx)]
    var_c = _cov(c, c)
    return {
        "n_hours": len(ts), "alpha": alpha, "beta_market": beta_m, "beta_sector": beta_s,
        "b_sector_market": b_sm, "resid_sigma_h": statistics.stdev(resid),
        "r2": 1 - _cov(resid, resid) / var_c if var_c > 0 else 0.0,
    }


def hedge_fit(rc: dict, rh: dict) -> dict | None:
    ts = sorted(set(rc) & set(rh))
    if len(ts) < 48:
        return None
    c = [rc[t] for t in ts]
    h = [rh[t] for t in ts]
    vh, vc = _cov(h, h), _cov(c, c)
    if vh <= 0 or vc <= 0:
        return None
    cov = _cov(c, h)
    return {"n_hours": len(ts), "beta": cov / vh, "r2": cov * cov / (vh * vc)}


def corwin_schultz(idx: dict, start: int, end: int) -> float:
    """High/low spread estimator (Corwin & Schultz 2012), averaged over the window."""
    ts = sorted(t for t in idx if start <= t < end)
    k = 3 - 2 * math.sqrt(2)
    vals = []
    for a, b in zip(ts, ts[1:]):
        if b - a != HOUR:
            continue
        h1, l1, h2, l2 = idx[a][2], idx[a][3], idx[b][2], idx[b][3]
        if min(h1, l1, h2, l2) <= 0:
            continue
        beta = math.log(h1 / l1) ** 2 + math.log(h2 / l2) ** 2
        gamma = math.log(max(h1, h2) / min(l1, l2)) ** 2
        alpha = (math.sqrt(2 * beta) - math.sqrt(beta)) / k - math.sqrt(gamma / k)
        vals.append(max(0.0, 2 * (math.exp(alpha) - 1) / (1 + math.exp(alpha))))
    return statistics.fmean(vals) if vals else float("nan")


def median_quote_volume(idx: dict, start: int, end: int) -> float:
    v = [r[5] for t, r in idx.items() if start <= t < end]
    return statistics.median(v) if v else 0.0


def window_return(idx: dict, t0: int, t1: int):
    p0, p1 = price_at(idx, t0), price_at(idx, t1)
    if not p0 or not p1:
        return None
    return math.log(p1 / p0)


def basket_window_return(peer_idx: dict[str, dict], t0: int, t1: int):
    vals = [r for r in (window_return(ix, t0, t1) for ix in peer_idx.values()) if r is not None]
    return (sum(vals) / len(vals), len(vals)) if len(vals) >= 2 else (None, len(vals))


def decompose(model: dict, R_c: float, R_m: float, R_s: float, spread: float) -> dict:
    market = model["beta_market"] * R_m
    sector = model["beta_sector"] * (R_s - model["b_sector_market"] * R_m)
    unexplained = R_c - market - sector
    half = spread / 2 if spread == spread else 0.0  # NaN-safe
    liquidity = math.copysign(min(abs(unexplained), half), unexplained) if unexplained else 0.0
    return {
        "observed": R_c, "market": market, "sector": sector,
        "liquidity": liquidity, "residual": unexplained - liquidity,
    }
