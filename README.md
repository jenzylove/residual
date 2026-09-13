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

**Pre-declared rules and a walk-forward selector.** Three direction rules were declared before any scoring:
- **Residual:** trade the company's own move.
- **Headline, hedged:** trade the guidance-surprise direction, keeping the hedge and the gates.
- **Agreement:** trade only when the company move and the surprise point the same way.

For each event, the strategy follows whichever rule did best on strictly earlier events. Every rule's standalone result is published whether it wins or loses.

**Position size.** The default is $2,500 of company notional. The size study (`size_study` in `data/results.json`, charted on the site) re-runs the whole walk-forward at $1k, $2.5k, $5k and $10k. Above $2.5k, Bitget's after-hours liquidity rejects most releases.

The direction (continuation vs reversal) and the threshold k are learned **walk-forward**. Each event's parameters come only from events whose exit came before its release; with fewer than 6 such events the default prior is used. Training uses the conservative-funding outcome.

## Dataset

- **Universe (18):**
  - Semiconductors: NVDA, AMD, AVGO, MU, INTC, MRVL, QCOM, KLAC, TXN
  - Internet: META, AMZN
  - Software: PLTR, CRM, PANW, CRWD, MDB
  - Hardware: HPE, SMCI

  These are the Bitget stock perpetuals whose companies print a numeric next-quarter revenue outlook in the press release.
- **Events:** 75 real earnings releases, Oct 2025 to Sep 2026, in `data/events.json`. 59 have every required field verified against archived sources. The other 16 are mostly older releases from newly added companies, written in a format the extractors do not cover; they predate those stocks' Bitget listing and would be NO_TRADE for market data regardless.
- **Market inputs:** one reproducible file per event in `data/snapshots/<event_id>.json`, containing Bitget hourly candles, fees and funding.
- **AI outputs:** `data/interpretations/<event_id>.json`, containing the prompt hash, model, raw responses and validation result.

## Results (walk-forward, 75 events)

All figures at the $2,500 default size. 
- **Outcomes:** 13 paired paper trades and 62 NO_TRADE decisions.
- **NO_TRADE reasons** (some events have several): market data 38, data incomplete 16, liquidity 14, below cost 5, reaction complete 4, rule disagreement 4, not robust 3, AI label 3, no hedge 3.

**Universe expansion (Sep 2026) added no trades.** Nine companies were added: QCOM, KLAC, TXN, HPE, SMCI, CRM, PANW, CRWD and MDB. None of their releases after listing produced a trade; each event's failed gates are listed in the Audit. The binding constraint on sample size is Bitget liquidity and listing history, not the number of companies covered.

**Primary result.** Only trades whose holding period has complete Bitget funding history are counted. Bitget serves funding only from about June 2026, so 9 of the 13 trades are excluded.

| Strategy | Net P&L | Trades counted | Excluded | Sharpe |
|---|---|---|---|---|
| **Strategy** (rule picked walk-forward) | **+$335.40** | 4 | 9 | 1.19 |
| Strategy, no AI gate (ablation) | +$327.52 | 4 | 9 | 1.03 |
| Residual rule alone | +$188.77 | 8 | 9 | 0.65 |
| Headline rule, hedged | +$329.61 | 8 | 9 | 1.14 |
| Agreement rule | +$335.40 | 4 | 5 | 1.19 |
| Unhedged, same signals | +$442.59 | 4 | 9 | 1.31 |
| **Naive headline, same events** (like-for-like) | **+$442.59** | 4 | 9 | 1.31 |
| Naive headline, every eligible event | −$6.62 | 18 | 18 | −0.01 |

**Sensitivity: all trades, conservative funding.** Every trade counts. Missing funding is charged against the position at the largest absolute rate observed for that symbol.

| Strategy | Net P&L | Trades | Sharpe |
|---|---|---|---|
| **Strategy** (rule picked walk-forward) | +$269.44 | 13 | 0.87 |
| Residual rule alone | +$122.80 | 17 | 0.38 |
| Headline rule, hedged | +$262.65 | 17 | 0.84 |
| Agreement rule | +$335.66 | 9 | 1.11 |
| Unhedged, same signals | +$382.80 | 13 | 0.99 |
| Naive headline, same events | +$511.29 | 13 | 1.31 |
| Naive headline, every eligible event | −$716.13 | 36 | −1.16 |

**Reading the results honestly:**
- The strategy is profitable in both views and at every tested size, but the plain headline trade on the same releases did better.
- The value sits in the gates: across every eligible release the headline trade loses (−$716 conservative), while on the releases RESIDUAL's gates select it wins.
- Of the three pre-declared rules, agreement scored best; the walk-forward selector moved to it only once enough history existed.
- With 4 to 17 trades, none of these differences is statistically meaningful.

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

CI (`.github/workflows/ci.yml`) runs on every push:
- the tests;
- `verify --offline`;
- an offline replay that must reproduce the committed decisions and summaries exactly;
- a strict JSON check on the site data.

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

The deployed site is a static export: landing page at https://residual-teal.vercel.app and dashboard at https://residual-teal.vercel.app/dashboard. Its live-watcher panel shows the log as of the last local run and does not update itself.

## Bitget Demo Trading (live-mode execution)

When `BITGET_DEMO_API_KEY`, `BITGET_DEMO_API_SECRET` and `BITGET_DEMO_API_PASSPHRASE` are set in `.env.local`, live-mode trades are placed as **Bitget Demo Trading orders** instead of local paper fills. How it works:
- Requests are signed per API v2 and carry the `paptrading: 1` header, so they reach the demo environment only.
- Both legs are market orders, all-or-nothing. If the second leg fails, the first is flattened with a reduce-only order.
- At the 24h horizon both legs are closed with reduce-only orders.
- Exchange order IDs, fill prices, fees and every request/response are stored with the position.

Demo contracts are discovered at runtime (`demo-check`). A universe symbol that Bitget Demo does not list is rejected before any order is sent.

The whole Demo test run is one command. It stops at the first failure and writes every step, plus the exchange request log, to `data/keyrun_report.json`:

```bash
python -m residual keyrun                             # credentials, public API, auth, account, symbol coverage, $50 roundtrip, live watcher pass
```

Individual steps:

```bash
python -m residual demo-check                         # auth, balance, which universe symbols exist on demo
python -m residual demo-roundtrip --notional 50       # open+close one small NVDA/QQQ pair; records -> data/demo_roundtrips.jsonl
python -m residual live                               # live watcher now executes on Bitget Demo
```

Historical replay results remain local paper accounting; only live-mode trades can have exchange-side Demo records.

**Verified against real Bitget Demo on 13 Sep 2026** (`data/keyrun_report.json`). The execution-test pair was NVDA long against AAPL short, $50 per leg. Four orders were accepted and filled:

| Leg | Open order | Open price | Close order | Close price |
|---|---|---|---|---|
| NVDA long | 1483033182613204993 | 217.85 | 1483033203639250945 | 217.77 |
| AAPL short | 1483033196173389825 | 332.70 | 1483033210475966465 | 332.75 |

Net result: −$0.14 after Bitget's reported fees.

What the real run established:
- Demo uses `USDT-FUTURES` / `USDT` with the `paptrading: 1` header.
- Demo accounts default to hedge mode; the client reads the position mode and formats orders to match.
- Demo funds land in the demo spot wallet. Transfer them to USDT-M Futures in the app, because the Demo API has no transfer endpoint.
- Demo lists NVDA, META and AMZN from the universe, but none of the strategy's hedge instruments (QQQ, SPY, SMH).
- **Hedge substitute (Demo only).** When the strategy hedge is not listed on Demo, the live path fits the best Demo-listed stock perpetual (AAPL, TSLA, META, AMZN or NVDA, excluding the company). It uses the same OLS fit and R² floor as the strategy hedge, and records the substitution with the position. If nothing fits, the result is NO_TRADE. Replay results are unaffected.
- `python -m residual demo-strategy-trade` executes a real past strategy decision on Demo (company leg plus fitted hedge) and closes it. Records go to `data/demo_strategy_trades.jsonl`.

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
