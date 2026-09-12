# RESIDUAL: final PRD audit

Status key: [x] done and verified · [~] partial (reason given) · [ ] not done

## 1. Product contract
- [x] Every event produces: event record, structured surprise, expected factor move, actual move, residual, hedge ratio, trade/no-trade decision, paper order record, post-event attribution (`data/results.json`, dashboard)
- [x] Not a chat assistant, sentiment bot, beat-equals-long strategy, rebalancer or pure backtest; naive beat→long exists only as a baseline
- [x] Unique capability: market-neutral attribution followed by an executable paired residual trade

## 2. Core behavior
- [x] Curated Bitget universe: 9 stock perpetuals, QQQ market proxy, SMH/QQQ/SPY hedges, sector peer baskets (`residual/universe.py`)
- [x] Per instrument: symbol mapping, hourly history, current ticker, spread and depth (live), fees and launch dates from the contracts endpoint
- [x] Insufficient data or no valid hedge → NO_TRADE (9 events rejected for market data)
- [x] Earnings from a primary source (SEC 8-K Item 2.02, Ex. 99.1): revenue, guidance, EPS where stated, management commentary, event timestamp
- [~] Consensus estimate: substituted with the company's own prior-quarter outlook midpoint. SEC has no consensus; this keeps every number traceable
- [~] Margins: no parseable GAAP gross-margin sentence in these releases; shown as "not found"
- [x] Numbers stored with source URL, verbatim snippet and document SHA-256, validated before the model (`python -m residual verify` → all verified)
- [x] Market data: Bitget candles, fees, funding; volatility (residual sigma), spread, volume
- [~] Funding: Bitget serves history only from about June 2026; earlier trades are flagged `unavailable_for_period`
- [x] Event calendar: release time, pre/after-market session, expiry window; live watcher estimates next release dates
- [x] 1 Event collector · 2 Earnings extractor · 3 Factor estimator · 4 Residual calculator
- [x] 5 Trade constructor with deterministic OLS hedge ratio (never from the LLM)
- [x] 6 AI interpretation (Claude Sonnet 5): 27/27 validated; labels only scale size; quotes checked against the source
- [x] 7 Risk gate: cost threshold, hedge, liquidity, data completeness, reaction complete, robustness across beta windows
- [x] 8 Paper executor: both legs, prices, quantities, fees, slippage, funding, balance
- [x] 9 Post-event evaluator: company leg, hedge leg, factor error, residual estimate, slippage, timing
- [x] UI: event board, surprise decomposition, strategy card, evidence panel, results panel (plus live watcher and method tabs)

## 3. Build and demo acceptance
- [x] Real historical events only (35), replayable with source URL, event timestamp, market timestamps, extracted values, decision, paper record
- [x] Live mode run against real EDGAR + Bitget; recorded NO_TRADE (no eligible release)
- [x] ≥15 real events, documented universe
- [x] Residual vs naive vs unhedged vs no-trade, plus a no-AI ablation
- [x] Walk-forward: parameters fit only on events that exited before each release
- [x] README runs the strategy from the documented dataset
- [x] ≥1 paired trade (9) and ≥1 NO_TRADE (26)
- [x] Both legs of every pair logged (`data/ledger.csv`)
- [x] Slippage and fees included
- [x] Results regenerate from code (`python -m residual replay --offline`)
- [x] Live watcher can add a new event record (code path shares `build_event`; no eligible release has occurred since, so none added yet)
- [x] LLM never supplies numbers to execution (validator rejects extra keys; size comes from a fixed label table)
- [x] Independent of AFTERSHOCK: no ActionGraph, onchain, exploit or contagion code
- [x] Dashboard deployed: https://residual-teal.vercel.app
