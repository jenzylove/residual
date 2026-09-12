# RESIDUAL: Event-Neutral Earnings Agent

> The market moved. How much of that move actually belonged to the company?

RESIDUAL isolates the company-specific part of an earnings reaction. It takes a stock's early post-earnings move on Bitget stock perpetuals, removes the broad-market, sector and liquidity contributions, and expresses what is left as a hedged pair (long company / short hedge, or the reverse). It is built for the Bitget S2 Alpha Factory track: earnings-driven trading, cross-market correlation and factor mining.

**Scope, stated plainly:**
- Market data comes from Bitget's public REST API. Historical replay execution is **local paper accounting**, with no exchange-side records.
- Live-mode trades can execute on **Bitget Demo Trading** when demo API credentials are configured (see below). RESIDUAL never places real-money orders.
- The surprise is a **company-guidance surprise**: reported revenue vs the company's own prior-quarter outlook. It is **not** an analyst-consensus surprise.

## What happens for each event

1. **Event collector.** Finds each SEC EDGAR 8-K with Item 2.02. The event timestamp is the SEC acceptance time, and the session (pre-market or after-market) is derived from it.
2. **Earnings extractor.** Pulls reported revenue and the next-quarter revenue outlook from the Exhibit 99.1 press release using fixed per-company patterns. Each value keeps the exact quoted snippet, the source URL and the document's SHA-256, and is re-derived from the snippet before use. Source documents are archived in `data/sources/`.
   - Required: revenue actual, the prior outlook (the guidance baseline), the new outlook, and the prior-quarter actual.
   - Optional evidence only: EPS and gross margin. The model never reads them, so their absence neither blocks nor resizes a trade. Gross margin is not found in any of these releases.
3. **Factor estimator.** Uses hourly Bitget perpetual returns from the 21 days before the release. The company is regressed on QQQ (market) and on an equal-weight basket of sector peers with the market component removed. Betas are estimated at 7, 14 and 21 days.
4. **Residual calculator.** Measures the move from the release hour to +2h, then subtracts the market contribution, the sector contribution and a liquidity effect (half the estimated spread). What remains is the residual.
5. **Trade constructor.** Pairs the company with one hedge instrument (SMH, QQQ or SPY, whichever fit best historically). The hedge ratio is an OLS beta. An LLM never sets it.
6. **AI interpretation.** Claude labels the residual *durable*, *temporary*, *already priced*, *contradicted by guidance* or *too uncertain*, and must cite 1 to 3 quotes that are checked against the press release. The label only scales position size (1.0 / 0.5 / 0). An invalid response means NO_TRADE. Labels can differ between runs because this model does not accept a temperature setting, so cached interpretations in `data/interpretations/` are what make a run reproducible.
7. **Risk gate.** Returns NO_TRADE when:
   - required data is incomplete;
   - market data is missing;
   - no hedge instrument has R² ≥ 0.10;
   - liquidity is too thin (spread above 30 bps, or position above 25% of median hourly volume);
   - the residual is below k × round-trip cost;
   - the residual's sign is not stable across the beta windows;
   - the early move has already reversed by half.
8. **Paper executor.** Records both legs at the next hourly open with slippage, Bitget taker fees and funding. The holding period is 24h, with a stop at 2.5% of company notional.
9. **Post-event evaluator.** Splits realized P&L into company leg, hedge leg, residual, factor/hedge error, slippage, fees, funding and signal-to-fill timing.

The direction (continuation vs reversal) and the threshold k are learned **walk-forward**. Each event's parameters come only from events whose exit came before its release; with fewer than 6 such events the default prior is used. Training uses the conservative-funding outcome.

## Dataset

- **Universe:** NVDA, AMD, AVGO, MU, INTC, MRVL (semiconductors) · META, AMZN (internet) · PLTR (software). These are the Bitget stock perpetuals whose companies print a numeric revenue outlook in the press release.
- **Events:** 35 real earnings releases, Oct 2025 to Sep 2026, in `data/events.json`. All required fields are verified against archived sources.
- **Market inputs:** one reproducible file per event in `data/snapshots/<event_id>.json`, containing Bitget hourly candles, fees and funding.
- **AI outputs:** `data/interpretations/<event_id>.json`, containing the prompt hash, model, raw responses and validation result.

## Results (walk-forward, 35 events)

- **Outcomes:** 9 paired paper trades and 26 NO_TRADE decisions.
- **NO_TRADE reasons** (some events have several): liquidity 14, market data 8, reaction complete 4, below cost 3, not robust 2, AI label 2.

**Primary result.** Only trades whose holding period has complete Bitget funding history are counted. Bitget serves funding only from about June 2026, so 4 of the 9 trades are excluded.

| Strategy | Net P&L | Trades counted | Excluded |
|---|---|---|---|
| Residual pair (AI-gated) | +$115.93 | 5 | 4 |
| Residual pair, no AI (ablation) | −$9.66 | 5 | 4 |
| Unhedged company trade, same signals | +$361.25 | 5 | 4 |
| **Naive headline, same events** (like-for-like) | **+$1,254.55** | 5 | 4 |
| Naive headline, every eligible event | +$1,062.20 | 9 | 18 |
| No trade | $0.00 | 0 | 0 |

**Sensitivity: all trades, conservative funding.** Every trade counts. Missing funding is charged against the position at the largest absolute rate observed for that symbol.

| Strategy | Net P&L | Trades |
|---|---|---|
| Residual pair (AI-gated) | −$77.73 | 9 |
| Unhedged company trade, same signals | −$42.62 | 9 |
| Naive headline, same events | +$401.51 | 9 |
| Naive headline, every eligible event | −$1,775.83 | 27 |

**Reading the results honestly:**
- On the same events, the naive headline direction beat the residual strategy in this sample.
- Hedging lowered the residual strategy's hit rate relative to unhedged in the primary run and did not improve P&L.
- The gates avoided most of the naive strategy's losses across all events, but the like-for-like comparison shows the residual signal itself did not add value here.
- With 5 to 9 trades, none of these differences is statistically meaningful.

## Run it

Requires Python 3.11+, with no third-party packages.

```bash
python -m residual verify --offline   # every numeric field re-derived from archived sources, no network
python -m residual replay --offline   # regenerate all results from committed data, no network
python -m unittest discover -s tests  # 17 tests incl. an end-to-end live-watcher fixture
python -m residual serve              # dashboard at http://localhost:8000

# refreshing data (network):
cp .env.example .env.local            # ANTHROPIC_API_KEY for the AI layer
python -m residual build              # SEC EDGAR -> data/events.json + data/sources/
python -m residual snapshot           # Bitget candles/funding -> data/snapshots/
python -m residual replay             # re-run, calling the LLM for any uncached interpretation
python -m residual live               # watch EDGAR for the next eligible event (add --loop 600)
```

`replay` writes `data/results.json`, the paper ledger `data/ledger.csv` (every order of both legs for executed trades), and `web/data.json` for the dashboard.

Network notes:
- RESIDUAL uses system DNS. If `api.bitget.com` does not resolve, it stops with an explanation. A DNS-over-HTTPS fallback exists only for local resolver faults and is **off** unless `RESIDUAL_DOH_FALLBACK=1`; do not use it to get around Bitget's regional access restrictions.
- SEC requests send a descriptive User-Agent; set `SEC_USER_AGENT` to your own contact.

## Live mode

`python -m residual live` polls EDGAR for new Item 2.02 filings. An event moves through these stages:
- **New filing:** an event record is added to `data/events.json`.
- **PENDING:** re-checked on every run until the 2-hour reaction window closes.
- **Gated decision:** made with live Bitget data.
- **Paper pair opened:** at the live bid/ask, only within one hour of the decision time.
- **Closed:** at the live bid/ask after 24h.

With nothing new, a run records NO_TRADE plus a live Bitget liquidity probe. `tests/test_live.py` covers this whole path with fixtures. No real new release has occurred since the dataset was built, so no live event has been recorded yet.

The deployed dashboard (https://residual-teal.vercel.app) is a static export. Its live-watcher panel shows the log as of the last local run and does not update itself.

## Bitget Demo Trading (live-mode execution)

When `BITGET_DEMO_API_KEY`, `BITGET_DEMO_API_SECRET` and `BITGET_DEMO_API_PASSPHRASE` are set in `.env.local`, live-mode trades are placed as **Bitget Demo Trading orders** instead of local paper fills. How it works:
- Requests are signed per API v2 and carry the `paptrading: 1` header, so they reach the demo environment only.
- Both legs are market orders, all-or-nothing. If the second leg fails, the first is flattened with a reduce-only order.
- At the 24h horizon both legs are closed with reduce-only orders.
- Exchange order IDs, fill prices, fees and every request/response are stored with the position.

Demo contracts are discovered at runtime (`demo-check`). A universe symbol that Bitget Demo does not list is rejected before any order is sent.

```bash
python -m residual demo-check                         # auth, balance, which universe symbols exist on demo
python -m residual demo-roundtrip --notional 50       # open+close one small NVDA/QQQ pair; records -> data/demo_roundtrips.jsonl
python -m residual live                               # live watcher now executes on Bitget Demo
```

Historical replay results remain local paper accounting; only live-mode trades can have exchange-side Demo records. Status: implemented and tested against a fake exchange (`tests/test_demo.py`, `tests/test_live.py`). **The run against real Bitget Demo credentials has not happened yet.**

## Layout

```
residual/   edgar.py extract.py events.py     earnings collection, provenance, source archive
            bitget.py market.py net.py        Bitget data + reproducible snapshots
            factors.py strategy.py paper.py   decomposition, gates, hedge, paper fills
            interpret.py                      validated LLM interpretation
            pipeline.py live.py __main__.py   replay/evaluation, live watcher, CLI
web/        index.html app.js style.css       event board, decomposition, evidence, results
data/       events.json sources/ snapshots/ interpretations/ results.json ledger.csv live_log.jsonl
```
