"""Curated Bitget universe: companies, sector peer baskets, market and hedge proxies.

Symbols are Bitget USDT-M perpetuals (`<TICKER>USDT`). Only companies that
publish a numeric next-quarter revenue outlook in their earnings press release
are included, so the guidance baseline for the company-guidance surprise always
has a primary-source citation. This is not an analyst-consensus surprise.
"""

MARKET = "QQQUSDT"  # broad-market proxy; the only index perp listed across the full sample

COMPANIES = {
    "NVDA": "semis", "AMD": "semis", "AVGO": "semis", "MU": "semis",
    "INTC": "semis", "MRVL": "semis", "QCOM": "semis", "KLAC": "semis", "TXN": "semis",
    "META": "internet", "AMZN": "internet",
    "PLTR": "software", "CRM": "software", "PANW": "software", "CRWD": "software", "MDB": "software",
    "HPE": "hardware", "SMCI": "hardware",
}

# Equal-weight sector baskets (the company itself is always excluded; peers without
# enough Bitget history at an event are dropped automatically).
PEERS = {
    "semis": ["NVDA", "AMD", "AVGO", "MU", "INTC", "MRVL", "TSM", "ASML", "ARM", "QCOM", "AMAT",
              "KLAC", "TXN", "LRCX", "ADI"],
    "internet": ["META", "AMZN", "GOOGL", "AAPL", "MSFT", "NFLX"],
    "software": ["MSFT", "ORCL", "CRM", "NOW", "SNOW", "PANW", "CRWD", "MDB", "ADBE", "PLTR"],
    "hardware": ["HPE", "SMCI", "DELL", "WDC", "ANET", "CSCO"],
}

# Tradeable single-instrument hedge candidates; the best historical fit wins.
HEDGES = {
    "semis": ["SMHUSDT", "QQQUSDT", "SPYUSDT"],
    "internet": ["QQQUSDT", "SPYUSDT"],
    "software": ["QQQUSDT", "SPYUSDT", "XLKUSDT"],
    "hardware": ["QQQUSDT", "SPYUSDT", "XLKUSDT"],
}


# Live Bitget Demo lists none of HEDGES (checked 2026-09-13). When a strategy hedge is missing on Demo,
# the live path may substitute the best-fitting Demo-listed stock perp, labelled as a substitute.
DEMO_FALLBACK_HEDGES = ["AAPLUSDT", "TSLAUSDT", "METAUSDT", "AMZNUSDT", "NVDAUSDT"]


def sym(ticker: str) -> str:
    return ticker + "USDT"


def peer_symbols(ticker: str) -> list[str]:
    return [sym(p) for p in PEERS[COMPANIES[ticker]] if p != ticker]


def hedge_symbols(ticker: str) -> list[str]:
    return HEDGES[COMPANIES[ticker]]


def snapshot_symbols(ticker: str) -> list[str]:
    out = [sym(ticker), MARKET] + hedge_symbols(ticker) + peer_symbols(ticker) + DEMO_FALLBACK_HEDGES
    return list(dict.fromkeys(out))
