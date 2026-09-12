"""Paper executor: fills, fees, slippage, funding and stop handling per leg."""
from .factors import HOUR, index, open_at, price_at


def simulate(snap: dict, legs: list[dict], t_entry: int, t_exit: int, max_loss: float, tag: str) -> dict | None:
    """Simulate a set of legs entered at t_entry and closed at t_exit (or at the stop).

    legs: [{symbol, side (+1 long / -1 short), notional, slip (fraction), role}]
    Entry executes at the open of the t_entry candle, exits at the close of the
    exit hour; both are adjusted by `slip` against the trader. A position is
    stopped at the first hourly close where combined mark-to-mid P&L <= -max_loss.
    """
    idx = {l["symbol"]: index(snap["candles"].get(l["symbol"], [])) for l in legs}
    entry_mid = {}
    for l in legs:
        p = open_at(idx[l["symbol"]], t_entry) or price_at(idx[l["symbol"]], t_entry)
        if not p:
            return None
        entry_mid[l["symbol"]] = p
    qty = {l["symbol"]: l["notional"] / entry_mid[l["symbol"]] for l in legs}

    exit_t, stopped = t_exit, False
    for t in range(t_entry + HOUR, t_exit + HOUR, HOUR):
        marks = [price_at(idx[l["symbol"]], t) for l in legs]
        if any(m is None for m in marks):
            continue
        pnl = sum(l["side"] * (m - entry_mid[l["symbol"]]) * qty[l["symbol"]] for l, m in zip(legs, marks))
        if pnl <= -max_loss:
            exit_t, stopped = t, True
            break

    out_legs, orders = [], []
    totals = {"gross_mid": 0.0, "fees": 0.0, "slippage": 0.0, "funding": 0.0, "net": 0.0}
    funding_complete = True
    for l in legs:
        s, side, q = l["symbol"], l["side"], qty[l["symbol"]]
        exit_mid = price_at(idx[s], exit_t)
        if exit_mid is None:
            return None
        fee_rate = float(snap["contracts"].get(s, {}).get("takerFeeRate") or 0.0006)
        entry_fill = entry_mid[s] * (1 + side * l["slip"])
        exit_fill = exit_mid * (1 - side * l["slip"])
        fees = fee_rate * q * (entry_fill + exit_fill)
        fund_info = snap.get("funding", {}).get(s, {})
        earliest = fund_info.get("earliest_available")
        funding, n_settle = 0.0, 0
        if earliest is not None and earliest <= t_entry:
            for x in fund_info.get("settlements", []):
                if t_entry < x["t"] <= exit_t:
                    mark = price_at(idx[s], x["t"]) or entry_mid[s]
                    funding += -side * x["rate"] * q * mark
                    n_settle += 1
        else:
            funding_complete = False
        gross_mid = side * (exit_mid - entry_mid[s]) * q
        slippage = q * (abs(entry_fill - entry_mid[s]) + abs(exit_fill - exit_mid))
        net = side * (exit_fill - entry_fill) * q - fees + funding
        out_legs.append({
            "role": l["role"], "symbol": s, "side": "long" if side > 0 else "short", "qty": q,
            "notional": l["notional"], "entry_mid": entry_mid[s], "entry_fill": entry_fill,
            "exit_mid": exit_mid, "exit_fill": exit_fill, "fee_rate": fee_rate, "fees": fees,
            "slippage": slippage, "funding": funding, "funding_settlements": n_settle,
            "gross_mid": gross_mid, "net": net,
        })
        for kind, t, px, sd in (("entry", t_entry, entry_fill, side), ("exit", exit_t, exit_fill, -side)):
            orders.append({"tag": tag, "leg": l["role"], "symbol": s, "type": kind, "time_ms": t,
                           "side": "buy" if sd > 0 else "sell", "qty": q, "price": px,
                           "notional": q * px, "fee": fee_rate * q * px})
        for k, v in (("gross_mid", gross_mid), ("fees", fees), ("slippage", slippage),
                     ("funding", funding), ("net", net)):
            totals[k] += v
    return {
        "legs": out_legs, "orders": orders, **totals,
        "entry_ms": t_entry, "exit_ms": exit_t, "stopped": stopped,
        "holding_hours": (exit_t - t_entry) / HOUR,
        "funding_data": "complete" if funding_complete else "unavailable_for_period",
        "funding_assumption": "observed_settlements_only" if funding_complete else
        "missing_settlements_treated_as_zero_for_simulation",
    }
