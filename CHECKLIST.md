# RESIDUAL implementation checklist (derived from the PRD)

Status key: [x] done and verified · [~] partial · [ ] not started · [!] blocked

## 1. Product contract
- [x] Event record, structured surprise, expected factor move, actual move, residual, hedge ratio, decision, paper order record, post-event attribution per event
- [x] Not a chat bot / sentiment bot / beat-equals-long strategy (naive beat→long is only a baseline)

## 2. Core behavior
- [x] Curated Bitget universe: 9 companies (NVDA AMD AVGO MU INTC MRVL META AMZN PLTR), QQQ market proxy, SMH/QQQ/SPY hedges, peer baskets (`residual/universe.py`)
- [x] Stable symbol mapping, historical candles, spread estimate, liquidity (quote volume), launch dates from Bitget contracts
- [x] Missing data or hedge → NO_TRADE
- [x] Earnings data from primary source (SEC EDGAR 8-K Item 2.02, Exhibit 99.1): revenue, guidance, EPS (where stated), commentary, timestamp
- [x] Consensus estimate: replaced by the company's own prior-quarter outlook midpoint (traceable primary source; SEC has no consensus)
- [ ] Margins: gross-margin pattern finds nothing in these releases; field shown as "not found"
- [x] Numerical values stored with source URL, verbatim snippet, document SHA-256; re-verified before use (`residual/extract.py`, `python -m residual verify`)
- [x] Market data: Bitget hourly candles, fees, funding history; live ticker + order book in live mode
- [x] Event calendar: release timestamp, pre/after-market session, expiry window, next-release estimate in the live watcher
- [x] 1 Event collector · 2 Earnings extractor · 3 Factor estimator · 4 Residual calculator
- [x] 5 Trade constructor with deterministic OLS hedge ratio
- [~] 6 AI interpretation layer: implemented and validated (labels only, quotes checked against source) — [!] needs a working LLM API key
- [x] 7 Risk gate: cost threshold, hedge availability, liquidity, data completeness, reaction complete, robustness across beta windows
- [x] 8 Paper executor: both legs, prices, quantities, fees, slippage, funding, balance
- [x] 9 Post-event evaluator: company leg, hedge leg, factor error, residual, slippage, timing
- [x] UI: event board, surprise decomposition, strategy card, evidence panel, results panel

## 3. Build and demo acceptance
- [x] Real historical earnings events (35), no generated events
- [x] Each event retains source URL, event timestamp, market-data timestamps, extracted values, decision, paper execution record
- [x] Live mode watches EDGAR for the next eligible event and records NO_TRADE when none qualifies
- [x] ≥15 real events across a documented universe
- [x] Baselines: residual, naive earnings direction, unhedged, no-trade
- [x] Walk-forward (expanding window; params fit only on events that exited before the release)
- [ ] README runs strategy from documented dataset
- [ ] Deployed dashboard
