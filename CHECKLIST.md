# RESIDUAL: PRD audit

Status key: [x] done and verified · [~] partial or narrowed (reason given) · [ ] not done
Numbers refer to the committed `data/results.json`.

## 1. Product contract
- [x] Every event produces an event record, structured surprise, factor decomposition (when market data exists) and a trade/no-trade decision record
- [~] Paper order record and post-event attribution exist **only for traded events** (9); the 26 no-trade events have a decision record with gate reasons instead
- [~] Hedge ratio is computed for every event with a usable hedge candidate, not for events rejected on market data
- [x] Not a chat assistant, sentiment bot, beat-equals-long strategy, rebalancer or pure backtest; naive direction exists only as a baseline

## 2. Core behavior
- [x] Curated Bitget universe: 18 stock perpetuals in four sector groups, QQQ market proxy, SMH/QQQ/SPY/XLK hedges, sector peer baskets
- [x] Insufficient market data → NO_TRADE: **38** events
- [x] Earnings from a primary source (SEC 8-K Item 2.02, Ex. 99.1) with source URL, verbatim snippet and SHA-256; `verify --offline` passes against archived sources
- [~] Surprise is a **company-guidance surprise** (vs prior-quarter company outlook), not a consensus surprise; renamed throughout code, UI and prompt
- [~] Margins: explicitly optional evidence (`validation.optional_fields`); not found in these releases; never used by the model
- [x] EPS optional evidence, extracted where stated
- [x] Market data: Bitget candles, fees, spread estimate, volume; live ticker/depth in live mode
- [~] Funding: complete only from about June 2026. Primary results **exclude** the 4 trades without funding data; a separate sensitivity charges them at the worst observed rate
- [x] Event calendar: release time, session, expiry window, estimated next releases
- [x] 1 Collector · 2 Extractor · 3 Factor estimator · 4 Residual calculator · 5 Trade constructor (OLS hedge ratio)
- [x] 6 AI interpretation: 27/27 validated responses; labels only scale size. Labels are not deterministic run-to-run; cached outputs make runs reproducible
- [x] 7 Risk gate (cost, hedge, liquidity, data completeness, reaction complete, robustness)
- [x] 8 Paper executor: both legs, prices, quantities, fees, slippage, funding (or exclusion flag), balance
- [x] 9 Post-event evaluator attribution for traded events
- [x] UI: event board, surprise decomposition, strategy card, evidence panel, results panel

## 3. Build and demo acceptance
- [x] 75 real historical events (59 fully verified), replayable with sources, timestamps, extracted values and decisions
- [x] ≥15 events; documented universe
- [x] Baselines: residual, unhedged (same signals), **naive on the same events** (like-for-like), naive on all events, no-trade, plus a no-AI ablation
- [x] Walk-forward evaluation (parameters fit only on events exited before each release)
- [x] ≥1 paired trade (13) and ≥1 NO_TRADE (62); both legs logged in `data/ledger.csv` (52 orders)
- [x] Slippage and fees included
- [x] Results regenerate from code **without network**: `replay --offline` uses committed sources, snapshots and cached interpretations
- [~] Live watcher: lifecycle proven by the deterministic fixture `tests/test_live.py` (new filing → record → PENDING → trade → close) and by one real run that recorded NO_TRADE. It has not yet added a real new event, because none has been released
- [x] LLM never supplies numbers to execution (extra keys rejected; size from a fixed label table)
- [~] Deployed dashboard: https://residual-teal.vercel.app is a static export; the live-watcher panel is a snapshot of the last local run
- [~] Trading usage: historical replay is **Bitget public market data + local paper accounting**. Live mode executes on **Bitget Demo Trading** when credentials are set:
  - signed v2 requests with `paptrading: 1`;
  - all-or-nothing pairs with rollback, reduce-only closes;
  - exchange order records stored; `demo-check` and `demo-roundtrip` provided.
  - Tested against a fake exchange only; **the run with real demo keys is pending.**
- [x] Independent of AFTERSHOCK

## Rubric work (Alpha Factory: executable, effective, verifiable)
- [x] Executable:
  - $2.5k default sized to Bitget liquidity; a size study re-runs the walk-forward at $1k/$2.5k/$5k/$10k;
  - Strict Demo execution refuses an unlisted hedge before placing either leg, with a fixture test;
  - `demo-strategy-trade` executes a replayed strategy decision on real Demo only when the original hedge is listed.
- [x] Effective:
  - three pre-declared rules with a walk-forward selector, all published;
  - Sharpe, Sortino and max drawdown, full period and last 90 days.
- [x] Verifiable: SEC hashes, offline replay reproduced in CI, quote-checked AI, public ledger, real Demo order IDs.
- [x] Frontend:
  - proof strip linking each claim to its evidence;
  - a 60-second guided tour;
  - a variants table and size-study chart;
  - the decision rule shown per event;
  - revenue figures linked to their SEC source.

## Result claims (not an edge, at $2,500)
- Primary: strategy +$335.40 (4 trades, Sharpe 1.19) vs naive headline on the same events +$442.59 (Sharpe 1.31)
- Conservative, all 13 trades: strategy +$269.44 (Sharpe 0.87) vs naive on the same events +$511.29 (Sharpe 1.31)
- Across every eligible event the headline trade loses (−$716.13); the gates carry the value

## Earlier claims (superseded, $10,000 size)
- Primary: residual +$115.93 (5 trades) vs naive headline on the same events +$1,254.55
- Conservative funding, all 9 trades: residual −$77.73 vs naive on the same events +$401.51
- The sample is too small to support any claim of alpha; like-for-like, the residual signal did not beat the headline direction

## Hardening done without keys
- [x] `python -m residual keyrun`: one-command Demo test run.
  - Steps: credentials, public API, auth, account, symbol coverage, $50 roundtrip, live watcher pass.
  - Report goes to `data/keyrun_report.json`; exits non-zero on the first failure.
- [x] `live --loop` survives a failed poll: the error is logged to `data/live_log.jsonl` and polling continues.
- [x] CI on every push: tests, offline provenance, offline replay must reproduce the committed results, strict JSON for the site.
- [x] Site data written as strict JSON (no NaN/Infinity), with a test.
- [x] `keyrun` passed against real Bitget Demo on 2026-09-13. Four orders were accepted and filled: NVDA/AAPL execution-test pair, $50 per leg, net −$0.14 after fees.
  - Order IDs are in the README and `data/keyrun_report.json`.
  - Findings: `USDT-FUTURES`/`USDT`, hedge mode by default (handled), funds must be moved from demo spot to futures in the app.
- [~] Demo lists no strategy hedge instrument (QQQ, SPY, SMH), so live strategy pairs on Demo resolve to NO_TRADE before any order is sent. The Demo run proves the adapter, not a substitute strategy.

## Infrastructure
- [x] DNS-over-HTTPS fallback is opt-in (`RESIDUAL_DOH_FALLBACK=1`), off by default, documented as not for bypassing regional restrictions
- [x] Env file is `.env.local` (git-ignored); `.env.example` committed
