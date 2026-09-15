"""Deterministic earnings extraction with provenance.

Every numeric value is captured by a regex over the normalized press-release
text. The exact matched snippet, the source URL and the SHA-256 of the source
bytes are stored with the value, and `verify_field` re-derives the value from
the snippet before anything enters the model.
"""
import hashlib
import re

from .edgar import normalize

EXTRACTOR_VERSION = "regex-v1"
B = 1000.0  # USD billions -> USD millions


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def _point(g):
    v = _num(g[0]) * B
    return v, v


def _range(g):
    return _num(g[0]) * B, _num(g[1]) * B


def _pct_band(g):
    mid, pct = _num(g[0]) * B, _num(g[1]) / 100
    return mid * (1 - pct), mid * (1 + pct)


def _abs_band_millions(g):
    mid, band = _num(g[0]) * B, _num(g[1])
    return mid - band, mid + band


def _range_millions(g):
    return _num(g[0]), _num(g[1])


def _abs_band_unit(g):
    mid = _num(g[0]) * B
    band = _num(g[1]) * (B if g[2].lower() == "billion" else 1)
    return mid - band, mid + band


# (pattern, flags, parser) -> parser returns USD millions
ACTUAL = {
    "NVDA": (r"revenue for the \w+ quarter ended [A-Z][a-z]+ \d{1,2}, \d{4}, of \$(\d+(?:\.\d+)?) billion", re.I, lambda g: _num(g[0]) * B),
    "META": (r"Revenue was \$(\d+(?:\.\d+)?) billion", 0, lambda g: _num(g[0]) * B),
    "AMZN": (r"Net sales increased \d+% to \$(\d+(?:\.\d+)?) billion", 0, lambda g: _num(g[0]) * B),
    "PLTR": (r"Revenue grew \d+% year-over-year and \d+% quarter-over-quarter to \$(\d+(?:\.\d+)?) billion", 0, lambda g: _num(g[0]) * B),
    "AMD": (r"revenue was (?:a record )?\$(\d+(?:\.\d+)?) billion", 0, lambda g: _num(g[0]) * B),
    "AVGO": (r"Revenue of \$([\d,]+(?:\.\d+)?) (million|billion)", 0,
             lambda g: _num(g[0]) * (B if g[1] == "billion" else 1)),
    "MU": (r"Revenue of \$(\d+(?:\.\d+)?) billion", 0, lambda g: _num(g[0]) * B),
    "INTC": (r"revenue was \$(\d+(?:\.\d+)?) billion", 0, lambda g: _num(g[0]) * B),
    "MRVL": (r"revenue for the \w+ quarter of fiscal \d{4} was \$(\d+(?:\.\d+)?) billion", re.I, lambda g: _num(g[0]) * B),
    # universe expansion (Sep 2026): Bitget listed US filers with a numeric next-quarter revenue outlook
    "QCOM": (r"Revenues \| \$([\d,]+) \|", 0, lambda g: _num(g[0])),  # GAAP income statement, USD millions
    "KLAC": (r"total revenues were \$(\d+(?:\.\d+)?) billion", re.I, lambda g: _num(g[0]) * B),
    "TXN": (r"reported \w+ quarter revenue of \$(\d+(?:\.\d+)?) billion", 0, lambda g: _num(g[0]) * B),
    # headline line only; segment lines ("Networking revenue was ...") must never match
    "HPE": [(r"Revenue : \$(\d+(?:\.\d+)?) billion, (?:up|down) \d+% from the prior-year period", 0, lambda g: _num(g[0]) * B),
            (r"Quarter Fiscal \d{4} Financial Results • Revenue : \$(\d+(?:\.\d+)?) billion", 0, lambda g: _num(g[0]) * B)],
    "SMCI": (r"Net sales of \$(\d+(?:\.\d+)?) billion versus", 0, lambda g: _num(g[0]) * B),
    "CRM": (r"(?:• Revenue|quarter revenue) of \$(\d+(?:\.\d+)?) billion, up", 0, lambda g: _num(g[0]) * B),
    "PANW": (r"Total revenue for the fiscal \w+ quarter \d{4} grew \d+% year over year to \$(\d+(?:\.\d+)?) billion", 0, lambda g: _num(g[0]) * B),
    "CRWD": (r"Total revenue was \$(\d+(?:\.\d+)?) billion", 0, lambda g: _num(g[0]) * B),
    "MDB": (r"Total revenue was \$(\d+(?:\.\d+)?) million", 0, lambda g: _num(g[0])),
}

# Next-quarter revenue outlook -> (low, high) in USD millions
GUIDE = {
    "NVDA": (r"Revenue is expected to be \$(\d+(?:\.\d+)?) billion, plus or minus (\d+(?:\.\d+)?)%", 0, _pct_band),
    "META": (r"total revenue to be in the range of \$(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?) billion", 0, _range),
    "AMZN": (r"Net sales are expected to be between \$(\d+(?:\.\d+)?) billion and \$(\d+(?:\.\d+)?) billion", 0, _range),
    "PLTR": (r"Revenue of between \$(\d+(?:\.\d+)?) - \$(\d+(?:\.\d+)?) billion", 0, _range),
    "AMD": (r"AMD expects revenue to be approximately \$(\d+(?:\.\d+)?) billion, plus or minus \$(\d+(?:\.\d+)?) million", 0, _abs_band_millions),
    "AVGO": (r"revenue guidance of approximately \$(\d+(?:\.\d+)?) billion", re.I, _point),
    "MU": (r"Revenue \| \$(\d+(?:\.\d+)?) billion ± \$(\d+(?:\.\d+)?) (billion|million)", 0, _abs_band_unit),
    "INTC": (r"Forecasting [a-z]+-quarter \d{4} revenue of \$(\d+(?:\.\d+)?) billion to \$(\d+(?:\.\d+)?) billion", 0, _range),
    "MRVL": (r"Net revenue is expected to be \$(\d+(?:\.\d+)?) billion \+/- (\d+(?:\.\d+)?)%", 0, _pct_band),
    "QCOM": (r"Revenues \| \| \$(\d+(?:\.\d+)?)B - \$(\d+(?:\.\d+)?)B", 0, _range),
    "KLAC": [(r"Total revenues are expected to be in a range of \$(\d+(?:\.\d+)?) billion \+/- \$(\d+(?:\.\d+)?) million", 0, _abs_band_millions),
             (r"Total revenues is expected to be in a range of \$(\d+(?:\.\d+)?) billion \+/- \$(\d+(?:\.\d+)?) million", 0, _abs_band_millions)],
    "TXN": (r"outlook is for revenue in the range of \$(\d+(?:\.\d+)?) billion to \$(\d+(?:\.\d+)?) billion", 0, _range),
    "HPE": [(r"HPE estimates revenue to be in the range of \$(\d+(?:\.\d+)?) billion to \$(\d+(?:\.\d+)?) billion", 0, _range),
            (r"HPE estimates revenue to be in the range of \$(\d+(?:\.\d+)?) billion and \$(\d+(?:\.\d+)?) billion", 0, _range)],
    "SMCI": [(r"The Company expects net sales in the range of \$(\d+(?:\.\d+)?) billion and \$(\d+(?:\.\d+)?) billion", 0, _range),
             (r"The Company expects net sales of \$(\d+(?:\.\d+)?) billion to \$(\d+(?:\.\d+)?) billion", 0, _range),
             (r"The Company expects net sales of at least \$(\d+(?:\.\d+)?) billion for the", 0, _point)],
    "CRM": [(r"quarter FY\d+ revenue guidance of \$(\d+(?:\.\d+)?) billion to \$(\d+(?:\.\d+)?) billion", 0, _range),
            (r"Revenue \| \$(\d+(?:\.\d+)?) - \$(\d+(?:\.\d+)?) billion", 0, _range)],
    "PANW": (r"Total revenue in the range of \$(\d+(?:\.\d+)?) billion to \$(\d+(?:\.\d+)?) billion", 0, _range),
    "CRWD": (r"Total revenue \| \$([\d,]+(?:\.\d+)?) - \$([\d,]+(?:\.\d+)?) million", 0, _range_millions),
    "MDB": [(r"Revenues are expected to be in the range of: \| \$(\d+(?:\.\d+)?) million to \$(\d+(?:\.\d+)?) million", 0, _range_millions),
            (r"Revenue \| \$(\d+(?:\.\d+)?) million to \$(\d+(?:\.\d+)?) million", 0, _range_millions)],
}

EPS = [
    (r"(?:GAAP )?earnings per diluted share (?:was|were|of) \$(\d+(?:\.\d+)?)", re.I),
    (r"diluted earnings per share (?:was|were|of) \$(\d+(?:\.\d+)?)", re.I),
    (r"Diluted EPS was \$(\d+(?:\.\d+)?)", 0),
    (r"(?:GAAP )?EPS (?:of|was) \$(\d+(?:\.\d+)?)", 0),
]
# Reported GAAP gross margin (percent), per company, first match = current quarter. Only companies whose
# release states it unambiguously; KLAC (guidance-style row), SMCI (unclear column) and AVGO/MU (dollar
# values) are deliberately not covered. Optional evidence: never used by the model.
GROSS_MARGIN = {
    "NVDA": [(r"Gross margin \| (\d+(?:\.\d+)?) \| %", 0)],
    "AMD": [(r"gross margin was (\d+(?:\.\d+)?)%", 0)],
    "INTC": [(r"GAAP gross margin percentage \| \| (\d+(?:\.\d+)?) \| %", 0)],
    "MRVL": [(r"GAAP gross margin \| \| (\d+(?:\.\d+)?) \| %", 0)],
    "MDB": [(r"representing a (\d+(?:\.\d+)?)% gross margin", 0)],
}
COMMENTARY = r'"([^"]{80,900})[,.]?" (?:said|stated) ([^."]{3,160})'


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _field(kind, ticker, pattern, flags, value, snippet, src):
    return {
        "value": value, "unit": "USD_millions" if kind.startswith("revenue") else kind_unit(kind),
        "snippet": snippet, "pattern": pattern, "flags": flags,
        "source_url": src["url"], "source_sha256": src["sha256"],
        "extractor": f"{EXTRACTOR_VERSION}:{ticker}:{kind}",
    }


def kind_unit(kind: str) -> str:
    return {"eps_diluted": "USD_per_share", "gross_margin": "percent"}.get(kind, "USD_millions")


def _specs(table, ticker):
    """A company may word its release differently over time; alternates are tried in order."""
    spec = table[ticker]
    return spec if isinstance(spec, list) else [spec]


def _match(table, ticker, norm):
    for pattern, flags, parse in _specs(table, ticker):
        m = re.search(pattern, norm, flags)
        if m:
            return pattern, flags, parse, m
    return None, None, None, None


def extract_actual(ticker, norm, src):
    pattern, flags, parse, m = _match(ACTUAL, ticker, norm)
    if not m:
        return None
    return _field("revenue_actual", ticker, pattern, flags, round(parse(m.groups()), 3), m.group(0), src)


def extract_guidance(ticker, norm, src):
    pattern, flags, parse, m = _match(GUIDE, ticker, norm)
    if not m:
        return None
    lo, hi = parse(m.groups())
    f = _field("revenue_guidance", ticker, pattern, flags, round((lo + hi) / 2, 3), m.group(0), src)
    f["low"], f["high"] = round(lo, 3), round(hi, 3)
    return f


def _first(specs, kind, ticker, norm, src):
    for pattern, flags in specs:
        m = re.search(pattern, norm, flags)
        if m:
            return _field(kind, ticker, pattern, flags, _num(m.group(1)), m.group(0), src)
    return None


def extract_commentary(norm, src):
    m = re.search(COMMENTARY, norm)
    if not m:
        return None
    return {"text": m.group(1), "speaker": m.group(2).strip(), "snippet": m.group(0),
            "source_url": src["url"], "source_sha256": src["sha256"]}


def extract_all(ticker: str, raw: bytes, text: str, url: str) -> dict:
    norm = normalize(text)
    src = {"url": url, "sha256": sha256(raw)}
    return {
        "revenue_actual": extract_actual(ticker, norm, src),
        "revenue_guidance_next": extract_guidance(ticker, norm, src),
        "eps_diluted": _first(EPS, "eps_diluted", ticker, norm, src),
        "gross_margin": _first(GROSS_MARGIN.get(ticker, []), "gross_margin", ticker, norm, src),
        "commentary": extract_commentary(norm, src),
    }


def verify_field(field: dict, text: str, raw: bytes | None = None) -> tuple[bool, str]:
    """Re-derive a numeric field from its stored snippet and source document."""
    if not field:
        return False, "missing"
    if raw is not None and sha256(raw) != field["source_sha256"]:
        return False, "source document hash mismatch"
    if field["snippet"] not in normalize(text):
        return False, "snippet not found in source"
    m = re.fullmatch(field["pattern"], field["snippet"], field["flags"])
    if not m:
        return False, "snippet does not match extractor pattern"
    kind = field["extractor"].split(":")[-1]
    ticker = field["extractor"].split(":")[1]
    if kind == "revenue_actual":
        parse = next(pr for pt, fl, pr in _specs(ACTUAL, ticker) if pt == field["pattern"])
        value = round(parse(m.groups()), 3)
    elif kind == "revenue_guidance":
        parse = next(pr for pt, fl, pr in _specs(GUIDE, ticker) if pt == field["pattern"])
        lo, hi = parse(m.groups())
        value = round((lo + hi) / 2, 3)
    else:
        value = _num(m.group(1))
    if abs(value - field["value"]) > 1e-9:
        return False, f"value {field['value']} != re-derived {value}"
    return True, "ok"
