# RESIDUAL: Event-Neutral Earnings Agent

> The market moved. How much of that move actually belonged to the company?

RESIDUAL trades only the company-specific part of an earnings reaction. It removes the broad-market, sector and liquidity contributions from a stock's early post-earnings move on Bitget stock perpetuals, then trades what is left as a hedged pair (long company / short hedge, or the reverse). It is built for the Bitget S2 Alpha Factory track: earnings-driven trading, cross-market correlation and factor mining.

Paper trading only. No orders are sent to Bitget.

## What happens for each event

1. **Event collector.** Finds each SEC EDGAR 8-K with Item 2.02 (results of operations). The event timestamp is the SEC acceptance time, and the session (pre-market or after-market) is derived from it.
2. **Earnings extractor.** Pulls reported revenue and the next-quarter revenue outlook from the Exhibit 99.1 press release using fixed per-company patterns. Every value keeps the exact quoted snippet, the source URL and the SHA-256 of the document, and is re-derived from the snippet before use.
   *Expected* revenue is the company's own prior-quarter outlook midpoint, cited to that earlier release. The SEC publishes no analyst consensus, so this is the traceable primary-source expectation.
3. **Factor estimator.** Uses hourly Bitget perpetual returns from the 21 days before the release. The company is regressed on QQQ (market) and on an equal-weight basket of sector peers with the market component removed. Betas are estimated at 7, 14 and 21 days.
4. **Residual calculator.** Measures the move from the release hour to +2h, then subtracts the market contribution, the sector contribution and a liquidity effect (half the estimated spread). What remains is the residual.
5. **Trade constructor.** Pairs the company with one hedge instrument (SMH, QQQ or SPY, whichever fit best historically). The hedge ratio is an OLS beta. An LLM never sets it.
6. **AI interpretation.** Claude labels the residual *durable*, *temporary*, *already priced*, *contradicted by guidance* or *too uncertain*, and must cite 1 to 3 verbatim quotes, which are checked against the press release. The label only scales position size (1.0 / 0.5 / 0). Any response that fails validation means NO_TRADE.
7. **Risk gate.** Returns NO_TRADE when:
   - event data is incomplete;
   - market data is missing;
   - no hedge instrument has R² ≥ 0.10;
   - liquidity is too thin (spread above 30 bps, or position above 25% of median hourly volume);
   - the residual is below k × round-trip cost;
   - the residual's sign is not stable across the beta windows;
   - the early move has already reversed by half.
8. **Paper executor.** Fills both legs at the next hourly open with slippage, Bitget taker fees and funding. The holding period is 24h, with a stop at 2.5% of company notional.
9. **Post-event evaluator.** Splits realized P&L into company leg, hedge leg, residual, factor/hedge error, slippage, fees, funding and signal-to-fill timing.

The direction (continuation vs reversal) and the threshold k are learned **walk-forward**. Each event's parameters come only from events whose exit came before its release; with fewer than 6 such events the default prior is used.

## Dataset

- **Universe:** NVDA, AMD, AVGO, MU, INTC, MRVL (semiconductors) · META, AMZN (internet) · PLTR (software). These are the Bitget stock perpetuals whose companies print a numeric revenue outlook in the press release.
- **Events:** 35 real earnings releases, Oct 2025 to Sep 2026, in `data/events.json`. All required numbers are verified against source.
- **Market inputs:** one reproducible file per event in `data/snapshots/<event_id>.json`, containing Bitget hourly candles, contract fees and funding.
- **AI outputs:** `data/interpretations/<event_id>.json`, containing the prompt hash, model, raw response and validation result.

## Results (walk-forward, 35 events)

| Strategy | Net P&L | Trades | Hit rate |
|---|---|---|---|
| Residual pair, AI-gated | +$264.55 | 9 | 33% |
| Residual pair, no AI (ablation) | +$65.64 | 9 | 33% |
| Unhedged company trade (same signals) | +$129.82 | 9 | 22% |
| Naive headline (beat → long, miss → short) | −$1,612.61 | 27 | 41% |
| No trade | $0.00 | 0 | n/a |

All strategies use $10,000 company notional, the same entry time, the same horizon and the same costs; balances start at $100,000. Of the 26 NO_TRADE events, 9 predate Bitget listing the stock or the market proxy with enough history, 14 fail the liquidity gate (entry falls in thin after-hours trading), and the rest fail robustness, cost or reaction-completeness checks. **Nine trades is too few to claim a statistically significant edge.** What the sample does show is that hedging and the gates reduce losses against naive headline trading.

Known limits:
- Bitget serves funding history only back to about June 2026, so funding for earlier trades is flagged `unavailable_for_period` rather than counted as zero.
- Gross margin is not present in a parseable form in these releases and shows as "not found".

## Run it

Requires Python 3.11+, with no third-party packages.

```bash
cp .env.example .env.local          # add ANTHROPIC_API_KEY (only needed for the AI layer)
python -m residual build            # SEC EDGAR -> data/events.json (verified provenance)
python -m residual verify           # re-check every numeric field against its source document
python -m residual snapshot         # Bitget candles/funding -> data/snapshots/
python -m residual replay           # walk-forward replay + baselines + no-AI ablation
python -m residual replay --offline # regenerate from cached interpretations, no API calls
python -m residual live             # watch EDGAR for the next eligible event (add --loop 600)
python -m residual serve            # dashboard at http://localhost:8000
python -m unittest discover -s tests
```

`replay` writes `data/results.json`, the paper ledger `data/ledger.csv` (every order of both legs), and `web/data.json` for the dashboard.

Network notes:
- `api.bitget.com` is DNS-filtered on some networks. `residual/net.py` then resolves it through Cloudflare DNS-over-HTTPS automatically.
- SEC requests send a descriptive User-Agent; set `SEC_USER_AGENT` to your own contact.

## Live mode

`python -m residual live` polls EDGAR for new Item 2.02 filings in the universe.
- **No new release:** it records `NO_TRADE` along with a live Bitget probe (bid/ask, spread, depth within 10 bps, funding) and estimated next release dates.
- **New release:** it adds the event record, then records one of:
  - `PENDING`, until the 2-hour reaction window closes;
  - a gated decision;
  - a paper pair opened at the live bid/ask, which a later run closes once the 24h horizon has passed.

## Layout

```
residual/   edgar.py extract.py events.py     earnings collection + provenance
            bitget.py market.py net.py        Bitget data + reproducible snapshots
            factors.py strategy.py paper.py   decomposition, gates, hedge, paper fills
            interpret.py                      validated LLM interpretation
            pipeline.py live.py __main__.py   replay/evaluation, live watcher, CLI
web/        index.html app.js style.css       event board, decomposition, evidence, results
data/       events.json snapshots/ interpretations/ results.json ledger.csv live_log.jsonl
```
