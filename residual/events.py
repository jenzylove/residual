"""Build the earnings event dataset from SEC EDGAR with verified provenance."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import edgar, universe
from .extract import extract_all, verify_field
from .net import cache_file_for, fetch

ROOT = Path(__file__).resolve().parent.parent
EVENTS_FILE = ROOT / "data" / "events.json"
REQUIRED = ("revenue_actual", "revenue_guidance_prior", "revenue_guidance_next", "revenue_prior_actual")


def _nth_sunday(year, month, n):
    d = datetime(year, month, 1, tzinfo=timezone.utc)
    d += timedelta(days=(6 - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def eastern_offset_hours(dt: datetime) -> int:
    """US Eastern UTC offset (DST from 2nd Sunday of March to 1st Sunday of November)."""
    start = _nth_sunday(dt.year, 3, 2) + timedelta(hours=7)
    end = _nth_sunday(dt.year, 11, 1) + timedelta(hours=6)
    return -4 if start <= dt < end else -5


def session(dt: datetime) -> str:
    et = dt + timedelta(hours=eastern_offset_hours(dt))
    minutes = et.hour * 60 + et.minute
    if minutes < 9 * 60 + 30:
        return "pre_market"
    if minutes >= 16 * 60:
        return "after_market"
    return "intraday"


def _load_release(filing: dict) -> dict:
    url = edgar.press_release_url(filing)
    raw = fetch(url)
    text = edgar.html_to_text(raw)
    return {"url": url, "raw": raw, "text": text,
            "fields": extract_all(filing["ticker"], raw, text, url)}


def _pct(a, b):
    return (a / b - 1) * 100


def build_event(filing: dict, prev: dict) -> dict:
    cur, old = _load_release(filing), _load_release(prev)
    release = edgar.accepted_utc(filing["accepted_et"])
    earnings = {
        "revenue_actual": cur["fields"]["revenue_actual"],
        "revenue_guidance_prior": old["fields"]["revenue_guidance_next"],
        "revenue_guidance_next": cur["fields"]["revenue_guidance_next"],
        "revenue_prior_actual": old["fields"]["revenue_actual"],
        "eps_diluted": cur["fields"]["eps_diluted"],
        "gross_margin": cur["fields"]["gross_margin"],
    }
    checks = []
    for name, f in earnings.items():
        if f is None:
            checks.append({"field": name, "ok": False, "detail": "not found in source"})
            continue
        doc = old if f["source_url"] == old["url"] else cur
        ok, detail = verify_field(f, doc["text"], doc["raw"])
        f["verified"] = ok
        checks.append({"field": name, "ok": ok, "detail": detail})
    missing = [n for n in REQUIRED if not (earnings[n] and earnings[n].get("verified"))]

    surprise = None
    if not missing:
        a = earnings["revenue_actual"]["value"]
        g = earnings["revenue_guidance_prior"]
        nxt = earnings["revenue_guidance_next"]["value"]
        guided_growth = _pct(nxt, a)
        prior_growth = _pct(g["value"], earnings["revenue_prior_actual"]["value"])
        diff = guided_growth - prior_growth
        surprise = {
            "expected_source": "company's prior-quarter revenue outlook midpoint",
            "revenue_expected": g["value"], "revenue_actual": a,
            "revenue_surprise_pct": round(_pct(a, g["value"]), 3),
            "vs_guidance_band": "above" if a > g["high"] else "below" if a < g["low"] else "inside",
            "next_quarter_guidance_mid": nxt,
            "guided_sequential_growth_pct": round(guided_growth, 3),
            "prior_guided_sequential_growth_pct": round(prior_growth, 3),
            "guidance_direction": "raised" if diff > 1 else "lowered" if diff < -1 else "maintained",
        }

    return {
        "event_id": f"{filing['ticker']}-{release.date().isoformat()}",
        "ticker": filing["ticker"],
        "company_symbol": universe.sym(filing["ticker"]),
        "sector_group": universe.COMPANIES[filing["ticker"]],
        "cik": filing["cik"],
        "accession": filing["accession"],
        "release_utc": release.isoformat().replace("+00:00", "Z"),
        "release_ms": int(release.timestamp() * 1000),
        "release_session": session(release),
        "source": {"press_release_url": cur["url"], "filing_index_url": filing["index_url"],
                   "sha256": earnings["revenue_actual"]["source_sha256"] if earnings["revenue_actual"] else None,
                   "cache_file": cache_file_for(cur["url"])},
        "prior_source": {"press_release_url": old["url"], "filing_index_url": prev["index_url"],
                         "accession": prev["accession"], "cache_file": cache_file_for(old["url"])},
        "earnings": earnings,
        "commentary": cur["fields"]["commentary"],
        "surprise": surprise,
        "validation": {"checks": checks, "missing_required": missing,
                       "all_required_verified": not missing},
        "status": "complete" if not missing else "data_incomplete",
    }


def build_dataset(since: str = "2025-10-15", until: str | None = None, tickers=None, cache=True) -> list[dict]:
    events = []
    for t in tickers or universe.COMPANIES:
        filings = edgar.earnings_filings(t, cache=cache)
        for i, f in enumerate(filings):
            day = f["accepted_et"][:10]
            if i == 0 or day < since or (until and day > until):
                continue
            ev = build_event(f, filings[i - 1])
            events.append(ev)
            print(f"  {ev['event_id']:<16} {ev['status']:<16} "
                  f"surprise={ev['surprise']['revenue_surprise_pct'] if ev['surprise'] else '-'}", flush=True)
    return sorted(events, key=lambda e: e["release_ms"])


def save_events(events: list[dict]):
    EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    EVENTS_FILE.write_text(json.dumps(events, indent=1), encoding="utf-8")


def load_events() -> list[dict]:
    return json.loads(EVENTS_FILE.read_text(encoding="utf-8")) if EVENTS_FILE.exists() else []
