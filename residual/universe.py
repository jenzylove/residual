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


# Bitget Demo Trading lists only these stock perpetuals (checked 2026-09-15) and no index/sector ETFs.
# The demo-executable mode is the same method restricted to instruments that venue can actually trade.
DEMO_LISTED_STOCKS = ["NVDAUSDT", "METAUSDT", "AMZNUSDT", "AAPLUSDT", "TSLAUSDT"]


def demo_companies() -> list[str]:
    return [t for t in COMPANIES if sym(t) in DEMO_LISTED_STOCKS]


def demo_hedge_pool(ticker: str) -> list[str]:
    return [s for s in DEMO_LISTED_STOCKS if s != sym(ticker)]


def sym(ticker: str) -> str:
    return ticker + "USDT"


def peer_symbols(ticker: str) -> list[str]:
    return [sym(p) for p in PEERS[COMPANIES[ticker]] if p != ticker]


def hedge_symbols(ticker: str) -> list[str]:
    return HEDGES[COMPANIES[ticker]]


def snapshot_symbols(ticker: str) -> list[str]:
    out = [sym(ticker), MARKET] + hedge_symbols(ticker) + peer_symbols(ticker)
    return list(dict.fromkeys(out))
