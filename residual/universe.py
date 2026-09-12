"""Curated Bitget universe: companies, sector peer baskets, market and hedge proxies.

Symbols are Bitget USDT-M perpetuals (`<TICKER>USDT`). Only companies that
publish a numeric next-quarter revenue outlook in their earnings press release
are included, so the "expected" value always has a primary-source citation.
"""

MARKET = "QQQUSDT"  # broad-market proxy; the only index perp listed across the full sample

COMPANIES = {
    "NVDA": "semis", "AMD": "semis", "AVGO": "semis", "MU": "semis",
    "INTC": "semis", "MRVL": "semis",
    "META": "internet", "AMZN": "internet",
    "PLTR": "software",
}

# Equal-weight sector baskets (the company itself is always excluded).
PEERS = {
    "semis": ["NVDA", "AMD", "AVGO", "MU", "INTC", "MRVL", "TSM", "ASML", "ARM", "QCOM", "AMAT"],
    "internet": ["META", "AMZN", "GOOGL", "AAPL", "MSFT", "NFLX"],
    "software": ["MSFT", "ORCL", "CRM", "NOW", "SNOW", "PANW", "CRWD"],
}

# Tradeable single-instrument hedge candidates; the best historical fit wins.
HEDGES = {
    "semis": ["SMHUSDT", "QQQUSDT", "SPYUSDT"],
    "internet": ["QQQUSDT", "SPYUSDT"],
    "software": ["QQQUSDT", "SPYUSDT"],
}


def sym(ticker: str) -> str:
    return ticker + "USDT"


def peer_symbols(ticker: str) -> list[str]:
    return [sym(p) for p in PEERS[COMPANIES[ticker]] if p != ticker]


def hedge_symbols(ticker: str) -> list[str]:
    return HEDGES[COMPANIES[ticker]]


def snapshot_symbols(ticker: str) -> list[str]:
    out = [sym(ticker), MARKET] + hedge_symbols(ticker) + peer_symbols(ticker)
    return list(dict.fromkeys(out))
