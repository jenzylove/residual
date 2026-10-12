# Prospective test: the October to December 2026 earnings season

Committed 12 October 2026, before the first earnings release in the window. The commit timestamp on
GitHub is the record of that order.

## Why

The backtest is finished and frozen. Everything learned from it, including the one change it
suggested, can only be tested on releases that have not happened yet. This file fixes, in advance,
what will be measured on those releases and what will count as success.

## What is frozen

The method at commit `48b9d1c` and the reporting slice added with this file. Two versions run side
by side on every release, from the same data, in the same replay:

- **v1, the strategy as submitted.** The hedged pair, every gate as published. It stays the headline
  and the only version that places Bitget Demo orders.
- **v2, unhedged mode.** The same signal, AI reading, walk-forward parameters, direction rule and
  gates, with the hedge removed: no hedge gate, and the residual is weighed against company-only
  trading costs. Paper only. It was designed after the backtest showed the unhedged trade beating the
  hedged one on the same releases, so its backtest (+$851.26 over 19 trades, Sharpe 1.505) is in
  sample and counts for nothing here.

Nothing in `residual/strategy.py`, `factors.py`, `market.py`, `paper.py`, `interpret.py`,
`universe.py`, or the scoring in `pipeline.py` changes during the window. If a data collection bug
is found, it is fixed, disclosed here with the date, and results are reported both before and after
the fix. No threshold or gate is changed for any reason.

## The window

Every earnings release from the 46 companies in `residual/universe.py` accepted by the SEC from
13 October 2026 00:00 UTC up to 31 December 2026 23:59 UTC. The live watcher records each one,
including every release it rejects and why, in `data/live_log.jsonl`, and replays the study when a
new release arrives. The results appear under `populations.prospective` in `data/results.json`.
Evaluation happens once, after the last release in the window has completed its holding period,
and no earlier than 5 January 2027.

## What will be reported, whatever it shows

For v1, v2 and the baselines (headline direction on the same releases, headline direction on every
eligible release): trades, net P&L, daily Sharpe, Sortino, max drawdown, turnover, and the release
selection permutation test. Funding in this window is observed, so all funding views agree.

## Predictions

- **P1.** v2 makes more net P&L than v1 on the window's releases. This is the test of the one change
  the backtest suggested.
- **P2.** Both v1 and v2 do better than trading the headline direction on every eligible release in
  the window.
- **P3.** v1's choice of releases beats random choices from the same eligible pool, permutation
  p below 0.05. If v1 takes fewer than 8 trades, P3 is reported as inconclusive rather than passed
  or failed.

If fewer than 5 trades happen across v1 and v2 together, the whole test is reported as
inconclusive. The window is not extended to rescue it.

## What happens next depends only on the result

If P1 holds and v2 does not trail its baselines, v2 becomes the strategy for the following season,
under a new prospective file. If P1 fails, v1 stays. Either way the result is published in the
README, failures included.
