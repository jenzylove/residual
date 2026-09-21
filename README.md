<p align="center">
  <img src="web/brand/mark.svg" alt="RESIDUAL" width="320">
</p>

<p align="center">
  <b>How much of that earnings move actually belonged to the company?</b><br>
  RESIDUAL strips the market, the sector and the liquidity effect out of an earnings reaction on Bitget
  stock perpetuals, and trades only what is left, hedged.
</p>

<p align="center">
  <a href="https://residual-teal.vercel.app"><b>Live app</b></a> ·
  <a href="https://residual-teal.vercel.app/dashboard"><b>Audit</b></a> ·
  <a href="https://github.com/jenzylove/residual/actions/workflows/ci.yml"><img src="https://github.com/jenzylove/residual/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
</p>

<p align="center">
  <img src="web/screenshots/hero.png" alt="RESIDUAL landing page" width="100%">
</p>

Built for the **Bitget AI Hackathon S2, Alpha Factory** track: earnings-driven trading, after-hours quotations, cross-market correlation and factor mining on US tokenized stocks.

## The problem

A stock jumps 6% after earnings. Most earnings bots buy that whole move. But a good part of it is usually the broad market rising in that hour, or the whole sector moving together, or simply thin after-hours pricing. Only the remainder belongs to the company.

RESIDUAL separates those four pieces on every release, trades only the company's part as a hedged pair, and shows the filing, the maths and the exchange order behind every decision. When the remainder is too small to beat costs, the hedge does not fit, or the book is too thin, it does nothing and says exactly why.

## Take one move apart

<p align="center">
  <img src="web/screenshots/signal-room.png" alt="Signal room: an earnings move split into market, sector, liquidity and company" width="100%">
</p>

NVDA moved **+4.10%** in the two hours after its release on 26 Aug 2026. The market explains **+0.88%**, the sector **−0.01%**, liquidity **+0.05%**. What belongs to the company is **+3.19%**, and that is what gets traded, long NVDA against short SMH, only because all eight gates passed.

## Architecture

```mermaid
flowchart TD
    A[SEC EDGAR<br/>Item 2.02 filings] -->|every 10 min| B[Watcher]
    B --> C[Extractor<br/>revenue + guidance<br/>snippet, URL, SHA-256]
    C --> D{Verified?}
    D -->|no| X[NO_TRADE<br/>data incomplete]
    D -->|yes| E[Factor model<br/>21d hourly Bitget returns<br/>market and sector betas]
    E --> F[Residual<br/>observed minus market, sector, liquidity]
    F --> G[AI reading<br/>Claude, quotes checked<br/>label scales size only]
    G --> H{8 risk gates}
    H -->|any fail| X
    H -->|all pass| I[Walk-forward selector<br/>residual, headline, agreement]
    C --> O[Post-hoc diagnostic<br/>analyst EPS consensus<br/>never selector-eligible]
    I --> J[Hedged pair<br/>company vs beta-weighted hedge]
    J --> K[Paper executor<br/>fees, slippage, funding]
    J --> L[Bitget Demo<br/>real orders in live mode]
    K --> M[Attribution<br/>company, hedge error, costs]
    L --> M
    M --> N[Site and Audit<br/>evidence, ledger, hashes]

    style F fill:#6c4ee6,color:#fff
    style X fill:#e8e6f0
    style L fill:#1b1a22,color:#fff
```

**Data in:** SEC EDGAR (filings), Bitget public REST (hourly candles, fees, funding, order book), Alpha Vantage (analyst EPS consensus), Anthropic Claude (the reading).
**Nothing leaves** except Bitget Demo orders in live mode. No real-money order is ever placed.

## Product flow

| Step | What happens | Where to see it |
|---|---|---|
| 1. Catch | Watcher polls EDGAR for Item 2.02 earnings filings across 18 companies | Watcher card, `data/live_log.jsonl` |
| 2. Read | Revenue and the company's own guidance extracted, each with its snippet and document hash | Signal room evidence line, Audit |
| 3. Split | Hourly betas against QQQ and a sector peer basket remove market and sector | Signal room bars |
| 4. Second reading | Claude labels the move, quoting the filing; the label can only shrink a position | Signal room, AI card |
| 5. Gate | Eight checks; one failure means no trade, with the reason in plain words | Gates panel |
| 6. Trade | Company leg against a beta-weighted hedge, both legs, costs included | Paper execution |
| 7. Explain | Result split into company move, hedge error, fees, slippage, funding | Attribution panel |

<p align="center">
  <img src="web/screenshots/paper-execution.png" alt="Paper execution and attribution" width="100%">
</p>

## Evidence contract

Every number on the site traces back to a document or an exchange response.

- **Earnings numbers** keep the exact sentence they came from, the SEC URL and the SHA-256 of the document. All 83 filings (79 earnings releases) verify, offline, against the archive in `data/sources/`.
- **Market inputs** are frozen per event in `data/snapshots/`, so the replay runs with no network at all.
- **AI answers** are cached in `data/interpretations/` with the prompt hash and raw response. Every quote is checked against the press release; an invented quote is rejected and the trade does not happen.
- **Paper orders** for both legs are in `data/ledger.csv`.
- **Demo orders** are real Bitget Demo order IDs in `data/keyrun_report.json` and `data/demo_strategy_trades.jsonl`.
- **CI** re-runs the replay on every push and fails if it does not reproduce the committed decisions.

## Results

<p align="center">
  <img src="web/screenshots/proof.png" alt="Proof section: rules, size study and demo-executable mode" width="100%">
</p>

### Five populations, never mixed

| Population | What it is | Size |
|---|---|---|
| Earnings releases | Every release examined, with SEC source, hashes and verified numbers | 79 releases |
| Main-mode backtest | Walk-forward strategy, hedged with index or sector ETFs | 15 trades (every trade counted) |
| Demo-mode backtest | Same method, restricted to instruments Bitget Demo lists | 6 trades |
| Demo execution checks | Historical decisions opened and closed in one pass on Bitget Demo | 6 pairs, net −$1.30 (venue cost) |
| Demo held pairs | Historical decisions held on Bitget Demo under the strategy's own exits | 1 closed, 2 open |

The first three are research and backtest. The last two are real Bitget Demo orders, and their dollars come from Bitget's fills and fees. The two are never added together.

### Backtest, walk-forward, every trade counted

Walk-forward over 79 releases at the $2,500 default size. Each decision used only information available before that release, including funding: each event's worst case funding charge uses only settlements before its release. Missing funding is charged at that worst rate.

| Rule | Net P&L | Trades | Sharpe (daily, annualised) | Max drawdown |
|---|---|---|---|---|
| **Strategy** (rule picked walk-forward) | **+$189.66** | 15 | 0.619 | −$218.68 |
| Agreement rule | +$323.11 | 11 | 1.084 | −$85.22 |
| Headline rule, hedged | +$237.89 | 21 | 0.763 | −$220.39 |
| Residual rule | +$168.53 | 21 | 0.518 | −$222.30 |
| Analyst consensus diagnostic (post hoc, never selected) | −$7.00 | 14 | -0.042 | −$152.92 |
| **Headline direction, same events, unhedged** | **+$547.47** | 15 | 1.376 | −$122.35 |
| Headline direction, every eligible event | −$738.51 | 37 | -1.205 | −$941.09 |

**What this shows.** The value is in which releases RESIDUAL agrees to trade. Taking the headline direction on every release loses $738.51; taking it only on the releases that clear RESIDUAL's gates makes +$547.47. Inside those releases the hedge cost more than it saved, so the unhedged baseline beats the strategy. We report the strategy the walk-forward selected, not the baseline, because picking the winner after seeing the results would be hindsight.

**Demo-executable mode:** +$122.19 over 6 trades (Sharpe 0.728) against the same-events baseline's +$64.60 (0.382). This is the one population where the strategy beats its baseline.

### Real orders on Bitget Demo

Held pairs are managed by the watcher with the backtest's own exits: a combined pair stop at 2.5% of company notional, or the holding period. Closing is restart safe; each leg's close has a fixed order ID, so a retry checks the exchange before sending anything.

- META-2026-07-29: held 6.93h, exit pair stop at -8.61%, net per Bitget −$8.38. It passed the -2.5% stop before the live stop existed; it closed on the first watcher cycle after the stop shipped, which is why the loss is past the stop.
- NVDA-2025-11-19: open, due 2026-09-22T12:23:03Z
- AMZN-2026-02-05: open, due 2026-09-22T12:23:14Z

Execution checks: 6 pairs, net −$1.30 in total, which is the venue's round trip cost and says nothing about the strategy.

The size study (charted on the site) re-runs the whole walk-forward at $1k, $2.5k, $5k and $10k. Above $2,500, Bitget's after hours liquidity rejects most releases.

## Honest limitations

- **The sample is bounded by the venue, not by the method.** 79 releases were examined across 316 days, but a release is only tradeable if the company's Bitget perpetual already existed with enough history at that moment. That leaves 37 analysable releases, of which 5 cleared every gate. Arista is the clearest case: its perpetual listed on 12 August 2026, eight days after its 4 August earnings, so that release can never be traded however good the signal was.
- **Five trades cannot establish an edge, and cannot refute one either.** Any Sharpe quoted on five trades is noise. What is visible at this sample size is the effect of the gates: taking every signal loses money (19 trades, -$69.80, Sharpe -0.03), while the subset that clears every gate makes money (5 trades, +$317.86, Sharpe 0.30). The abstention is doing the work.
- **The hedge did not pay on these five.** Unhedged on the same releases returned $487.03 with a $37.64 drawdown, against $317.86 and $68.84 hedged. On this sample the hedge cost both return and drawdown. That is published here rather than buried, and it is the first thing a larger sample should settle.
- **The surprise is a guidance surprise**, reported revenue against the company's own prior outlook, because the SEC publishes no consensus. A later-added analyst-EPS consensus series is published as a post-hoc diagnostic; it is never eligible for walk-forward selection and is the worst baseline.
- **Funding history** reaches back only about 90 days on Bitget, so older trades carry a worst case funding charge, computed point in time. The tables above count those trades; the view that drops them has 5 trades for +$317.86.
- **Bitget Demo lists no index or sector ETF**, so main-mode strategy pairs cannot execute there. Demo mode exists for that reason, and the adapter refuses substitutes.
- **Thin books cap size rather than rejecting the release.** The position is the largest notional that stays inside 25% of the observed pre-event hourly volume, up to the $2,500 base, and the release is dropped only if that falls below a fifth of base. Volume is measured before the release, so this changes size and never the decision.
- **AI labels are not deterministic** run to run; the cached answers are what make a replay reproducible.

## Sample window and out-of-sample split

First release 2025-10-21, last release 2026-09-02: 316 days, comfortably past the 60-day minimum. There is no in-sample period to quote, because there is no in-sample fit. Every event is scored with parameters fitted only on events whose exit precedes that event's release, so all 316 days and every scored trade are out of sample by construction. The rule itself (residual, headline or agreement) is chosen the same way, walk-forward, and the selection for each event is recorded in `web/data.json`.

## Quick start

Python 3.11+, no third-party packages.

```bash
python -m residual verify --offline   # re-derive every number from the archived filings
python -m residual replay --offline   # regenerate every result, no network
python -m unittest discover -s tests  # 56 tests
python -m residual serve              # the site at http://localhost:8000
```

Refreshing data, and live mode, need network and keys in `.env.local` (see `.env.example`):

```bash
python -m residual build              # SEC EDGAR -> data/events.json + data/sources/
python -m residual snapshot           # Bitget candles and funding -> data/snapshots/
python -m residual replay             # re-run, calling Claude for anything uncached
python -m residual live               # one watcher cycle (add --loop 600 to keep going)
python -m residual keyrun             # full Bitget Demo check: auth, coverage, roundtrip
python -m residual demo-strategy-trade --mode demo --notional 100
```

Windows, to keep the watcher running silently and publishing to the site:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_watcher.ps1
```

## Audit

<p align="center">
  <img src="web/screenshots/audit.png" alt="Audit page" width="100%">
</p>

Every table, source link, document hash, paper order and operator detail: [residual-teal.vercel.app/dashboard](https://residual-teal.vercel.app/dashboard).

## Layout

```
residual/   edgar.py extract.py events.py consensus.py   filings, extraction, provenance, consensus
            bitget.py market.py net.py                   Bitget data and frozen snapshots
            factors.py strategy.py paper.py              decomposition, gates, rules, paper fills
            interpret.py                                 validated AI reading
            demo.py live.py pipeline.py __main__.py      Demo execution, watcher, replay, CLI
web/        index.html landing.js body.css orb.js        landing page and 3D hero
            dashboard.html app.js style.css              audit
data/       events.json sources/ snapshots/ consensus/   the evidence
            results.json ledger.csv live_log.jsonl       the output
```

Paper trading research. Not investment advice.
