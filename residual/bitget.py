"""Bitget public market data (USDT-M stock perpetuals)."""
from datetime import datetime, timezone

from .net import fetch_json

BASE = "https://api.bitget.com"
PT = "USDT-FUTURES"
HOUR_MS = 3_600_000


def _data(path: str, *, cache: bool):
    j = fetch_json(BASE + path, cache=cache)
    if j.get("code") != "00000":
        raise RuntimeError(f"bitget error {j.get('code')}: {j.get('msg')} ({path})")
    return j["data"]


def hourly_candles(symbol: str, start_ms: int, end_ms: int) -> list[dict]:
    """Hourly candles whose open time lies in [start_ms, end_ms).

    Pages are requested with endTime aligned to 200-hour blocks so cache keys are
    stable; blocks entirely in the past are immutable and served from cache.
    """
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    block = 200 * HOUR_MS
    rows: dict[int, dict] = {}
    b_end = ((end_ms // block) + 1) * block
    while b_end > start_ms:
        immutable = b_end < now_ms - 2 * HOUR_MS
        data = _data(
            f"/api/v2/mix/market/history-candles?symbol={symbol}&productType={PT}"
            f"&granularity=1H&endTime={b_end}&limit=200",
            cache=immutable,
        )
        for c in data:
            t = int(c[0])
            if start_ms <= t < end_ms:
                rows[t] = {"t": t, "o": float(c[1]), "h": float(c[2]), "l": float(c[3]),
                           "c": float(c[4]), "v": float(c[5]), "qv": float(c[6])}
        if not data:
            break
        b_end -= block
    return [rows[k] for k in sorted(rows)]


def contracts(*, cache: bool = True) -> dict[str, dict]:
    return {c["symbol"]: c for c in _data(f"/api/v2/mix/market/contracts?productType={PT}", cache=cache)}


def ticker(symbol: str) -> dict:
    return _data(f"/api/v2/mix/market/ticker?symbol={symbol}&productType={PT}", cache=False)[0]


def depth(symbol: str, limit: int = 15) -> dict:
    return _data(f"/api/v2/mix/market/merge-depth?symbol={symbol}&productType={PT}&limit={limit}", cache=False)


def funding_history(symbol: str, *, cache: bool = False) -> list[dict]:
    """All funding settlements Bitget still serves (roughly the last 90 days)."""
    out = []
    for page in range(1, 20):
        d = _data(f"/api/v2/mix/market/history-fund-rate?symbol={symbol}&productType={PT}"
                  f"&pageSize=100&pageNo={page}", cache=cache)
        if not d:
            break
        out += [{"t": int(x["fundingTime"]), "rate": float(x["fundingRate"])} for x in d]
    return sorted(out, key=lambda x: x["t"])
