"""SEC EDGAR: earnings 8-K (Item 2.02) discovery and press-release text."""
import html
import re
from datetime import datetime, timezone

from .net import fetch, fetch_json

CIKS = {
    "NVDA": 1045810, "META": 1326801, "AMZN": 1018724, "PLTR": 1321655,
    "AMD": 2488, "AVGO": 1730168, "MU": 723125, "INTC": 50863,
    "NFLX": 1065280, "MRVL": 1835632,
    "QCOM": 804328, "KLAC": 319201, "TXN": 97476, "HPE": 1645590, "SMCI": 1375365,
    "CRM": 1108524, "PANW": 1327567, "CRWD": 1535527, "MDB": 1441816,
}


def earnings_filings(ticker: str, *, cache: bool = True) -> list[dict]:
    """All Item 2.02 8-K filings in the recent submissions list, oldest first."""
    cik = CIKS[ticker]
    sub = fetch_json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", cache=cache)
    r = sub["filings"]["recent"]
    out = []
    for i, form in enumerate(r["form"]):
        if form == "8-K" and "2.02" in r["items"][i]:
            acc = r["accessionNumber"][i]
            accepted = datetime.strptime(r["acceptanceDateTime"][i][:19], "%Y-%m-%dT%H:%M:%S")
            out.append({
                "ticker": ticker,
                "cik": cik,
                "accession": acc,
                "filing_date": r["filingDate"][i],
                "accepted_et": accepted.isoformat(),
                "index_url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/",
            })
    return sorted(out, key=lambda f: f["accepted_et"])


_PR_HINTS = re.compile(r"(pr|press|ex99|ex-99|99-?1|exhibit99|earnings)", re.I)


def press_release_url(filing: dict) -> str:
    """Locate the Exhibit 99.1 press release inside a filing."""
    items = fetch_json(filing["index_url"] + "index.json")["directory"]["item"]
    names = [i["name"] for i in items if i["name"].lower().endswith((".htm", ".html"))]
    names = [n for n in names if not n.endswith("-index.html") and not n.endswith("-index-headers.html")
             and not n.startswith("R") and "commentary" not in n.lower()]
    primary = [n for n in names if re.match(r"^[a-z]+-\d{8}\.htm$", n)]
    exhibits = [n for n in names if n not in primary]
    ranked = sorted(exhibits, key=lambda n: (not _PR_HINTS.search(n), len(n)))
    if ranked:
        return filing["index_url"] + ranked[0]
    return filing["index_url"] + primary[0]


def html_to_text(raw: bytes) -> str:
    s = raw.decode("utf-8", errors="replace")
    s = re.sub(r"(?is)<(script|style).*?</\1>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|h\d)>", "\n", s)
    s = re.sub(r"(?i)</t[dh]>", " | ", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s).replace("\xa0", " ").replace("​", "")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\s*\n\s*", "\n", s)
    return s.strip()


def normalize(s: str) -> str:
    """Whitespace/quote normalization used for snippet verification."""
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("—", "-").replace("–", "-")
    return re.sub(r"\s+", " ", s).strip()


def press_release_text(url: str) -> str:
    return html_to_text(fetch(url))


def accepted_utc(accepted: str) -> datetime:
    """EDGAR acceptanceDateTime is UTC (AAPL's 4:30pm ET release reads 20:30Z)."""
    return datetime.fromisoformat(accepted).replace(tzinfo=timezone.utc)
