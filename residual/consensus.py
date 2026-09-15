"""Analyst EPS consensus (Alpha Vantage EARNINGS), cached with provenance.

Alpha Vantage reports `reportedDate`, so each quarter maps to one of our SEC events exactly,
with no fiscal-calendar guesswork. Values are stored per ticker under data/consensus/ with the
fetch timestamp and provider, and are re-read from there afterwards (free tier: 25 calls/day).
"""
import json
import os
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "data" / "consensus"
PROVIDER = "alphavantage:EARNINGS"


def _fetch(ticker: str) -> dict:
    key = os.environ.get("ALPHAVANTAGE_API_KEY")
    if not key:
        raise RuntimeError("ALPHAVANTAGE_API_KEY not set")
    url = f"https://www.alphavantage.co/query?function=EARNINGS&symbol={ticker}&apikey={key}"
    with urllib.request.urlopen(url, timeout=40) as r:
        body = json.load(r)
    rows = body.get("quarterlyEarnings")
    if not rows:
        raise RuntimeError(f"no quarterlyEarnings for {ticker}: {json.dumps(body)[:160]}")
    return {"ticker": ticker, "provider": PROVIDER,
            "source_url": f"https://www.alphavantage.co/query?function=EARNINGS&symbol={ticker}",
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "quarters": [{k: q.get(k) for k in ("fiscalDateEnding", "reportedDate", "reportedEPS",
                                                "estimatedEPS", "surprise", "surprisePercentage", "reportTime")}
                         for q in rows]}


def load(ticker: str, *, refresh: bool = False) -> dict | None:
    p = DIR / f"{ticker}.json"
    if p.exists() and not refresh:
        return json.loads(p.read_text(encoding="utf-8"))
    try:
        rec = _fetch(ticker)
    except Exception:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    DIR.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rec, indent=1), encoding="utf-8")
    return rec


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def for_event(ticker: str, release_date: str) -> dict | None:
    """The consensus record whose reportedDate matches this release (same day, or one day either side)."""
    rec = load(ticker)
    if not rec:
        return None
    for q in rec["quarters"]:
        d = q.get("reportedDate")
        if not d:
            continue
        if abs((int(d[8:10]) - int(release_date[8:10]))) <= 1 and d[:7] == release_date[:7]:
            est, act = _f(q.get("estimatedEPS")), _f(q.get("reportedEPS"))
            if est in (None, 0) or act is None:
                return None
            return {"eps_estimate": est, "eps_reported": act,
                    "consensus_surprise_pct": round((act - est) / abs(est) * 100, 3),
                    "fiscal_date_ending": q.get("fiscalDateEnding"), "reported_date": d,
                    "report_time": q.get("reportTime"), "provider": rec["provider"],
                    "source_url": rec["source_url"], "fetched_at": rec["fetched_at"],
                    "basis": "analyst EPS consensus at the time of the report (Alpha Vantage)"}
    return None
